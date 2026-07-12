from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Callable, Any

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


EXAMPLE_GAME_PROMPT = (
    "Refine the SwiftUI tutorial and homestead guidance copy around the current "
    "tutorial overlay, Homestead screen, and current UI shell. Keep this to UI "
    "copy/state files. Avoid Docs, Planning_Bundles, ArtSource, animal folders, "
    "Assets.xcassets, generated files, build outputs, DerivedData, .premode, "
    ".agents, signing settings, dependency files, and CI."
)


@dataclass
class StressCase:
    name: str
    prompt: str
    setup: Callable[[Path], None]
    expected_files: set[str]
    expected_context_files: set[str]
    use_repo_map: bool = False


@dataclass
class StressResult:
    case: str
    prompt: str
    expected_files: list[str]
    locator_primary_files: list[str]
    locator_support_files: list[str]
    locator_verification_files: list[str]
    dependency_relations: list[dict[str, Any]]
    compiler_candidate_edit_files: list[str]
    read_only_support_files_count: int
    verification_files: list[str]
    allowed_if_justified: list[str]
    locator_confidence: str
    ambiguity_reasons: list[str]
    context_fit: dict[str, Any]
    candidate_contract_risk: Any
    budget_report: dict[str, Any]
    packet_token_count: int
    expected_selected: bool
    result: str
    notes: list[str]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _prepare(repo: Path) -> None:
    _git(repo, "init")
    init_project(repo)
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def _paths(files: Any) -> list[str]:
    return [str(item.get("path")) for item in files or [] if isinstance(item, dict) and item.get("path")]


def _all_context_paths(result: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for key in ("candidate_edit_files", "likely_edit_files", "read_only_support_files", "related_tests", "suggested_tests"):
        paths.update(_paths(result.get(key)))
    for key in ("full_text_files", "summarized_files", "manifest_only_files"):
        paths.update(_paths((result.get("context_tiers") or {}).get(key)))
    return paths


def _candidate_paths(result: dict[str, Any]) -> list[str]:
    return _paths(result.get("candidate_edit_files"))


def _budget_report(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics") or {}
    caps = result.get("caps") or {}
    packet_budget = ((result.get("evidence_summary") or {}).get("packet_budget_stats") or {})
    return {
        "packet_total_tokens": metrics.get("packet_total_tokens"),
        "hard_packet_token_budget": caps.get("hard_packet_token_budget"),
        "budget_exceeded_by": metrics.get("budget_exceeded_by"),
        "over_budget_reason": metrics.get("over_budget_reason"),
        "full_text_file_count": metrics.get("full_text_file_count"),
        "summary_file_count": metrics.get("summary_file_count"),
        "manifest_file_count": metrics.get("manifest_file_count"),
        "hard_selected_context_token_budget": packet_budget.get("hard_selected_context_token_budget"),
    }


def _compile_case(repo: Path, case: StressCase) -> dict[str, Any]:
    return compile_prompt(
        repo,
        case.prompt,
        "lite",
        use_repo_map=case.use_repo_map,
        cache_optimized=True,
        record=False,
    )


def _common_result(case: StressCase, result: dict[str, Any], notes: list[str]) -> StressResult:
    locator = result.get("locator_evidence") or {}
    candidates = _candidate_paths(result)
    all_context = _all_context_paths(result)
    has_expected_files = bool(case.expected_files or case.expected_context_files)
    expected_selected = (
        True
        if not has_expected_files
        else bool(case.expected_files & set(candidates)) or bool(case.expected_context_files & all_context)
    )
    budget = _budget_report(result)
    budget_ok = not bool(budget.get("budget_exceeded_by"))
    status = "pass" if expected_selected and budget_ok and not notes else "fail"
    return StressResult(
        case=case.name,
        prompt=case.prompt,
        expected_files=sorted(case.expected_files | case.expected_context_files),
        locator_primary_files=_paths(locator.get("primary_files")),
        locator_support_files=_paths(locator.get("support_files")),
        locator_verification_files=_paths(locator.get("verification_files")),
        dependency_relations=list(locator.get("dependency_relations") or [])[:16],
        compiler_candidate_edit_files=candidates,
        read_only_support_files_count=len(result.get("read_only_support_files") or []),
        verification_files=_paths(result.get("related_tests")) + _paths(result.get("suggested_tests")),
        allowed_if_justified=_paths((result.get("patch_boundary") or {}).get("allowed_if_justified")),
        locator_confidence=str(locator.get("confidence") or "low"),
        ambiguity_reasons=list(locator.get("ambiguity_reasons") or []),
        context_fit=((result.get("evidence_summary") or {}).get("locator_context_fit") or {}),
        candidate_contract_risk=result.get("candidate_contract_risk") or (result.get("patch_boundary") or {}).get("candidate_contract_risk"),
        budget_report=budget,
        packet_token_count=int((result.get("metrics") or {}).get("packet_total_tokens") or 0),
        expected_selected=expected_selected,
        result=status,
        notes=notes,
    )


def _assert_contains(paths: set[str], expected: set[str], notes: list[str], label: str) -> None:
    missing = sorted(expected - paths)
    if missing:
        notes.append(f"missing_{label}:{','.join(missing)}")


def _assert_not_candidates(candidates: set[str], blocked: set[str], notes: list[str], label: str) -> None:
    present = sorted(candidates & blocked)
    if present:
        notes.append(f"unexpected_{label}_candidate:{','.join(present)}")


def _validate(case: StressCase, result: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    candidates = set(_candidate_paths(result))
    candidate_order = _candidate_paths(result)
    all_context = _all_context_paths(result)
    locator = result.get("locator_evidence") or {}
    confidence = str(locator.get("confidence") or "low")
    relations = list(locator.get("dependency_relations") or [])

    _assert_contains(candidates | all_context, case.expected_context_files, notes, "context_file")
    _assert_contains(candidates, case.expected_files, notes, "candidate_file")
    if (result.get("metrics") or {}).get("budget_exceeded_by"):
        notes.append("budget_exceeded")

    if case.name == "exampleservice_cli_wording":
        _assert_contains(candidates, case.expected_files, notes, "exampleservice_target")
        _assert_not_candidates(candidates, {"setup.py", "pyproject.toml", "tests/test_exampleservice_cli.py"}, notes, "negative_constraint")
        # A grouped 3-message / 4-file CLI edit is a correct-but-multi-file locate:
        # calibrated confidence of high OR medium is acceptable (fail only if it
        # collapses to low). Reflects Lab 7.2H confidence calibration.
        if confidence == "low":
            notes.append(f"locator_confidence_low:{confidence}")
    elif case.name == "examplegame_swiftui_ui_copy":
        required = {
            "ExampleGame/Views/MainMenuView.swift",
            "ExampleGame/Views/BottomBarView.swift",
            "ExampleGame/Views/HomesteadView.swift",
            "ExampleGame/Views/HomesteadLocationSceneView.swift",
            "ExampleGame/ViewModels/GameSessionViewModel+HomesteadNavigation.swift",
        }
        _assert_contains(candidates, required, notes, "examplegame_swift")
        _assert_contains(candidates | all_context, {"ExampleGame/Views/TutorialOverlayView.swift"}, notes, "examplegame_tutorial_overlay")
    elif case.name == "generic_ui_start_button":
        if not candidates or "src/app/page.tsx" not in candidates:
            notes.append("start_page_not_candidate")
        _assert_not_candidates(set(list(candidates)[:1]), {"src/components/Button.tsx", "src/utils/start.ts", "docs/start-button.md"}, notes, "generic_start")
        if confidence not in {"high", "medium"}:
            notes.append(f"locator_confidence_low:{confidence}")
    elif case.name == "multi_hop_checkout_calculation":
        if not {"src/hooks/useCheckoutTotals.ts", "src/lib/pricing.ts"} & (candidates | all_context):
            notes.append("checkout_helper_cluster_missing")
        _assert_contains(candidates | all_context, {"src/pages/CheckoutPage.tsx", "tests/checkout-flow.test.ts"}, notes, "checkout_context")
        if not relations:
            notes.append("checkout_dependency_relations_missing")
        _assert_not_candidates(set(list(candidates)[:1]), {"docs/checkout.md"}, notes, "checkout_docs")
    elif case.name == "api_route_service_split":
        _assert_contains(candidates | all_context, {"src/api/routes/user_handler.py", "src/services/user_settings.py"}, notes, "api_cluster")
        _assert_not_candidates(set(candidate_order[:1]), {"src/api/routes/index.py"}, notes, "generic_index")
        if not relations:
            notes.append("api_dependency_relations_missing")
    elif case.name == "test_focused_prompt":
        _assert_contains(candidates | all_context, {"tests/test_replay_timeout.py"}, notes, "test_prompt")
        _assert_contains(candidates | all_context, {"src/replay_runner.py"}, notes, "test_source_support")
    elif case.name == "config_package_prompt":
        _assert_contains(candidates, {"pyproject.toml"}, notes, "config_candidate")
        _assert_contains(candidates | all_context, {"src/cli.py"}, notes, "config_source_support")
    elif case.name == "docs_prompt":
        _assert_contains(candidates | all_context, {"README.md", "docs/troubleshooting.md"}, notes, "docs")
    elif case.name == "ci_build_prompt":
        _assert_contains(candidates, {".github/workflows/ci.yml"}, notes, "ci_candidate")
    elif case.name == "migration_database_prompt":
        _assert_contains(candidates, {"migrations/002_user_settings_preference.sql"}, notes, "migration_candidate")
    elif case.name == "low_confidence_ambiguity":
        if confidence == "high":
            notes.append("low_confidence_case_reported_high")
        if not locator.get("ambiguity_reasons"):
            notes.append("low_confidence_ambiguity_reasons_missing")
        weak = {"src/telemetry.py", "src/inventory.py", "src/timeout.py"}
        if len(candidates & weak) > 2:
            notes.append("weak_files_flooded_candidates")
    elif case.name == "secret_transport_hygiene":
        serialized = json.dumps(result.get("locator_evidence") or {}, sort_keys=True)
        if ".env" in all_context or ".env" in serialized or "literal-secret-token" in serialized:
            notes.append("secret_transported")
        _assert_contains(candidates | all_context, {"src/config.py"}, notes, "config_source")
    return notes


def setup_exampleservice(repo: Path) -> None:
    _write(
        repo / "cpp" / "src" / "main.cpp",
        """
        #include <iostream>
        #include <stdexcept>
        void print_usage() {
            std::cerr << "Usage: exampleservice_diag --profile <actuator|power> --input <csv> --output <json>\\n";
        }
        int main(int argc, char** argv) {
            try {
                if (argc < 2) throw std::runtime_error("Missing required argument: --profile");
                std::cout << "Wrote PASS/NONE result to results/output.json\\n";
                return 0;
            } catch (const std::exception& ex) {
                print_usage();
                std::cerr << "Error: " << ex.what() << "\\n";
                return 2;
            }
        }
        """,
    )
    _write(
        repo / "tools" / "run_diagnostic_batch.py",
        "import argparse\n"
        "def run_diagnostic_batch(): return 'diagnostic batch help text CLI wording error status run'\n"
        "if __name__ == '__main__': argparse.ArgumentParser(description='Run diagnostics').parse_args()\n",
    )
    _write(repo / "tools" / "create_demo_outputs.py", "def create_demo_outputs(): return 'demo outputs success status message'\n")
    _write(
        repo / "ros2" / "exampleservice_ros" / "tools" / "export_scenarios_to_csv.py",
        "import argparse\n"
        "def export_scenarios_to_csv(): return 'CSV scenario export help text summary written status message'\n"
        "if __name__ == '__main__': argparse.ArgumentParser(description='Export deterministic scenario CSVs').parse_args()\n",
    )
    _write(repo / "tools" / "build_html_report.py", "import argparse\n")
    _write(repo / "tests" / "test_exampleservice_cli.py", "def test_cli_regression(): pass\n")
    _write(repo / "setup.py", "setup(name='exampleservice')\n")


def setup_examplegame(repo: Path) -> None:
    (repo / "ExampleGame.xcodeproj").mkdir()
    _write(repo / "ExampleGame" / "Views" / "MainMenuView.swift", "struct MainMenuView { var tutorialOverlayVisible = false }\n")
    _write(repo / "ExampleGame" / "Views" / "BottomBarView.swift", "struct BottomBarView { var body: String { \"bar\" } }\n")
    _write(repo / "ExampleGame" / "Views" / "HomesteadView.swift", "struct HomesteadView { var mapGuidance = \"Tap a place\" }\n")
    _write(repo / "ExampleGame" / "Views" / "TutorialOverlayView.swift", "struct TutorialOverlayView { var copy = \"Tap Homestead to continue\" }\n")
    _write(repo / "ExampleGame" / "Views" / "HomesteadLocationSceneView.swift", "struct HomesteadLocationSceneView { var backToMapHint = \"Map\" }\n")
    _write(repo / "ExampleGame" / "Views" / "PannableHomesteadMapView.swift", "struct PannableHomesteadMapView { var zoom = 1 }\n")
    _write(repo / "ExampleGame" / "Views" / "SharedViewStyles.swift", "struct SharedViewStyles {}\n")
    _write(repo / "ExampleGame" / "Views" / "FounderSelectView.swift", "struct FounderSelectView { var body: String { \"founder\" } }\n")
    _write(repo / "ExampleGame" / "Views" / "EventCardView.swift", "struct EventCardView { var body: String { \"event\" } }\n")
    _write(repo / "ExampleGame" / "ViewModels" / "GameSessionViewModel+HomesteadNavigation.swift", "final class GameSessionViewModel { var tutorialState = 0 }\n")
    _write(repo / "ExampleGame" / "Models" / "TutorialState.swift", "struct TutorialState { var step: Int }\n")
    _write(repo / "Docs" / "Planning_Bundles" / "Week_04" / "AGENTS.md", "# Planning\nHistorical planning only.\n")
    _write(repo / "Docs" / "app_reality_alignment.md", "# Reality\nDocs only.\n")


def setup_start(repo: Path) -> None:
    _write(repo / "src" / "app" / "page.tsx", 'export function HomeScreen() { return <main aria-label="Home Screen"><button>Start</button></main> }\n')
    _write(repo / "src" / "components" / "Button.tsx", "export const Button = ({children}) => <button>{children}</button>\n")
    _write(repo / "src" / "screens" / "SettingsScreen.tsx", "export function SettingsScreen(){ return <><button>Save</button><button>Reset</button></> }\n")
    _write(repo / "docs" / "start-button.md", "# Start button\nMove the Start button docs.\n")
    _write(repo / "src" / "utils" / "start.ts", "export function startTimer(){ return Date.now() }\n")


def setup_checkout(repo: Path) -> None:
    _write(repo / "src" / "pages" / "CheckoutPage.tsx", 'import { useCheckoutTotals } from "../hooks/useCheckoutTotals"\nexport function CheckoutPage(){ const total = useCheckoutTotals(); return <span>{total}</span> }\n')
    _write(repo / "src" / "hooks" / "useCheckoutTotals.ts", 'import { calculateDiscountedTotal } from "../lib/pricing"\nexport function useCheckoutTotals(){ return calculateTotal(calculateDiscountedTotal()) }\nexport function calculateTotal(value=0){ return value }\n')
    _write(repo / "src" / "lib" / "pricing.ts", "export function calculateDiscountedTotal(){ return taxTotalWithDiscountRounding() }\n")
    _write(repo / "tests" / "checkout-flow.test.ts", 'import { useCheckoutTotals } from "../src/hooks/useCheckoutTotals"\ntest("checkout total discount", () => {})\n')
    _write(repo / "docs" / "checkout.md", "# Checkout\nCheckout total discount docs.\n")


def setup_api(repo: Path) -> None:
    _write(repo / "src" / "api" / "routes" / "user_handler.py", "from src.services.user_settings import update_user_settings\nROUTE = '/users'\ndef handler(payload): return update_user_settings(payload)\n")
    _write(repo / "src" / "services" / "user_settings.py", "def update_user_settings(payload):\n    if payload is None:\n        raise ValueError('missing update payload')\n")
    _write(repo / "src" / "api" / "routes" / "index.py", "ROUTES = ['/users']\n")
    _write(repo / "tests" / "test_user_settings_api.py", "def test_missing_update_payload(): pass\n")


def setup_replay_test(repo: Path) -> None:
    _write(repo / "tests" / "test_replay_timeout.py", "from src.replay_runner import replay_timeout\ndef test_replay_timeout_expectation(): assert replay_timeout() == 'expected timeout'\n")
    _write(repo / "src" / "replay_runner.py", "def replay_timeout(): return 'timeout'\n")


def setup_config(repo: Path) -> None:
    _write(repo / "pyproject.toml", "[project.scripts]\nexampleservice = 'src.cli:main'\n")
    _write(repo / "src" / "cli.py", "def main(): pass\n")
    _write(repo / "README.md", "Run the exampleservice command.\n")


def setup_docs(repo: Path) -> None:
    _write(repo / "README.md", "# Install\nInstall instructions for the package.\n")
    _write(repo / "docs" / "troubleshooting.md", "# Troubleshooting\nInstall troubleshooting steps.\n")
    _write(repo / "src" / "install.py", "def install_command(): return 'install'\n")


def setup_ci(repo: Path) -> None:
    _write(repo / ".github" / "workflows" / "ci.yml", "name: CI\njobs:\n  test:\n    steps:\n      - run: pytes\n")
    _write(repo / "tests" / "test_smoke.py", "def test_smoke(): assert True\n")
    _write(repo / "src" / "app.py", "def app(): return 1\n")


def setup_migration(repo: Path) -> None:
    _write(repo / "migrations" / "002_user_settings_preference.sql", "ALTER TABLE user_settings ADD COLUMN missing_preference TEXT;\n")
    _write(repo / "src" / "models" / "user_settings.py", "class UserSettings: preference = None\n")
    _write(repo / "src" / "services" / "user_settings.py", "def update_preference(): pass\n")


def setup_low_confidence(repo: Path) -> None:
    _write(repo / "src" / "telemetry.py", "from src.inventory import inventory_helper\n# telemetry helper\n")
    _write(repo / "src" / "inventory.py", "from src.timeout import timeout_helper\n# inventory helper\n")
    _write(repo / "src" / "timeout.py", "# timeout helper\n")


def setup_secret(repo: Path) -> None:
    _write(repo / ".env", "API_TOKEN=literal-secret-token\n")
    _write(repo / "src" / "config.py", "API_TOKEN_ENV = 'API_TOKEN'\ndef load_api_token(): return API_TOKEN_ENV\n")
    _write(repo / "README.md", "API token setup uses the API_TOKEN environment variable.\n")


def stress_cases() -> list[StressCase]:
    return [
        StressCase(
            "exampleservice_cli_wording",
            "Make three small CLI/user-message clarity improvements: one help text, one error message, one success/status message. Do not change packaging. Do not change tests. Run the regression command.",
            setup_exampleservice,
            {"tools/run_diagnostic_batch.py", "tools/create_demo_outputs.py", "ros2/exampleservice_ros/tools/export_scenarios_to_csv.py", "cpp/src/main.cpp"},
            set(),
            use_repo_map=True,
        ),
        StressCase(
            "examplegame_swiftui_ui_copy",
            EXAMPLE_GAME_PROMPT,
            setup_examplegame,
            {
                "ExampleGame/Views/MainMenuView.swift",
                "ExampleGame/Views/BottomBarView.swift",
                "ExampleGame/Views/HomesteadView.swift",
                "ExampleGame/Views/HomesteadLocationSceneView.swift",
                "ExampleGame/ViewModels/GameSessionViewModel+HomesteadNavigation.swift",
            },
            {"ExampleGame/Views/TutorialOverlayView.swift"},
            use_repo_map=True,
        ),
        StressCase("generic_ui_start_button", 'Move the "Start" button on the Home Screen.', setup_start, {"src/app/page.tsx"}, set()),
        StressCase("multi_hop_checkout_calculation", "Fix checkout total calculation when discount is applied.", setup_checkout, set(), {"src/hooks/useCheckoutTotals.ts", "src/lib/pricing.ts"}),
        StressCase("api_route_service_split", "Fix the user settings API handler when the update payload is missing.", setup_api, set(), {"src/api/routes/user_handler.py", "src/services/user_settings.py"}),
        StressCase("test_focused_prompt", "Fix the failing replay timeout test expectation.", setup_replay_test, set(), {"tests/test_replay_timeout.py", "src/replay_runner.py"}),
        StressCase("config_package_prompt", "Fix the console script entry point.", setup_config, {"pyproject.toml"}, {"src/cli.py"}),
        StressCase("docs_prompt", "Clarify README install instructions and troubleshooting.", setup_docs, set(), {"README.md", "docs/troubleshooting.md"}),
        StressCase("ci_build_prompt", "Fix the GitHub Actions build step for the test command.", setup_ci, {".github/workflows/ci.yml"}, set()),
        StressCase("migration_database_prompt", "Update the user settings migration to add the missing preference column.", setup_migration, {"migrations/002_user_settings_preference.sql"}, set()),
        StressCase("low_confidence_ambiguity", "Fix telemetry inventory timeout behavior.", setup_low_confidence, set(), set()),
        StressCase("secret_transport_hygiene", "Update API token config loading.", setup_secret, set(), {"src/config.py"}),
    ]


def run_stress_suite(base_tmp: Path | None = None) -> list[StressResult]:
    results: list[StressResult] = []
    with tempfile.TemporaryDirectory(prefix="lab_7_2e_compile_stress_", dir=base_tmp) as td:
        root = Path(td)
        for case in stress_cases():
            repo = root / case.name
            repo.mkdir(parents=True, exist_ok=True)
            case.setup(repo)
            _prepare(repo)
            compiled = _compile_case(repo, case)
            notes = _validate(case, compiled)
            results.append(_common_result(case, compiled, notes))
    return results


def _status_line(result: StressResult) -> str:
    return (
        f"| {result.case} | {result.result} | {', '.join(result.expected_files) or '-'} | "
        f"{', '.join(result.compiler_candidate_edit_files[:5]) or '-'} | "
        f"{result.locator_confidence} | {result.packet_token_count} | "
        f"{'; '.join(result.notes) or '-'} |"
    )


def render_markdown(results: list[StressResult]) -> str:
    passed = sum(1 for result in results if result.result == "pass")
    failed = len(results) - passed
    ready = failed == 0
    lines = [
        "# Lab 7.2E Compile-Only Stress + Live-Run Readiness",
        "",
        "## 1. Executive summary",
        f"- Cases passed: {passed}/{len(results)}",
        f"- Cases failed: {failed}",
        f"- Live ExampleService comparison readiness: {'ready' if ready else 'not ready'}",
        "- No live Codex run was performed.",
        "- No external repositories were downloaded.",
        "",
        "## 2. Test matrix",
        "| Case | Result | Expected file or area | Candidate edit files | Locator confidence | Packet tokens | Notes |",
        "|---|---|---|---|---|---:|---|",
    ]
    lines.extend(_status_line(result) for result in results)
    lines.extend([
        "",
        "## 3. Pass/fail table",
        "| Case | Expected selected | Result |",
        "|---|---:|---|",
    ])
    lines.extend(f"| {result.case} | {str(result.expected_selected).lower()} | {result.result} |" for result in results)
    lines.extend(["", "## 4. Detailed case results"])
    for result in results:
        lines.extend([
            f"### {result.case}",
            f"- Prompt: {result.prompt}",
            f"- Locator primary: {result.locator_primary_files}",
            f"- Locator support: {result.locator_support_files}",
            f"- Locator verification: {result.locator_verification_files}",
            f"- Dependency relations: {result.dependency_relations}",
            f"- Compiler candidates: {result.compiler_candidate_edit_files}",
            f"- Read-only support count: {result.read_only_support_files_count}",
            f"- Verification files: {result.verification_files}",
            f"- Allowed if justified: {result.allowed_if_justified}",
            f"- Ambiguity reasons: {result.ambiguity_reasons}",
            f"- Context fit: {result.context_fit}",
            f"- Budget: {result.budget_report}",
            f"- Notes: {result.notes or ['none']}",
            "",
        ])
    exampleservice = next(result for result in results if result.case == "exampleservice_cli_wording")
    examplegame = next(result for result in results if result.case == "examplegame_swiftui_ui_copy")
    lines.extend([
        "## 5. ExampleService readiness assessment",
        f"- Result: {exampleservice.result}",
        f"- Candidate files: {exampleservice.compiler_candidate_edit_files}",
        f"- Locator confidence: {exampleservice.locator_confidence}",
        "",
        "## 6. ExampleGame stability assessment",
        f"- Result: {examplegame.result}",
        f"- Candidate files: {examplegame.compiler_candidate_edit_files}",
        f"- Locator confidence: {examplegame.locator_confidence}",
        "",
        "## 7. Token/budget summary",
        "| Case | Packet tokens | Hard budget | Budget exceeded by |",
        "|---|---:|---:|---:|",
    ])
    for result in results:
        budget = result.budget_report
        lines.append(f"| {result.case} | {budget.get('packet_total_tokens')} | {budget.get('hard_packet_token_budget')} | {budget.get('budget_exceeded_by')} |")
    lines.extend([
        "",
        "## 8. Locator confidence summary",
        "| Case | Confidence | Ambiguity reasons |",
        "|---|---|---|",
    ])
    for result in results:
        lines.append(f"| {result.case} | {result.locator_confidence} | {', '.join(result.ambiguity_reasons) or '-'} |")
    lines.extend([
        "",
        "## 9. Residual limitations",
        "- Import extraction remains best-effort and local; it does not use language servers.",
        "- Swift relation extraction still depends mostly on filename/sibling heuristics.",
        "- This pass is compile-only and cannot prove live model edit quality.",
        "",
        "## 10. Recommendation",
        "Ready for controlled live ExampleService comparison." if ready else "Not ready for controlled live ExampleService comparison; resolve failing cases first.",
        "",
    ])
    return "\n".join(lines)


def write_artifacts(results: list[StressResult], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "lab_7_2e_compile_stress_results.json"
    md_path = out_dir / "lab_7_2e_compile_stress_report.md"
    json_path.write_text(json.dumps([asdict(result) for result in results], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(results), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Lab 7.2E compile-only locator readiness stress cases.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Directory for markdown and JSON readiness artifacts.")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or Path("/private/tmp") / f"lab_7_2e_locator_readiness_{int(time.time())}"
    results = run_stress_suite()
    artifacts = write_artifacts(results, out_dir)
    print(json.dumps({"artifacts": artifacts, "results": [asdict(result) for result in results]}, indent=2, sort_keys=True))
    return 0 if all(result.result == "pass" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
