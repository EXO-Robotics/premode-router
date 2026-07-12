from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.locator import extract_prompt_evidence, locate_files


REPLAY_PROMPT = "Fix the replay timeout behavior so actuator timeout failures are reported clearly and the regression still passes."


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


def _write_replay_runtime_fixture(repo: Path) -> None:
    _write(
        repo / "ros2" / "exampleservice_ros" / "exampleservice_ros" / "scenario_loader.py",
        """
        import yaml

        def load_replay_scenarios(path):
            data = yaml.safe_load(open(path))
            return [
                {"name": "actuator_timeout", "replay": True, "timeout": row["timeout"]}
                for row in data["scenarios"]
            ]
        """,
    )
    _write(
        repo / "ros2" / "exampleservice_ros" / "exampleservice_ros" / "replay_runner.py",
        """
        from .diagnostic_result import build_timeout_failure_result

        class ReplayRunner:
            def execute_replay(self, scenario):
                if scenario.get("actuator") == "timeout":
                    return build_timeout_failure_result("actuator timeout failure")
                return {"status": "ok", "message": "replay complete"}
        """,
    )
    _write(
        repo / "ros2" / "exampleservice_ros" / "exampleservice_ros" / "diagnostic_result.py",
        """
        def build_timeout_failure_result(message):
            if "timeout" in message:
                return {"status": "failed", "failure": "actuator timeout", "message": message}
            raise ValueError("missing timeout failure message")
        """,
    )
    _write(
        repo / "ros2" / "exampleservice_ros" / "exampleservice_ros" / "diagnostic_bridge_node.py",
        """
        import rclpy

        class DiagnosticBridgeNode:
            def publish_status(self, result):
                self.publisher.publish(result["status"])
        """,
    )
    _write(
        repo / "tests" / "run_ros_replay_regression.py",
        """
        from ros2.exampleservice_ros.exampleservice_ros.replay_runner import ReplayRunner
        print("replay regression still passes")
        """,
    )
    _write(
        repo / "tests" / "test_replay_timeout.py",
        """
        def test_replay_timeout_failure_message():
            assert "timeout"
        """,
    )


def test_replay_timeout_behavior_prefers_runtime_and_result_sources(repo: Path) -> None:
    _write_replay_runtime_fixture(repo)

    evidence = extract_prompt_evidence(REPLAY_PROMPT)
    result = locate_files(repo, REPLAY_PROMPT, max_files=8)

    primary_paths = _paths(result.primary_files)
    all_paths = _paths(result.primary_files + result.support_files + result.verification_files)

    assert evidence.test_verification_intent
    assert not evidence.test_edit_intent
    assert "behavior" in evidence.behavior_terms or "timeout" in evidence.behavior_terms
    assert "ros2/exampleservice_ros/exampleservice_ros/replay_runner.py" in primary_paths
    assert "ros2/exampleservice_ros/exampleservice_ros/diagnostic_result.py" in _paths(result.primary_files + result.support_files)
    assert "ros2/exampleservice_ros/exampleservice_ros/scenario_loader.py" not in primary_paths
    assert "ros2/exampleservice_ros/exampleservice_ros/scenario_loader.py" in all_paths
    assert "ros2/exampleservice_ros/exampleservice_ros/diagnostic_bridge_node.py" not in primary_paths
    assert "tests/run_ros_replay_regression.py" in _paths(result.verification_files + result.support_files)
    assert "tests/test_replay_timeout.py" in _paths(result.verification_files + result.support_files)
    assert any(signal.startswith("behavior_source:") for signal in _signals(result, "ros2/exampleservice_ros/exampleservice_ros/replay_runner.py"))
    assert any(
        signal.startswith("scenario_data_surface_downranked_for_behavior_prompt")
        for signal in _signals(result, "ros2/exampleservice_ros/exampleservice_ros/scenario_loader.py")
    )
    assert result.confidence in {"medium", "high"}


def test_compile_replay_timeout_keeps_regression_tests_read_only(repo: Path) -> None:
    _write_replay_runtime_fixture(repo)
    _prepare(repo)

    result = compile_prompt(repo, REPLAY_PROMPT, "lite", record=False)

    candidates = _manifest_paths(result["candidate_edit_files"])
    assert "ros2/exampleservice_ros/exampleservice_ros/replay_runner.py" in candidates
    assert "ros2/exampleservice_ros/exampleservice_ros/scenario_loader.py" not in candidates
    assert "tests/run_ros_replay_regression.py" not in candidates
    assert "tests/test_replay_timeout.py" not in candidates
    assert {"tests/run_ros_replay_regression.py", "tests/test_replay_timeout.py"} <= _all_context_paths(result)


def test_checkout_discount_calculation_prefers_pricing_logic(repo: Path) -> None:
    _write(
        repo / "src" / "pages" / "CheckoutPage.tsx",
        """
        import { useCheckoutTotals } from "../hooks/useCheckoutTotals"
        export function CheckoutPage() {
          const total = useCheckoutTotals()
          return <span>checkout total {total}</span>
        }
        """,
    )
    _write(
        repo / "src" / "hooks" / "useCheckoutTotals.ts",
        """
        import { calculateDiscountedTotal } from "../lib/pricing"
        export function useCheckoutTotals(items, discount) {
          return calculateDiscountedTotal(items, discount)
        }
        """,
    )
    _write(
        repo / "src" / "lib" / "pricing.ts",
        """
        export function calculateDiscountedTotal(items, discount) {
          const subtotal = items.reduce((total, item) => total + item.price, 0)
          const discounted = subtotal - discount
          return Math.round(discounted * 100) / 100
        }
        """,
    )

    result = locate_files(repo, "Fix checkout total calculation when discount is applied.")

    assert "src/lib/pricing.ts" in _paths(result.primary_files + result.support_files)
    assert result.primary_files[0].path in {"src/lib/pricing.ts", "src/hooks/useCheckoutTotals.ts"}
    assert result.primary_files[0].path != "src/pages/CheckoutPage.tsx"
    assert any(signal.startswith("behavior_source:") for signal in _signals(result, "src/lib/pricing.ts"))
    assert result.dependency_relations


def test_api_missing_payload_prefers_handler_service_behavior_cluster(repo: Path) -> None:
    _write(repo / "src" / "api" / "routes" / "index.py", 'ROUTES = ["/users", "/settings"]\n')
    _write(
        repo / "src" / "api" / "routes" / "user_handler.py",
        """
        from src.services.user_settings import update_user_settings

        def handle_user_settings(request):
            payload = request.json()
            return update_user_settings(payload)
        """,
    )
    _write(
        repo / "src" / "services" / "user_settings.py",
        """
        def update_user_settings(payload):
            if payload is None:
                raise ValueError("missing update payload")
            return {"status": "updated", "settings": payload}
        """,
    )

    result = locate_files(repo, "Fix the user settings API handler when the update payload is missing.")

    selected = _paths(result.primary_files + result.support_files)
    assert "src/api/routes/user_handler.py" in selected
    assert "src/services/user_settings.py" in selected
    assert "src/api/routes/index.py" not in _paths(result.primary_files[:1])
    assert any(signal.startswith("behavior_source:") for signal in _signals(result, "src/services/user_settings.py"))


def test_csv_export_missing_output_folder_prefers_writer_cli_cluster(repo: Path) -> None:
    _write(
        repo / "tools" / "export_csv.py",
        """
        import argparse
        from src.exporter.csv_writer import write_csv

        parser = argparse.ArgumentParser(description="CSV export")
        parser.add_argument("--output-folder", help="Folder for CSV output")

        def main(output_folder):
            return write_csv(output_folder)
        """,
    )
    _write(
        repo / "src" / "exporter" / "csv_writer.py",
        """
        def write_csv(output_folder):
            if not output_folder:
                raise ValueError("output folder is missing")
            return {"status": "written", "output": output_folder}
        """,
    )
    _write(repo / "tools" / "build_html_report.py", "import argparse\nparser = argparse.ArgumentParser(description='Build HTML report')\n")

    result = locate_files(repo, "Improve the CSV export error message when the output folder is missing.")

    selected = _paths(result.primary_files + result.support_files)
    assert "tools/export_csv.py" in selected
    assert "src/exporter/csv_writer.py" in selected
    assert "tools/build_html_report.py" not in _paths(result.primary_files[:1])
    assert any(signal.startswith("behavior_source:") for signal in _signals(result, "src/exporter/csv_writer.py"))
    assert any(
        relation.source == "tools/export_csv.py" and relation.target == "src/exporter/csv_writer.py"
        for relation in result.dependency_relations
    )
