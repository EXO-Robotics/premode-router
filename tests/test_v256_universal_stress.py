from __future__ import annotations

from pathlib import Path

from premode.stress import run_universal_stress, stress_cases, format_stress_table


def test_universal_stress_cases_cover_expected_matrix() -> None:
    names = {case.name for case in stress_cases()}
    assert {
        "python_src_layout",
        "python_cli_reexport",
        "rust_cli",
        "go_cli",
        "typescript_pnpm_monorepo",
        "swift_ios",
        "native_cpp_scons",
        "mixed_monorepo",
        "control_plane",
        "adversarial_readme_secret",
        "tiny_repo",
    }.issubset(names)


def test_universal_stress_harness_passes_and_reports_scorecard(tmp_path: Path) -> None:
    out = tmp_path / "stress.json"
    report = run_universal_stress(profile="lite", out_path=out)
    assert report["case_count"] >= 10
    assert report["failed"] == 0, report["cases"]
    assert out.exists()
    assert report["output_path"] == str(out)
    table = format_stress_table(report)
    assert "fixture | status | project" in table
    assert "Summary:" in table


def test_universal_stress_report_contains_token_and_boundary_columns() -> None:
    report = run_universal_stress(profile="lite")
    mixed = next(case for case in report["cases"] if case["name"] == "mixed_monorepo")
    assert mixed["task_root"] == "tools/worker"
    assert "tools/worker/src/worker/cli.py" in mixed["allowed_edit_files"]
    assert "frontend/package.json" in mixed["forbidden_without_user_confirmation"]
    assert mixed["packet_total_tokens"] <= 12000
    secret = next(case for case in report["cases"] if case["name"] == "adversarial_readme_secret")
    assert ".env" not in secret["likely_files"]
