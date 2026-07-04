from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from premode.benchmark import compile_mode_comparison, run_benchmark
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


FORBIDDEN_SCAFFOLDING_TERMS = (
    "warning",
    "scope",
    "contract",
    "forbidden",
    "must",
    "do not",
    "verify",
    "verification",
    "review",
    "validation",
    "confidence",
    "decision",
    "policy",
    "command",
    "acceptance",
    "safety",
    "run this",
    "do-not-edit",
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _repo(repo: Path) -> None:
    _write(
        repo / "src" / "helpers.py",
        """
def normalize_total(value):
    return int(value)
""",
    )
    _write(
        repo / "src" / "app.py",
        """
from src.helpers import normalize_total

def build_config(completion=False):
    return {"completion": completion}

def calculate_total(value):
    return normalize_total(value) + 1
""",
    )
    _write(
        repo / "tests" / "test_app.py",
        """
from src.app import build_config, calculate_total

def test_completion_config():
    assert build_config(completion=True)["completion"] is True

def test_calculate_total():
    assert calculate_total(2) == 3
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


def _strip_dynamic(packet: str) -> str:
    text = re.sub(r"<TASK>.*?</TASK>", "<TASK></TASK>", packet, flags=re.DOTALL)
    for tag in ("TASK_CLASS", "PRIMARY_FILES", "RELATED_TESTS", "SUPPORT_RELATIONS", "SUPPORT_FILES", "REPO"):
        text = re.sub(rf"<{tag}>.*?</{tag}>", f"<{tag}></{tag}>", text, flags=re.DOTALL)
    text = re.sub(r"<FILE\b.*?</FILE>", "<FILE></FILE>", text, flags=re.DOTALL)
    return text.lower()


def _compile(repo: Path, variant: str = "tool_assisted_backbone") -> dict:
    return compile_prompt(
        repo,
        "Update build_config completion behavior in src/app.py and keep tests aligned.",
        "lite",
        packet_version="v5",
        packet_variant=variant,
        cache_optimized=True,
    )


def test_tool_assisted_backbone_variant_is_selectable(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo)

    assert result["packet_version"] == "v5"
    assert result["packet_variant"] == "tool_assisted_backbone"
    assert result["tool_assisted_backbone"]["primary_files"]
    assert result["metrics"]["task_class"] in {
        "runtime_source",
        "test_only",
        "docs_only",
        "config_package",
        "multi_surface_runtime",
        "ambiguous_low_confidence",
    }


def test_cli_accepts_tool_assisted_backbone(repo: Path) -> None:
    _repo(repo)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "premode.cli",
            "compile",
            "Update build_config completion behavior in src/app.py.",
            "--repo",
            str(repo),
            "--profile",
            "lite",
            "--packet-version",
            "v5",
            "--packet-variant",
            "tool_assisted_backbone",
            "--json",
            "--no-record",
        ],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["packet_variant"] == "tool_assisted_backbone"


def test_tool_assisted_packet_shape_is_backbone_only(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo)
    packet = result["packet"]

    assert packet.startswith("PREMODE_CONTEXT_PACKET_V5")
    assert "schema: tool-assisted-ranked-backbone" in packet
    assert "<TASK>" in packet
    assert "<TASK_CLASS>" in packet
    assert "<PRIMARY_FILES>" in packet
    assert "<RELATED_TESTS>" in packet
    assert "<END_PREMODE_CONTEXT_PACKET_V5>" in packet
    assert "<FILE " not in packet
    assert "<FORMAT>" not in packet
    assert "<REPO>" not in packet


def test_tool_assisted_scaffolding_has_no_diagnostic_or_behavior_terms(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(
        repo,
        "Update src/app.py. Literal task words: warning scope review verification command policy do not.",
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_backbone",
        cache_optimized=True,
    )

    scaffold = _strip_dynamic(result["packet"])
    for term in FORBIDDEN_SCAFFOLDING_TERMS:
        assert term not in scaffold
    assert result["model_facing_leakage_check"]["model_facing_diagnostic_leakage"] is False
    assert result["metrics"]["model_facing_diagnostic_leakage"] is False


def test_tool_assisted_caps_anchors_and_relations(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo)

    assert result["metrics"]["anchor_count"] <= 12
    assert result["metrics"]["support_relation_count"] <= 3
    primary_paths = set(result["tool_assisted_backbone"]["primary_files"])
    related_paths = set(result["tool_assisted_backbone"]["related_tests"])
    for path, anchors in result["anchors_by_path"].items():
        limit = 2 if path in related_paths and path not in primary_paths else 3
        assert len(anchors) <= limit


def test_tool_assisted_filters_scaffold_meta_anchors(repo: Path) -> None:
    _repo(repo)
    _write(
        repo / "src" / "scaffold.py",
        """
def premode_command_warning_policy_review():
    return True
""",
    )
    index_project(repo, "lite")
    result = compile_prompt(
        repo,
        "Update premode command warning policy review scaffold behavior in src/scaffold.py.",
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_backbone",
        cache_optimized=True,
    )

    anchors = [
        anchor["anchor_text"].lower()
        for per_path in (result["anchors_by_path"] or {}).values()
        for anchor in per_path
    ]
    assert not any("premode" in anchor or "command" in anchor or "policy" in anchor for anchor in anchors)
    assert result["filtered_anchor_terms"]


def test_tool_assisted_metadata_stays_out_of_band(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo)

    assert result["anchor_quality"]
    assert result["support_relations"] is not None
    assert result["discovery_stats"]["files_scanned_count"] > 0
    assert "anchor_quality" not in result["packet"]
    assert "discovery_stats" not in result["packet"]
    assert "strength" not in result["packet"]


def test_tool_assisted_discovery_cost_metrics_are_present(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo)
    stats = result["discovery_stats"]

    for key in (
        "discovery_wall_ms",
        "rg_call_count",
        "files_scanned_count",
        "lines_scanned_count",
        "bytes_scanned_count",
        "anchors_generated_count",
        "anchors_selected_count",
        "relations_generated_count",
        "relations_selected_count",
        "anchor_filter_reject_count",
        "discovery_error_count",
    ):
        assert key in stats
        assert key in result["metrics"]


def test_existing_v5_and_v3_modes_remain_available(repo: Path) -> None:
    _repo(repo)
    v5 = compile_prompt(repo, "Update build_config.", "lite", packet_version="v5", packet_variant="ranked_paths_plus_anchors")
    v3 = compile_prompt(repo, "Update build_config.", "lite", packet_version="v3")

    assert v5["packet_variant"] == "ranked_paths_plus_anchors"
    assert "schema: ranked-context-only" in v5["packet"]
    assert v3["packet_marker"] == "PREMODE_COMPILED_PACKET_V3"


def test_compile_mode_comparison_exposes_tool_assisted_variants(repo: Path) -> None:
    _repo(repo)
    modes = {row["mode"]: row for row in compile_mode_comparison(repo, "Update build_config completion behavior.", profile="lite")}

    assert "v5_tool_assisted_backbone" in modes
    assert "v5_tool_assisted_backbone_no_task_class" in modes
    assert "v5_tool_assisted_backbone_no_relations" in modes
    assert modes["v5_tool_assisted_backbone"]["support_relation_count"] is not None


def test_tool_assisted_small_benchmark_passes(repo: Path) -> None:
    _repo(repo)
    prompts = repo / "prompts.json"
    prompts.write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "name": "tool_backbone",
                        "prompt": "Update build_config completion behavior in src/app.py.",
                        "expected_files": ["src/app.py"],
                        "expected_tests": ["tests/test_app.py"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = run_benchmark(
        repo,
        prompts_path=prompts,
        profile="lite",
        packet_version="v5",
        packet_variant="tool_assisted_backbone",
        cache_optimized=True,
    )
    assert report["benchmark_status"] == "pass"
    assert report["cases"][0]["packet_variant"] == "tool_assisted_backbone"


def test_tool_assisted_no_task_class_ablation_omits_task_class(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "tool_assisted_backbone_no_task_class")

    assert "<TASK_CLASS>" not in result["packet"]
    assert result["task_class"]
    assert result["packet_variant"] == "tool_assisted_backbone_no_task_class"


def test_tool_assisted_no_relations_ablation_omits_support_relations(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "tool_assisted_backbone_no_relations")

    assert "<SUPPORT_RELATIONS>" not in result["packet"]
    assert result["support_relations"] is not None
    assert result["packet_variant"] == "tool_assisted_backbone_no_relations"
