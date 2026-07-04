from __future__ import annotations

from pathlib import Path

from premode.benchmark import compile_mode_comparison
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _repo(repo: Path) -> None:
    _write(
        repo / "src" / "app.py",
        """
def build_config(completion=False):
    return {"completion": completion}

def render_total(value):
    return f"Total: {value}"
""",
    )
    _write(
        repo / "tests" / "test_app.py",
        """
from src.app import build_config

def test_completion_config():
    assert build_config(completion=True)["completion"] is True
""",
    )
    _write(
        repo / "README.md",
        """
# Completion

The completion option is documented here.
""",
    )
    _write(
        repo / "pyproject.toml",
        """
[project]
name = "demo"
""",
    )
    init_project(repo)
    index_project(repo, "lite")


def test_v5_ranked_paths_plus_anchors_renders_data_only_anchors(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(
        repo,
        "Update build_config completion behavior in src/app.py.",
        "lite",
        packet_version="v5",
        packet_variant="ranked_paths_plus_anchors",
    )

    packet = result["packet"]
    assert result["packet_variant"] == "ranked_paths_plus_anchors"
    assert "anchors:" in packet
    assert "<FILE " not in packet
    assert result["metrics"]["anchor_count"] >= 1
    assert result["metrics"]["file_block_count"] == 0
    assert result["model_facing_leakage_check"]["model_facing_diagnostic_leakage"] is False


def test_v5_ranked_paths_no_support_omits_support_section_items(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(
        repo,
        "Update build_config completion behavior with README context.",
        "lite",
        packet_version="v5",
        packet_variant="ranked_paths_no_support",
    )

    packet = result["packet"]
    assert result["packet_variant"] == "ranked_paths_no_support"
    assert result["metrics"]["support_count"] == 0
    assert "<SUPPORT_FILES>\n</SUPPORT_FILES>" in packet
    assert "<FILE " not in packet


def test_v5_ranked_paths_tests_first_orders_related_tests_before_primary(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(
        repo,
        "Add a regression in tests/test_app.py for completion config.",
        "lite",
        packet_version="v5",
        packet_variant="ranked_paths_tests_first",
    )

    packet = result["packet"]
    assert result["packet_variant"] == "ranked_paths_tests_first"
    assert packet.index("<RELATED_TESTS>") < packet.index("<PRIMARY_FILES>")
    assert "<FILE " not in packet


def test_v5_selective_snippets_keeps_blocks_compact(repo: Path) -> None:
    _repo(repo)
    _write(repo / "src" / "large.py", "\n".join(f"LINE_{idx} = {idx}" for idx in range(500)))
    init_project(repo)
    index_project(repo, "lite")

    result = compile_prompt(
        repo,
        "Update build_config completion behavior in src/app.py without changing large.py.",
        "lite",
        packet_version="v5",
        packet_variant="ranked_paths_selective_snippets",
    )

    assert result["packet_variant"] == "ranked_paths_selective_snippets"
    assert result["metrics"]["snippet_token_count"] < 500
    assert "LINE_499" not in result["packet"]
    assert result["model_facing_leakage_check"]["model_facing_diagnostic_leakage"] is False


def test_v5_ranked_paths_top1_is_extreme_focus(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(
        repo,
        "Update build_config and render_total.",
        "lite",
        packet_version="v5",
        packet_variant="ranked_paths_top1",
    )

    assert result["packet_variant"] == "ranked_paths_top1"
    assert result["metrics"]["ranked_primary_count"] == 1
    assert result["metrics"]["support_count"] == 0
    assert "anchors:" in result["packet"]


def test_compile_mode_comparison_exposes_v5_research_variants(repo: Path) -> None:
    _repo(repo)
    reports = compile_mode_comparison(repo, "Update build_config completion behavior.", profile="lite")
    modes = {report["mode"] for report in reports}

    assert "v5_ranked_paths_plus_anchors" in modes
    assert "v5_ranked_paths_selective_snippets" in modes
    assert "v5_ranked_paths_no_support" in modes
    assert "v5_ranked_paths_tests_first" in modes
    assert "v5_ranked_paths_top1" in modes
