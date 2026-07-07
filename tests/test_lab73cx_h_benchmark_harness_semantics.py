from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode import cli
from premode.benchmark import run_benchmark
from premode.compiler import compile_prompt


LITERAL_SYMBOL_KWARGS = {
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
    "record_artifacts": False,
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _commit(repo: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Pre Mode", "-c", "user.email=premode@example.test", "commit", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo / ".gitignore", ".premode/\n")
    _write(repo / ".premodeignore", "secrets/\n")
    _write(repo / "pyproject.toml", "[project]\nname='demo'")
    _write(repo / "src" / "app.py", "def run():\n    return 'ok'")
    _write(repo / "src" / "helper.py", "def help_app():\n    return 'help'")
    _write(repo / "tests" / "test_app.py", "def test_run():\n    assert True")
    _write(
        repo / "benchmark_prompts.json",
        json.dumps(
            {
                "prompts": [
                    {
                        "name": "app_fix",
                        "prompt": "Fix src/app.py and run the related test.",
                        "expected_files": ["src/app.py"],
                        "expected_tests": ["tests/test_app.py"],
                        "expected_primary_node": "root",
                    }
                ]
            }
        ),
    )
    _git(repo, "add", ".")
    _commit(repo)
    return repo


def test_compile_only_benchmark_rows_expose_metric_semantics(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    report = run_benchmark(
        repo,
        profile="lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
    )

    assert report["compile_only"] is True
    assert report["live_codex_run"] is False
    assert report["live_input_tokens"] is None
    assert report["live_cached_tokens"] is None
    assert report["live_cost_savings"] is None
    assert report["cache_mode"] == "strategy_isolated"
    assert report["shared_cache_measured"] is False
    assert report["public_private_comparison_valid"] is False
    assert report["comparison_invalid_reason"] == "public_unavailable"
    assert report["metric_semantics"]["derived_cache_adjusted_input"].startswith("benchmark-derived")

    lane = report["lane_metadata"]
    for key in (
        "branch",
        "head",
        "package_version",
        "python_version",
        "source_path",
        "source_dirty",
        "prompt_suite_hash",
        "benchmark_harness_hash",
        "public_clone_used",
        "public_private_comparison_valid",
        "comparison_invalid_reason",
    ):
        assert key in lane

    row = report["cases"][0]
    assert row["schema_version"] == "premode.benchmark.case.v2"
    assert row["benchmark_kind"] == "compile_only_harness_row"
    assert row["compile_only"] is True
    assert row["live_codex_run"] is False
    assert row["live_input_tokens"] is None
    assert row["live_cached_tokens"] is None
    assert row["live_cost_savings"] is None
    assert row["packet_total_tokens"] and row["packet_total_tokens"] == row["packet_tokens"]
    assert row["selected_context_tokens"] is not None
    assert row["eligible_repo_surface_tokens"] and row["eligible_repo_surface_tokens"] == row["eligible_repo_tokens"]
    assert row["full_repo_reduction_percent"] is not None
    assert row["estimated_savings_vs_eligible_repo_percent"] == row["full_repo_reduction_percent"]
    assert row["estimated_savings_alias_status"] == "deprecated_compatibility_alias_for_full_repo_reduction_percent"
    assert row["derived_cache_adjusted_input"] is not None
    assert row["derived_cache_adjusted_input_semantics"] == "benchmark_derived_cache_shape_estimate_not_live_usage"
    assert row["cache_mode"] == "strategy_isolated"
    assert row["run_temperature"] in {"cold", "warm", "repeated_warm"}
    assert row["inventory_cache_hit"] in {True, False}
    assert row["topology_cache_hit"] in {True, False}
    assert row["full_walk_performed"] in {True, False}
    assert row["files_walked"] is not None
    assert row["files_listed"] is not None
    assert row["files_content_read"] is not None
    assert row["bytes_read"] is not None
    assert row["compile_ms"] is not None
    assert row["prompt_preserved"] is True
    assert row["model_facing_leak_check"]["passed"] is True
    assert row["expected_file_hit_at_1"] in {True, False}
    assert row["expected_file_hit_at_3"] in {True, False}
    assert row["expected_file_hit_at_5"] in {True, False}
    assert row["expected_test_hit_at_5"] in {True, False}
    assert row["expected_primary_node_hit"] in {True, False}
    assert row["packet_hash"]
    assert row["static_prefix_hash"]
    assert row["first_1024_hash"]
    assert isinstance(row["warnings_out_of_band"], list)
    assert row["errors"] == []


def test_cache_mode_can_label_shared_cache_without_mixing_defaults(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    default = run_benchmark(repo, profile="lite")
    shared = run_benchmark(repo, profile="lite", cache_mode="shared_cache")

    assert default["cache_mode"] == "strategy_isolated"
    assert default["shared_cache_measured"] is False
    assert default["cases"][0]["cache_mode"] == "strategy_isolated"
    assert shared["cache_mode"] == "shared_cache"
    assert shared["shared_cache_measured"] is True
    assert shared["cases"][0]["cache_mode"] == "shared_cache"


def test_benchmark_cli_emits_normalized_compile_only_fields(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)

    assert cli.main(["benchmark", "--repo", str(repo), "--profile", "lite", "--plugin", "literal_symbol", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["compile_only"] is True
    assert payload["live_codex_run"] is False
    assert payload["cache_mode"] == "strategy_isolated"
    assert payload["cases"][0]["packet_total_tokens"] == payload["cases"][0]["packet_tokens"]
    assert payload["cases"][0]["live_input_tokens"] is None


def test_v5_literal_symbol_packet_is_unchanged_by_benchmark_semantics(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = compile_prompt(repo, "Fix src/app.py", "lite", **LITERAL_SYMBOL_KWARGS)

    run_benchmark(
        repo,
        profile="lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
    )
    after = compile_prompt(repo, "Fix src/app.py", "lite", **LITERAL_SYMBOL_KWARGS)

    assert after["packet"] == before["packet"]
    for forbidden in ("live_input_tokens", "derived_cache_adjusted_input", "cache_mode", "TASK_CLASS", "SUPPORT_RELATIONS"):
        assert forbidden not in after["packet"]


def test_external_fixture_gate_remains_optional() -> None:
    text = Path("tests/test_locator_option_value_evidence.py").read_text(encoding="utf-8")
    assert "@pytest.mark.external_fixtures" in text
    assert "PREMODE_ENABLE_EXTERNAL_FIXTURES" in text
