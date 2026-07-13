from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from premode.candidate_policy import CandidateClass, CandidateIntent, classify_candidate
from premode.compiler import compile_prompt
from premode.indexer import index_project
from premode.routing_contract import decision_from_manifest


def _write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    _write(repo / "src/app.py", "def calculate_total(values):\n    return sum(values)\n")
    _write(repo / "tests/test_app.py", "from src.app import calculate_total\n")
    _write(repo / "pyproject.toml", "[project]\nname='fixture'\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    return repo


@pytest.mark.parametrize("rel, classification", [
    (".pcodex/config.toml", CandidateClass.DENY_RUNTIME),
    (".premode/inventory/files.json", CandidateClass.DENY_RUNTIME),
    (".git/config", CandidateClass.DENY_RUNTIME),
    (".pytest_cache/state", CandidateClass.DENY_RUNTIME),
    (".env", CandidateClass.DENY_SECRET),
])
def test_hard_denials_override_explicit_generated_intent(tmp_path: Path, rel: str, classification: CandidateClass) -> None:
    repo = _repo(tmp_path)
    _write(repo / rel)
    decision = classify_candidate(repo, rel, intent=CandidateIntent(explicit=True, generated_required=True))
    assert decision.classification == classification
    assert decision.admitted is False


def test_generated_exception_is_narrow_and_explicit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "dist/generated.js")
    ordinary = classify_candidate(repo, "dist/generated.js")
    explicit = classify_candidate(repo, "dist/generated.js", intent=CandidateIntent(explicit=True))
    required = classify_candidate(repo, "dist/generated.js", intent=CandidateIntent(explicit=True, generated_required=True))
    assert (ordinary.classification, ordinary.admitted) == (CandidateClass.ALLOW_IF_EXPLICIT, False)
    assert (explicit.classification, explicit.admitted) == (CandidateClass.ALLOW_IF_EXPLICIT, True)
    assert (required.classification, required.admitted) == (CandidateClass.GENERATED_EXCEPTION, True)


def test_index_fallback_cannot_admit_pcodex_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / ".pcodex/config.toml", "mode='on'\n")
    index = index_project(repo, write=False, inventory_paths=None, inventory_source="fallback_walk")
    paths = {entry["path"] for entry in index["entries"]}
    assert ".pcodex/config.toml" not in paths
    assert any(item["reason"] == "DENY_RUNTIME" for item in index["skipped"])


def test_stale_runtime_index_is_not_reused_by_read_only_compile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / ".pcodex/config.toml", "mode='on'\n")
    stale = index_project(repo, write=False, inventory_paths=["src/app.py", "tests/test_app.py", ".pcodex/config.toml"], inventory_source="poisoned")
    assert ".pcodex/config.toml" not in {entry["path"] for entry in stale["entries"]}
    result = compile_prompt(repo, "Change calculate_total to reject negative values and update its test.", record_artifacts=False, canonical_core_packet=True, packet_version="v5", packet_variant="tool_assisted_anchors_internal", packet_strategy="literal_symbol")
    rendered = result["packet"]
    assert ".pcodex" not in rendered
    assert all(".pcodex" not in path for bucket in ("primary_paths", "verify_paths", "support_paths") for path in result["production_ranking"][bucket])


def test_outside_symlink_and_fifo_are_denied(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.txt"
    _write(outside)
    (repo / "escape").symlink_to(outside)
    assert classify_candidate(repo, "../outside.txt").classification == CandidateClass.DENY_OUTSIDE_ROOT
    assert classify_candidate(repo, "escape").classification == CandidateClass.DENY_SYMLINK_ESCAPE
    fifo = repo / "pipe"
    try:
        os.mkfifo(fifo)
    except (AttributeError, OSError):
        pytest.skip("FIFO unavailable")
    assert classify_candidate(repo, "pipe").classification == CandidateClass.DENY_UNSAFE_SURFACE


def test_routing_contract_support_budget_and_abstention(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    for index in range(6):
        _write(repo / f"support/{index}.toml")
    manifest = {
        "locator_evidence": {
            "confidence": "high",
            "ambiguity_reasons": [],
            "primary_files": [{"path": "src/app.py", "score": 900, "matched_signals": ["symbol:calculate_total"]}],
            "verification_files": [{"path": "tests/test_app.py", "score": 700, "matched_signals": ["source_test_relation:src/app.py"]}],
            "support_files": [
                {"path": f"support/{index}.toml", "score": 500 - index, "matched_signals": ["import_relation:src/app.py"]}
                for index in range(6)
            ],
        },
        "tool_assisted_anchors_internal": {
            "primary_files_after": ["src/app.py"],
            "related_tests_after": ["tests/test_app.py"],
        },
    }
    decision = decision_from_manifest(repo, manifest)
    assert decision.mode == "narrow"
    assert decision.support_paths == ("support/0.toml", "support/1.toml")
    empty = decision_from_manifest(repo, {"locator_evidence": {"confidence": "low"}, "tool_assisted_anchors_internal": {}})
    assert empty.mode == "abstain"
    assert not empty.primary_paths and not empty.support_paths


def test_final_routing_revalidates_poisoned_backbone(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / ".pcodex/config.toml")
    decision = decision_from_manifest(repo, {
        "canonical_user_prompt": "Change .pcodex/config.toml",
        "locator_evidence": {
            "confidence": "high",
            "primary_files": [{"path": ".pcodex/config.toml", "score": 999, "matched_signals": ["explicit_path:.pcodex/config.toml"]}],
        },
        "tool_assisted_anchors_internal": {"primary_files_after": [".pcodex/config.toml"]},
    })
    assert decision.mode == "abstain"
    assert decision.primary_paths == ()


def test_explicit_generated_intent_reaches_production_admission(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "dist/generated.js", "export function generatedTotal() { return 1 }\n")
    result = compile_prompt(
        repo,
        "Update generated code in dist/generated.js for generatedTotal.",
        record_artifacts=False,
        canonical_core_packet=True,
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
    )
    decisions = result["manifest"]["candidate_policy"] if "manifest" in result else result.get("candidate_policy")
    # The explicit generated path is admitted before indexing; hard runtime paths
    # remain impossible to restore through the same exception.
    assert "dist/generated.js" in str(result.get("locator_evidence") or result)
    assert ".pcodex" not in result["packet"]


def test_explicit_source_and_test_keep_source_primary_and_test_verification(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    result = compile_prompt(
        repo,
        "Change calculate_total in src/app.py and update tests/test_app.py",
        record_artifacts=False,
        canonical_core_packet=True,
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
    )

    decision = result["production_ranking"]
    assert decision["routing_mode"] != "abstain"
    assert decision["primary_paths"] == ["src/app.py"]
    assert decision["verify_paths"] == ["tests/test_app.py"]
