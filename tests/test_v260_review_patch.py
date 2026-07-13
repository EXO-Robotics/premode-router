from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.cli import main
from premode.codex_exec import CodexOptions, run_codex
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.review_patch import review_patch


def _git(repo: Path, *args: str) -> None:
    try:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"git {' '.join(args)} timed out in {repo}") from exc


def _prepare(repo: Path) -> None:
    init_project(repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text("from src.app import value\n\ndef test_value():\n    assert value() == 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def _compile(repo: Path, prompt: str = "Fix src/app.py without touching frontend/package.json") -> dict:
    return compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=True, save=True)


def test_review_patch_no_git_repo_errors_cleanly(tmp_path):
    result = review_patch(tmp_path)
    assert result["merge_readiness"] == "blocked"
    assert "requires a git repository" in result["error"]


def test_review_patch_no_packet_errors_cleanly(repo):
    _prepare(repo)
    result = review_patch(repo)
    assert result["merge_readiness"] == "blocked"
    assert "No saved Pre-mode packet found" in result["error"]


def test_review_patch_no_changes_passes(repo):
    _prepare(repo)
    _compile(repo)
    result = review_patch(repo)
    assert result["merge_readiness"] == "pass"
    assert result["changed_files"] == []
    assert result["recommended_next_step"] == "No patch changes detected."


def test_review_patch_reports_changed_files_and_json_out(repo):
    _prepare(repo)
    _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    out_path = repo / ".premode" / "out" / "review_report.json"
    result = review_patch(repo, out_path=out_path)
    assert "src/app.py" in result["changed_files"]
    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8"))["review_kind"] == "patch_review"


def test_allowed_file_change_passes_with_evidence(repo):
    _prepare(repo)
    _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    claims = repo / ".premode" / "out" / "agent_report.md"
    claims.write_text("Ran python -m pytest. 1 passed.", encoding="utf-8")
    result = review_patch(repo, claims_path=claims)
    assert result["merge_readiness"] == "pass"
    assert "src/app.py" in result["allowed_files_changed"]
    assert result["verification"]["verification_status"] == "evidence_found"


def test_unexpected_file_change_warns(repo):
    _prepare(repo)
    _compile(repo)
    (repo / "README.md").write_text("# Changed\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "warning"
    assert "README.md" in result["unexpected_files_changed"]


def test_forbidden_file_change_blocks(repo):
    _prepare(repo)
    _compile(repo, "Fix src/app.py")
    (repo / "src" / "premode").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "premode" / "codex_exec.py").write_text("# forbidden\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "blocked"
    assert "src/premode/codex_exec.py" in result["forbidden_files_touched"]


def test_prompt_forbidden_file_change_blocks(repo):
    _prepare(repo)
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text('{"scripts":{"test":"echo ok"}}\n', encoding="utf-8")
    index_project(repo, "lite")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add frontend")
    _compile(repo, "Fix src/app.py without touching frontend/package.json")
    (repo / "frontend" / "package.json").write_text('{"scripts":{"test":"echo bad"}}\n', encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "blocked"
    assert "frontend/package.json" in result["prompt_forbidden_files_touched"]


def test_secret_like_file_change_blocks(repo):
    _prepare(repo)
    _compile(repo)
    (repo / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "blocked"
    assert ".env" in result["secret_like_paths_touched"]


def test_generated_state_file_change_blocks(repo):
    _prepare(repo)
    _compile(repo)
    (repo / "PROJECT" / "state").mkdir(parents=True)
    (repo / "PROJECT" / "state" / "task_queue_normalized_latest.json").write_text("{}\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "blocked"
    assert "PROJECT/state/task_queue_normalized_latest.json" in result["generated_or_state_mutation"]


def test_dependency_file_change_warns(repo):
    _prepare(repo)
    _compile(repo, "Fix src/app.py")
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.2.0'\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "warning"
    assert "pyproject.toml" in result["dependency_or_build_files_changed"]


def test_ci_file_change_warns(repo):
    _prepare(repo)
    _compile(repo, "Fix src/app.py")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "test.yml").write_text("name: test\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "warning"
    assert ".github/workflows/test.yml" in result["ci_files_changed"]


def test_expected_verification_from_packet(repo):
    _prepare(repo)
    result = _compile(repo)
    contract = result["review_contract"]
    assert "expected_verification" in contract
    assert any("pytest" in cmd for cmd in contract["expected_verification"])


def test_claimed_tests_without_evidence_warns(repo):
    _prepare(repo)
    _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    claims = repo / ".premode" / "out" / "agent_report.md"
    claims.write_text("pytest passed", encoding="utf-8")
    result = review_patch(repo, claims_path=claims)
    assert result["merge_readiness"] == "warning"
    assert result["verification"]["verification_status"] == "claimed_without_evidence"


def test_test_log_evidence_found(repo):
    _prepare(repo)
    compiled = _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    packet_sha = compiled["compiled_packet_sha256"]
    (repo / ".premode" / "out" / "test.log").write_text(f"packet_sha256: {packet_sha}\npython -m pytest\n1 passed in 0.01s\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["verification"]["verification_status"] == "evidence_found"


def test_failed_test_log_blocks_or_warns(repo):
    _prepare(repo)
    compiled = _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    packet_sha = compiled["compiled_packet_sha256"]
    (repo / ".premode" / "out" / "test.log").write_text(f"packet_sha256: {packet_sha}\n1 failed, 0 passed\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "blocked"
    assert result["verification"]["verification_status"] == "failed_evidence_found"
    assert result["recommended_next_step"] == "Fix failing tests or revert the patch before review."


def test_premode_index_runtime_metadata_is_ignored(repo):
    _prepare(repo)
    _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    (repo / ".premode" / "index").mkdir(parents=True, exist_ok=True)
    (repo / ".premode" / "index" / "index.json").write_text("{}\n", encoding="utf-8")
    claims = repo / ".premode" / "out" / "agent_report.md"
    claims.write_text("python -m pytest\n1 passed\n", encoding="utf-8")
    result = review_patch(repo, claims_path=claims)
    assert ".premode/index/index.json" not in result["changed_files"]
    assert result["merge_readiness"] == "pass"


def test_zero_failed_is_not_failed_evidence(repo):
    _prepare(repo)
    compiled = _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    packet_sha = compiled["compiled_packet_sha256"]
    (repo / ".premode" / "out" / "test.log").write_text(f"packet_sha256: {packet_sha}\n10 passed, 0 failed in 0.12s\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "pass"
    assert result["verification"]["verification_status"] == "evidence_found"


def test_stale_passing_log_is_unbound_warning(repo):
    _prepare(repo)
    _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    (repo / ".premode" / "out" / "old.log").write_text("packet_sha256: " + "a" * 64 + "\n1 passed\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "warning"
    assert result["verification"]["verification_status"] == "evidence_present_but_unbound"


def test_stale_failing_log_is_unbound_not_blocking(repo):
    _prepare(repo)
    _compile(repo)
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    (repo / ".premode" / "out" / "old.log").write_text("packet_sha256: " + "b" * 64 + "\n1 failed, 0 passed\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "warning"
    assert result["verification"]["verification_status"] == "evidence_present_but_unbound"


def test_secret_like_old_path_rename_blocks(repo):
    _prepare(repo)
    (repo / ".env").write_text("TOKEN=baseline\n", encoding="utf-8")
    _git(repo, "add", ".env")
    _git(repo, "commit", "-m", "add secret baseline")
    _compile(repo, "Fix src/app.py")
    _git(repo, "mv", ".env", "config.txt")
    result = review_patch(repo)
    assert result["merge_readiness"] == "blocked"
    assert ".env" in result["secret_like_paths_touched"]


def test_prompt_forbidden_raw_path_without_fresh_index_blocks(repo):
    _prepare(repo)
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text('{"scripts":{"test":"echo ok"}}\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add frontend without reindexing")
    _compile(repo, "Edit src/app.py only; do not touch frontend/package.json or generated/state.json")
    (repo / "frontend" / "package.json").write_text('{"scripts":{"test":"echo bad"}}\n', encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "blocked"
    assert "frontend/package.json" in result["prompt_forbidden_files_touched"]


def test_no_tests_needed_for_docs_only_patch(repo):
    _prepare(repo)
    _compile(repo, "Update README.md docs")
    (repo / "README.md").write_text("# Docs only\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["verification"]["verification_status"] == "not_applicable"


def test_cli_review_patch_json_output(monkeypatch, capsys, repo):
    _prepare(repo)
    _compile(repo)
    monkeypatch.chdir(repo)
    rc = main(["review-patch", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["review_kind"] == "patch_review"


def test_pcodex_dry_run_does_not_save_packet_for_review(repo):
    _prepare(repo)
    dry = run_codex(repo, "Fix src/app.py", None, CodexOptions(dry_run=True))
    assert dry["saved_artifacts"] is None
    assert not (repo / ".premode" / "out" / "last_packet.json").exists()


def test_packet_v3_contains_review_contract(repo):
    _prepare(repo)
    result = _compile(repo)
    assert result["packet_version"] == "PREMODE_COMPILED_PACKET_V3"
    assert result["review_contract"]["allowed_edit_files"]
    saved = json.loads((repo / ".premode" / "out" / "last_packet.json").read_text(encoding="utf-8"))
    assert saved["review_contract"]["packet_sha256"] == result["compiled_packet_sha256"]


def test_v2_packet_fallback_still_compiles(repo):
    _prepare(repo)
    result = compile_prompt(repo, "Fix src/app.py", "lite", packet_version="v2")
    assert result["packet"].startswith("PREMODE_COMPILED_PACKET_V2")
    assert "review_contract" in result


def test_compile_saves_pre_agent_worktree_state(repo):
    _prepare(repo)
    result = _compile(repo)
    state = result["review_contract"]["pre_agent_worktree_state"]
    assert state["available"] is True
    assert state["git_head_sha"]
    saved = json.loads((repo / ".premode" / "out" / "last_packet.json").read_text(encoding="utf-8"))
    assert saved["pre_agent_worktree_state"]["git_head_sha"] == state["git_head_sha"]


def test_review_since_compile_ignores_preexisting_untracked_premode_setup_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "src/app.py")
    _git(repo, "commit", "-m", "baseline")
    init_project(repo)
    compile_prompt(repo, "Fix src/app.py", "lite", use_repo_map=True, cache_optimized=True, save=True)
    result = review_patch(repo, since_compile=True)
    assert result["merge_readiness"] == "pass"
    assert result["changed_files"] == []
    assert any(path.startswith(".premode/") or path == ".premodeignore" for path in result["preexisting_changes"])
    assert not any(path in result["unexpected_files_changed"] for path in result["preexisting_changes"])


def test_preexisting_dirty_file_changed_again_becomes_agent_candidate(repo):
    _prepare(repo)
    (repo / "notes.txt").write_text("preexisting note\n", encoding="utf-8")
    _compile(repo, "Fix src/app.py")
    (repo / "notes.txt").write_text("agent changed note\n", encoding="utf-8")
    result = review_patch(repo, since_compile=True)
    assert "notes.txt" in result["changed_files"]
    assert "notes.txt" in result["unexpected_files_changed"]
    assert result["merge_readiness"] == "warning"


def test_review_patch_reports_base_ref_fallback_metadata(repo):
    _prepare(repo)
    _compile(repo)
    result = review_patch(repo, base_ref="definitely_missing_branch")
    assert result["base_ref_requested"] == "definitely_missing_branch"
    assert result["base_ref_used"] == "HEAD"
    assert result["base_ref_fallback_reason"]


def test_review_patch_findings_are_split(repo):
    _prepare(repo)
    _compile(repo, "Fix src/app.py")
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.3.0'\n", encoding="utf-8")
    result = review_patch(repo)
    assert result["merge_readiness"] == "warning"
    assert result["blocking_findings"] == []
    assert any("dependency/build" in item for item in result["warning_findings"])
    assert result["risk_findings"] == result["warning_findings"] + result["info_findings"]


def test_review_patch_since_compile_uses_saved_head(repo):
    _prepare(repo)
    compiled = _compile(repo)
    saved_head = compiled["review_contract"]["pre_agent_worktree_state"]["git_head_sha"]
    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    result = review_patch(repo, since_compile=True)
    assert result["since_compile"] is True
    assert result["base_ref_used"] == saved_head
    assert result["diff_metadata"]["review_mode"] == "since_compile"
    assert "src/app.py" in result["changed_files"]


def test_untracked_generated_output_after_compile_blocks_since_compile(repo):
    _prepare(repo)
    _compile(repo, "Fix src/app.py without touching generated outputs or _claw_output.")
    (repo / "_claw_output" / "foo").mkdir(parents=True)
    (repo / "_claw_output" / "foo" / "result.txt").write_text("runtime proof\n", encoding="utf-8")
    result = review_patch(repo, since_compile=True)
    assert result["merge_readiness"] == "blocked"
    assert "_claw_output/foo/result.txt" in result["generated_or_state_mutation"]


def test_untracked_secret_like_file_after_compile_blocks(repo):
    _prepare(repo)
    _compile(repo, "Fix src/app.py")
    (repo / ".env.local").write_text("TOKEN=abc\n", encoding="utf-8")
    result = review_patch(repo, since_compile=True)
    assert result["merge_readiness"] == "blocked"
    assert ".env.local" in result["secret_like_paths_touched"]


def test_preexisting_untracked_file_at_compile_ignored_when_unchanged(repo):
    _prepare(repo)
    (repo / "notes.txt").write_text("preexisting\n", encoding="utf-8")
    _compile(repo, "Fix src/app.py")
    result = review_patch(repo, since_compile=True)
    assert result["merge_readiness"] == "pass"
    assert "notes.txt" in result["preexisting_changes"]
    assert "notes.txt" not in result["changed_files"]


def test_negative_directory_prompt_blocks_untracked_data_and_checkpoints(repo):
    _prepare(repo)
    _compile(repo, "Fix src/app.py. Do not touch notebooks, data, or model checkpoints.")
    (repo / "data").mkdir()
    (repo / "data" / "raw.csv").write_text("x\n", encoding="utf-8")
    (repo / "models").mkdir()
    (repo / "models" / "checkpoint.bin").write_text("weights\n", encoding="utf-8")
    result = review_patch(repo, since_compile=True)
    assert result["merge_readiness"] == "blocked"
    assert "data/raw.csv" in result["prompt_forbidden_files_touched"]
    assert "models/checkpoint.bin" in result["prompt_forbidden_files_touched"]
