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


def _compile(repo: Path, prompt: str | None = None, *, strategy: str | None = None) -> dict:
    return compile_prompt(
        repo,
        prompt or "Update build_config completion behavior in src/app.py and keep tests aligned.",
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy=strategy,
        cache_optimized=True,
    )


def _strip_dynamic(packet: str) -> str:
    text = re.sub(r"<TASK>.*?</TASK>", "<TASK></TASK>", packet, flags=re.DOTALL)
    for tag in ("PRIMARY_FILES", "RELATED_TESTS"):
        text = re.sub(rf"<{tag}>.*?</{tag}>", f"<{tag}></{tag}>", text, flags=re.DOTALL)
    return text.lower()


def _anchor_types(result: dict) -> set[str]:
    return {
        str(anchor.get("anchor_type") or anchor.get("type") or "")
        for anchors in (result.get("anchors_by_path") or {}).values()
        for anchor in anchors
    }


def _generated_anchor_types(result: dict) -> set[str]:
    internal = result.get("tool_assisted_anchors_internal") or {}
    return {
        str(anchor.get("anchor_type") or anchor.get("type") or "")
        for anchors in (internal.get("generated_anchors_by_path") or {}).values()
        for anchor in anchors
    }


def test_variant_and_strategy_are_selectable(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, strategy="literal_symbol_config")

    assert result["packet_version"] == "v5"
    assert result["packet_variant"] == "tool_assisted_anchors_internal"
    assert result["metrics"]["strategy_selected"] == "literal_symbol_config"
    assert result["tool_assisted_anchors_internal"]["base_variant"] == "ranked_paths_plus_anchors"


def test_cli_accepts_internal_anchor_variant_and_strategy(repo: Path) -> None:
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
            "tool_assisted_anchors_internal",
            "--packet-strategy",
            "literal_symbol",
            "--json",
            "--no-record",
        ],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["packet_variant"] == "tool_assisted_anchors_internal"
    assert payload["metrics"]["strategy_selected"] == "literal_symbol"


def test_model_facing_packet_contract_is_ranked_paths_plus_anchors_only(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo)
    packet = result["packet"]

    assert packet.startswith("PREMODE_CONTEXT_PACKET_V5")
    assert "schema: ranked-paths-plus-anchors" in packet
    assert "<TASK>" in packet
    assert "<PRIMARY_FILES>" in packet
    assert "<RELATED_TESTS>" in packet
    assert "<END_PREMODE_CONTEXT_PACKET_V5>" in packet
    assert "anchors:" in packet
    assert "<TASK_CLASS>" not in packet
    assert "<SUPPORT_RELATIONS>" not in packet
    assert "<SUPPORT_FILES>" not in packet
    assert "<FILE " not in packet


def test_model_facing_packet_has_no_forbidden_scaffolding(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update src/app.py. Literal task words: warning scope review validation command policy do not.")

    scaffold = _strip_dynamic(result["packet"])
    for term in FORBIDDEN_SCAFFOLDING_TERMS:
        assert term not in scaffold
    assert result["model_facing_leakage_check"]["model_facing_diagnostic_leakage"] is False
    assert result["metrics"]["model_facing_diagnostic_leakage"] is False


def test_literal_symbol_and_test_probes_select_anchors(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, strategy="literal_symbol")
    types = _anchor_types(result)

    assert "literal" in types or "cli_flag" in types
    assert "symbol" in types
    assert "test_name" in types


def test_config_probe_selects_config_anchors(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update the package metadata name in pyproject.toml.", strategy="literal_symbol_config")

    assert {"config_section", "package_name"} & _anchor_types(result)


def test_docs_heading_probe_selects_heading_anchors(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update the Completion docs heading in README.md.", strategy="literal_symbol_docs")

    assert "heading" in _anchor_types(result)


def test_import_probe_keeps_relations_json_only(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, strategy="literal_symbol_import_boost")
    internal = result["tool_assisted_anchors_internal"]

    assert "import_name" in _generated_anchor_types(result)
    assert "ranking_adjustments" in internal
    assert internal["internal_relations_json_only"] is not None
    assert "<SUPPORT_RELATIONS>" not in result["packet"]
    assert "imports " not in _strip_dynamic(result["packet"])


def test_scaffold_meta_anchors_are_rejected(repo: Path) -> None:
    _repo(repo)
    _write(
        repo / "src" / "scaffold.py",
        """
def premode_command_warning_policy_review():
    return True
""",
    )
    index_project(repo, "lite")
    result = _compile(repo, "Update premode command warning policy review behavior in src/scaffold.py.")

    selected = [
        str(anchor.get("anchor_text") or "").lower()
        for anchors in (result.get("anchors_by_path") or {}).values()
        for anchor in anchors
    ]
    assert not any("premode" in anchor or "command" in anchor or "policy" in anchor for anchor in selected)
    assert result["filtered_anchor_terms"]


def test_anchor_caps_and_scan_limits_are_enforced(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo)
    stats = result["discovery_stats"]

    assert result["metrics"]["anchor_count"] <= 12
    assert stats["files_scanned_count"] <= stats["max_files_scanned"] <= 8
    assert stats["lines_scanned_count"] <= stats["max_lines_scanned"]
    assert stats["bytes_scanned_count"] <= stats["max_bytes_scanned"]


def test_json_diagnostics_keep_task_class_and_relations_out_of_band(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo)
    internal = result["tool_assisted_anchors_internal"]

    assert internal["task_class_json_only"]
    assert internal["internal_relations_json_only"] is not None
    assert internal["model_facing_allowed"]["task_class"] is False
    assert internal["model_facing_allowed"]["support_relations"] is False
    assert "task_class_json_only" not in result["packet"]
    assert "internal_relations_json_only" not in result["packet"]


def test_strategy_comparison_metrics_are_computed(repo: Path) -> None:
    _repo(repo)
    modes = {row["mode"]: row for row in compile_mode_comparison(repo, "Update build_config completion behavior.", profile="lite")}

    row = modes["v5_tool_assisted_anchors_internal_literal_symbol_config"]
    assert row["packet_variant"] == "tool_assisted_anchors_internal"
    assert row["packet_strategy"] == "literal_symbol_config"
    assert row["anchors_selected_count"] is not None
    assert row["model_facing_leakage"] is False


def test_existing_ranked_paths_plus_anchors_output_remains_unchanged(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(repo, "Update build_config completion behavior.", "lite", packet_version="v5", packet_variant="ranked_paths_plus_anchors")

    assert result["packet_variant"] == "ranked_paths_plus_anchors"
    assert "schema: ranked-context-only" in result["packet"]
    assert "<TASK_CLASS>" not in result["packet"]
    assert "<SUPPORT_RELATIONS>" not in result["packet"]


def test_existing_tool_assisted_backbone_output_remains_unchanged(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(repo, "Update build_config completion behavior.", "lite", packet_version="v5", packet_variant="tool_assisted_backbone")

    assert result["packet_variant"] == "tool_assisted_backbone"
    assert "schema: tool-assisted-ranked-backbone" in result["packet"]
    assert "<TASK_CLASS>" in result["packet"]


def test_local_benchmark_passes_for_internal_anchor_variant(repo: Path) -> None:
    _repo(repo)
    prompts = repo / "prompts.json"
    prompts.write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "name": "internal_anchors",
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
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="policy_by_prompt_type",
        cache_optimized=True,
    )
    assert report["benchmark_status"] == "pass"
    assert report["packet_variant_requested"] == "tool_assisted_anchors_internal"
    assert report["packet_strategy_requested"] == "policy_by_prompt_type"
    assert report["cases"][0]["packet_variant"] == "tool_assisted_anchors_internal"
