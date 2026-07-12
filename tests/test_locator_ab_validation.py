from __future__ import annotations

import subprocess
from pathlib import Path

import premode.compiler as compiler
from premode.config import init_project
from premode.indexer import index_project
from premode.locator import LocateResult
from premode.context_constraints import classify_path_for_routing
from premode.routing_safety import classify_path_for_routing as legacy_classify_path_for_routing
from tests.test_v2615_swift_source_recovery import PROMPT as EXAMPLE_GAME_PROMPT
from tests.test_v2615_swift_source_recovery import _make_examplegame_like_repo


LOCATOR_DISABLED = LocateResult([], [], [], "low", [], [], ["locator_disabled_for_ab_validation"])


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
    for key in ("full_text_files", "summarized_files", "manifest_only_files"):
        paths.update(_paths((result.get("context_tiers") or {}).get(key) or []))
    return paths


def _compile_pair(repo: Path, prompt: str, *, use_repo_map: bool = False) -> tuple[dict, dict]:
    real_locate = compiler.locate_files
    try:
        compiler.locate_files = lambda *args, **kwargs: LOCATOR_DISABLED
        before = compiler.compile_prompt(repo, prompt, "lite", use_repo_map=use_repo_map, cache_optimized=True, record=False)
        compiler.locate_files = real_locate
        after = compiler.compile_prompt(repo, prompt, "lite", use_repo_map=use_repo_map, cache_optimized=True, record=False)
        return before, after
    finally:
        compiler.locate_files = real_locate


def test_ab_start_button_home_screen_locator_recovers_specific_page(repo: Path) -> None:
    _write(repo / "src" / "app" / "page.tsx", 'export function HomeScreen() { return <button>Start</button> }\n')
    _write(repo / "src" / "components" / "Button.tsx", "export const Button = ({children}) => <button>{children}</button>\n")
    _prepare(repo)

    before, after = _compile_pair(repo, 'Move the "Start" button on the Home Screen.')

    assert "src/app/page.tsx" not in _paths(before["candidate_edit_files"])
    assert "src/app/page.tsx" in _paths(after["candidate_edit_files"])
    assert "src/components/Button.tsx" not in _paths(after["candidate_edit_files"][:1])
    assert after["locator_evidence"]["confidence"] == "high"


def test_ab_replayrunner_generic_filename_locator_recovers_symbol_file(repo: Path) -> None:
    _write(repo / "src" / "main.py", "class ReplayRunner:\n    def timeout_handling(self):\n        return 'timeout handling'\n")
    _write(repo / "src" / "replay.py", "def replay_helper(): return True\n")
    _prepare(repo)

    before, after = _compile_pair(repo, "Fix ReplayRunner timeout handling.")

    assert "src/main.py" not in _paths(before["candidate_edit_files"])
    assert "src/main.py" in _paths(after["candidate_edit_files"])
    assert after["locator_evidence"]["primary_files"][0]["path"] == "src/main.py"
    signals = after["locator_evidence"]["primary_files"][0]["matched_signals"]
    assert "symbol:ReplayRunner" in signals
    assert "content:timeout" in signals


def test_ab_exampleservice_cli_candidate_set_stays_stable(repo: Path) -> None:
    _write(repo / "tools" / "run_diagnostic_batch.py", "import argparse\ndef run_diagnostic_batch(): return 'diagnostic batch CLI wording'\n")
    _write(repo / "tools" / "create_demo_outputs.py", "def create_demo_outputs(): return 'demo outputs created'\n")
    _write(repo / "ros2" / "exampleservice_ros" / "tools" / "export_scenarios_to_csv.py", "def export_scenarios_to_csv(): return 'CSV scenario export output folder'\n")
    _write(repo / "tools" / "build_html_report.py", "import argparse\n")
    _prepare(repo)

    before, after = _compile_pair(
        repo,
        "Update ExampleService CLI wording for diagnostic batch, CSV scenario export, and demo output creation.",
        use_repo_map=True,
    )
    expected = {
        "tools/run_diagnostic_batch.py",
        "tools/create_demo_outputs.py",
        "ros2/exampleservice_ros/tools/export_scenarios_to_csv.py",
    }

    assert expected <= set(_paths(before["candidate_edit_files"]))
    assert expected <= set(_paths(after["candidate_edit_files"]))
    assert after["metrics"]["packet_total_tokens"] <= before["metrics"]["packet_total_tokens"] + 50


def test_ab_examplegame_swiftui_candidate_set_stays_stable(tmp_path: Path) -> None:
    repo = tmp_path
    _make_examplegame_like_repo(repo)
    _git(repo, "init")
    _prepare(repo)

    before, after = _compile_pair(repo, EXAMPLE_GAME_PROMPT, use_repo_map=True)
    expected = {
        "ExampleGame/Views/MainMenuView.swift",
        "ExampleGame/Views/BottomBarView.swift",
        "ExampleGame/Views/HomesteadView.swift",
        "ExampleGame/Views/HomesteadLocationSceneView.swift",
        "ExampleGame/ViewModels/GameSessionViewModel+HomesteadNavigation.swift",
    }

    assert expected <= set(_paths(before["candidate_edit_files"]))
    assert expected <= set(_paths(after["candidate_edit_files"]))
    assert after["metrics"]["packet_total_tokens"] <= before["metrics"]["packet_total_tokens"] + 50


def test_docs_tests_config_ci_and_migrations_are_normal_relevant_artifacts(repo: Path) -> None:
    _write(repo / "README.md", "# Install\nInstall instructions.\n")
    _write(repo / "docs" / "troubleshooting.md", "Troubleshooting install steps.\n")
    _write(repo / "tests" / "test_checkout_flow.py", "def test_checkout_flow(): assert checkout_total() == 10\n")
    _write(repo / "src" / "checkout.py", "def checkout_total(): return 0\n")
    _write(repo / "pyproject.toml", "[project.scripts]\nexampleservice = 'src.cli:main'\n")
    _write(repo / "src" / "cli.py", "def main(): pass\n")
    _write(repo / ".github" / "workflows" / "ci.yml", "name: CI\njobs:\n  test:\n    steps:\n      - run: pytest\n")
    _write(repo / "migrations" / "001_add_inventory.sql", "ALTER TABLE inventory ADD COLUMN timeout INTEGER;\n")
    _prepare(repo)

    docs = compiler.compile_prompt(repo, "Clarify README install instructions and troubleshooting.", "lite", record=False)
    tests = compiler.compile_prompt(repo, "Fix the failing checkout flow test.", "lite", record=False)
    config = compiler.compile_prompt(repo, "Fix the console script entry point.", "lite", record=False)
    ci = compiler.compile_prompt(repo, "Fix the CI workflow pytest command.", "lite", record=False)
    migration = compiler.compile_prompt(repo, "Fix the inventory database migration timeout column.", "lite", record=False)

    assert {"README.md", "docs/troubleshooting.md"} & set(_paths(docs["candidate_edit_files"]))
    assert "tests/test_checkout_flow.py" in _all_context_paths(tests)
    assert "pyproject.toml" in _paths(config["candidate_edit_files"])
    assert ".github/workflows/ci.yml" in _paths(ci["candidate_edit_files"])
    assert "migrations/001_add_inventory.sql" in _paths(migration["candidate_edit_files"])


def test_ab_typescript_ui_and_api_handler_stay_specific(repo: Path) -> None:
    _write(repo / "src" / "pages" / "Profile.tsx", 'export function ProfileScreen() { return <button>Save changes</button> }\n')
    _write(repo / "src" / "components" / "Button.tsx", "export const Button = ({children}) => <button>{children}</button>\n")
    _write(repo / "src" / "api" / "routes" / "user_handler.py", "ROUTE = '/users'\ndef update_user_settings(payload):\n    if payload is None:\n        raise ValueError('missing update payload')\n")
    _write(repo / "src" / "api" / "routes" / "index.py", "ROUTES = ['/users']\n")
    _prepare(repo)

    _before_ui, after_ui = _compile_pair(repo, 'Update the "Save changes" React UI copy on the Profile screen.')
    _before_api, after_api = _compile_pair(repo, "Fix the user settings API handler when the update payload is missing.")

    assert "src/pages/Profile.tsx" in _paths(after_ui["candidate_edit_files"])
    assert "src/components/Button.tsx" not in _paths(after_ui["candidate_edit_files"][:1])
    assert "src/api/routes/user_handler.py" in _paths(after_api["candidate_edit_files"])
    assert "src/api/routes/index.py" not in _paths(after_api["candidate_edit_files"][:1])


def test_low_confidence_ab_does_not_overpromote_weak_split_terms(repo: Path) -> None:
    _write(repo / "src" / "a.py", "# telemetry helper\n")
    _write(repo / "src" / "b.py", "# inventory helper\n")
    _write(repo / "src" / "c.py", "# timeout helper\n")
    _prepare(repo)

    _before, after = _compile_pair(repo, "Fix telemetry inventory timeout behavior.")

    assert after["locator_evidence"]["confidence"] in {"low", "medium"}
    assert after["locator_evidence"]["ambiguity_reasons"]
    assert "terms_split_across_many_files" in after["locator_evidence"]["ambiguity_reasons"]
    assert not ({"src/a.py", "src/b.py", "src/c.py"} & set(_paths(after["candidate_edit_files"])))
    assert after["evidence_summary"]["locator_context_fit"]["confidence"] in {"low", "medium"}


def test_context_constraints_rename_keeps_legacy_import_and_result_fields(repo: Path) -> None:
    assert classify_path_for_routing("src/app.py") == legacy_classify_path_for_routing("src/app.py")
    _write(repo / "src" / "app.py", "def app(): return 1\n")
    _prepare(repo)

    result = compiler.compile_prompt(repo, "Fix src/app.py.", "lite", record=False)

    assert "safety_blocked_files" in result
    assert "prompt_forbidden_files" in result
    assert "locator_evidence" in result
