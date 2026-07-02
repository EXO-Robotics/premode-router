from __future__ import annotations

from pathlib import Path

from premode.locator import extract_prompt_evidence, locate_files


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _paths(files) -> list[str]:
    return [file.path for file in files]


def _all_paths(result) -> list[str]:
    return _paths(result.primary_files + result.support_files + result.verification_files)


def test_ui_generic_button_filename_loses_to_literal_home_screen(repo: Path) -> None:
    _write(
        repo / "src" / "app" / "page.tsx",
        """
        export function HomeScreen() {
          return <main><button>Start</button></main>
        }
        """,
    )
    _write(repo / "src" / "components" / "Button.tsx", "export const Button = () => <button />\n")

    result = locate_files(repo, 'Move the "Start" button on the Home Screen.')

    assert result.primary_files[0].path == "src/app/page.tsx"
    assert "src/components/Button.tsx" not in _paths(result.primary_files[:1])
    signals = result.primary_files[0].matched_signals
    assert 'quoted_literal:"Start"' in signals
    assert any(signal in signals for signal in ["content:screen", "symbol:HomeScreen", "symbol_term:HomeScreen"])


def test_cli_export_error_uses_literal_and_domain_terms(repo: Path) -> None:
    _write(
        repo / "tools" / "export_csv.py",
        """
        import argparse
        def export_csv(output_folder):
            raise ValueError("output folder is missing")
        parser = argparse.ArgumentParser(description="CSV export")
        """,
    )
    _write(repo / "tools" / "build_html_report.py", "import argparse\nparser = argparse.ArgumentParser()\n")

    result = locate_files(repo, "Improve the CSV export error message when the output folder is missing.")

    assert result.primary_files[0].path == "tools/export_csv.py"
    assert "tools/build_html_report.py" not in _paths(result.primary_files[:1])
    signals = result.primary_files[0].matched_signals
    for term in ["csv", "export", "output", "folder", "error"]:
        assert any(signal.endswith(f":{term}") for signal in signals)


def test_generic_api_handler_prefers_specific_user_settings_file(repo: Path) -> None:
    _write(
        repo / "src" / "api" / "routes" / "user_handler.py",
        """
        ROUTE = "/users"
        def update_user_settings(payload):
            if payload is None:
                raise ValueError("missing update payload")
        """,
    )
    _write(repo / "src" / "api" / "routes" / "index.py", 'ROUTES = ["/users"]\n')

    result = locate_files(repo, "Fix the user settings API handler when the update payload is missing.")

    assert result.primary_files[0].path == "src/api/routes/user_handler.py"
    assert "src/api/routes/index.py" not in _paths(result.primary_files[:1])
    signals = result.primary_files[0].matched_signals
    for term in ["user", "settings", "update", "payload", "missing"]:
        assert any(signal.endswith(f":{term}") for signal in signals)


def test_regression_behavior_puts_source_primary_and_test_verification(repo: Path) -> None:
    _write(
        repo / "src" / "replay" / "replay_runner.py",
        """
        class ReplayRunner:
            def handle_actuator_timeout(self):
                return "actuator timeout"
        """,
    )
    _write(repo / "tests" / "test_replay_timeout.py", "from src.replay.replay_runner import ReplayRunner\n")

    result = locate_files(repo, "Fix the replay regression failing on actuator timeout.")

    assert result.primary_files[0].path == "src/replay/replay_runner.py"
    assert "tests/test_replay_timeout.py" in _paths(result.verification_files + result.support_files)
    signals = result.primary_files[0].matched_signals
    for term in ["replay", "actuator", "timeout"]:
        assert any(signal.endswith(f":{term}") or signal == "symbol:ReplayRunner" for signal in signals)


def test_docs_prompt_can_select_docs_as_primary(repo: Path) -> None:
    _write(repo / "README.md", "# Install\nRun the install command.\n")
    _write(repo / "docs" / "troubleshooting.md", "Troubleshooting install issues.\n")
    _write(repo / "src" / "main.py", "def main(): pass\n")

    result = locate_files(repo, "Clarify README install instructions and troubleshooting.")

    assert result.primary_files[0].role == "docs"
    assert "README.md" in _all_paths(result)
    assert "docs/troubleshooting.md" in _all_paths(result)
    assert "src/main.py" not in _paths(result.primary_files)


def test_negative_constraints_downrank_tests_and_packaging(repo: Path) -> None:
    _write(repo / "tools" / "export_csv.py", 'def export_csv(): raise ValueError("export error")\n')
    _write(repo / "tests" / "test_export_csv.py", "def test_export_csv(): pass\n")
    _write(repo / "setup.py", "entry_points={'console_scripts': []}\n")

    evidence = extract_prompt_evidence("Improve the CSV export error message. Do not edit tests or packaging.")
    result = locate_files(repo, "Improve the CSV export error message. Do not edit tests or packaging.")

    assert "tests" in evidence.negative_terms
    assert "packaging" in evidence.negative_terms
    assert result.primary_files[0].path == "tools/export_csv.py"
    assert "tests/test_export_csv.py" not in _paths(result.primary_files)
    assert "setup.py" not in _paths(result.primary_files)


def test_generic_filename_can_win_with_symbol_and_content(repo: Path) -> None:
    _write(
        repo / "main.py",
        """
        class ReplayRunner:
            def timeout_handling(self):
                return "timeout handling"
        """,
    )
    _write(repo / "replay.py", "from main import ReplayRunner\n")

    result = locate_files(repo, "Fix ReplayRunner timeout handling.")

    assert result.primary_files[0].path == "main.py"
    signals = result.primary_files[0].matched_signals
    assert "symbol:ReplayRunner" in signals
    assert "content:timeout" in signals


def test_tests_are_normal_repo_artifacts_when_prompt_asks_for_test(repo: Path) -> None:
    _write(repo / "tests" / "test_checkout_flow.py", "def test_checkout_flow(): assert checkout_total() == 10\n")
    _write(repo / "src" / "checkout.py", "def checkout_total(): return 0\n")

    result = locate_files(repo, "Fix the failing checkout flow test.")

    assert "tests/test_checkout_flow.py" in _paths(result.primary_files + result.verification_files)
    assert all(file.role != "secret" for file in result.primary_files)


def test_config_is_normal_repo_artifact_for_entry_point_prompt(repo: Path) -> None:
    _write(repo / "pyproject.toml", "[project.scripts]\nrobotriage = 'src.cli:main'\n")
    _write(repo / "src" / "cli.py", "def main(): pass\n")

    result = locate_files(repo, "Fix the console script entry point.")

    assert result.primary_files[0].path == "pyproject.toml"
    assert result.primary_files[0].role == "config"


def test_secret_files_are_not_transported(repo: Path) -> None:
    _write(repo / ".env", "API_TOKEN=super-secret-token\n")
    _write(repo / "src" / "config.py", "API_TOKEN_ENV = 'API_TOKEN'\ndef load_config(): return API_TOKEN_ENV\n")

    result = locate_files(repo, "Update config loading for the API token.")

    assert ".env" not in _all_paths(result)
    assert result.primary_files[0].path == "src/config.py"


def test_explicit_path_wins(repo: Path) -> None:
    _write(repo / "src" / "auth" / "login.ts", "export const login = () => null\n")
    _write(repo / "src" / "auth" / "session.ts", "export function refreshToken() { return 'token refresh' }\n")

    result = locate_files(repo, "Update src/auth/session.ts to clarify token refresh handling.")

    assert result.primary_files[0].path == "src/auth/session.ts"
    assert "explicit_path:src/auth/session.ts" in result.primary_files[0].matched_signals
    assert result.confidence == "high"


def test_symbol_match_beats_path_only(repo: Path) -> None:
    _write(
        repo / "src" / "main.py",
        """
        class CheckoutFlow:
            def total_calculation(self):
                return "total calculation"
        """,
    )
    _write(repo / "src" / "checkout.py", "from .main import CheckoutFlow\n")

    result = locate_files(repo, "Fix CheckoutFlow total calculation.")

    assert result.primary_files[0].path == "src/main.py"
    signals = result.primary_files[0].matched_signals
    assert "symbol:CheckoutFlow" in signals
    assert "content:total" in signals or "content:calculation" in signals
