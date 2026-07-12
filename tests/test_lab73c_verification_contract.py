from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.compiler import _review_contract_from_manifest, compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.review_patch import review_patch


RICH_PROMPT = (
    "Improve the CLI help text for choosing an output theme so users understand "
    "what values are allowed and what happens when they pass an invalid theme."
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _prepare_example_cli_repo(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "example_cli").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "example_cli" / "__main__.py").write_text(
        """
import argparse

THEMES = ["ansi_dark", "ansi_light", "monokai"]

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
    (repo / "tests" / "test_main.py").write_text(
        """
from example_cli.__main__ import build_parser

def test_theme_choices():
    parser = build_parser()
    theme_action = next(action for action in parser._actions if "--theme" in action.option_strings)
    assert "ansi_dark" in theme_action.choices
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Rich CLI\n\nUse `--theme` to choose output styling.\n", encoding="utf-8")
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def _compile_rich(repo: Path, prompt: str = RICH_PROMPT) -> dict:
    return compile_prompt(
        repo,
        prompt,
        "lite",
        packet_version="v3",
        packet_detail_mode="evidence_snippets",
        snippet_budget_tokens=900,
        save=True,
        record_artifacts=False,
    )


def _write_passing_claim(repo: Path) -> Path:
    claims = repo / ".premode" / "out" / "agent_report.md"
    claims.parent.mkdir(parents=True, exist_ok=True)
    claims.write_text("Ran python -m pytest. 1 passed.", encoding="utf-8")
    return claims


def test_example_cli_verification_edit_file_is_contract_inside(repo: Path) -> None:
    _prepare_example_cli_repo(repo)
    compiled = _compile_rich(repo)

    assert compiled["review_contract"]["candidate_edit_files"] == ["src/example_cli/__main__.py"]
    assert compiled["review_contract"]["verification_files"] == ["tests/test_main.py"]
    assert compiled["review_contract"]["verification_edit_files"] == ["tests/test_main.py"]

    (repo / "src" / "example_cli" / "__main__.py").write_text(
        (repo / "src" / "example_cli" / "__main__.py").read_text(encoding="utf-8").replace(
            'help="Output theme"',
            'help="Output theme. Allowed: ansi_dark, ansi_light, or monokai. Invalid values fail with parser usage."',
        ),
        encoding="utf-8",
    )
    (repo / "tests" / "test_main.py").write_text(
        (repo / "tests" / "test_main.py").read_text(encoding="utf-8")
        + "\n\ndef test_theme_help_mentions_invalid_values():\n    assert 'Invalid values' in build_parser().format_help()\n",
        encoding="utf-8",
    )

    result = review_patch(repo, claims_path=_write_passing_claim(repo))

    assert result["merge_readiness"] == "pass"
    assert "src/example_cli/__main__.py" in result["changed_candidate_files"]
    assert "tests/test_main.py" in result["changed_verification_edit_files"]
    assert "tests/test_main.py" not in result["changed_outside_packet_files"]
    assert "tests/test_main.py" not in result["changed_unlisted_files"]
    assert any("verification evidence coverage" in item for item in result["info_findings"])


def test_example_cli_source_only_edit_still_passes(repo: Path) -> None:
    _prepare_example_cli_repo(repo)
    _compile_rich(repo)
    (repo / "src" / "example_cli" / "__main__.py").write_text(
        (repo / "src" / "example_cli" / "__main__.py").read_text(encoding="utf-8").replace(
            'help="Output theme"',
            'help="Output theme. Allowed values: ansi_dark, ansi_light, monokai."',
        ),
        encoding="utf-8",
    )

    result = review_patch(repo, claims_path=_write_passing_claim(repo))

    assert result["merge_readiness"] == "pass"
    assert result["changed_candidate_files"] == ["src/example_cli/__main__.py"]
    assert result["changed_verification_edit_files"] == []


def test_example_cli_unrelated_file_edit_warns_outside_packet(repo: Path) -> None:
    _prepare_example_cli_repo(repo)
    _compile_rich(repo)
    (repo / "docs").mkdir()
    (repo / "docs" / "notes.md").write_text("unrelated\n", encoding="utf-8")

    result = review_patch(repo, since_compile=True)

    assert result["merge_readiness"] == "warning"
    assert "docs/notes.md" in result["changed_outside_packet_files"]
    assert any("outside the saved packet context" in item for item in result["warning_findings"])


def test_example_cli_support_file_edit_warns_separately(repo: Path) -> None:
    _prepare_example_cli_repo(repo)
    _compile_rich(repo)
    packet_path = repo / ".premode" / "out" / "last_packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    contract = packet["review_contract"]
    contract["support_files"] = ["README.md"]
    contract["read_only_support_files"] = ["README.md"]
    contract["packet_files"] = sorted(set(contract.get("packet_files", []) + ["README.md"]))
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (repo / "README.md").write_text("# Rich CLI\n\nChanged support text.\n", encoding="utf-8")

    result = review_patch(repo, since_compile=True)

    assert result["merge_readiness"] == "warning"
    assert "README.md" in result["changed_support_files"]
    assert any("support/reference context" in item for item in result["warning_findings"])


def test_review_contract_normalizes_locator_support_dicts() -> None:
    contract = _review_contract_from_manifest(
        {
            "patch_boundary": {
                "allowed_edit_files": [{"path": "src/example_cli/__main__.py"}],
            },
            "support_files": [
                {
                    "path": "README.md",
                    "kind": "docs",
                    "reason": "locator_support_evidence",
                }
            ],
            "verification_files": [{"path": "tests/test_main.py"}],
        },
        packet_sha256="test-sha",
    )

    assert contract["candidate_edit_files"] == ["src/example_cli/__main__.py"]
    assert contract["support_files"] == ["README.md"]
    assert "README.md" in contract["packet_files"]
    assert all("{'path':" not in path for path in contract["packet_files"])


def test_example_cli_prompt_forbidden_edit_still_blocks(repo: Path) -> None:
    _prepare_example_cli_repo(repo)
    _compile_rich(repo, RICH_PROMPT + " Do not touch README.md.")
    (repo / "README.md").write_text("# Forbidden change\n", encoding="utf-8")

    result = review_patch(repo, since_compile=True)

    assert result["merge_readiness"] == "blocked"
    assert "README.md" in result["prompt_forbidden_files_touched"]
