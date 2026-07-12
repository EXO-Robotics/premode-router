from __future__ import annotations

from pathlib import Path

from premode.locator import locate_files


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _paths(files) -> list[str]:
    return [file.path for file in files]


def _all_paths(result) -> list[str]:
    return _paths(result.primary_files + result.support_files + result.verification_files)


def test_noisy_home_screen_start_button_keeps_specific_page_primary(repo: Path) -> None:
    _write(
        repo / "src" / "app" / "page.tsx",
        """
        export function HomeScreen() {
          return <main aria-label="Home Screen"><button>Start</button></main>
        }
        """,
    )
    _write(repo / "src" / "components" / "Button.tsx", "export const Button = ({children}) => <button>{children}</button>\n")
    _write(
        repo / "src" / "screens" / "SettingsScreen.tsx",
        """
        export function SettingsScreen() {
          return <section><button>Save</button><button>Reset</button><button>Cancel</button></section>
        }
        """,
    )
    _write(repo / "docs" / "start-button.md", "# Start button\nDocs for the Start button.\n")
    _write(repo / "src" / "utils" / "start.ts", "export function startTimer() { return Date.now() }\n")

    result = locate_files(repo, 'Move the "Start" button on the Home Screen.')

    assert result.primary_files[0].path == "src/app/page.tsx"
    assert "src/components/Button.tsx" not in _paths(result.primary_files)
    assert "docs/start-button.md" not in _paths(result.primary_files)
    assert "src/utils/start.ts" not in _paths(result.primary_files)
    assert result.confidence in {"high", "medium"}
    signals = result.primary_files[0].matched_signals
    assert 'quoted_literal:"Start"' in signals
    for term in ["home", "screen", "button"]:
        assert any(signal.endswith(f":{term}") or term in signal for signal in signals)


def test_noisy_checkout_total_calculation_symbol_beats_path_only(repo: Path) -> None:
    _write(
        repo / "src" / "main.py",
        """
        class CheckoutFlow:
            def calculate_total(self, items):
                return sum(item.total for item in items)
        """,
    )
    _write(repo / "src" / "checkout.py", "from .main import CheckoutFlow\n")
    _write(repo / "src" / "utils" / "math.py", "def total(values): return sum(values)\n")
    _write(repo / "docs" / "checkout.md", "Checkout documentation and totals overview.\n")
    _write(repo / "tests" / "test_checkout_flow.py", "def test_checkout_total(): assert calculate_total([]) == 0\n")

    result = locate_files(repo, "Fix CheckoutFlow total calculation.")

    assert result.primary_files[0].path == "src/main.py"
    assert "src/checkout.py" not in _paths(result.primary_files[:1])
    assert "tests/test_checkout_flow.py" in _paths(result.verification_files + result.support_files)
    assert "docs/checkout.md" not in _paths(result.primary_files)
    signals = result.primary_files[0].matched_signals
    assert "symbol:CheckoutFlow" in signals
    assert "content:total" in signals
    assert "content:calculation" in signals


def test_api_route_ambiguity_prefers_user_handler_cluster(repo: Path) -> None:
    _write(repo / "src" / "api" / "routes" / "index.py", 'ROUTES = ["/users", "/settings"]\n')
    _write(
        repo / "src" / "api" / "routes" / "user_handler.py",
        """
        ROUTE = "/users"
        def update_user_settings(payload):
            if payload is None:
                raise ValueError("missing update payload")
        """,
    )
    _write(
        repo / "src" / "api" / "routes" / "settings_handler.py",
        """
        ROUTE = "/settings"
        def read_settings():
            return {}
        """,
    )
    _write(repo / "tests" / "test_user_settings_api.py", "def test_missing_update_payload(): pass\n")

    result = locate_files(repo, "Fix the user settings API handler when the update payload is missing.")

    assert result.primary_files[0].path == "src/api/routes/user_handler.py"
    assert "src/api/routes/settings_handler.py" not in _paths(result.primary_files[:1])
    assert "src/api/routes/index.py" not in _paths(result.primary_files[:1])
    assert "tests/test_user_settings_api.py" in _paths(result.verification_files + result.support_files)
    assert result.confidence in {"high", "medium"}
    assert not {"only_surface_matches", "generic_filename_without_content_evidence"} & set(result.ambiguity_reasons)


def test_docs_are_primary_when_prompt_asks_for_docs(repo: Path) -> None:
    _write(repo / "README.md", "# Install\nInstall instructions for the package.\n")
    _write(repo / "docs" / "troubleshooting.md", "# Troubleshooting\nInstall troubleshooting steps.\n")
    _write(repo / "src" / "install.py", "def install_command(): return 'install'\n")

    result = locate_files(repo, "Clarify README install instructions and troubleshooting.")

    assert result.primary_files[0].role == "docs"
    assert "README.md" in _paths(result.primary_files + result.support_files)
    assert "docs/troubleshooting.md" in _paths(result.primary_files + result.support_files)
    assert "src/install.py" not in _paths(result.primary_files)


def test_tests_can_be_primary_when_prompt_asks_for_test_expectation(repo: Path) -> None:
    _write(
        repo / "tests" / "test_replay_timeout.py",
        "def test_replay_timeout_expectation(): assert replay_timeout() == 'expected timeout'\n",
    )
    _write(repo / "src" / "replay_runner.py", "def replay_timeout(): return 'timeout'\n")

    result = locate_files(repo, "Fix the failing replay timeout test expectation.")

    assert result.primary_files[0].path == "tests/test_replay_timeout.py"
    assert "src/replay_runner.py" in _paths(result.support_files + result.verification_files)


def test_config_can_be_primary_for_console_script_entry_point(repo: Path) -> None:
    _write(repo / "pyproject.toml", "[project.scripts]\nexampleservice = 'src.cli:main'\n")
    _write(repo / "src" / "cli.py", "def main(): pass\n")
    _write(repo / "README.md", "Run the exampleservice command.\n")

    result = locate_files(repo, "Fix the console script entry point.")

    assert result.primary_files[0].path == "pyproject.toml"
    assert result.primary_files[0].role == "config"
    assert "src/cli.py" in _paths(result.support_files + result.verification_files)


def test_low_confidence_when_terms_are_split_across_weak_files(repo: Path) -> None:
    _write(repo / "src" / "a.py", "# telemetry helper\n")
    _write(repo / "src" / "b.py", "# inventory helper\n")
    _write(repo / "src" / "c.py", "# timeout helper\n")

    result = locate_files(repo, "Fix the telemetry inventory timeout behavior.")

    assert result.confidence in {"low", "medium"}
    assert "high" != result.confidence
    reasons = set(result.ambiguity_reasons)
    assert "terms_split_across_many_files" in reasons or any(reason.startswith("uncovered_core_terms:") for reason in reasons)


def test_secret_file_remains_non_transported_in_token_config_prompt(repo: Path) -> None:
    _write(repo / ".env", "API_TOKEN=literal-secret-token\n")
    _write(repo / "src" / "config.py", "API_TOKEN_ENV = 'API_TOKEN'\ndef load_api_token(): return API_TOKEN_ENV\n")
    _write(repo / "README.md", "API token setup uses the API_TOKEN environment variable.\n")

    result = locate_files(repo, "Update API token config loading.")

    assert ".env" not in _all_paths(result)
    assert "src/config.py" in _paths(result.primary_files + result.support_files)
    assert "README.md" in _paths(result.support_files + result.verification_files) or "README.md" not in _all_paths(result)
    assert all("unsafe" not in signal and "forbidden" not in signal for file in result.primary_files + result.support_files for signal in file.matched_signals)
