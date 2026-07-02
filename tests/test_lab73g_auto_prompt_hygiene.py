from __future__ import annotations

from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.live_ledger import parse_exploration_ledger_from_text


def _index(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")


def _make_paths_only_repo(repo: Path) -> str:
    (repo / "tools").mkdir(parents=True)
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
    (repo / "tests").mkdir()
    (repo / "tests" / "test_demo_output.py").write_text("def test_demo_output():\n    assert True\n", encoding="utf-8")
    _index(repo)
    return "Improve the diagnostic demo output wording without changing runtime behavior."


def _make_evidence_repo(repo: Path) -> str:
    (repo / "src").mkdir(parents=True, exist_ok=True)
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
    _index(repo)
    return 'Improve the "Export ready for review" CLI message in src/command.py.'


def _assert_review_patch_metadata_is_harness_only(result: dict) -> None:
    packet = result["packet"]
    assert "premode review-patch" not in packet
    assert "Run premode" not in packet
    assert "review_boundary" not in packet
    assert "review-patch" not in packet
    assert "Pre-mode validation" not in packet
    assert "find premode" not in packet.lower()

    metadata = result["harness_review_metadata"]
    assert metadata["mode"] == "out_of_band"
    assert metadata["model_facing"] is False
    assert metadata["review_patch"]["runner"] == "harness"
    assert metadata["review_patch"]["model_facing"] is False
    assert "Harness may run review-patch" in metadata["review_patch"]["instruction"]


def test_auto_paths_only_packet_hygiene_and_json_diagnostics(repo: Path) -> None:
    prompt = _make_paths_only_repo(repo)

    result = compile_prompt(
        repo,
        prompt,
        "lite",
        packet_version="v3",
        packet_detail_mode="auto",
        snippet_budget_tokens=600,
        record_artifacts=False,
    )

    packet = result["packet"]
    _assert_review_patch_metadata_is_harness_only(result)
    assert result["packet_detail_mode_selected"] == "paths_only"
    assert result["model_facing_evidence_tokens"] == 0
    assert "Compact Factual Evidence Snippets" not in packet
    assert "packet_mode_selection_reasons" not in packet
    assert "packet_mode_selection_signals" not in packet
    assert "support_edit_surface_risk" not in packet
    assert "multi_surface_risk" not in packet
    assert "paths-only selected because" not in packet
    assert "support files present with" not in packet

    assert result["packet_mode_selection_reasons"]
    assert result["packet_mode_selection_signals"]["support_files_present"] is True
    assert result["support_edit_surface_risk_strength"] in {"none", "weak"}
    assert result["multi_surface_risk_strength"] in {"none", "weak"}


def test_forced_paths_only_packet_keeps_review_patch_harness_only(repo: Path) -> None:
    prompt = _make_paths_only_repo(repo)

    result = compile_prompt(
        repo,
        prompt,
        "lite",
        packet_version="v3",
        packet_detail_mode="paths_only",
        record_artifacts=False,
    )

    assert result["packet_detail_mode_selected"] == "paths_only"
    _assert_review_patch_metadata_is_harness_only(result)


def test_auto_paths_only_render_equivalent_to_forced_paths_only(repo: Path) -> None:
    prompt = _make_paths_only_repo(repo)

    auto = compile_prompt(repo, prompt, "lite", packet_version="v3", packet_detail_mode="auto", record_artifacts=False)
    forced = compile_prompt(repo, prompt, "lite", packet_version="v3", packet_detail_mode="paths_only", record_artifacts=False)

    assert auto["packet_detail_mode_selected"] == "paths_only"
    _assert_review_patch_metadata_is_harness_only(auto)
    _assert_review_patch_metadata_is_harness_only(forced)
    assert auto["packet"] == forced["packet"]
    assert auto["auto_render_equivalent_to_forced_selected_mode"] is True
    assert auto["forced_mode_compared"] == "paths_only"
    assert auto["auto_selected_mode_model_facing_equivalent"] is True
    assert auto["auto_selected_mode_packet_diff_summary"] == []
    assert auto["auto_paths_only_model_facing_equivalent"] is True
    assert auto["auto_paths_only_packet_diff_summary"] == []


def test_forced_evidence_snippets_packet_keeps_review_patch_harness_only(repo: Path) -> None:
    prompt = _make_evidence_repo(repo)

    result = compile_prompt(
        repo,
        prompt,
        "lite",
        packet_version="v3",
        packet_detail_mode="evidence_snippets",
        snippet_budget_tokens=600,
        record_artifacts=False,
    )

    assert result["packet_detail_mode_selected"] == "evidence_snippets"
    assert "Compact Factual Evidence Snippets" in result["packet"]
    _assert_review_patch_metadata_is_harness_only(result)


def test_auto_evidence_snippets_render_equivalent_and_clean(repo: Path) -> None:
    prompt = _make_evidence_repo(repo)

    auto = compile_prompt(
        repo,
        prompt,
        "lite",
        packet_version="v3",
        packet_detail_mode="auto",
        snippet_budget_tokens=600,
        record_artifacts=False,
    )
    forced = compile_prompt(
        repo,
        prompt,
        "lite",
        packet_version="v3",
        packet_detail_mode="evidence_snippets",
        snippet_budget_tokens=600,
        record_artifacts=False,
    )

    assert auto["packet_detail_mode_selected"] == "evidence_snippets"
    _assert_review_patch_metadata_is_harness_only(auto)
    _assert_review_patch_metadata_is_harness_only(forced)
    assert auto["packet"] == forced["packet"]
    assert "Compact Factual Evidence Snippets" in auto["packet"]
    assert "Export ready for review" in auto["packet"]
    assert "packet_mode_selection_reasons" not in auto["packet"]
    assert "packet_mode_selection_signals" not in auto["packet"]
    assert "support_edit_surface_risk" not in auto["packet"]
    assert auto["auto_render_equivalent_to_forced_selected_mode"] is True
    assert auto["forced_mode_compared"] == "evidence_snippets"
    assert auto["auto_selected_mode_model_facing_equivalent"] is True
    assert auto["auto_selected_mode_packet_diff_summary"] == []


def test_packet_debug_metadata_is_opt_in(repo: Path) -> None:
    prompt = _make_paths_only_repo(repo)

    default = compile_prompt(repo, prompt, "lite", packet_version="v3", packet_detail_mode="auto", record_artifacts=False)
    debug = compile_prompt(
        repo,
        prompt,
        "lite",
        packet_version="v3",
        packet_detail_mode="auto",
        include_packet_debug_metadata=True,
        record_artifacts=False,
    )

    assert "packet_mode_selection_reasons" not in default["packet"]
    assert "packet_mode_selection_reasons" in debug["packet"]
    assert "packet_mode_selection_signals" in debug["packet"]
    assert debug["include_packet_debug_metadata"] is True


def test_exploration_ledger_splits_explicit_reads_from_mentions() -> None:
    text = """
$ cat src/app.py
src/app.py contents
$ rg "Theme" .
src/app.py:12:Theme values
docs/help.md:4:Theme help
output: generated path reports/theme_report.html
validation: pytest failed in tests/test_theme.py
stdout: command mentioned configs/theme.json
changed src/app.py
""".strip()

    ledger = parse_exploration_ledger_from_text(
        text,
        candidate_files=["src/app.py"],
        packet_files=["src/app.py", "docs/help.md", "tests/test_theme.py"],
    )

    assert ledger["explicit_file_reads"] == ["src/app.py"]
    assert ledger["explicit_file_read_count"] == 1
    assert "docs/help.md" in ledger["search_result_file_mentions"]
    assert "configs/theme.json" in ledger["command_output_file_mentions"]
    assert ledger["validation_output_file_mentions"] == ["tests/test_theme.py"]
    assert ledger["generated_output_file_mentions"] == ["reports/theme_report.html"]
    assert "docs/help.md" not in ledger["explicit_file_reads"]
    assert "tests/test_theme.py" not in ledger["explicit_file_reads"]
    assert ledger["all_referenced_file_count"] >= 5
    assert ledger["unique_files_read_semantics"] == "deprecated_heuristic_all_referenced_files"
