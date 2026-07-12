from __future__ import annotations

from pathlib import Path

import pytest

from premode.candidate_policy import CandidateClassification, evaluate_candidate
from premode.locator import FileRelation, LocateResult, LocatedFile
from premode.ranker_protocol import B0_ROUTING_BASE_V1
from premode.routing_base import compile_routing_base
from premode.routing_decision import RoutingMode, decide_routing, render_model_request
from premode.routing_decision import routing_input_from_ranked
from premode.ranker_protocol import RankedCandidate, RankedCandidates
from premode.task_intent import compute_task_intent


def _file(path: str, score: int, role: str = "source", *signals: str) -> LocatedFile:
    return LocatedFile(path, score, role, "high" if score >= 420 else "medium", list(signals))


def _result(*, primary=(), verification=(), support=(), confidence="high", ambiguity=(), relations=(), policy=None) -> LocateResult:
    records = policy
    if records is None:
        records = [{"normalized_path": item.path, "final_admissibility": "ALLOW", "final_policy_receipt": {"receipt_sha256": f"test:{item.path}"}} for item in [*primary, *verification, *support]]
    metadata = {"candidate_policy": {"records": records}, "candidate_provenance": records}
    result = LocateResult(list(primary), list(support), list(verification), confidence, [], [], list(ambiguity), list(relations), metadata=metadata)
    all_files = [*primary, *verification, *support]
    ranked = RankedCandidates(B0_ROUTING_BASE_V1.configuration_hash, tuple(RankedCandidate(item.path, item.path, item.score, index, f"evidence:{item.path}", ()) for index, item in enumerate(sorted(all_files, key=lambda value: (-value.score, value.path)), start=1)))
    return routing_input_from_ranked(result, ranked)


@pytest.mark.parametrize("path", ["nested/.pcodex/config.toml", "foo/bar/.premode/index.json", "package/.git/HEAD", "tmp/cache/.pcodex/state.json"])
def test_nested_runtime_components_are_hard_denied(tmp_path: Path, path: str) -> None:
    result = evaluate_candidate(tmp_path, path, "explicit_prompt_path", {"explicit_paths": [path], "generated_intent": True})
    assert result.classification in {CandidateClassification.DENY_RUNTIME, CandidateClassification.DENY_SECRET}
    assert result.admitted is False
    assert result.final_admissibility is None


def test_generated_intent_is_one_stable_value_and_never_overrides_runtime(tmp_path: Path) -> None:
    intent = compute_task_intent("Regenerate vendor/client.py and nested/.pcodex/generated.py.")
    assert intent.generated_content_intent is True
    assert compute_task_intent("Regenerate vendor/client.py and nested/.pcodex/generated.py.") == intent
    generated = evaluate_candidate(tmp_path, "vendor/client.py", "inventory", intent.to_candidate_context())
    runtime = evaluate_candidate(tmp_path, "nested/.pcodex/generated.py", "explicit_prompt_path", intent.to_candidate_context())
    assert generated.final_admissibility == "GENERATED_EXCEPTION_QUALIFIED"
    assert runtime.admitted is False


def test_support_and_verification_cannot_rescue_weak_primary() -> None:
    decision = decide_routing(_result(primary=[_file("src/app.py", 30)], verification=[_file("tests/test_app.py", 900, "test")], support=[_file("pyproject.toml", 1000, "config", "explicit_path:pyproject.toml")]), "Fix app.")
    assert decision.mode is RoutingMode.ABSTAIN
    assert decision.support_paths == ()
    assert decision.confidence_dimensions.primary_confidence == 30


def test_final_policy_closure_is_required_in_normal_strict_route() -> None:
    with pytest.raises(ValueError, match="lacks final policy receipt"):
        decide_routing(_result(primary=[_file("src/app.py", 600)], policy=[]), "Fix app.")


def test_mode_calibration_contract_covers_all_three_modes() -> None:
    cases = [
        (_result(primary=[_file("src/a.py", 900, "source", "explicit_path:src/a.py")]), "Change src/a.py.", RoutingMode.NARROW),
        (_result(primary=[_file("src/a.py", 800, "source", "symbol:calculate_total")], verification=[_file("tests/test_a.py", 500, "test")]), "Change calculate_total.", RoutingMode.NARROW),
        (_result(primary=[_file("pkg/a.py", 700)], verification=[_file("pkg/test_a.py", 400, "test")]), "Fix package behavior.", RoutingMode.NARROW),
        (_result(primary=[_file("pkg/a.py", 650)]), "Change pkg/a.py.", RoutingMode.NARROW),
        (_result(primary=[_file("a/x.py", 500), _file("b/y.py", 430)], ambiguity=["cross_package_intent"]), "Update workspace packages.", RoutingMode.BROAD),
        (_result(primary=[_file("src/a.py", 500)], verification=[_file("tests/test_a.py", 350, "test")], ambiguity=["top_score_gap_small"]), "Update source test config closure.", RoutingMode.BROAD),
        (_result(primary=[_file("src/a.py", 500)], support=[_file("pyproject.toml", 300, "config", "build_config")], ambiguity=["build_dependency"]), "Update build dependency.", RoutingMode.BROAD),
        (_result(primary=[_file("gen/a.py", 600)], ambiguity=["bounded_generated_resolution"]), "Regenerate gen/a.py.", RoutingMode.BROAD),
        (_result(), "Review the repository broadly.", RoutingMode.ABSTAIN),
        (_result(primary=[_file("a/util.py", 700)], ambiguity=["duplicate_basename_unresolved"]), "Fix util.py.", RoutingMode.ABSTAIN),
        (_result(primary=[_file("src/a.py", 20)], support=[_file("pyproject.toml", 900, "config")]), "Improve behavior.", RoutingMode.ABSTAIN),
        (_result(primary=[_file("src/a.py", 200)]), "Refactor broadly.", RoutingMode.ABSTAIN),
    ]
    assert [decide_routing(result, task).mode for result, task, _ in cases] == [expected for _, _, expected in cases]


def test_end_to_end_runtime_regression_and_packet_authority(tmp_path: Path) -> None:
    for relative, content in {
        "src/app.py": "def calculate_total(values):\n    return sum(values)\n",
        "tests/test_app.py": "from src.app import calculate_total\n",
        "pyproject.toml": "[project]\nname='fixture'\n",
        ".pcodex/config.toml": "poison=true\n",
        "nested/.pcodex/state.json": "{}\n",
    }.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    result = compile_routing_base(tmp_path, "Change calculate_total to reject negative values and update its test.")
    assert result["routing_mode"] == "NARROW"
    assert result["packet"].count("Change calculate_total to reject negative values and update its test.") == 1
    assert result["model_facing_selected_paths"] == result["selected_paths"]
    assert not any(".pcodex" in path for path in result["selected_paths"])
    denied = {item["normalized_path"] for item in result["candidate_policy"]["records"] if item["final_admissibility"] is None}
    assert {".pcodex/config.toml", "nested/.pcodex/state.json"}.issubset(denied)


def test_abstention_is_byte_exact() -> None:
    task = "Review the repository broadly.\nDo not infer hidden context."
    decision = decide_routing(_result(), task)
    assert decision.mode is RoutingMode.ABSTAIN
    assert render_model_request(decision).encode() == task.encode()


def test_b0_configuration_hash_is_stable() -> None:
    assert B0_ROUTING_BASE_V1.configuration_hash == "f1a5b8f2a9701d4281f52a10871c9a2de3e976cc1dff7eddb00edacf63f39128"
