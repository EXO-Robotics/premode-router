from __future__ import annotations

from pathlib import Path

from premode.config import init_project
from premode.evidence_snippets import _line_matches, _prompt_terms, extract_evidence_snippets
from premode.indexer import index_project
from premode.lab73l import compile_v3_scaffold_free
from premode.live_ledger import command_ledger_from_events
from premode.locator import extract_prompt_evidence, locate_files


META_TERMS = {
    "lab", "benchmark", "harness", "constraint", "constraints", "prompt",
    "repository", "repo", "validation", "xcode", "xcodebuild", "cache",
    "packet", "codex", "premode", "review-patch",
}


def _index(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_scaffold_meta_terms_do_not_become_locator_terms_but_domain_survives(repo: Path) -> None:
    _write(
        repo / "src" / "rich_cli" / "__main__.py",
        """
import argparse

def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=["dark", "light"])
    return parser
""",
    )
    _write(repo / "src" / "HomesteadView.swift", "struct HomesteadView { let TodayPlan = \"TodayPlan\" }")
    _write(repo / "tools" / "diagnostic.py", "def diagnostic(): return 'diagnostic theme'")
    _index(repo)

    scaffolded = (
        "Lab 7.3L benchmark harness constraints prompt repository cache packet codex "
        "Improve diagnostic theme handling for Homestead TodayPlan and --theme."
    )

    evidence = extract_prompt_evidence(scaffolded)
    locator = locate_files(repo, scaffolded)
    terms = set(evidence.domain_terms) | set(locator.covered_prompt_terms) | set(locator.uncovered_prompt_terms)

    assert META_TERMS.isdisjoint(terms)
    assert {"diagnostic", "theme"} <= set(evidence.domain_terms)
    assert "TodayPlan" in evidence.symbols_or_entities
    assert "--theme" in evidence.option_flags


def test_evidence_prompt_terms_filter_scaffold_but_keep_literals_flags_paths_and_symbols() -> None:
    pairs = _prompt_terms(
        'Lab benchmark constraints validation repository prompt "Export ready" '
        "--theme TodayPlanView src/rich_cli/__main__.py"
    )
    signals = {signal for signal, _term in pairs}

    assert not any("Lab" in signal for signal in signals)
    assert not any("benchmark" in signal for signal in signals)
    assert not any("validation" in signal for signal in signals)
    assert 'quoted_literal:Export ready' in signals
    assert "option_flag:--theme" in signals
    assert "symbol:TodayPlanView" in signals
    assert "path:src/rich_cli/__main__.py" in signals


def test_snippet_line_matching_is_token_aware_for_words_and_substring_for_code_terms() -> None:
    assert not _line_matches("available themes are listed here", "Lab")
    assert not _line_matches("collaborate on the patch", "lab")
    assert _line_matches("the theme value is listed here", "theme")
    assert _line_matches('parser.add_argument("--theme")', "--theme")
    assert _line_matches("struct TodayPlanView: View {}", "TodayPlanView")
    assert _line_matches("open src/rich_cli/__main__.py", "src/rich_cli/__main__.py")


def test_scaffold_terms_do_not_create_lab_snippet_matches(repo: Path) -> None:
    _write(repo / "src" / "app.py", "AVAILABLE = True\nTHEME = 'dark'\n")
    _index(repo)
    located = locate_files(repo, "Lab benchmark prompt constraints improve theme.")

    packet = extract_evidence_snippets(repo, "Lab benchmark prompt constraints improve theme.", primary_files=located.primary_files)
    matched = [signal for snippet in packet["snippets"] for signal in snippet["matched_signals"]]

    assert "literal:Lab" not in matched
    assert "symbol:Lab" not in matched
    assert not any(signal.endswith(":benchmark") or signal.endswith(":prompt") for signal in matched)


def test_clean_narrow_cli_auto_selects_paths_only_without_loose_scaffold_escalation(repo: Path) -> None:
    _write(
        repo / "src" / "rich_cli" / "__main__.py",
        """
import argparse

def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=["dark", "light"], help="Output theme")
    return parser
""",
    )
    _write(repo / "tests" / "test_cli.py", "from rich_cli.__main__ import build_parser\n")
    _index(repo)

    result = compile_v3_scaffold_free(
        repo,
        "Clarify the --theme CLI help text in src/rich_cli/__main__.py.",
        repo / "snapshots" / "rich_cli",
        harness_constraints="Do not stage changes. Do not commit.",
        snippet_budget_tokens=600,
    )

    assert result["packet_detail_mode_selected"] == "paths_only"
    assert result["auto_render_equivalent_to_forced_selected_mode"] is True
    assert "review-patch" not in result["packet"]
    snapshot = result["stdin_snapshot"]
    assert Path(snapshot["raw_task_prompt_path"]).read_text(encoding="utf-8").startswith("Clarify the --theme")
    assert Path(snapshot["packet_compile_input_task_path"]).read_text(encoding="utf-8") == "Clarify the --theme CLI help text in src/rich_cli/__main__.py."
    assert Path(snapshot["final_codex_stdin_path"]).exists()
    assert len(Path(repo / "snapshots" / "rich_cli" / "final_codex_stdin.sha256").read_text(encoding="utf-8").strip()) == 64


def test_command_ledger_extracts_reads_memory_and_xcode_actuals_from_argv() -> None:
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'rg \"Lab 7.3J\" /Users/example/.codex/memories/MEMORY.md'", "exit_code": 0, "status": "completed", "stdout": "Lab 7.3J\n"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'rg \"theme\" src tests'", "exit_code": 0, "status": "completed", "stdout": "src/app.py:1:theme\n"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'sed -n 1,20p src/app.py'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'nl -ba src/view.py'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'rg \"xcodebuild\" README.md'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'open -a Xcode .'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'xcodebuild test'", "exit_code": 0, "status": "completed"}},
    ]

    ledger = command_ledger_from_events(events)

    assert ledger["explicit_file_reads"] == ["src/app.py", "src/view.py", "README.md"]
    assert not any("MEMORY.md" in path for path in ledger["explicit_file_reads"])
    assert ledger["memory_command_count"] == 1
    assert ledger["memory_search_commands"]
    assert ledger["memory_search_before_repo_search"] is True
    assert ledger["memory_query_terms"] == ["Lab 7.3J"]
    assert ledger["memory_output_bytes"] > 0
    assert ledger["actual_xcode_command_count"] == 2
    assert ledger["xcode_command_violation_detected"] is True
    assert ledger["xcode_search_mention_count"] == 1
    assert ledger["xcode_string_mention_count"] >= 1
