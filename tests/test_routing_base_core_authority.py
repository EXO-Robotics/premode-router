from __future__ import annotations

from pathlib import Path

import pytest

from premode.candidate_evidence import CandidateEvidence, evidence_from_materialized
from premode.candidate_materializer import RepositoryInventory, materialize_candidates
from premode.locator import LocateResult, LocatedFile
from premode.ranker_protocol import B0_ROUTING_BASE_V1, RankedCandidate, RankedCandidates, rank
from premode.routing_base import compile_routing_base
from premode.routing_decision import decide_routing
from premode.task_intent import compute_task_intent


def _write(root: Path, relative: str, content: str = "def target():\n    return True\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_existing_explicit_path_has_truthful_additive_materialization(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py")
    intent = compute_task_intent("Change src/app.py.")
    result = materialize_candidates("Change src/app.py.", intent, RepositoryInventory.capture(tmp_path, ["src/app.py"]))
    candidate = result.admitted[0]
    assert candidate.provenance_sources == ("inventory", "explicit_prompt_path")
    assert candidate.provenance_chain == ("inventory", "explicit_prompt_path")
    assert len([item for item in result.policy_results if item.normalized_path == "src/app.py"]) == 2


def test_hard_denied_candidate_never_becomes_evidence(tmp_path: Path) -> None:
    intent = compute_task_intent("Inspect nested/.pcodex/config.toml.")
    result = materialize_candidates(intent.exact_task_sha256, intent, RepositoryInventory.capture(tmp_path, ["nested/.pcodex/config.toml"]))
    assert not result.admitted
    with pytest.raises(ValueError):
        evidence_from_materialized(result.candidates[0])


def test_candidate_evidence_is_pre_rank_only_and_hash_stable(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py")
    intent = compute_task_intent("Change src/app.py.")
    candidate = materialize_candidates("Change src/app.py.", intent, RepositoryInventory.capture(tmp_path, ["src/app.py"])).admitted[0]
    first = evidence_from_materialized(candidate, path_evidence=("path:src/app.py",), score_components={"compatibility_adjustment": 500})
    second = evidence_from_materialized(candidate, path_evidence=("path:src/app.py",), score_components={"compatibility_adjustment": 500})
    assert first.evidence_hash == second.evidence_hash
    assert not {"final_score", "final_rank", "selected_role", "emitted_to_packet"} & set(first.to_dict())


def test_ranker_accepts_candidate_evidence_only_and_preserves_lineage(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py")
    intent = compute_task_intent("Change src/app.py.")
    candidate = materialize_candidates("Change src/app.py.", intent, RepositoryInventory.capture(tmp_path, ["src/app.py"])).admitted[0]
    evidence = evidence_from_materialized(candidate, score_components={"compatibility_adjustment": 500})
    ranked = rank((evidence,), B0_ROUTING_BASE_V1)
    assert ranked.candidates[0].candidate_id == evidence.candidate_id
    assert ranked.candidates[0].evidence_hash == evidence.evidence_hash
    assert ranked.candidates[0].final_score == sum(evidence.score_components.values())
    with pytest.raises(TypeError):
        rank((object(),), B0_ROUTING_BASE_V1)  # type: ignore[arg-type]


def test_routing_decision_rejects_raw_locate_result() -> None:
    located = LocateResult([LocatedFile("src/app.py", 500, "source", "high", ["symbol:app"])], [], [], "high", [], [], [], metadata={})
    with pytest.raises(TypeError, match="RankedCandidates"):
        decide_routing(located, "Fix app.")


def test_normal_pipeline_lineage_and_packet_authority(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py", "def calculate_total(values):\n    return sum(values)\n")
    _write(tmp_path, "tests/test_app.py", "from src.app import calculate_total\n")
    result = compile_routing_base(tmp_path, "Change calculate_total and update its test.")
    receipt = result["routing_authority_receipt"]
    assert receipt["authority_id"] == "normal_routing_authority.v1"
    assert set(receipt["ranked_candidate_ids"]).issubset(receipt["materialized_candidate_ids"])
    assert result["packet_source"] in {"canonical_packet_v1", "standard_passthrough"}
    assert result["packet_source"] == ("standard_passthrough" if result["routing_mode"] == "ABSTAIN" else "canonical_packet_v1")


def test_task_prompt_evidence_is_constructed_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py")
    import premode.locator as locator

    calls = 0
    original = locator.extract_prompt_evidence

    def counted(prompt: str):
        nonlocal calls
        calls += 1
        return original(prompt)

    monkeypatch.setattr(locator, "extract_prompt_evidence", counted)
    result = compile_routing_base(tmp_path, "Change src/app.py.")
    assert calls == 1
    assert result["routing_authority_receipt"]["task_intent_sha256"] == result["task_intent"]["exact_task_sha256"]


def test_abstain_has_standard_passthrough_source(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py")
    task = "Review the repository broadly."
    result = compile_routing_base(tmp_path, task)
    assert result["routing_mode"] == "ABSTAIN"
    assert result["packet"] == task
    assert result["packet_source"] == "standard_passthrough"
