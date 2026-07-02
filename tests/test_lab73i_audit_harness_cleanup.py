from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.config import init_project
from premode.lab73i import (
    build_lab73j_harness_config,
    build_lane_claims,
    cleanup_lab_branches,
    is_protected_branch,
)
from premode.live_ledger import command_ledger_from_events, parse_exploration_ledger_from_text
from premode.review_patch import review_patch


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False, timeout=30)


def _baseline(repo: Path) -> None:
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    result = _git(repo, "commit", "-m", "baseline")
    assert result.returncode == 0, result.stderr


def _write_packet_contract(repo: Path, contract: dict) -> None:
    out = repo / ".premode" / "out"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "packet_sha256": "a" * 64,
        "compiled_packet_sha256": "a" * 64,
        "review_contract": {
            "packet_sha256": "a" * 64,
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


def test_lane_final_and_harness_claims_write_structured_claims_file(repo: Path) -> None:
    lane = {
        "task": "robotriage",
        "lane": "auto",
        "worktree": str(repo),
        "lightweight_validation_results": [
            "python3 -m py_compile tools/create_demo_outputs.py tools/run_diagnostic_batch.py: pass",
            "model-reported tests/run_regression_tests.py: 11/11 diagnostic cases passed",
            "swiftc -parse touched Swift files: pass",
            "git diff --cached --quiet: pass",
            "pytest unavailable in lane; no dependency download attempted",
        ],
        "final_agent_messages": [
            "Validation:\n- Passed: `git diff --check`\n- Passed: `python3 tests/run_regression_tests.py` -> Summary: 11/11 diagnostic cases passed.\n- Not run: `pytest` unavailable.",
        ],
    }

    payload = build_lane_claims(lane)

    commands = [claim["command"] for claim in payload["claims"]]
    assert "python3 -m py_compile tools/create_demo_outputs.py tools/run_diagnostic_batch.py" in commands
    assert "python3 tests/run_regression_tests.py" in commands
    assert "git diff --check" in commands
    assert "swiftc -parse touched Swift files" in commands
    assert "git diff --cached --quiet" not in commands
    assert all(claim["trusted_as_execution_proof"] is False for claim in payload["claims"])


def test_review_patch_binds_json_claims_as_untrusted_specific_evidence(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "command.py").write_text("VALUE = 1\n", encoding="utf-8")
    _baseline(repo)
    _write_packet_contract(repo, {"candidate_edit_files": ["src/command.py"], "allowed_edit_files": ["src/command.py"], "packet_files": ["src/command.py"]})
    (repo / "src" / "command.py").write_text("VALUE = 2\n", encoding="utf-8")
    claims = repo / ".premode" / "out" / "claims.json"
    claims.write_text(
        json.dumps(
            {
                "source": "live_harness",
                "trusted_as_execution_proof": False,
                "claims": [
                    {
                        "command": "python3 tests/run_regression_tests.py",
                        "claimed_result": "11/11 diagnostic cases passed",
                        "source": "model_final_message",
                        "trusted_as_execution_proof": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    before = review_patch(repo, base_ref="HEAD")
    after = review_patch(repo, base_ref="HEAD", claims_path=claims)

    assert before["merge_readiness"] == "warning"
    assert after["merge_readiness"] == "pass"
    assert after["validation_evidence"][0]["trusted_as_execution_proof"] is False
    assert after["validation_evidence"][0]["source"] == "model_final_message"


def test_vague_and_unrelated_json_claims_do_not_satisfy_test_evidence(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "command.py").write_text("VALUE = 1\n", encoding="utf-8")
    _baseline(repo)
    _write_packet_contract(repo, {"candidate_edit_files": ["src/command.py"], "allowed_edit_files": ["src/command.py"], "packet_files": ["src/command.py"]})
    (repo / "src" / "command.py").write_text("VALUE = 2\n", encoding="utf-8")
    claims = repo / ".premode" / "out" / "claims.json"
    claims.write_text(
        json.dumps(
            {
                "claims": [
                    {"claimed_result": "tests passed", "source": "model_final_message"},
                    {"command": "npm test", "source": "model_final_message"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = review_patch(repo, base_ref="HEAD", claims_path=claims)

    assert result["merge_readiness"] == "warning"
    assert result["verification"]["verification_status"] == "claimed_without_evidence"


def test_command_ledger_categories_repeats_after_edit_and_failures() -> None:
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'pwd'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'rg -n value src tests'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'cat src/app.py'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'cat src/app.py'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "src/app.py", "kind": "update"}], "status": "completed"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Implemented the patch; final quick validation now."}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'python3 -m py_compile src/app.py'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'git status --short'", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'pytest'", "exit_code": 1, "status": "completed"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'unknown-tool --flag'", "exit_code": 0, "status": "completed"}},
    ]

    ledger = command_ledger_from_events(events)

    assert ledger["total"] == 9
    assert ledger["environment_probe_commands"] == 1
    assert ledger["search_commands"] == 1
    assert ledger["file_read_commands"] == 2
    assert ledger["edit_commands"] == 1
    assert ledger["validation_commands"] == 2
    assert ledger["status_diff_commands"] == 1
    assert ledger["other_commands"] == 1
    assert ledger["validation_commands_after_last_edit"] == 2
    assert ledger["status_diff_commands_after_last_edit"] == 1
    assert ledger["failed_or_blocked_commands"][0]["command"].endswith("pytest'")
    assert ledger["repeated_commands"][0]["count"] == 2
    assert ledger["commands_after_patch_complete_signal"] == 4


def test_command_output_path_mentions_do_not_count_as_explicit_file_reads() -> None:
    ledger = parse_exploration_ledger_from_text(
        "$ python3 tools/build.py\n"
        "output: README.md\n"
        "stdout wrote src/generated.py\n"
    )

    assert ledger["explicit_file_read_count"] == 0
    assert "README.md" in ledger["command_output_file_mentions"]


def test_lab73j_harness_config_balances_order_and_limits_forced_controls() -> None:
    metadata = {
        "tasks": {
            "robotriage": {
                "baseline": "/tmp/robotriage",
                "prompt": "canary robotriage",
                "lanes": {"standard": {"baseline_head": "abc"}, "auto": {"baseline_head": "abc"}},
            },
            "goldpine": {
                "baseline": "/tmp/goldpine",
                "prompt": "canary goldpine",
                "lanes": {"standard": {"baseline_head": "def"}, "auto": {"baseline_head": "def"}},
            },
            "rich_cli": {
                "baseline": "/tmp/rich",
                "prompt": "canary rich",
                "lanes": {"standard": {"baseline_head": "ghi"}, "auto": {"baseline_head": "ghi"}},
            },
        }
    }

    config = build_lab73j_harness_config(metadata, Path("/tmp/lab73j"))

    assert config["fresh_worktree_required_per_prompt_lane_repeat"] is True
    assert all(run["baseline_commit"] for run in config["runs"])
    assert all(run["worktree_path"] for run in config["runs"])
    canary_primary = [
        run for run in config["runs"]
        if run["repo"] == "robotriage" and run["prompt_id"] == "robotriage_p1" and run["lane"] in {"standard", "v3_auto"}
    ]
    assert len(canary_primary) == 6
    assert any(run["repeat_index"] == 2 and run["lane_order"][0] == "v3_auto" for run in canary_primary)
    forced = [run for run in config["runs"] if run["forced_control"]]
    assert forced
    assert all(run["prompt_id"].endswith("_p1") for run in forced)
    assert {run["lane"] for run in forced} == {"v3_paths_only", "v3_evidence_snippets"}
    assert config["parent_spawned_token_accounting"]["parent_pcodex_tokens"] is None
    assert config["parent_spawned_token_accounting"]["null_reason"]


def test_branch_cleanup_dry_run_preserves_protected_current_and_unique(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    _git(repo, "branch", "test-merged")
    _git(repo, "branch", "v73-protected")
    _git(repo, "checkout", "-b", "lab-unique")
    (repo / "unique.txt").write_text("keep\n", encoding="utf-8")
    _git(repo, "add", "unique.txt")
    _git(repo, "commit", "-m", "unique")
    _git(repo, "checkout", "master")

    cleanup = cleanup_lab_branches([repo], dry_run=True)
    result = cleanup["repos"][0]

    assert is_protected_branch("main")
    assert is_protected_branch("v73-protected")
    deleted = {item["branch"] for item in result["deleted_branches"]}
    preserved = {item["branch"]: item["reason"] for item in result["preserved_branches"]}
    assert "test-merged" in deleted
    assert preserved["lab-unique"] == "unique_commits"
    assert preserved["v73-protected"] == "protected_branch_pattern"
    assert result["no_staged_changes_confirmation"] is True
