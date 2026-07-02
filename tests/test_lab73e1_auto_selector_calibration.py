from __future__ import annotations

from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _compile_auto(repo: Path, prompt: str) -> dict:
    index_project(repo, "lite")
    return compile_prompt(
        repo,
        prompt,
        "lite",
        packet_version="v3",
        packet_detail_mode="auto",
        snippet_budget_tokens=600,
        record_artifacts=False,
    )


def _paths(items: list[dict] | list[str] | None) -> list[str]:
    out: list[str] = []
    for item in items or []:
        out.append(str(item.get("path") if isinstance(item, dict) else item))
    return out


def test_narrow_script_with_weak_support_selects_paths_only(repo: Path) -> None:
    init_project(repo)
    (repo / "tools").mkdir()
    (repo / "tools" / "create_demo_output.py").write_text(
        """
def main():
    print("Diagnostic demo output written")
    print("Demo output is ready")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "tools" / "generate_sample_data.py").write_text(
        """
def build_sample():
    return {"status": "sample output ready"}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_demo_output.py").write_text("def test_demo_output():\n    assert True\n", encoding="utf-8")

    result = _compile_auto(repo, "Improve the diagnostic demo output wording without changing runtime behavior.")
    signals = result["packet_mode_selection_signals"]

    assert result["packet_detail_mode_selected"] == "paths_only"
    assert signals["support_files_present"] is True
    assert signals["support_edit_surface_risk_strength"] in {"none", "weak"}
    assert signals["multi_surface_risk_strength"] in {"none", "weak"}
    assert signals["verification_files_present"] is True
    assert "support files present with" in " ".join(result["packet_mode_selection_reasons"])


def test_narrow_cli_flag_help_selects_paths_only_with_support_present(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "cli.py").write_text(
        """
import argparse

def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=["light", "dark"], help="Output theme")
    return parser
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "cli.md").write_text("The --theme flag changes output colors.\n", encoding="utf-8")

    result = _compile_auto(repo, "Improve the --theme CLI help text so values are clear.")
    signals = result["packet_mode_selection_signals"]

    assert result["packet_detail_mode_selected"] == "paths_only"
    assert signals["dominant_candidate"] is True
    assert signals["primary_direct_edit_surface"] is True
    assert signals["support_files_present"] is True
    assert signals["support_edit_surface_risk_strength"] in {"none", "weak"}


def test_multi_surface_ui_state_task_still_selects_evidence_snippets(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "views").mkdir(parents=True)
    (repo / "src" / "state").mkdir(parents=True)
    (repo / "src" / "views" / "DashboardView.swift").write_text(
        """
struct DashboardView {
    let title = "Next action"
    let body = "Today plan"
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "src" / "state" / "DashboardState.swift").write_text(
        """
struct DashboardState {
    let nextAction = "Today plan"
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = _compile_auto(repo, "Improve next action clarity across the dashboard view and state.")
    signals = result["packet_mode_selection_signals"]

    assert result["packet_detail_mode_selected"] == "evidence_snippets"
    assert signals["multi_surface_risk_strength"] in {"medium", "strong"}


def test_generic_index_with_split_evidence_still_selects_evidence_snippets(repo: Path) -> None:
    init_project(repo)
    (repo / "app" / "checkout").mkdir(parents=True)
    (repo / "app" / "checkout" / "index.tsx").write_text(
        """
export function CheckoutView() {
  return <p>{emptyCartMessage}</p>
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "app" / "checkout" / "cartState.ts").write_text(
        "export const emptyCartMessage = 'Your cart is empty';\n",
        encoding="utf-8",
    )

    result = _compile_auto(repo, "Improve the empty cart message shown in checkout.")
    signals = result["packet_mode_selection_signals"]

    assert result["packet_detail_mode_selected"] == "evidence_snippets"
    assert signals["generic_filename_risk"] is True or signals["multi_surface_risk_strength"] in {"medium", "strong"}


def test_explicit_auto_calibration_overrides_still_force_modes(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "cli.py").write_text("HELP = 'Output theme'\n", encoding="utf-8")
    index_project(repo, "lite")
    prompt = "Improve the output theme help text."

    paths_only = compile_prompt(repo, prompt, "lite", packet_version="v3", packet_detail_mode="paths_only", record_artifacts=False)
    snippets = compile_prompt(repo, prompt, "lite", packet_version="v3", packet_detail_mode="evidence_snippets", record_artifacts=False)

    assert paths_only["packet_detail_mode_selected"] == "paths_only"
    assert snippets["packet_detail_mode_selected"] == "evidence_snippets"


def test_selection_signals_explain_strong_support_escalation(repo: Path) -> None:
    init_project(repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "command.py").write_text(
        """
from .output_copy import render_banner

def message():
    return render_banner("Export ready for review")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "src" / "output_copy.py").write_text(
        """
DEFAULT_BANNER = "Export ready for review"

def render_banner(value=DEFAULT_BANNER):
    return value
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = _compile_auto(repo, 'Improve the "Export ready for review" CLI message in src/command.py.')
    signals = result["packet_mode_selection_signals"]

    assert result["packet_detail_mode_selected"] == "evidence_snippets"
    assert signals["support_files_present"] is True
    assert signals["support_edit_surface_risk_strength"] in {"medium", "strong"}
    assert signals["support_edit_surface_risk"] is True
    assert any("support files include" in reason for reason in result["packet_mode_selection_reasons"])
    assert "src/output_copy.py" in _paths(result["support_files"]) or "src/output_copy.py" in _paths(result["candidate_edit_files"])
