"""Lab 7.2K — realistic ExampleService replay-timeout localization.

Reproduces the real clean-baseline failure where a "fix the replay timeout
behavior" prompt drifted to actuator/report/demo/html surfaces instead of the
runtime/result behavior source, and verifies the fix keeps CLI, report-output,
and verification-clause behavior stable.
"""
from __future__ import annotations

from pathlib import Path

from premode.locator import locate_files


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_exampleservice_like_repo(repo: Path) -> None:
    # --- Runtime/result behavior source (the correct edit surface) -------------
    _write(repo / "ros2/exampleservice_ros/exampleservice_ros/diagnostic_bridge_node.py", """
# M3 diagnostic bridge runtime. Converts replay runtime messages into actuator
# CSV, invokes the C++ diagnostic CLI, and publishes /exampleservice/diagnostic_result.
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

class DiagnosticBridgeNode(Node):
    def __init__(self, timeout_s=5.0):
        super().__init__("diagnostic_bridge_node")
        self.timeout_s = timeout_s
        self.sub = self.create_subscription(String, "/joint_state", self._on_msg, 10)
        self.pub = self.create_publisher(String, "/exampleservice/diagnostic_result", 10)
    def _on_msg(self, msg):
        if self._elapsed_since_replay() > self.timeout_s:
            # actuator replay timeout: report the failure result clearly
            self.get_logger().error("actuator timeout during replay; reporting FAILURE")
            result = {"status": "FAILURE", "message": "actuator timeout failure during replay"}
        else:
            result = self._run_diagnostic(msg)
        self.pub.publish(String(data=result["message"]))
""")
    _write(repo / "ros2/exampleservice_ros/exampleservice_ros/trajectory_player_node.py", """
# M2 trajectory player node. Publishes deterministic commanded joint position.
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64
class TrajectoryPlayerNode(Node):
    def __init__(self, playback_rate=1.0):
        super().__init__("trajectory_player_node")
        self.playback_rate = playback_rate
        self.pub = self.create_publisher(Float64, "/joint_command", 10)
    def run(self):
        while rclpy.ok():
            self.pub.publish(Float64(data=0.0))
""")
    _write(repo / "cpp/src/actuator_profile.cpp", """
// Computes actuator diagnostic result and failure status from telemetry.
#include "actuator_profile.hpp"
DiagnosticResult classify_actuator(const Samples& s) {
    DiagnosticResult result;
    result.status = s.exceeded ? "FAILURE" : "OK";
    result.message = result.status == "FAILURE" ? "actuator fault detected" : "actuator nominal";
    return result;
}
""")
    _write(repo / "ros2/exampleservice_ros/exampleservice_ros/scenario_loader.py", """
# Loads scenario definitions (data/fixtures) for replay.
import yaml
def load_scenario(name):
    return yaml.safe_load(open(name))
def expected_by_name(name):
    return load_scenario(name)["expected"]
""")
    # --- Output / report / demo surfaces (should NOT be primary for behavior) ---
    _write(repo / "tools/build_html_report.py", """
import argparse
# Builds an HTML diagnostic report from a result JSON. Renders actuator status.
def build(result, out):
    open(out, "w").write("<html>actuator report: " + result["message"] + "</html>")
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build HTML report"); p.add_argument("--result")
""")
    _write(repo / "tools/create_demo_outputs.py", """
import argparse
# CLI demo output generator. Prints created files and success messages.
def main():
    p = argparse.ArgumentParser(); p.add_argument("--out", help="output dir")
    print("Demo outputs created"); print("wrote results")
""")
    _write(repo / "tools/run_diagnostic_batch.py", """
import argparse
# CLI batch runner. Help/usage/error/success messages for the diagnostic tool.
def main():
    p = argparse.ArgumentParser(description="Run diagnostic batch")
    p.add_argument("--in", help="input directory")
    if not ok:
        raise SystemExit("error: missing input")
    print("completed")
""")
    _write(repo / "cpp/src/main.cpp", """
#include <iostream>
// ExampleService diagnostic CLI entrypoint.
int main(int argc, char** argv) {
    if (argc < 2) { std::cerr << "Usage: exampleservice_diag <csv>" << std::endl; return 1; }
    std::cout << "diagnostic complete" << std::endl; return 0;
}
""")
    _write(repo / "ros2/exampleservice_ros/tools/export_scenarios_to_csv.py", """
import argparse
# Exports scenario CSVs. CLI help/usage.
p = argparse.ArgumentParser(description="Export scenario CSVs")
p.add_argument("--config", help="scenario yaml")
print("exported")
""")
    _write(repo / "portfolio_evidence/exampleservice_ros2/tools/render_evidence_pngs.py", """
# Renders evidence PNG images from diagnostic result JSON.
def render(results):
    for r in results:
        open(r["name"] + ".png", "wb").write(b"png")
""")
    _write(repo / "dashboard/streamlit_app.py", "import streamlit as st\nst.write('actuator diagnostic result dashboard')\n")
    _write(repo / "reports/actuator_binding_report.html", "<html>" + ("actuator failure report " * 200) + "</html>")
    _write(repo / "results/actuator_result.json", '{"status": "FAILURE", "message": "actuator fault"}\n')
    _write(repo / "docs/demo_walkthrough.md", "# Demo walkthrough\nReplay the scenario and read the actuator report.\n")
    # --- Verification / regression harness (verification/support, not primary) --
    _write(repo / "ros2/exampleservice_ros/tests/run_ros_replay_regression.py", "print('replay regression: 6/6 passed')\n")
    _write(repo / "ros2/exampleservice_ros/tests/run_diagnostic_bridge_runtime_check.py", "# runtime check: actuator timeout must be reported\nprint('runtime check passed')\n")
    _write(repo / "tests/run_regression_tests.py", "print('11/11 diagnostic cases passed')\n")


REPLAY_PROMPT = "Fix the replay timeout behavior so actuator timeout failures are reported clearly and the regression still passes."
CLI_PROMPT = "Make the command-line output easier to understand: clarify one help message, one error message, and one success message. Do not change tests or packaging."
REPORT_PROMPT = "Improve the generated diagnostic report output so users can understand actuator failures more easily."
REPLAY_NO_TESTS_PROMPT = "Fix the replay timeout behavior and make sure the regression still passes. Do not change tests."

_OUTPUT_ARTIFACT_MARKERS = ("report", "dashboard", "streamlit", "evidence", "render", ".html", ".json", ".md")


def _is_runtime_behavior_source(path: str) -> bool:
    p = path.lower()
    return p.endswith((".py", ".cpp", ".cc")) and not any(m in p for m in _OUTPUT_ARTIFACT_MARKERS) and "/tests/" not in p


# --- Test A: realistic replay-timeout localization -----------------------------

def test_replay_timeout_selects_runtime_result_source_not_report_demo(repo: Path):
    _make_exampleservice_like_repo(repo)
    r = locate_files(repo, REPLAY_PROMPT)
    primary = [f.path for f in r.primary_files]
    verification = [f.path for f in r.verification_files]

    # A runtime/result behavior source is a primary candidate.
    assert any(_is_runtime_behavior_source(p) for p in primary), primary
    assert "ros2/exampleservice_ros/exampleservice_ros/diagnostic_bridge_node.py" in primary or "cpp/src/actuator_profile.cpp" in primary
    # Report / demo / html / data / docs artifacts are NOT primary edit candidates.
    for bad in ("reports/actuator_binding_report.html", "tools/build_html_report.py",
                "dashboard/streamlit_app.py", "results/actuator_result.json",
                "docs/demo_walkthrough.md", "portfolio_evidence/exampleservice_ros2/tools/render_evidence_pngs.py"):
        assert bad not in primary, f"{bad} should not be primary"
    # Regression/runtime-check harnesses are verification/support, not primary.
    assert not any("/tests/" in p or p.startswith("tests/") for p in primary)
    assert any("regression" in p or "runtime_check" in p or "/tests/" in p for p in verification)
    # Not false-high: multiple plausible files -> medium/high acceptable, not low-only artifacts.
    assert r.confidence in {"medium", "high"}


# --- Test B: CLI target-set stability ------------------------------------------

def test_cli_target_set_remains_stable(repo: Path):
    _make_exampleservice_like_repo(repo)
    r = locate_files(repo, CLI_PROMPT)
    # Candidate context = primary + support; the CLI target set must remain present.
    candidates = {f.path for f in r.primary_files} | {f.path for f in r.support_files}
    for expected in ("tools/create_demo_outputs.py", "tools/run_diagnostic_batch.py",
                     "cpp/src/main.cpp", "ros2/exampleservice_ros/tools/export_scenarios_to_csv.py"):
        assert expected in candidates, f"CLI target {expected} missing: {candidates}"
    # The demo output generator is not demoted for a CLI message prompt.
    assert "tools/create_demo_outputs.py" in {f.path for f in r.primary_files}


# --- Test C: report/demo prompt still works ------------------------------------

def test_report_output_prompt_keeps_report_files_candidate(repo: Path):
    _make_exampleservice_like_repo(repo)
    r = locate_files(repo, REPORT_PROMPT)
    all_paths = {f.path for f in r.primary_files} | {f.path for f in r.support_files}
    # Report/demo/output files are NOT globally suppressed when the prompt asks for report output.
    assert any(("report" in p) or ("dashboard" in p) or p.endswith(".html") for p in all_paths), all_paths


# --- Test D: verification clause stays stable ----------------------------------

def test_replay_timeout_do_not_change_tests_keeps_tests_as_verification(repo: Path):
    _make_exampleservice_like_repo(repo)
    r = locate_files(repo, REPLAY_NO_TESTS_PROMPT)
    primary = [f.path for f in r.primary_files]
    # Source/runtime candidates only in primary; no test/regression harness as an edit candidate.
    assert primary, "expected at least one source candidate"
    assert not any("/tests/" in p or p.startswith("tests/") for p in primary), primary
    # No report/docs/data artifact promoted to primary either.
    for bad in ("reports/actuator_binding_report.html", "docs/demo_walkthrough.md", "results/actuator_result.json"):
        assert bad not in primary
