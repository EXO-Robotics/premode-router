from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.locator import locate_files


DOCS_PROMPT = "Clarify the setup instructions so a new user knows how to run the diagnostic regression and understand the output."
REPORT_PROMPT = "Improve the generated diagnostic report output so users can understand actuator failures more easily."
REPLAY_PROMPT = "Fix the replay timeout behavior so actuator timeout failures are reported clearly."
REPLAY_WITH_REGRESSION_PROMPT = "Fix the replay timeout behavior so actuator timeout failures are reported clearly and the regression still passes."
CLI_PROMPT = "Make the command-line output easier to understand: clarify one help message, one error message, and one success message. Do not change tests or packaging."


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _prepare(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def _paths(files) -> list[str]:
    return [str(item.get("path")) for item in files if isinstance(item, dict)]


def _all_context_paths(result: dict) -> set[str]:
    paths: set[str] = set()
    for key in ("candidate_edit_files", "likely_edit_files", "read_only_support_files", "related_tests", "suggested_tests"):
        paths.update(_paths(result.get(key) or []))
    return paths


def _make_docs_repo(repo: Path) -> None:
    _write(
        repo / "README.md",
        """
        # ExampleService

        ## Setup
        Install locally, then run the diagnostic regression:
        python3 tests/run_regression_tests.py

        The output summary explains how many diagnostic cases passed.
        """,
    )
    _write(
        repo / "docs" / "troubleshooting.md",
        """
        # Troubleshooting

        If setup fails, rerun the diagnostic regression command and read the
        output. New users should compare the PASS/FAIL output summary.
        """,
    )
    _write(repo / "tools" / "run_diagnostic_batch.py", "import argparse\nprint('diagnostic batch complete')\n")
    _write(repo / "src" / "runtime.py", "def run_runtime_behavior(): return 'diagnostic output'\n")


def _make_artifact_repo(repo: Path) -> None:
    _write(
        repo / "tools" / "build_html_report.py",
        """
        import argparse
        def build_html_report(result):
            return f"<html><h1>Diagnostic report</h1><p>actuator failure: {result['failure']}</p></html>"
        if __name__ == "__main__":
            parser = argparse.ArgumentParser(description="Build generated diagnostic report output")
            parser.add_argument("--result")
        """,
    )
    _write(repo / "reports" / "template.html", "<html><h1>Diagnostic report output</h1><p>actuator failure details</p></html>\n")
    _write(repo / "dashboard" / "streamlit_app.py", "import streamlit as st\nst.write('diagnostic report dashboard output for actuator failures')\n")
    _write(
        repo / "src" / "diagnostic_bridge_node.py",
        """
        class DiagnosticBridgeNode:
            def publish_result(self):
                return {"status": "FAILURE", "message": "actuator timeout failure reported clearly"}
        """,
    )
    _write(
        repo / "src" / "actuator_profile.cpp",
        """
        DiagnosticResult classify_actuator() {
            DiagnosticResult result;
            result.status = "FAILURE";
            return result;
        }
        """,
    )
    _write(repo / "docs" / "replay_timeout.md", "Replay timeout behavior and actuator timeout failure notes.\n")
    _write(repo / "tests" / "run_replay_regression.py", "print('runtime timeout regression passed')\n")


def _make_exampleservice_cli_repo(repo: Path) -> None:
    _write(repo / "tools" / "create_demo_outputs.py", "import argparse\np=argparse.ArgumentParser(description='Create demo outputs')\np.add_argument('--out', help='output folder')\nprint('success: demo outputs created')\n")
    _write(repo / "tools" / "run_diagnostic_batch.py", "import argparse\np=argparse.ArgumentParser(description='Run diagnostic batch')\np.add_argument('--input', help='input folder')\nraise SystemExit('error: missing input')\nprint('status: complete')\n")
    _write(repo / "cpp" / "src" / "main.cpp", '#include <iostream>\nint main(){ std::cerr << "Usage: exampleservice_diag --input <csv>"; std::cerr << " error: missing input"; std::cout << "status ok success"; }\n')
    _write(repo / "ros2" / "exampleservice_ros" / "tools" / "export_scenarios_to_csv.py", "import argparse\np=argparse.ArgumentParser(description='Export scenario CSVs')\np.add_argument('--output', help='output folder')\nraise SystemExit('error: missing scenario')\nprint('success: exported scenarios')\n")
    _write(repo / "ros2" / "exampleservice_ros" / "exampleservice_ros" / "diagnostic_bridge_node.py", "class DiagnosticBridgeNode: pass\n")
    _write(repo / "tests" / "test_cli.py", "def test_cli(): pass\n")
    _write(repo / "setup.py", "setup(name='exampleservice')\n")


def test_docs_setup_prompt_promotes_docs_to_locator_primary_and_compiler_candidate(repo: Path) -> None:
    _make_docs_repo(repo)
    located = locate_files(repo, DOCS_PROMPT)
    primary = {f.path for f in located.primary_files}
    assert {"README.md", "docs/troubleshooting.md"} & primary
    assert "src/runtime.py" not in primary

    _prepare(repo)
    compiled = compile_prompt(repo, DOCS_PROMPT, "lite", record=False)
    candidates = set(_paths(compiled["candidate_edit_files"]))
    assert {"README.md", "docs/troubleshooting.md"} & candidates
    assert "tools/run_diagnostic_batch.py" in _all_context_paths(compiled)


def test_docs_prompt_does_not_promote_docs_for_behavior_task(repo: Path) -> None:
    _make_artifact_repo(repo)
    located = locate_files(repo, REPLAY_PROMPT)
    primary = {f.path for f in located.primary_files}
    assert "docs/replay_timeout.md" not in primary
    assert {"src/diagnostic_bridge_node.py", "src/actuator_profile.cpp"} & primary


def test_report_output_prompt_promotes_report_output_files_to_candidates(repo: Path) -> None:
    _make_artifact_repo(repo)
    located = locate_files(repo, REPORT_PROMPT)
    primary = {f.path for f in located.primary_files}
    assert any(path in primary for path in {"tools/build_html_report.py", "reports/template.html", "dashboard/streamlit_app.py"})

    _prepare(repo)
    compiled = compile_prompt(repo, REPORT_PROMPT, "lite", record=False)
    candidates = set(_paths(compiled["candidate_edit_files"]))
    assert any(path in candidates for path in {"tools/build_html_report.py", "reports/template.html", "dashboard/streamlit_app.py"})
    assert "src/diagnostic_bridge_node.py" in _all_context_paths(compiled)


def test_report_behavior_verb_does_not_promote_report_artifacts(repo: Path) -> None:
    _make_artifact_repo(repo)
    located = locate_files(repo, REPLAY_PROMPT)
    primary = {f.path for f in located.primary_files}
    assert "reports/template.html" not in primary
    assert "tools/build_html_report.py" not in primary
    assert "dashboard/streamlit_app.py" not in primary
    assert {"src/diagnostic_bridge_node.py", "src/actuator_profile.cpp"} & primary


def test_exampleservice_cli_target_set_remains_stable(repo: Path) -> None:
    _make_exampleservice_cli_repo(repo)
    _prepare(repo)
    compiled = compile_prompt(repo, CLI_PROMPT, "lite", record=False)
    candidates = set(_paths(compiled["candidate_edit_files"]))
    assert {
        "tools/create_demo_outputs.py",
        "tools/run_diagnostic_batch.py",
        "cpp/src/main.cpp",
        "ros2/exampleservice_ros/tools/export_scenarios_to_csv.py",
    } <= candidates
    assert "ros2/exampleservice_ros/exampleservice_ros/diagnostic_bridge_node.py" not in candidates
    assert "setup.py" not in candidates
    assert not any(path.startswith("tests/") for path in candidates)


def test_replay_timeout_stability_keeps_report_artifacts_out_of_primary(repo: Path) -> None:
    _make_artifact_repo(repo)
    located = locate_files(repo, REPLAY_WITH_REGRESSION_PROMPT)
    primary = {f.path for f in located.primary_files}
    verification = {f.path for f in located.verification_files}
    assert {"src/diagnostic_bridge_node.py", "src/actuator_profile.cpp"} & primary
    assert not {"tools/build_html_report.py", "reports/template.html", "dashboard/streamlit_app.py"} & primary
    assert any(path.startswith("tests/") for path in verification)
