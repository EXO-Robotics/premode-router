from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.locator import extract_prompt_evidence, locate_files


RICH_PROMPT = (
    "Improve the CLI help text for choosing an output theme so users understand "
    "what values are allowed and what happens when they pass an invalid theme."
)
ROBOTRIAGE_CLI_PROMPT = (
    "Make the command-line output easier to understand: clarify one help message, "
    "one error message, and one success message. Do not change tests or packaging."
)


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
    paths: set[str] = set()
    for key in ("candidate_edit_files", "likely_edit_files", "read_only_support_files", "related_tests", "suggested_tests"):
        paths.update(_manifest_paths(result.get(key) or []))
    return paths


def _signals(result, path: str) -> list[str]:
    for file in result.primary_files + result.support_files + result.verification_files:
        if file.path == path:
            return file.matched_signals
    return []


def _assert_no_behavior_conclusion(result) -> None:
    forbidden = ("should_error", "should_fallback", "invalid_behavior_expected", "risk")
    signals = [
        signal
        for file in result.primary_files + result.support_files + result.verification_files
        for signal in file.matched_signals
    ]
    assert not any(any(term in signal for term in forbidden) for signal in signals)
    assert not any(any(term in reason for term in forbidden) for reason in result.ambiguity_reasons)


def test_option_declaration_plus_use_site_selects_cli_file_and_test_context(repo: Path) -> None:
    _write(
        repo / "src" / "app" / "__main__.py",
        """
        import click
        from rich.syntax import Syntax

        @click.command()
        @click.option("--theme", default="ansi_dark", metavar="THEME", help="Set syntax theme.")
        def main(theme):
            renderable = Syntax("print('hi')", "python", theme=theme)
            return renderable
        """,
    )
    _write(
        repo / "tests" / "test_theme.py",
        """
        def test_invalid_theme_value_mentions_theme():
            assert "invalid theme"
        """,
    )

    result = locate_files(repo, RICH_PROMPT)

    assert "src/app/__main__.py" in _paths(result.primary_files)
    assert "tests/test_theme.py" in _paths(result.verification_files + result.support_files)
    signals = _signals(result, "src/app/__main__.py")
    assert "option_decl:--theme" in signals
    assert "option_use:theme" in signals
    assert any(signal.startswith("option_default:") for signal in signals)
    assert any("theme" in signal for signal in _signals(result, "tests/test_theme.py"))
    _assert_no_behavior_conclusion(result)


def test_option_declaration_only_reports_missing_invalid_evidence(repo: Path) -> None:
    _write(
        repo / "src" / "cli.py",
        """
        import argparse
        parser = argparse.ArgumentParser(description="Run the tool")
        parser.add_argument("--mode", metavar="MODE", help="Select mode")
        """,
    )

    prompt = "Improve help text for --mode so users understand what happens when they pass an invalid mode."
    evidence = extract_prompt_evidence(prompt)
    result = locate_files(repo, prompt)

    assert "--mode" in evidence.option_flags
    assert "src/cli.py" in _paths(result.primary_files)
    assert "invalid" in result.uncovered_prompt_terms
    signals = _signals(result, "src/cli.py")
    assert "option_decl:--mode" in signals
    assert not any(signal.startswith("option_value_evidence:") for signal in signals)
    _assert_no_behavior_conclusion(result)


def test_explicit_choices_are_option_value_evidence(repo: Path) -> None:
    _write(
        repo / "src" / "cli.py",
        """
        import argparse
        parser = argparse.ArgumentParser(description="Render output")
        parser.add_argument("--format", choices=["json", "text"], help="Output format")
        """,
    )

    result = locate_files(repo, "Clarify the output format help so users know the allowed values.")

    assert "src/cli.py" in _paths(result.primary_files)
    signals = _signals(result, "src/cli.py")
    assert any(signal.startswith("option_choices:") and "json" in signal and "text" in signal for signal in signals)
    assert {"allowed", "values"} <= set(result.covered_prompt_terms)


def test_parser_error_evidence_is_factual_option_signal(repo: Path) -> None:
    _write(
        repo / "tools" / "run_profile.py",
        """
        import argparse
        parser = argparse.ArgumentParser(description="Run profile")
        parser.add_argument("--profile", help="Profile name")

        def validate(profile):
            if profile not in {"actuator", "power"}:
                parser.error("invalid profile")
            return profile
        """,
    )

    result = locate_files(repo, "Clarify the help for --profile so users know invalid profiles fail with an error.")

    assert "tools/run_profile.py" in _paths(result.primary_files)
    signals = _signals(result, "tools/run_profile.py")
    assert "option_decl:--profile" in signals
    assert any(signal.startswith("option_value_evidence:") and "parser.error" in signal for signal in signals)
    assert any(signal.startswith("option_error_handler:") for signal in signals)
    _assert_no_behavior_conclusion(result)


def test_default_fallback_evidence_is_not_behavior_guidance(repo: Path) -> None:
    _write(
        repo / "src" / "theme_cli.py",
        """
        import argparse

        DEFAULT_THEME = "ansi_dark"
        parser = argparse.ArgumentParser(description="Render theme")
        parser.add_argument("--theme", default=DEFAULT_THEME, help="Theme name")

        def resolve_theme(theme):
            try:
                return load_theme(theme)
            except LookupError:
                return DEFAULT_THEME  # fallback default
        """,
    )

    result = locate_files(repo, "Clarify the help for --theme so users know unsupported themes fall back to the default.")

    assert "src/theme_cli.py" in _paths(result.primary_files)
    signals = _signals(result, "src/theme_cli.py")
    assert "option_decl:--theme" in signals
    assert any(signal.startswith("option_value_evidence:") and "fallback" in signal for signal in signals)
    assert any(signal.startswith("option_value_evidence:") and "default" in signal for signal in signals)
    _assert_no_behavior_conclusion(result)


def test_rich_cli_option_value_compile_includes_docs_and_tests_as_evidence(repo: Path) -> None:
    _write(
        repo / "src" / "rich_cli" / "__main__.py",
        """
        import click
        from rich.syntax import Syntax

        @click.command()
        @click.option("--theme", metavar="THEME", default="ansi_dark", help="Set syntax theme.")
        def main(theme):
            renderable = Syntax("print('hi')", "python", theme=theme)
            return renderable
        """,
    )
    _write(
        repo / "README.md",
        """
        # rich-cli

        You can specify a syntax theme with `--theme`.

        rich loop.py --theme dracula

        The default theme is `ansi_dark`.
        """,
    )
    _write(
        repo / "tests" / "test_main.py",
        """
        def test_theme_help_mentions_allowed_values(runner):
            result = runner.invoke(["--help"])
            assert "--theme" in result.output

        def test_invalid_theme_invocation_is_documented(runner):
            result = runner.invoke(["--theme", "not-a-theme", "print('hi')"])
            assert result.exit_code == 0
        """,
    )
    _prepare(repo)

    result = compile_prompt(repo, RICH_PROMPT, "lite", record=False)

    candidates = _manifest_paths(result["candidate_edit_files"])
    all_context = _all_context_paths(result)
    assert "src/rich_cli/__main__.py" in candidates
    assert "README.md" in all_context
    assert "tests/test_main.py" in all_context
    assert "README.md" not in candidates
    assert "tests/test_main.py" not in candidates
    packet = result["packet"]
    assert "should_error" not in packet
    assert "should_fallback" not in packet
    assert "invalid_behavior_expected" not in packet
    locator = result["locator_evidence"]
    emitted_signals = [
        signal
        for section in ("primary_files", "support_files", "verification_files")
        for file in locator[section]
        for signal in file["matched_signals"]
    ]
    assert not any("should_error" in signal or "should_fallback" in signal for signal in emitted_signals)


def test_rich_cli_compile_only_retrieves_theme_option_evidence_if_local_clone_exists() -> None:
    repo = Path("/private/tmp/premode_labs/external_repos/rich-cli")
    if not repo.exists():
        pytest.skip("local Rich-CLI clone not available")

    result = compile_prompt(repo, RICH_PROMPT, "lite", record=False)

    candidates = _manifest_paths(result["candidate_edit_files"])
    assert "src/rich_cli/__main__.py" in candidates
    locator = result["locator_evidence"]
    primary = locator["primary_files"]
    main = next(file for file in primary if file["path"] == "src/rich_cli/__main__.py")
    signals = main["matched_signals"]
    assert "option_decl:--theme" in signals
    assert "option_use:theme" in signals
    assert any(signal.startswith("option_default:") for signal in signals)
    assert any(signal.startswith("option_value_evidence:") for signal in signals)
    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]
    assert "should_error" not in result["packet"]
    assert "should_fallback" not in result["packet"]
    assert "invalid_behavior_expected" not in result["packet"]


def test_robotriage_cli_target_set_stays_stable_with_option_value_evidence(repo: Path) -> None:
    _write(repo / "tools" / "create_demo_outputs.py", "import argparse\np=argparse.ArgumentParser(description='Create demo outputs')\np.add_argument('--out', help='output folder')\nprint('success: demo outputs created')\n")
    _write(repo / "tools" / "run_diagnostic_batch.py", "import argparse\np=argparse.ArgumentParser(description='Run diagnostic batch')\np.add_argument('--profile', help='profile value')\nraise SystemExit('error: missing profile')\nprint('status: complete')\n")
    _write(repo / "cpp" / "src" / "main.cpp", '#include <iostream>\nint main(){ std::cerr << "Usage: robotriage_diag --profile <actuator|power>"; std::cerr << " error: missing profile"; std::cout << "status ok success"; }\n')
    _write(repo / "ros2" / "robotriage_ros" / "tools" / "export_scenarios_to_csv.py", "import argparse\np=argparse.ArgumentParser(description='Export scenario CSVs')\np.add_argument('--output-root', help='output folder')\nraise SystemExit('error: missing scenario')\nprint('success: exported scenarios')\n")
    _write(repo / "ros2" / "robotriage_ros" / "robotriage_ros" / "diagnostic_bridge_node.py", "class DiagnosticBridgeNode: pass\n")
    _write(repo / "tests" / "test_cli.py", "def test_cli(): pass\n")
    _write(repo / "setup.py", "setup(name='robotriage')\n")
    _prepare(repo)

    result = compile_prompt(repo, ROBOTRIAGE_CLI_PROMPT, "lite", record=False)

    candidates = set(_manifest_paths(result["candidate_edit_files"]))
    assert {
        "tools/create_demo_outputs.py",
        "tools/run_diagnostic_batch.py",
        "cpp/src/main.cpp",
        "ros2/robotriage_ros/tools/export_scenarios_to_csv.py",
    } <= candidates
    assert "ros2/robotriage_ros/robotriage_ros/diagnostic_bridge_node.py" not in candidates
    assert "setup.py" not in candidates
    assert not any(path.startswith("tests/") for path in candidates)
    assert "tests/test_cli.py" in _all_context_paths(result)
