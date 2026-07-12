from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.cli import main as premode_main
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


PROMPT = (
    "Make three small CLI/user-message clarity improvements: one help text, one error message, "
    "one success/status message. Do not change packaging. Do not change tests. "
    "After the patch, run the regression command."
)
COMBINED_NEGATIVE_PROMPT = (
    "Make the command-line output easier to understand: clarify one help message, one error message, "
    "and one success message. Do not change tests or packaging."
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


def _paths(items) -> list[str]:
    return [str(item.get("path")) for item in items if isinstance(item, dict)]


def _all_context_paths(result: dict) -> set[str]:
    paths: set[str] = set()
    for key in ("candidate_edit_files", "likely_edit_files", "read_only_support_files", "related_tests", "suggested_tests"):
        paths.update(_paths(result.get(key) or []))
    for key in ("full_text_files", "summarized_files", "manifest_only_files"):
        paths.update(_paths((result.get("context_tiers") or {}).get(key) or []))
    return paths


def _make_exampleservice_like_repo(repo: Path) -> None:
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
                std::cout << "PASS NONE -> results/output.json\\n";
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
        """
        import argparse
        import subprocess
        import sys

        def main():
            parser = argparse.ArgumentParser(description="Run ExampleService diagnostics over generated samples.")
            parser.add_argument("--executable", help="Path to exampleservice_diag")
            args = parser.parse_args()
            completed = subprocess.run([args.executable or "exampleservice_diag"], text=True, capture_output=True)
            print(completed.stdout.strip())
            if completed.returncode != 0:
                print("exampleservice_diag failed", file=sys.stderr)
                return completed.returncode
            return 0
        if __name__ == "__main__":
            raise SystemExit(main())
        """,
    )
    _write(
        repo / "tools" / "create_demo_outputs.py",
        """
        import subprocess

        def run(cmd):
            print("$ " + " ".join(cmd))
            subprocess.run(cmd, check=True)

        def main():
            run(["exampleservice_diag"])
            print("\\nSuccess: demo outputs created.")
            print("Result: results/actuator_result.json")
            print("Report: reports/actuator_report.html")
            return 0
        if __name__ == "__main__":
            raise SystemExit(main())
        """,
    )
    _write(
        repo / "ros2" / "exampleservice_ros" / "tools" / "export_scenarios_to_csv.py",
        """
        import argparse

        def main():
            parser = argparse.ArgumentParser(description="Export deterministic scenario CSVs for ExampleService classification.")
            parser.add_argument("--config", help="Scenario YAML config path.")
            parser.add_argument("--output-root", help="Output root for generated scenario CSVs.")
            parser.parse_args()
            print("[EXPORT] actuator_healthy: ros_runs/out.csv")
            print("Summary written: ros_runs/summary.json")
            return 0
        if __name__ == "__main__":
            raise SystemExit(main())
        """,
    )
    _write(
        repo / "ros2" / "exampleservice_ros" / "exampleservice_ros" / "diagnostic_bridge_node.py",
        """
        import subprocess
        import rclpy

        class DiagnosticBridgeNode:
            def __init__(self):
                self.last_result_message = None
            def get_logger(self):
                return self
            def error(self, text):
                pass
            def _run_bridge_classification(self):
                completed = subprocess.run(["exampleservice_diag"], text=True, capture_output=True)
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "exampleservice_diag failed")
                self.get_logger().error("M3 diagnostic bridge failed")
            def _diagnostic_array_for_error(self, error_message):
                return {"status": "ERROR", "message": "M3 bridge incomplete or runtime error", "error": error_message}
        """,
    )
    _write(repo / "tools" / "build_html_report.py", "import argparse\nparser = argparse.ArgumentParser(description='Build HTML report')\n")
    _write(repo / "docs" / "notes.md", "CLI user-message regression command status success text.\n")
    _write(repo / "tests" / "run_regression_tests.py", "print('Summary: 11/11 diagnostic cases passed.')\n")
    _write(repo / "pyproject.toml", "[project]\nname='exampleservice'\n")
    _write(repo / "ros2" / "exampleservice_ros" / "setup.py", "from setuptools import setup\nsetup(name='exampleservice_ros')\n")
    _prepare(repo)


def _make_homestead_next_action_repo(repo: Path) -> None:
    _write(repo / "ExampleGame.xcodeproj" / "project.pbxproj", "// !$*UTF8*$!\n")
    _write(
        repo / "ExampleGame" / "Views" / "HomesteadView.swift",
        """
        import SwiftUI

        struct HomesteadView: View {
            @ObservedObject var viewModel: GameSessionViewModel
            @State private var isShowingTodayPlan = false

            var body: some View {
                VStack {
                    PannableHomesteadMapView(markers: viewModel.mapMarkers)
                    Button("Today") { isShowingTodayPlan = true }
                    if isShowingTodayPlan {
                        TodayPlanView(plan: viewModel.todayPlan)
                    }
                }
            }
        }
        """,
    )
    _write(
        repo / "ExampleGame" / "Views" / "TodayPlanView.swift",
        """
        import SwiftUI

        struct TodayPlanView: View {
            let plan: TodayPlan

            var body: some View {
                VStack {
                    Text("Today in ExampleGame")
                    ForEach(plan.requiredItems) { item in
                        Text(item.text)
                    }
                }
            }
        }
        """,
    )
    _write(
        repo / "ExampleGame" / "ViewModels" / "GameSessionViewModel+TodayPlan.swift",
        """
        import Foundation

        struct TodayPlanItem: Identifiable {
            let id = UUID()
            let text: String
        }

        struct TodayPlan {
            let requiredItems: [TodayPlanItem]
        }

        extension GameSessionViewModel {
            var todayPlan: TodayPlan {
                TodayPlan(requiredItems: todayPlanRequiredItems())
            }

            private func todayPlanRequiredItems() -> [TodayPlanItem] {
                [TodayPlanItem(text: "Help Eli settle the homestead.")]
            }
        }
        """,
    )
    _write(
        repo / "ExampleGame" / "Views" / "PannableHomesteadMapView.swift",
        """
        import SwiftUI

        struct PannableHomesteadMapView: View {
            let markers: [HomesteadMapMarker]
            var body: some View { Text("Homestead map") }
        }
        """,
    )
    _write(repo / "ExampleGame" / "ViewModels" / "GameSessionViewModel.swift", "final class GameSessionViewModel: ObservableObject { var mapMarkers: [HomesteadMapMarker] = [] }\n")
    _write(repo / "ExampleGame" / "Models" / "HomesteadMapMarker.swift", "struct HomesteadMapMarker {}\n")
    _write(repo / "ExampleGame" / "Views" / "PlayerActivities" / "StarterMinigames" / "ChopWoodGameEngine.swift", "struct ChopWoodGameEngine { var nextActionResult = \"action result\" }\n")
    _write(repo / "Docs" / "ExampleGame_Rough_Screen_Mockups_v1.md", "Homestead screen notes mention today and the next action.\n")
    _prepare(repo)


def test_exampleservice_live_parity_prompt_selects_cli_surfaces_not_runtime_node(repo: Path) -> None:
    _make_exampleservice_like_repo(repo)

    result = compile_prompt(repo, PROMPT, "lite", use_repo_map=True, cache_optimized=True, record=False)

    candidates = _paths(result["candidate_edit_files"])
    assert "cpp/src/main.cpp" in candidates
    assert "tools/run_diagnostic_batch.py" in candidates
    assert "tools/create_demo_outputs.py" in candidates
    assert "ros2/exampleservice_ros/exampleservice_ros/diagnostic_bridge_node.py" not in candidates
    assert "ros2/exampleservice_ros/tools/export_scenarios_to_csv.py" in _all_context_paths(result)
    assert any(
        "cli_entrypoint" in signal
        for file in result["locator_evidence"]["primary_files"]
        for signal in file["matched_signals"]
    )
    prompt_forbidden = set(_paths(result["prompt_forbidden_files"]))
    assert "tests/**" in prompt_forbidden
    assert "setup.py" in prompt_forbidden
    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]


def test_exampleservice_packet_keeps_locator_metadata_out_of_model_facing_prompt(repo: Path) -> None:
    _make_exampleservice_like_repo(repo)

    result = compile_prompt(repo, PROMPT, "lite", use_repo_map=True, cache_optimized=True, record=False)
    packet = result["packet"]

    assert "locator_evidence" not in packet
    assert "dependency_relations" not in packet
    assert "last_context_manifest.json" in packet
    assert "Summary: 11/11 diagnostic cases passed" not in packet
    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]


def test_exampleservice_combined_tests_or_packaging_constraint_keeps_targets(repo: Path) -> None:
    _make_exampleservice_like_repo(repo)

    result = compile_prompt(repo, COMBINED_NEGATIVE_PROMPT, "lite", use_repo_map=True, cache_optimized=True, record=False)

    candidates = _paths(result["candidate_edit_files"])
    assert "cpp/src/main.cpp" in candidates
    assert "tools/run_diagnostic_batch.py" in candidates
    assert "tools/create_demo_outputs.py" in candidates
    assert "ros2/exampleservice_ros/tools/export_scenarios_to_csv.py" in candidates
    assert "ros2/exampleservice_ros/exampleservice_ros/diagnostic_bridge_node.py" not in candidates
    assert not any(path.startswith("tests/") or "/tests/" in path for path in candidates)
    assert "pyproject.toml" not in candidates
    prompt_forbidden = set(_paths(result["prompt_forbidden_files"]))
    assert "tests/**" in prompt_forbidden
    assert "setup.py" in prompt_forbidden


def test_examplegame_homestead_next_action_prompt_promotes_today_plan_sources(repo: Path) -> None:
    _make_homestead_next_action_repo(repo)

    result = compile_prompt(
        repo,
        "Make the homestead screen clearer about what I should do next today. "
        "I want the next important action to be obvious without adding a lot of extra text.",
        "lite",
        use_repo_map=True,
        cache_optimized=True,
        record=False,
    )

    candidates = set(_paths(result["candidate_edit_files"]))
    assert candidates
    assert "ExampleGame/Views/HomesteadView.swift" in candidates
    assert "ExampleGame/Views/TodayPlanView.swift" in candidates
    assert "ExampleGame/ViewModels/GameSessionViewModel+TodayPlan.swift" in candidates
    assert "ExampleGame.xcodeproj/project.pbxproj" not in candidates
    assert not any("Minigames" in path or "GameEngine.swift" in path for path in candidates)
    support = _all_context_paths(result)
    assert "Docs/ExampleGame_Rough_Screen_Mockups_v1.md" in support
    diagnostics = result["routing_filter_diagnostics"]
    assert diagnostics["source_recovery_attempted"] is True
    assert diagnostics["safe_candidate_count"] >= 4


def test_debug_env_reports_active_local_package(capsys) -> None:
    assert premode_main(["debug-env"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["premode_import_path"].endswith("src/premode/cli.py")
    assert payload["compiler_path"].endswith("src/premode/compiler.py")
    assert payload["locator_path"].endswith("src/premode/locator.py")
    assert payload["locator_integration_enabled"] is True
    assert payload["dependency_proximity_enabled"] is True
    assert payload["context_constraints_available"] is True
