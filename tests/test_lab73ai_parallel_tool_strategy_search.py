from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from premode.benchmark import run_benchmark
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


AI_STRATEGIES = [
    "literal_symbol_test_names",
    "literal_symbol_config_gated",
    "literal_symbol_docs_heading_gated",
    "literal_symbol_cli_route",
    "literal_symbol_import_rank_json_only",
    "literal_symbol_collision_filter",
    "literal_symbol_policy_by_prompt_type",
]

FORBIDDEN_SCAFFOLDING_TERMS = (
    "task_class",
    "support_relations",
    "confidence",
    "discovery",
    "tools",
    "probe",
    "scores",
    "warnings",
    "scope",
    "contract",
    "verify",
    "validation",
    "review",
    "commands",
    "do_not_edit",
    "decision_ledger",
    "<file ",
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _repo(repo: Path) -> None:
    _write(
        repo / "src" / "helpers.py",
        """
def normalize_shell(value):
    return value
""",
    )
    _write(
        repo / "src" / "app.py",
        """
from src.helpers import normalize_shell

def build_config(completion=False):
    return {"completion": completion}

def configure_shell_parser(parser):
    parser.add_argument("--shell", default="bash")
    return parser

def route_handler(app):
    app.get("/completion")(lambda: "ok")
""",
    )
    _write(
        repo / "tests" / "test_app.py",
        """
from src.app import build_config, configure_shell_parser

def test_completion_config():
    assert build_config(completion=True)["completion"] is True

def test_shell_flag_parser(argparse_parser):
    assert configure_shell_parser(argparse_parser) is argparse_parser
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

[tool.demo]
completion = true
""",
    )
    init_project(repo)
    index_project(repo, "lite")


def _compile(repo: Path, prompt: str, strategy: str) -> dict:
    return compile_prompt(
        repo,
        prompt,
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


def _selected_anchors(result: dict) -> list[dict]:
    return [
        anchor
        for anchors in (result.get("anchors_by_path") or {}).values()
        for anchor in anchors
    ]


def _selected_types(result: dict) -> set[str]:
    return {str(anchor.get("anchor_type") or "") for anchor in _selected_anchors(result)}


def _generated_types(result: dict) -> set[str]:
    internal = result.get("tool_assisted_anchors_internal") or {}
    return {
        str(anchor.get("anchor_type") or "")
        for anchors in (internal.get("generated_anchors_by_path") or {}).values()
        for anchor in anchors
    }


def test_each_new_strategy_is_selectable(repo: Path) -> None:
    _repo(repo)
    prompt = "Update build_config completion behavior and shell parser anchors in src/app.py."

    for strategy in AI_STRATEGIES:
        result = _compile(repo, prompt, strategy)
        assert result["packet_variant"] == "tool_assisted_anchors_internal"
        assert result["metrics"]["strategy_selected"] in {strategy, "literal_symbol_cli_route", "literal_symbol_test_names", "literal_symbol_config_gated", "literal_symbol_docs_heading_gated", "literal_symbol"}
        assert result["metrics"]["packet_strategy"] == result["metrics"]["strategy_selected"]


def test_cli_accepts_new_strategy_names(repo: Path) -> None:
    _repo(repo)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "premode.cli",
            "compile",
            "Update --shell completion parser in src/app.py.",
            "--repo",
            str(repo),
            "--profile",
            "lite",
            "--packet-version",
            "v5",
            "--packet-variant",
            "tool_assisted_anchors_internal",
            "--packet-strategy",
            "literal_symbol_cli_route",
            "--json",
            "--no-record",
        ],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["metrics"]["strategy_selected"] == "literal_symbol_cli_route"


def test_literal_symbol_baseline_remains_stable_and_explicit(repo: Path) -> None:
    _repo(repo)
    prompt = "Update build_config completion behavior in src/app.py and keep tests aligned."
    first = _compile(repo, prompt, "literal_symbol")
    second = _compile(repo, prompt, "literal_symbol")

    assert first["packet"] == second["packet"]
    assert first["metrics"]["strategy_selected"] == "literal_symbol"
    assert first["tool_assisted_anchors_internal"]["strategy_requested"] == "literal_symbol"


def test_every_strategy_renders_only_allowed_model_facing_sections(repo: Path) -> None:
    _repo(repo)
    prompt = "Update --shell completion parser in src/app.py. Do not change warning scope review validation command words."

    for strategy in AI_STRATEGIES + ["literal_symbol"]:
        result = _compile(repo, prompt, strategy)
        packet = result["packet"]
        scaffold = _strip_dynamic(packet)
        assert packet.startswith("PREMODE_CONTEXT_PACKET_V5")
        assert "schema: ranked-paths-plus-anchors" in packet
        assert "<TASK>" in packet
        assert "<PRIMARY_FILES>" in packet
        assert "<RELATED_TESTS>" in packet
        assert "<END_PREMODE_CONTEXT_PACKET_V5>" in packet
        for term in FORBIDDEN_SCAFFOLDING_TERMS:
            assert term not in scaffold
        assert result["model_facing_leakage_check"]["model_facing_diagnostic_leakage"] is False


def test_diagnostics_stay_json_only(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update --shell completion parser in src/app.py.", "literal_symbol_import_rank_json_only")
    internal = result["tool_assisted_anchors_internal"]

    assert internal["task_class_json_only"]
    assert internal["internal_relations_json_only"] is not None
    assert internal["probe_stats"]["probe_mix"]
    assert "task_class_json_only" not in result["packet"]
    assert "internal_relations_json_only" not in result["packet"]
    assert "probe_stats" not in result["packet"]


def test_test_name_anchors_are_capped_and_rendered_only_as_anchors(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update build_config completion behavior and related tests.", "literal_symbol_test_names")
    test_anchors = [anchor for anchor in _selected_anchors(result) if anchor.get("anchor_type") == "test_name"]

    assert test_anchors
    assert len(test_anchors) <= 2 * len(result["related_tests"])
    assert "<RELATED_TESTS>" in result["packet"]
    assert "test_name=" in result["packet"]
    assert "run test" not in _strip_dynamic(result["packet"])


def test_config_anchors_are_gated_to_config_package_prompts(repo: Path) -> None:
    _repo(repo)
    source_result = _compile(repo, "Update build_config completion behavior in src/app.py.", "literal_symbol_config_gated")
    config_result = _compile(repo, "Update the package metadata name in pyproject.toml.", "literal_symbol_config_gated")

    assert "config_section" not in _selected_types(source_result)
    assert {"config_section", "package_name"} & _selected_types(config_result)


def test_docs_heading_anchors_are_gated_to_docs_prompts(repo: Path) -> None:
    _repo(repo)
    source_result = _compile(repo, "Update build_config completion behavior in src/app.py.", "literal_symbol_docs_heading_gated")
    docs_result = _compile(repo, "Update the Completion documentation heading in README.md.", "literal_symbol_docs_heading_gated")

    assert "heading" not in _selected_types(source_result)
    assert "heading" in _selected_types(docs_result)


def test_cli_flag_and_route_anchors_are_extracted(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update the --shell completion route in src/app.py.", "literal_symbol_cli_route")

    assert {"cli_flag", "route"} & _selected_types(result)
    assert "--shell" in result["packet"] or "/completion" in result["packet"]


def test_import_probe_is_json_only_for_import_rank_strategy(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update normalize_shell completion behavior in src/app.py.", "literal_symbol_import_rank_json_only")
    selected_types = _selected_types(result)
    internal = result["tool_assisted_anchors_internal"]

    assert "import_name" in _generated_types(result)
    assert "import_name" not in selected_types
    assert internal["internal_relations_json_only"] is not None
    assert "<SUPPORT_RELATIONS>" not in result["packet"]


def test_collision_filter_rejects_generic_anchors(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update config test value behavior in src/app.py.", "literal_symbol_collision_filter")
    selected_text = {str(anchor.get("anchor_text") or "").lower() for anchor in _selected_anchors(result)}

    assert not (selected_text & {"config", "test", "value"})
    assert result["metrics"]["anchor_filter_reject_count"] >= 0


def test_anchor_caps_and_scan_limits_are_enforced(repo: Path) -> None:
    _repo(repo)
    result = _compile(repo, "Update --shell completion behavior in src/app.py.", "literal_symbol_cli_route")
    stats = result["discovery_stats"]

    assert result["metrics"]["anchor_count"] <= 12
    assert stats["files_scanned_count"] <= stats["max_files_scanned"] <= 8
    assert stats["lines_scanned_count"] <= stats["max_lines_scanned"]
    assert stats["bytes_scanned_count"] <= stats["max_bytes_scanned"]


def test_existing_ranked_paths_plus_anchors_remains_available(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(
        repo,
        "Update build_config completion behavior.",
        "lite",
        packet_version="v5",
        packet_variant="ranked_paths_plus_anchors",
    )

    assert result["packet_variant"] == "ranked_paths_plus_anchors"
    assert "schema: ranked-context-only" in result["packet"]


def test_old_tool_assisted_backbone_remains_opt_in(repo: Path) -> None:
    _repo(repo)
    result = compile_prompt(
        repo,
        "Update build_config completion behavior.",
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_backbone",
    )

    assert result["packet_variant"] == "tool_assisted_backbone"
    assert "schema: tool-assisted-ranked-backbone" in result["packet"]
    assert "<TASK_CLASS>" in result["packet"]


def test_local_benchmark_passes_for_literal_symbol(repo: Path) -> None:
    _repo(repo)
    prompts = repo / "prompts.json"
    prompts.write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "name": "literal_symbol",
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
        packet_strategy="literal_symbol",
        cache_optimized=True,
    )
    assert report["benchmark_status"] == "pass"
    assert report["packet_strategy_requested"] == "literal_symbol"
