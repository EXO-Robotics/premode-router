from __future__ import annotations

import json
from pathlib import Path

from premode.benchmark import run_benchmark


def _write_fixture_paths(repo: Path) -> None:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text("def test_value():\n    assert True\n", encoding="utf-8")


def _fake_compile(likely_files: list[str], related_tests: list[str]):
    def compile_prompt(*args, **kwargs):
        return {
            "packet_version": "PREMODE_COMPILED_PACKET_V3",
            "resource_profile": "lite",
            "packet_mode": "standard",
            "packet_detail_mode": "paths_only",
            "metrics": {"eligible_readable_repo_tokens": 1000, "packet_total_tokens": 100},
            "caps": {"hard_packet_token_budget": 12000},
            "impact_map": {"likely_files": likely_files, "related_tests": related_tests},
            "cacheable_prefix_tokens": 40,
            "dynamic_suffix_tokens": 60,
        }

    return compile_prompt


def _write_prompts(repo: Path) -> Path:
    prompts = repo / "bench.json"
    prompts.write_text(
        json.dumps({
            "prompts": [{
                "name": "app_case",
                "prompt": "Fix src/app.py and verify tests/test_app.py.",
                "expected_files": ["src/app.py"],
                "expected_tests": ["tests/test_app.py"],
            }]
        }),
        encoding="utf-8",
    )
    return prompts


def test_lab73o_reports_nonzero_precision_and_summary_metrics(repo, monkeypatch):
    _write_fixture_paths(repo)
    from premode import benchmark as bench

    monkeypatch.setattr(
        bench,
        "compile_prompt",
        _fake_compile(
            ["src/app.py", "src/extra.py"],
            ["tests/test_app.py", "tests/test_extra.py"],
        ),
    )

    report = run_benchmark(repo, prompts_path=_write_prompts(repo))
    case = report["cases"][0]
    summary = report["summary"]

    assert report["benchmark_status"] == "pass"
    assert case["likely_file_precision"] == 0.5
    assert case["likely_file_recall"] == 1.0
    assert case["related_test_precision"] == 0.5
    assert case["related_test_recall"] == 1.0
    assert case["likely_file_extra_count"] == 1
    assert case["related_test_extra_count"] == 1
    assert case["likely_file_selected_count"] == 2
    assert case["related_test_selected_count"] == 2
    assert summary["macro_likely_file_precision"] == 0.5
    assert summary["micro_likely_file_precision"] == 0.5
    assert summary["macro_related_test_precision"] == 0.5
    assert summary["micro_related_test_precision"] == 0.5
    assert summary["average_likely_file_extra_count"] == 1.0
    assert summary["average_related_test_extra_count"] == 1.0


def test_lab73o_zero_selected_sets_have_null_precision(repo, monkeypatch):
    _write_fixture_paths(repo)
    from premode import benchmark as bench

    monkeypatch.setattr(bench, "compile_prompt", _fake_compile([], []))

    report = run_benchmark(repo, prompts_path=_write_prompts(repo))
    case = report["cases"][0]

    assert case["likely_file_precision"] is None
    assert case["related_test_precision"] is None
    assert case["likely_file_recall"] == 0.0
    assert case["related_test_recall"] == 0.0
    assert case["likely_file_selected_count"] == 0
    assert case["related_test_selected_count"] == 0


def test_lab73o_precision_and_broad_warnings_do_not_fail_benchmark(repo, monkeypatch):
    _write_fixture_paths(repo)
    from premode import benchmark as bench

    broad_likely = ["src/app.py"] + [f"src/extra_{i}.py" for i in range(9)]
    broad_tests = ["tests/test_app.py"] + [f"tests/test_extra_{i}.py" for i in range(9)]
    monkeypatch.setattr(bench, "compile_prompt", _fake_compile(broad_likely, broad_tests))

    report = run_benchmark(repo, prompts_path=_write_prompts(repo))
    case = report["cases"][0]
    summary = report["summary"]
    warnings_by_code = {item["code"]: item for item in case["validation_warnings"]}

    assert report["benchmark_status"] == "warning"
    assert summary["benchmark_failure_count"] == 0
    assert case["validation_failures"] == []
    assert {
        "low_likely_file_precision",
        "low_related_test_precision",
        "broad_likely_file_selection",
        "broad_related_test_selection",
    } <= set(warnings_by_code)
    assert warnings_by_code["low_likely_file_precision"]["precision"] == 0.1
    assert warnings_by_code["low_likely_file_precision"]["threshold"] == 0.25
    assert warnings_by_code["low_related_test_precision"]["precision"] == 0.1
    assert warnings_by_code["low_related_test_precision"]["threshold"] == 0.2
    assert case["expected_file_hit_but_low_precision"] is True
    assert case["expected_test_hit_but_low_precision"] is True
    assert case["likely_file_precision_warning"] is True
    assert case["related_test_precision_warning"] is True
    assert case["broad_likely_files_warning"] is True
    assert case["broad_related_tests_warning"] is True
    assert warnings_by_code["broad_likely_file_selection"]["selected_count"] == 10
    assert warnings_by_code["broad_related_test_selection"]["selected_count"] == 10
    assert summary["max_likely_file_selected_count"] == 10
    assert summary["max_related_test_selected_count"] == 10
    assert summary["broad_likely_file_case_count"] == 1
    assert summary["broad_related_test_case_count"] == 1
