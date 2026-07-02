from __future__ import annotations

import json
from pathlib import Path

from premode.benchmark import compile_mode_comparison
from premode.cli import main
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.evidence_snippets import extract_evidence_snippets, has_interpretive_snippet_text
from premode.indexer import index_project
from premode.live_ledger import normalize_live_metrics, normalize_token_ledger
from premode.locator import locate_files


RICH_PROMPT = (
    "Improve the CLI help text for choosing an output theme so users understand "
    "what values are allowed and what happens when they pass an invalid theme."
)


def _prepare_cli_repo(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "rich_cli").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "rich_cli" / "__main__.py").write_text(
        """
import argparse

THEMES = ["ansi_dark", "monokai", "solarized-light"]

def build_parser():
    parser = argparse.ArgumentParser(description="Render rich CLI output")
    parser.add_argument("--theme", default="ansi_dark", choices=THEMES, help="Output theme")
    return parser

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.theme
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_rich_cli.py").write_text(
        """
from rich_cli.__main__ import build_parser

def test_theme_choices():
    parser = build_parser()
    assert parser
""".strip()
        + "\n",
        encoding="utf-8",
    )
    index_project(repo, "lite")


def test_locate_json_includes_factual_snippets(monkeypatch, capsys, repo: Path) -> None:
    _prepare_cli_repo(repo)
    monkeypatch.chdir(repo)

    rc = main(["locate", RICH_PROMPT, "--json", "--snippet-budget-tokens", "400"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["prompt"] == RICH_PROMPT
    assert payload["primary_files"]
    assert payload["primary_files"][0]["matched_signals"]
    snippets = payload["primary_files"][0]["snippets"]
    assert snippets
    assert snippets[0]["start_line"] <= snippets[0]["end_line"]
    assert "--theme" in snippets[0]["text"] or "theme" in snippets[0]["text"].lower()
    assert not has_interpretive_snippet_text(snippets)


def test_snippet_extraction_line_ranges_and_budget(repo: Path) -> None:
    _prepare_cli_repo(repo)
    located = locate_files(repo, RICH_PROMPT)

    packet = extract_evidence_snippets(
        repo,
        RICH_PROMPT,
        primary_files=located.primary_files,
        support_files=located.support_files,
        verification_files=located.verification_files,
        snippet_budget_tokens=120,
    )

    assert packet["model_facing_evidence_tokens"] <= 120
    assert packet["snippets"]
    for snippet in packet["snippets"]:
        assert snippet["start_line"] >= 1
        assert snippet["end_line"] >= snippet["start_line"]
        assert len(snippet["text"].splitlines()) < 12
    assert not has_interpretive_snippet_text(packet["snippets"])


def test_v3_paths_only_stays_small_and_evidence_mode_adds_suffix_snippets(repo: Path) -> None:
    _prepare_cli_repo(repo)

    paths_only = compile_prompt(repo, RICH_PROMPT, "lite", packet_version="v3", packet_detail_mode="paths_only", record_artifacts=False)
    with_snippets = compile_prompt(repo, RICH_PROMPT, "lite", packet_version="v3", packet_detail_mode="evidence_snippets", snippet_budget_tokens=1000, record_artifacts=False)

    assert paths_only["packet"].startswith("PREMODE_COMPILED_PACKET_V3")
    assert paths_only["packet_detail_mode"] == "paths_only"
    assert "## 12. Do-Not-Edit Paths" in paths_only["packet"]
    assert "Compact Factual Evidence Snippets" not in paths_only["packet"]
    assert paths_only["metrics"]["model_facing_evidence_tokens"] == 0

    assert with_snippets["packet_detail_mode"] == "evidence_snippets"
    assert "## 12. Compact Factual Evidence Snippets" in with_snippets["packet"]
    assert with_snippets["metrics"]["model_facing_evidence_tokens"] > 0
    assert with_snippets["metrics"]["packet_total_tokens"] > paths_only["metrics"]["packet_total_tokens"]
    assert with_snippets["metrics"]["paths_only_packet_tokens"] == paths_only["metrics"]["packet_total_tokens"]
    assert with_snippets["cacheable_prefix_sha256"] == paths_only["cacheable_prefix_sha256"]
    assert with_snippets["packet"].index("Compact Factual Evidence Snippets") > with_snippets["packet"].index("## DYNAMIC SUFFIX")
    assert "last_context_manifest" in with_snippets["packet"]


def test_metrics_naming_and_compile_mode_comparison(repo: Path) -> None:
    _prepare_cli_repo(repo)

    result = compile_prompt(repo, RICH_PROMPT, "lite", packet_version="v3", packet_detail_mode="evidence_snippets", record_artifacts=False)
    metrics = result["metrics"]
    assert metrics["full_repo_reduction_percent"] == metrics["estimated_savings_vs_eligible_repo_percent"]
    assert "live savings" not in result["packet"].lower()

    modes = compile_mode_comparison(repo, RICH_PROMPT, profile="lite", use_repo_map=False, snippet_budget_tokens=800)
    by_mode = {item["mode"]: item for item in modes}
    assert {"standard_raw_prompt", "v3_paths_only", "v3_evidence_snippets", "v2_full_context_if_available"} <= set(by_mode)
    assert by_mode["v3_paths_only"]["model_facing_evidence_tokens"] == 0
    assert by_mode["v3_evidence_snippets"]["model_facing_evidence_tokens"] > 0
    assert by_mode["v3_evidence_snippets"]["packet_total_tokens"] > by_mode["v3_paths_only"]["packet_total_tokens"]


def test_live_token_ledger_nulls_and_cache_adjustment() -> None:
    ledger = normalize_token_ledger({"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 70})
    assert ledger["input_tokens_total"] == 1000
    assert ledger["input_tokens_uncached"] == 400
    assert ledger["input_tokens_cached"] == 600
    assert ledger["cache_adjusted_input_tokens"] == 460
    assert ledger["output_tokens"] == 70

    missing = normalize_live_metrics({})
    assert missing["token_ledger"]["input_tokens_total"] is None
    assert missing["token_ledger"]["cache_adjusted_input_tokens"] is None
    assert missing["exploration_ledger"]["command_count"] is None
