from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.review_patch import review_patch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _baseline(repo: Path) -> None:
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


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


def test_auto_selects_paths_only_for_obvious_cli_flag_file(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "command.py").write_text(
        """
import argparse

def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-path", help="Path for exported files")
    return parser
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "paths.md").write_text("Output paths can be configured.\n", encoding="utf-8")

    result = _compile_auto(repo, "Improve the help text for --export-path in the command module.")

    assert result["packet_detail_mode_requested"] == "auto"
    assert result["packet_detail_mode_selected"] == "paths_only"
    signals = result["packet_mode_selection_signals"]
    assert signals["dominant_candidate"] is True
    assert signals["prompt_coverage_ratio"] >= 0.6
    assert result["paths_only_packet_tokens"] > 0
    assert result["evidence_snippet_packet_tokens"] > result["paths_only_packet_tokens"]


def test_auto_selects_paths_only_for_obvious_demo_script(repo: Path) -> None:
    init_project(repo)
    (repo / "tools").mkdir()
    (repo / "tools" / "sample_export.py").write_text(
        """
def main():
    print("Demo export complete")
    print("Sample export script wrote demo output")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("Export samples live in tools.\n", encoding="utf-8")

    result = _compile_auto(repo, "Update the demo output wording in the sample export script.")

    assert result["packet_detail_mode_selected"] == "paths_only"
    assert result["packet_mode_selection_signals"]["dominant_candidate"] is True
    assert result["promoted_support_candidate_files"] == []


def test_auto_selects_evidence_for_generic_checkout_index(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "checkout").mkdir(parents=True)
    (repo / "src" / "checkout" / "index.tsx").write_text(
        """
export function CheckoutScreen({ cart }) {
  if (!cart.items.length) return <p>Your cart is empty</p>
  return <button>Checkout</button>
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "src" / "checkout" / "cartState.ts").write_text(
        "export const emptyCartMessage = 'Your cart is empty';\n",
        encoding="utf-8",
    )

    result = _compile_auto(repo, "Improve the empty cart message shown on the checkout screen.")

    assert result["packet_detail_mode_selected"] == "evidence_snippets"
    signals = result["packet_mode_selection_signals"]
    assert signals["generic_filename_risk"] is True or signals["multi_surface_risk"] is True


def test_auto_selects_evidence_for_route_service_split(repo: Path) -> None:
    init_project(repo)
    (repo / "app" / "api" / "export").mkdir(parents=True)
    (repo / "app" / "api" / "export" / "route.ts").write_text(
        "import { createExportFolder } from '../../../src/services/exportFolder';\nexport async function POST(){ return createExportFolder(); }\n",
        encoding="utf-8",
    )
    (repo / "src" / "services").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "services" / "exportFolder.ts").write_text(
        "export function createExportFolder(){ throw new Error('Export folder creation failed'); }\n",
        encoding="utf-8",
    )

    result = _compile_auto(repo, "Fix the error shown when export folder creation fails.")

    assert result["packet_detail_mode_selected"] == "evidence_snippets"
    signals = result["packet_mode_selection_signals"]
    assert signals["multi_surface_risk"] is True or signals["top_score_gap_ratio"] < 0.35


def test_auto_selects_paths_only_for_clear_docs_update(repo: Path) -> None:
    init_project(repo)
    (repo / "README.md").write_text("Install with `oldtool install`.\n", encoding="utf-8")
    (repo / "src" / "cli.py").write_text("CLI_NAME = 'newtool'\n", encoding="utf-8")

    result = _compile_auto(repo, "Update the README installation command for the new CLI name.")

    assert result["packet_detail_mode_selected"] == "paths_only"
    assert "README.md" in _paths(result["candidate_edit_files"])


def test_auto_selects_evidence_for_behavior_fix_with_nearby_test(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "replay.py").write_text("REPLAY_TIMEOUT_SECONDS = 30\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_replay_timeout.py").write_text(
        "from src.replay import REPLAY_TIMEOUT_SECONDS\n\ndef test_timeout():\n    assert REPLAY_TIMEOUT_SECONDS == 30\n",
        encoding="utf-8",
    )

    result = _compile_auto(repo, "Fix replay timeout behavior and add regression coverage if needed.")

    assert result["packet_detail_mode_selected"] == "evidence_snippets"
    assert "tests/test_replay_timeout.py" in _paths(result["verification_files"] + result["verification_edit_files"])


def test_auto_marks_low_confidence_for_vague_flow_prompt(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "setup.py").write_text("def setup_flow():\n    return 'ready'\n", encoding="utf-8")
    (repo / "src" / "helpers.py").write_text("def helper():\n    return True\n", encoding="utf-8")

    result = _compile_auto(repo, "Make the setup flow better.")

    assert result["packet_mode_selection_signals"]["low_confidence_search_advised"] is True
    assert any("low-confidence" in reason or "ambiguity" in reason for reason in result["packet_mode_selection_reasons"])


def test_explicit_packet_mode_overrides_still_work(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "checkout").mkdir(parents=True)
    (repo / "src" / "checkout" / "index.tsx").write_text("export const message = 'Your cart is empty';\n", encoding="utf-8")
    index_project(repo, "lite")
    prompt = "Improve the empty cart message shown on the checkout screen."

    paths_only = compile_prompt(repo, prompt, "lite", packet_version="v3", packet_detail_mode="paths_only", record_artifacts=False)
    snippets = compile_prompt(repo, prompt, "lite", packet_version="v3", packet_detail_mode="evidence_snippets", record_artifacts=False)

    assert paths_only["packet_detail_mode"] == "paths_only"
    assert paths_only["packet_detail_mode_selected"] == "paths_only"
    assert snippets["packet_detail_mode"] == "evidence_snippets"
    assert snippets["packet_detail_mode_selected"] == "evidence_snippets"


def _write_packet_contract(repo: Path, contract: dict) -> None:
    out = repo / ".premode" / "out"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "packet_sha256": "test-packet",
        "compiled_packet_sha256": "test-packet",
        "review_contract": {
            "packet_sha256": "test-packet",
            "raw_prompt_sha256": "prompt",
            "secret_like_patterns": [],
            "generated_or_state_patterns": [],
            "dependency_or_build_patterns": [],
            "ci_patterns": [],
            "expected_verification": [],
            **contract,
        },
    }
    (out / "last_packet.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_review_patch_reports_promoted_support_candidate_edit(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "command.py").write_text("HELP = 'Export ready'\n", encoding="utf-8")
    (repo / "src" / "output_view.py").write_text("LABEL = 'Export ready'\n", encoding="utf-8")
    _baseline(repo)
    _write_packet_contract(
        repo,
        {
            "candidate_edit_files": ["src/command.py", "src/output_view.py"],
            "allowed_edit_files": ["src/command.py", "src/output_view.py"],
            "support_files": ["src/output_view.py"],
            "promoted_support_candidate_files": ["src/output_view.py"],
            "promotion_reasons": {"src/output_view.py": ["support file shares matched literal or symbol evidence with a candidate"]},
            "packet_files": ["src/command.py", "src/output_view.py"],
        },
    )
    (repo / "src" / "command.py").write_text("HELP = 'Export finished'\n", encoding="utf-8")
    (repo / "src" / "output_view.py").write_text("LABEL = 'Export finished'\n", encoding="utf-8")

    result = review_patch(repo, base_ref="HEAD")

    assert result["merge_readiness"] == "warning"
    assert "src/output_view.py" in result["changed_promoted_support_candidate_files"]
    assert "src/output_view.py" not in result["changed_outside_packet_files"]
    assert any("promoted support candidate" in item for item in result["info_findings"])


def test_review_patch_unrelated_support_and_test_only_semantics(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "command.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "README.md").write_text("Reference docs.\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_command.py").write_text("def test_value():\n    assert True\n", encoding="utf-8")
    _baseline(repo)
    _write_packet_contract(
        repo,
        {
            "candidate_edit_files": ["src/command.py"],
            "allowed_edit_files": ["src/command.py"],
            "support_files": ["README.md"],
            "verification_files": ["tests/test_command.py"],
            "verification_edit_files": ["tests/test_command.py"],
            "packet_files": ["src/command.py", "README.md", "tests/test_command.py"],
        },
    )
    (repo / "README.md").write_text("Changed reference docs.\n", encoding="utf-8")
    (repo / "tests" / "test_command.py").write_text("def test_value():\n    assert 1 == 1\n", encoding="utf-8")

    result = review_patch(repo, base_ref="HEAD")

    assert "README.md" in result["changed_support_files"]
    assert "tests/test_command.py" in result["changed_verification_edit_files"]
    assert "tests/test_command.py" not in result["changed_promoted_support_candidate_files"]
    assert result["merge_readiness"] == "warning"


def test_review_patch_prompt_forbidden_still_blocks(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "command.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "README.md").write_text("Do not edit.\n", encoding="utf-8")
    _baseline(repo)
    _write_packet_contract(
        repo,
        {
            "candidate_edit_files": ["src/command.py"],
            "allowed_edit_files": ["src/command.py"],
            "support_files": ["README.md"],
            "prompt_forbidden_files": ["README.md"],
            "packet_files": ["src/command.py", "README.md"],
        },
    )
    (repo / "README.md").write_text("Forbidden change.\n", encoding="utf-8")

    result = review_patch(repo, base_ref="HEAD")

    assert result["merge_readiness"] == "blocked"
    assert "README.md" in result["prompt_forbidden_files_touched"]


def test_specific_validation_claims_are_reported_as_untrusted_evidence(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "command.py").write_text("VALUE = 1\n", encoding="utf-8")
    _baseline(repo)
    _write_packet_contract(repo, {"candidate_edit_files": ["src/command.py"], "allowed_edit_files": ["src/command.py"], "packet_files": ["src/command.py"]})
    (repo / "src" / "command.py").write_text("VALUE = 2\n", encoding="utf-8")
    claims = repo / ".premode" / "out" / "claims.md"
    claims.write_text(
        "python3 tests/run_regression_tests.py with 11/11 diagnostic cases passed\n"
        "python3 -m py_compile tools/create_demo_outputs.py tools/run_diagnostic_batch.py\n"
        "git diff --check\n",
        encoding="utf-8",
    )

    result = review_patch(repo, base_ref="HEAD", claims_path=claims)

    commands = [item["command"] for item in result["validation_evidence"]]
    assert "python3 tests/run_regression_tests.py" in commands
    assert "python3 -m py_compile tools/create_demo_outputs.py tools/run_diagnostic_batch.py" in commands
    assert "git diff --check" in commands
    assert all(item["trusted_as_execution_proof"] is False for item in result["validation_evidence"])
    assert not any("Tests were claimed but no supporting evidence" in item for item in result["warning_findings"])


def test_vague_and_unrelated_validation_claims_do_not_satisfy_test_evidence(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "command.py").write_text("VALUE = 1\n", encoding="utf-8")
    _baseline(repo)
    _write_packet_contract(repo, {"candidate_edit_files": ["src/command.py"], "allowed_edit_files": ["src/command.py"], "packet_files": ["src/command.py"]})
    (repo / "src" / "command.py").write_text("VALUE = 2\n", encoding="utf-8")
    vague = repo / ".premode" / "out" / "vague.md"
    vague.write_text("tests passed\n", encoding="utf-8")

    vague_result = review_patch(repo, base_ref="HEAD", claims_path=vague)

    assert vague_result["merge_readiness"] == "warning"
    assert any("Tests were claimed but no supporting evidence" in item for item in vague_result["warning_findings"])
    unrelated = repo / ".premode" / "out" / "unrelated.md"
    unrelated.write_text("npm test\n", encoding="utf-8")
    unrelated_result = review_patch(repo, base_ref="HEAD", claims_path=unrelated)
    assert unrelated_result["validation_evidence"][0]["command"] == "npm test"
    assert unrelated_result["verification"]["verification_status"] == "claimed_without_evidence"
