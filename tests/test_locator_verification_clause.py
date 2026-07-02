from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.locator import extract_prompt_evidence, locate_files


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
    return [file.path for file in files]


def _manifest_paths(items) -> list[str]:
    return [str(item.get("path")) for item in items if isinstance(item, dict)]


def _all_context_paths(result: dict) -> set[str]:
    out: set[str] = set()
    for key in ("candidate_edit_files", "likely_edit_files", "read_only_support_files", "related_tests", "suggested_tests"):
        out.update(_manifest_paths(result.get(key) or []))
    return out


def _write_replay_fixture(repo: Path) -> None:
    _write(
        repo / "src" / "replay_runner.py",
        """
        class ReplayRunner:
            def report_actuator_timeout(self):
                return "actuator timeout failure reported clearly"
        """,
    )
    _write(
        repo / "tests" / "test_replay_timeout.py",
        """
        from src.replay_runner import ReplayRunner
        def test_replay_timeout_expectation():
            assert "timeout" in ReplayRunner().report_actuator_timeout()
        """,
    )
    _write(
        repo / "tests" / "run_replay_regression.py",
        """
        from tests.test_replay_timeout import test_replay_timeout_expectation
        if __name__ == "__main__":
            test_replay_timeout_expectation()
            print("regression passed")
        """,
    )


def test_verification_clause_does_not_make_tests_primary(repo: Path) -> None:
    _write_replay_fixture(repo)
    prompt = "Fix the replay timeout behavior so actuator timeout failures are reported clearly and the regression still passes."

    result = locate_files(repo, prompt)

    assert result.primary_files[0].path == "src/replay_runner.py"
    assert "tests/test_replay_timeout.py" in _paths(result.verification_files + result.support_files)
    assert "tests/run_replay_regression.py" in _paths(result.verification_files + result.support_files)
    assert not any(file.path.startswith("tests/") for file in result.primary_files)
    evidence = extract_prompt_evidence(prompt)
    assert evidence.test_verification_intent
    assert not evidence.test_edit_intent


def test_compile_verification_clause_demotes_tests_from_candidates(repo: Path) -> None:
    _write_replay_fixture(repo)
    _prepare(repo)

    result = compile_prompt(
        repo,
        "Fix the replay timeout behavior so actuator timeout failures are reported clearly and the regression still passes.",
        "lite",
        record=False,
    )

    candidates = _manifest_paths(result["candidate_edit_files"])
    assert "src/replay_runner.py" in candidates
    assert "tests/test_replay_timeout.py" not in candidates
    assert "tests/run_replay_regression.py" not in candidates
    assert {"tests/test_replay_timeout.py", "tests/run_replay_regression.py"} <= _all_context_paths(result)


def test_explicit_test_edit_prompt_still_allows_tests(repo: Path) -> None:
    _write_replay_fixture(repo)
    _prepare(repo)

    result = compile_prompt(repo, "Fix the failing replay timeout test expectation.", "lite", record=False)

    candidates = _manifest_paths(result["candidate_edit_files"])
    assert "tests/test_replay_timeout.py" in candidates
    assert "src/replay_runner.py" in _all_context_paths(result)


def test_add_coverage_prompt_allows_tests(repo: Path) -> None:
    _write_replay_fixture(repo)
    _prepare(repo)

    result = compile_prompt(repo, "Add coverage for actuator timeout regression behavior.", "lite", record=False)

    candidates = _manifest_paths(result["candidate_edit_files"])
    assert any(path.startswith("tests/") for path in candidates)
    assert "src/replay_runner.py" in _all_context_paths(result)


def test_do_not_change_tests_keeps_tests_as_verification_context(repo: Path) -> None:
    _write_replay_fixture(repo)
    _prepare(repo)

    result = compile_prompt(
        repo,
        "Fix the replay timeout error message. Do not change tests. Run the regression after the patch.",
        "lite",
        record=False,
    )

    candidates = _manifest_paths(result["candidate_edit_files"])
    assert "src/replay_runner.py" in candidates
    assert not any(path.startswith("tests/") for path in candidates)
    assert {"tests/test_replay_timeout.py", "tests/run_replay_regression.py"} <= _all_context_paths(result)


def test_cli_wording_with_regression_verification_keeps_runner_read_only(repo: Path) -> None:
    _write(
        repo / "tools" / "run_diagnostic_batch.py",
        """
        import argparse
        parser = argparse.ArgumentParser(description="Run diagnostic batch")
        def main():
            raise RuntimeError("diagnostic error message")
        """,
    )
    _write(repo / "tests" / "run_regression_tests.py", "print('diagnostic regression passed')\n")
    _prepare(repo)

    result = compile_prompt(
        repo,
        "Clarify the CLI error message and run the diagnostic regression command afterward.",
        "lite",
        record=False,
    )

    candidates = _manifest_paths(result["candidate_edit_files"])
    assert "tools/run_diagnostic_batch.py" in candidates
    assert "tests/run_regression_tests.py" not in candidates
    assert "tests/run_regression_tests.py" in _all_context_paths(result)


def test_regression_runner_edit_prompt_allows_runner_candidate(repo: Path) -> None:
    _write_replay_fixture(repo)
    _prepare(repo)

    result = compile_prompt(repo, "Repair the regression runner so it reports failures correctly.", "lite", record=False)

    candidates = _manifest_paths(result["candidate_edit_files"])
    assert "tests/run_replay_regression.py" in candidates
