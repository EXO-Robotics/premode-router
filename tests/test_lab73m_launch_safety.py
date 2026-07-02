from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import cli
from premode.codex_exec import CodexOptions, codex_capabilities_from_help, run_codex
from premode.config import init_project
from premode.indexer import index_project
from premode.launch_safety import (
    REQUIRED_EXTERNAL_PAYLOAD_FIELDS,
    RootGuardError,
    build_external_payload_manifest,
    resolve_cli_repo,
)


CODEX_HELP = """
Usage: codex exec [OPTIONS] -
  -C <DIR>
  --sandbox <MODE>
  --approval-mode <MODE>
  --ephemeral
"""


def test_explicit_repo_is_respected_literally_and_reports_parent_git_root(repo: Path) -> None:
    nested = repo / "src"
    resolution = resolve_cli_repo(repo, nested)

    assert resolution.repo == nested.resolve()
    assert resolution.guard["explicit_repo"] is True
    assert resolution.guard["cwd_git_root"] == str(repo.resolve())
    assert resolution.guard["intended_worktree"] == str(nested.resolve())
    assert resolution.guard["root_escalated"] is True
    assert resolution.guard["git_root_equals_intended_worktree"] is False
    assert resolution.guard["scan_budget"] == 5000
    assert isinstance(resolution.guard["intended_file_count"], int)
    assert isinstance(resolution.guard["detected_file_count"], int)


def test_auto_repo_discovery_reports_root_escalation(repo: Path) -> None:
    nested = repo / "src"
    resolution = resolve_cli_repo(nested)

    assert resolution.repo == repo.resolve()
    assert resolution.guard["explicit_repo"] is False
    assert resolution.guard["root_escalated"] is True
    assert resolution.guard["cwd_git_root"] == str(repo.resolve())
    assert resolution.guard["intended_worktree"] == str(nested.resolve())


def test_root_guard_can_hard_fail_on_escalation(repo: Path) -> None:
    nested = repo / "src"

    with pytest.raises(RootGuardError) as raised:
        resolve_cli_repo(repo, nested, fail_on_root_escalation=True)

    assert raised.value.guard["root_escalated"] is True
    assert raised.value.guard["error"] == "detected git root differs from intended worktree"


def test_external_payload_manifest_has_required_fields_and_blocks_git_root_mismatch(repo: Path) -> None:
    nested = repo / "src"
    manifest = build_external_payload_manifest(
        run_id="lab73m",
        repo=nested,
        lane="auto",
        cwd=nested,
        intended_worktree=nested,
        final_stdin_path=nested / ".premode" / "out" / "external_payload_stdin.txt",
        packet="PREMODE_COMPILED_PACKET_V3\nFiles: src/App.swift\n",
        compiled={"packet_detail_mode": "paths_only"},
    )

    for field in REQUIRED_EXTERNAL_PAYLOAD_FIELDS:
        assert field in manifest
    assert manifest["git_root_equals_intended_worktree"] is False
    assert manifest["launch_allowed"] is False
    assert "cwd_git_root_mismatch" in manifest["block_reasons"]


def test_external_payload_blocks_private_repo_source_snippets(repo: Path) -> None:
    manifest = build_external_payload_manifest(
        run_id="lab73m",
        repo=repo,
        lane="enhanced",
        cwd=repo,
        intended_worktree=repo,
        final_stdin_path=repo / ".premode" / "out" / "external_payload_stdin.txt",
        packet="PREMODE_COMPILED_PACKET_V3\n```swift\nstruct SecretFeature {}\n```\n",
        compiled={"packet_detail_mode": "evidence_snippets"},
        repo_is_private=True,
    )

    assert manifest["contains_source_snippets"] is True
    assert manifest["launch_allowed"] is False
    assert "private_repo_source_snippets" in manifest["block_reasons"]


def test_external_payload_blocks_private_paths_only_when_policy_forbids_path_disclosure(repo: Path) -> None:
    manifest = build_external_payload_manifest(
        run_id="lab73m",
        repo=repo,
        lane="paths-only",
        cwd=repo,
        intended_worktree=repo,
        final_stdin_path=repo / ".premode" / "out" / "external_payload_stdin.txt",
        packet=f"PREMODE_COMPILED_PACKET_V3\nFiles: {repo / 'src' / 'App.swift'}\n",
        compiled={"packet_detail_mode": "paths_only"},
        repo_is_private=True,
        private_paths_forbidden=True,
    )

    assert manifest["contains_source_snippets"] is False
    assert manifest["contains_absolute_paths"] is True
    assert manifest["launch_allowed"] is False
    assert "private_repo_paths_forbidden" in manifest["block_reasons"]


def test_codex_dry_run_writes_external_payload_manifest(monkeypatch, repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")
    caps = codex_capabilities_from_help(CODEX_HELP)
    monkeypatch.setattr("premode.codex_exec.detect_codex_capabilities", lambda: caps)

    dry = run_codex(repo, "Fix src/App.swift", "lite", CodexOptions(dry_run=True))

    manifest_path = Path(dry["external_payload_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_path.name == "external_payload_manifest.json"
    assert Path(manifest["final_stdin_path"]).name == "external_payload_stdin.txt"
    assert manifest["launch_allowed"] is True
    assert manifest["final_stdin_sha256"] == dry["compiled_packet_sha256"]
    assert manifest["final_stdin_bytes"] > 0


def test_cli_codex_repo_flag_passes_literal_repo_to_launch_path(monkeypatch, repo: Path) -> None:
    nested = repo / "src"
    captured = {}

    def fake_run_codex(repo_root: Path, prompt: str, profile: str | None, options: CodexOptions) -> dict:
        captured["repo_root"] = repo_root
        captured["prompt"] = prompt
        captured["profile"] = profile
        captured["options"] = options
        return {"returncode": 0, "external_launch_allowed": True}

    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "run_codex", fake_run_codex)

    assert cli.main(["codex", "Fix src/App.swift", "--repo", str(nested), "--dry-run"]) == 0
    assert captured["repo_root"] == nested.resolve()
    assert captured["prompt"] == "Fix src/App.swift"
    assert captured["options"].dry_run is True


def test_cli_codex_repo_flag_can_fail_hard_on_root_escalation(monkeypatch, capsys, repo: Path) -> None:
    nested = repo / "src"
    monkeypatch.chdir(repo)

    with pytest.raises(SystemExit) as raised:
        cli.main(["codex", "Fix src/App.swift", "--repo", str(nested), "--fail-on-root-escalation", "--dry-run"])

    assert raised.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["root_guard"]["root_escalated"] is True
    assert payload["root_guard"]["intended_worktree"] == str(nested.resolve())
