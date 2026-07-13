from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.benchmark import run_benchmark, format_benchmark_report, load_prompt_cases
from premode.cli import main
from premode.config import init_project
from premode.indexer import index_project


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _prepare(repo: Path) -> None:
    init_project(repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text("from src.app import value\n\ndef test_value():\n    assert value() == 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='bench-demo'\nversion='0.1.0'\n", encoding="utf-8")
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def test_benchmark_runs_prompt_suite_and_reports_metrics(repo):
    _prepare(repo)
    prompts = repo / "benchmark_prompts.json"
    prompts.write_text(json.dumps({
        "prompts": [
            {
                "name": "app_fix",
                "prompt": "Fix src/app.py and run the related tests",
                "expected_files": ["src/app.py"],
                "expected_tests": ["tests/test_app.py"],
            }
        ]
    }), encoding="utf-8")
    report = run_benchmark(repo, prompts_path=prompts, profile="lite", use_repo_map=True, cache_optimized=True)
    assert report["benchmark_kind"] == "premode_benchmark"
    assert report["prompt_count"] == 1
    assert report["summary"]["prompt_count"] == 1
    case = report["cases"][0]
    assert case["packet_version"] == "PREMODE_COMPILED_PACKET_V3"
    assert case["packet_tokens"] > 0
    assert 0 < case["cacheable_prefix_tokens"] < 1024
    assert case["cacheable_prefix_percent"] is not None
    assert case["dynamic_suffix_percent"] is not None
    assert "src/app.py" in case["likely_files"]
    assert case["likely_file_match"]["hit_count"] == 1
    assert case["related_test_match"]["hit_count"] == 1


def test_benchmark_json_out_and_human_format(repo):
    _prepare(repo)
    out = repo / ".premode" / "out" / "benchmark_report.json"
    report = run_benchmark(repo, profile="lite", out_path=out)
    assert out.exists()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["benchmark_kind"] == "premode_benchmark"
    text = format_benchmark_report(report)
    assert "Pre-mode benchmark" in text
    assert "case | status | packet_tokens" in text


def test_benchmark_include_review_counts_pass(repo):
    _prepare(repo)
    prompts = repo / "bench.json"
    prompts.write_text(json.dumps(["Fix src/app.py"]), encoding="utf-8")
    report = run_benchmark(repo, prompts_path=prompts, include_review=True, review_against="HEAD", review_since_compile=True)
    assert report["include_review"] is True
    assert report["cases"][0]["review"]["merge_readiness"] == "pass"
    assert report["summary"]["review_readiness_counts"]["pass"] == 1


def test_cli_benchmark_json(monkeypatch, capsys, repo):
    _prepare(repo)
    monkeypatch.chdir(repo)
    rc = main(["benchmark", "--profile", "lite", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["benchmark_kind"] == "premode_benchmark"
    assert payload["summary"]["prompt_count"] >= 1



def test_benchmark_summary_surfaces_budget_exceeded_prompts(repo, monkeypatch):
    _prepare(repo)
    from premode import benchmark as bench

    def fake_compile_prompt(*args, **kwargs):
        return {
            "packet_version": "PREMODE_COMPILED_PACKET_V3",
            "resource_profile": "lite",
            "packet_mode": "standard",
            "metrics": {
                "eligible_readable_repo_tokens": 100000,
                "packet_total_tokens": 13000,
                "estimated_savings_vs_eligible_repo_percent": 87.0,
                "selected_context_tokens": 2000,
                "policy_metadata_tokens": 9000,
                "budget_exceeded_by": 1000,
            },
            "caps": {"hard_packet_token_budget": 12000},
            "impact_map": {"likely_files": ["src/app.py"], "related_tests": []},
            "cacheable_prefix_tokens": 1500,
            "dynamic_suffix_tokens": 11500,
            "cacheable_prefix_sha256": "a",
            "dynamic_suffix_sha256": "b",
            "repo_map_sha256": "c",
            "compiled_packet_sha256": "d",
        }

    monkeypatch.setattr(bench, "compile_prompt", fake_compile_prompt)
    prompts = repo / "bench.json"
    prompts.write_text(json.dumps([{"name": "too_big", "prompt": "Fix the build"}]), encoding="utf-8")
    report = run_benchmark(repo, prompts_path=prompts)
    assert report["prompt_count"] == 1
    exceeded = report["summary"]["budget_exceeded_prompts"]
    assert exceeded[0]["name"] == "too_big"
    assert exceeded[0]["over_by"] == 1000
    assert exceeded[0]["likely_reason"] == "policy_metadata_or_packet_overhead"


def test_benchmark_guard_warns_on_missing_expectations_and_null_hit_rates(repo, monkeypatch):
    _prepare(repo)
    from premode import benchmark as bench

    def fake_compile_prompt(*args, **kwargs):
        return {
            "packet_version": "PREMODE_COMPILED_PACKET_V3",
            "resource_profile": "lite",
            "packet_mode": "standard",
            "packet_detail_mode": "paths_only",
            "metrics": {"eligible_readable_repo_tokens": 1000, "packet_total_tokens": 100},
            "caps": {"hard_packet_token_budget": 12000},
            "impact_map": {"likely_files": [], "related_tests": []},
            "cacheable_prefix_tokens": 40,
            "dynamic_suffix_tokens": 60,
        }

    monkeypatch.setattr(bench, "compile_prompt", fake_compile_prompt)
    prompts = repo / "bench.json"
    prompts.write_text(json.dumps([{"name": "under_specified", "prompt": "Fix it"}]), encoding="utf-8")

    report = run_benchmark(repo, prompts_path=prompts)
    case = report["cases"][0]
    codes = {item["code"] for item in case["validation_warnings"]}
    assert report["benchmark_status"] == "warning"
    assert case["benchmark_status"] == "warning"
    assert {"missing_expected_files", "missing_expected_tests", "null_likely_file_hit_rate", "null_related_test_hit_rate"} <= codes
    assert case["likely_file_match"]["hit_rate"] is None
    assert case["related_test_match"]["hit_rate"] is None
    assert report["summary"]["validation_warning_count"] == 4


def test_benchmark_guard_fails_on_misses_missing_paths_and_forbidden_primary_files(repo, monkeypatch):
    _prepare(repo)
    from premode import benchmark as bench

    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "plan.md").write_text("# Planning\n", encoding="utf-8")

    def fake_compile_prompt(*args, **kwargs):
        return {
            "packet_version": "PREMODE_COMPILED_PACKET_V3",
            "resource_profile": "lite",
            "packet_mode": "standard",
            "packet_detail_mode": "paths_only",
            "metrics": {"eligible_readable_repo_tokens": 1000, "packet_total_tokens": 100},
            "caps": {"hard_packet_token_budget": 12000},
            "impact_map": {"likely_files": ["docs/plan.md"], "related_tests": []},
            "cacheable_prefix_tokens": 40,
            "dynamic_suffix_tokens": 60,
        }

    monkeypatch.setattr(bench, "compile_prompt", fake_compile_prompt)
    prompts = repo / "bench.json"
    prompts.write_text(json.dumps({
        "prompts": [
            {
                "name": "bad_expectations",
                "prompt": "Fix source, not docs.",
                "expected_files": ["src/app.py", "src/missing.py"],
                "expected_tests": ["tests/test_app.py"],
                "forbidden_primary_files": ["docs/*.md"],
            }
        ]
    }), encoding="utf-8")

    report = run_benchmark(repo, prompts_path=prompts)
    case = report["cases"][0]
    codes = {item["code"] for item in case["validation_failures"]}
    assert report["benchmark_status"] == "fail"
    assert case["benchmark_status"] == "fail"
    assert {"missing_expected_paths", "expected_files_not_routed", "expected_tests_not_routed", "forbidden_primary_files_routed"} <= codes
    assert case["forbidden_file_match"]["hits"] == ["docs/*.md"]
    assert report["summary"]["benchmark_failure_count"] == 1


def test_example_benchmark_suite_has_expected_local_paths_and_requested_categories():
    repo_root = Path(__file__).resolve().parents[1]
    cases, source = load_prompt_cases(repo_root, repo_root / "examples" / "benchmark_prompts.json")
    categories = {case.get("category") for case in cases}
    assert source.endswith("examples/benchmark_prompts.json")
    assert {
        "cli_help",
        "behavior_bug",
        "docs_only",
        "test_only",
        "config",
        "ci_workflow",
        "migration_refactor",
        "swiftui_like_fixture",
        "exampleservice_like_diagnostic_tooling",
        "typo_vague_prompt",
        "docs_heavy_repo_prompt",
    } <= categories
    for case in cases:
        assert case.get("expected_files"), case["name"]
        assert case.get("expected_tests"), case["name"]
        for path in list(case.get("expected_files") or []) + list(case.get("expected_tests") or []):
            assert (repo_root / path).exists(), f"{case['name']} expected missing local path {path}"


def test_benchmark_cache_split_percentages(repo):
    _prepare(repo)
    report = run_benchmark(repo, profile="lite")
    summary = report["summary"]
    assert summary["average_cacheable_prefix_percent"] is not None
    assert summary["average_dynamic_suffix_percent"] is not None
    for case in report["cases"]:
        if not case.get("error"):
            assert case["cacheable_prefix_percent"] is not None
            assert case["dynamic_suffix_percent"] is not None


def test_docs_primary_flow_mentions_since_compile():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "premode review-patch --since-compile" in text
    assert "premode benchmark --profile lite" in text


def test_v265_v27_prompt_exists_but_linter_not_implemented():
    prompt_path = Path("docs/history/codex-prompts/CODEX_ONE_SHOT_PROMPT_v2.7.0.md")
    assert prompt_path.exists()
    text = prompt_path.read_text(encoding="utf-8")
    assert "premode lint-agents" in text
    parser = main.__globals__["build_parser"]()
    subparsers = [a for a in parser._actions if getattr(a, "choices", None)]
    choices = subparsers[0].choices if subparsers else {}
    assert "lint-agents" not in choices


def test_v266_docs_are_current_and_concise():
    readme = Path("README.md").read_text(encoding="utf-8")
    index = Path("docs/history/codex-prompts/FINAL_PACKAGE_INDEX.md").read_text(encoding="utf-8")
    report = Path("docs/history/codex-prompts/IMPLEMENTATION_REPORT.md").read_text(encoding="utf-8")
    assert "0.3.0b1" in readme
    assert "premode review-patch --since-compile" in readme
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q" in readme
    assert "v0.2.6.20" in index
    assert "v0.2.6.18" in report
    assert len(index.splitlines()) < 140
