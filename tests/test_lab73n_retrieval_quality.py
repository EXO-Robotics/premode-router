from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.locator import locate_files


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    return tmp_path


def _index(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")


def test_docs_primary_gate_keeps_qa_markdown_out_of_ui_bug_candidates(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src" / "ui").mkdir(parents=True)
    (repo / "src" / "ui" / "screen_button.py").write_text(
        "class ScreenButton:\n    def render_screen(self):\n        return 'button'\n",
        encoding="utf-8",
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "qa_button_critique.md").write_text(
        "# Button critique\nThe screen button bug is described here.\n",
        encoding="utf-8",
    )
    _index(repo)

    result = compile_prompt(repo, "Fix the UI screen button bug.", "lite", use_repo_map=True, record_artifacts=False)

    candidates = [item["path"] for item in result["candidate_edit_files"]]
    assert "src/ui/screen_button.py" in candidates
    assert "docs/qa_button_critique.md" not in candidates


def test_docs_primary_gate_ranks_readme_for_quickstart_prompt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# App\n\n## Quickstart\nold\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    _index(repo)

    result = compile_prompt(repo, "Update the README quickstart instructions.", "lite", use_repo_map=True, record_artifacts=False)

    candidates = [item["path"] for item in result["candidate_edit_files"]]
    assert candidates
    assert candidates[0] == "README.md"
    assert "README.md" in candidates


def test_docs_prompt_with_source_symbol_keeps_source_as_support(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# App\n\n## Quickstart\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "widget_screen.py").write_text("class WidgetScreen:\n    pass\n", encoding="utf-8")
    _index(repo)

    result = compile_prompt(
        repo,
        "Document WidgetScreen in the README quickstart without changing runtime source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = [item["path"] for item in result["candidate_edit_files"]]
    support = [item["path"] for item in result["read_only_support_files"]]
    assert "README.md" in candidates
    assert "src/widget_screen.py" in support or "src/widget_screen.py" not in candidates


def test_typo_normalization_maps_screen_and_improves_ui_fixture(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "screen_view.py").write_text(
        "class ScreenView:\n    def render_screen(self):\n        return 'screen'\n",
        encoding="utf-8",
    )
    _index(repo)

    located = locate_files(repo, "Fix the screeen rendering bug.", max_files=5)

    assert located.typo_normalizations.get("screeen") == "screen"
    assert located.primary_files
    assert located.primary_files[0].path == "src/screen_view.py"
    assert "screeen" not in located.uncovered_prompt_terms


def test_non_locating_filler_terms_do_not_become_uncovered_terms(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "screen_view.py").write_text("def screen():\n    return 'screen'\n", encoding="utf-8")
    _index(repo)

    located = locate_files(repo, "There is an issue with screen behavior.", max_files=5)

    assert "there" not in located.uncovered_prompt_terms
    assert "issue" not in located.uncovered_prompt_terms


def test_cli_flags_and_exact_symbols_are_preserved_during_typo_normalization(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "cli.py").write_text(
        "def add_packet_mode(parser):\n    parser.add_argument('--packet-mode')\n",
        encoding="utf-8",
    )
    _index(repo)

    located = locate_files(repo, "Clarify --packet-mode handling in add_packet_mode.", max_files=5)

    assert located.typo_normalizations == {}
    assert located.primary_files
    assert located.primary_files[0].path == "src/cli.py"


def test_decision_ledger_explains_selected_and_rejected_expected_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def screen():\n    return 'screen'\n", encoding="utf-8")
    (repo / "generated").mkdir()
    (repo / "generated" / "cache.py").write_text("def generated_screen():\n    return 'screen'\n", encoding="utf-8")
    _index(repo)

    result = compile_prompt(repo, "Fix screen behavior in src/app.py.", "lite", use_repo_map=True)
    records = {item["path"]: item for item in result["file_decision_ledger"]["records"]}

    for path in ("src/app.py", "generated/cache.py"):
        record = records[path]
        for field in (
            "path",
            "eligible",
            "skip_reason",
            "raw_score",
            "score_deltas",
            "matched_prompt_terms",
            "typo_normalized_terms",
            "role_classification",
            "dirty_contribution",
            "repo_map_hints",
            "locator_hints",
            "final_bucket",
            "why_promoted",
            "why_rejected",
            "model_facing",
            "saved_only",
        ):
            assert field in record
    assert records["src/app.py"]["candidate"] is True
    assert records["generated/cache.py"]["why_rejected"] is not None
    assert records["generated/cache.py"]["skipped"] is True
