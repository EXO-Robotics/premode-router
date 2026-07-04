from __future__ import annotations

import re
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


V4_FORBIDDEN_SCAFFOLDING_TERMS = (
    "warning",
    "scope",
    "review",
    "verification",
    "forbidden",
    "do not edit",
    "run",
    "must",
    "should",
    "confidence",
    "candidate reason",
    "decision ledger",
)


def _prepare(repo: Path) -> None:
    init_project(repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text(
        "from src.app import value\n\n"
        "def test_value():\n"
        "    assert value() == 1\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    index_project(repo, "lite")


def _without_user_task(packet: str) -> str:
    return re.sub(r"<USER_TASK>.*?</USER_TASK>", "<USER_TASK></USER_TASK>", packet, flags=re.DOTALL)


def _without_file_content(packet: str) -> str:
    return re.sub(r"```text\n.*?\n```", "```text\n\n```", packet, flags=re.DOTALL)


def _scaffold(packet: str) -> str:
    return _without_file_content(_without_user_task(packet)).lower()


def test_v4_context_only_packet_keeps_diagnostics_out_of_model_facing_text(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(
        repo,
        "Update src/app.py behavior.",
        "lite",
        use_repo_map=True,
        packet_version="v4",
        packet_detail_mode="paths_only",
        save=True,
    )

    packet = result["packet"]
    scaffold = _scaffold(packet)
    assert packet.startswith("PREMODE_CONTEXT_PACKET_V4")
    assert "schema: context-only" in packet
    assert "<USER_TASK>\nUpdate src/app.py behavior.\n</USER_TASK>" in packet
    assert "FILE 1: src/app.py" in packet
    assert "tests/test_app.py" in packet
    for term in V4_FORBIDDEN_SCAFFOLDING_TERMS:
        assert term not in scaffold

    assert result["warnings"] == result["trust_boundary_warnings"]
    assert result["patch_boundary"]
    assert result["review_contract"]
    assert result["harness_review_metadata"]["model_facing"] is False
    assert result["file_decision_ledger"]
    assert result["decision_ledger"] == result["file_decision_ledger"]
    assert result["confidence"] in {"high", "medium", "low"}
    assert result["likely_files"]
    assert result["related_tests"]
    assert result["cacheable_prefix_tokens"] > 0
    assert result["dynamic_suffix_tokens"] > 0
    assert result["compiled_packet_sha256"]


def test_v4_related_tests_are_rendered_as_data_not_commands(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(
        repo,
        "Update src/app.py behavior.",
        "lite",
        use_repo_map=True,
        packet_version="v4",
        packet_detail_mode="evidence_snippets",
    )

    packet = result["packet"]
    scaffold = _scaffold(packet)
    assert "<RELATED_TESTS>" in packet
    assert "FILE 1: tests/test_app.py" in packet
    assert "command" not in scaffold
    assert "suggestion" not in scaffold
    assert "verification" not in scaffold
    assert result["evidence_snippet_packet"]["snippets"]
    assert result["model_facing_evidence_tokens"] > 0


def test_v4_hygiene_allows_user_prompt_words_only_inside_user_task(repo: Path) -> None:
    _prepare(repo)
    prompt = (
        "Update src/app.py. Literal words for regression: warning scope review "
        "verification forbidden must should run do not edit confidence decision ledger."
    )

    result = compile_prompt(
        repo,
        prompt,
        "lite",
        use_repo_map=True,
        packet_version="v4",
        packet_detail_mode="paths_only",
    )

    packet = result["packet"]
    assert f"<USER_TASK>\n{prompt}\n</USER_TASK>" in packet
    scaffold = _scaffold(packet)
    for term in V4_FORBIDDEN_SCAFFOLDING_TERMS:
        assert term not in scaffold


def test_v3_behavior_is_preserved_when_v4_is_not_selected(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(
        repo,
        "Update src/app.py behavior.",
        "lite",
        use_repo_map=True,
        cache_optimized=True,
    )

    packet = result["packet"]
    assert packet.startswith("PREMODE_COMPILED_PACKET_V3")
    assert "## 2. Stable agent contract" in packet
    assert "## 12. Do-Not-Edit Paths" in packet
