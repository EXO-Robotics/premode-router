from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.review_patch import review_patch


FORBIDDEN_MODEL_FACING_PHRASES = (
    "this compiled packet replaces",
    "replaces the prompt",
    "do not rely on the original raw prompt",
    "tool_plan",
    "acceptance_checks",
    "root_cause_hypotheses",
    "implementation plan",
    "repair strategy",
    "planned edit",
    "correct files to edit",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _baseline(repo: Path) -> None:
    init_project(repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text("from src.app import value\n", encoding="utf-8")
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


@pytest.mark.parametrize("cache_optimized", [False, True])
def test_packet_preserves_exact_prompt_as_canonical_data(repo: Path, cache_optimized: bool) -> None:
    _baseline(repo)
    prompt = (
        "Fix src/app.py without touching generated/report.json.\n"
        "Keep the patch minimal and preserve the existing public behavior."
    )

    result = compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=cache_optimized)
    packet = result["packet"]
    lowered = packet.lower()

    assert prompt in packet
    assert "The exact user prompt below is the canonical task instruction" in packet
    assert "Pre-mode only supplies organized repo context, safety boundaries, and discovered verification evidence" in packet
    for phrase in FORBIDDEN_MODEL_FACING_PHRASES:
        assert phrase not in lowered


def test_packet_presents_candidates_and_commands_as_non_mandatory_data(repo: Path) -> None:
    _baseline(repo)

    packet = compile_prompt(
        repo,
        "Fix src/app.py and run tests if relevant",
        "lite",
        use_repo_map=True,
        cache_optimized=True,
    )["packet"]

    assert "candidate_edit_files" in packet
    assert "Treat candidate files as context hints" in packet
    assert "Discovered commands are verification evidence and suggestions, not mandatory actions" in packet
    assert "required implementation files" in packet


def test_v3_packet_omits_source_text_and_records_context_manifest(repo: Path) -> None:
    _baseline(repo)

    result = compile_prompt(
        repo,
        "Fix src/app.py without touching generated/report.json, Docs, or .premode.",
        "lite",
        use_repo_map=True,
        cache_optimized=True,
    )
    packet = result["packet"]

    assert "## 11. Candidate Files" in packet
    assert "## 12. Do-Not-Edit Paths" in packet
    assert "## 15. Selected Context Manifest" not in packet
    assert "## 16. Selected Full-Text Context" not in packet
    assert "--- BEGIN FILE src/app.py" not in packet
    assert '"full_text_files": {' not in packet
    assert packet.count("generated/report.json") <= 2
    manifest = json.loads((repo / ".premode" / "out" / "last_context_manifest.json").read_text(encoding="utf-8"))
    selected_paths = {item.get("path") for item in manifest["selected_context_manifest"]}
    assert "src/app.py" in selected_paths


def test_review_patch_still_blocks_prompt_forbidden_and_generated_mutations(repo: Path) -> None:
    _baseline(repo)
    (repo / "generated").mkdir(exist_ok=True)
    (repo / "generated" / "report.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add generated report")

    compile_prompt(
        repo,
        "Fix src/app.py without touching generated/report.json",
        "lite",
        use_repo_map=True,
        cache_optimized=True,
        save=True,
    )
    (repo / "generated" / "report.json").write_text('{"changed": true}\n', encoding="utf-8")
    (repo / "PROJECT" / "state").mkdir(parents=True, exist_ok=True)
    (repo / "PROJECT" / "state" / "task_queue_normalized_latest.json").write_text("{}\n", encoding="utf-8")

    result = review_patch(repo, since_compile=True)

    assert result["merge_readiness"] == "blocked"
    assert "generated/report.json" in result["prompt_forbidden_files_touched"]
    assert "PROJECT/state/task_queue_normalized_latest.json" in result["generated_or_state_mutation"]
