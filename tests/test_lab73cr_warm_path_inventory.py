from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from premode import cli
from premode import pcodex_bootstrap as pcodex
from premode.compiler import compile_prompt
from premode.inventory import (
    build_inventory,
    inventory_cache_path,
    inventory_is_fresh,
    load_inventory,
    refresh_inventory_if_needed,
)


RAW_PROMPT = "Fix the failing login test"
LITERAL_SYMBOL_KWARGS = {
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _commit(repo: Path, message: str = "seed") -> None:
    subprocess.run(
        ["git", "-c", "user.name=Pre Mode", "-c", "user.email=premode@example.test", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _repo(tmp_path: Path, *, commit: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo / "README.md", "# Test Repo")
    _write(repo / "AGENTS.md", "Keep scope tight.")
    _write(repo / "src" / "auth" / "login.py", "def login_user(name):\n    return name.strip()")
    _write(repo / "tests" / "test_login.py", "from src.auth.login import login_user\n\ndef test_login_user():\n    assert login_user(' a ') == 'a'")
    _write(repo / ".gitignore", ".premode/\nnode_modules/\nbuild/\n")
    _git(repo, "add", "README.md", "AGENTS.md", "src/auth/login.py", "tests/test_login.py", ".gitignore")
    if commit:
        _commit(repo)
    return repo


def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PCODEX_ENABLED", raising=False)
    monkeypatch.delenv("PCODEX_ALGORITHM", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG_PATH", raising=False)


def test_git_inventory_uses_ls_files_and_records_tracked_untracked(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "src" / "auth" / "new_helper.py", "def helper():\n    return True")

    result = build_inventory(repo)
    inventory = result.inventory
    assert inventory is not None
    assert inventory["inventory_source"] == "git_ls_files"
    assert "src/auth/login.py" in inventory["paths"]
    assert "src/auth/new_helper.py" in inventory["paths"]
    assert inventory["tracked_count"] >= 4
    assert inventory["untracked_count"] >= 1
    assert result.metrics.git_commands_run >= 2
    assert result.metrics.full_walk_performed is False


def test_inventory_respects_premodeignore_and_skips_runtime_generated_dirs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / ".premodeignore", "secret_notes.md\nlogs/\n")
    _write(repo / "secret_notes.md", "do not include")
    _write(repo / "logs" / "build.log", "hidden")
    _write(repo / ".premode" / "out" / "cache_manifest.json", "{}")
    _write(repo / "node_modules" / "pkg" / "index.js", "module.exports = {}")
    _write(repo / "build" / "generated.py", "x = 1")

    inventory = build_inventory(repo).inventory
    assert inventory is not None
    assert "secret_notes.md" not in inventory["paths"]
    assert "logs/build.log" not in inventory["paths"]
    assert not any(path.startswith(".premode/") for path in inventory["paths"])
    assert not any(path.startswith("node_modules/") for path in inventory["paths"])
    assert not any(path.startswith("build/") for path in inventory["paths"])
    assert inventory["ignored_by_premode_count"] >= 2
    assert inventory["skipped_runtime_count"] >= 0
    assert inventory["skipped_generated_count"] >= 0


def test_inventory_cache_is_written_under_ignored_local_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    build_inventory(repo)
    path = inventory_cache_path(repo)
    assert path == repo / ".premode" / "inventory" / "files.json"
    assert path.exists()
    assert load_inventory(repo)["schema_version"] == "premode.git_file_inventory.v1"
    ignored = subprocess.run(["git", "check-ignore", ".premode/inventory/files.json"], cwd=repo, text=True, capture_output=True)
    assert ignored.returncode == 0


def test_inventory_freshness_detects_schema_branch_head_file_and_ignore_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    payload = build_inventory(repo).inventory
    assert inventory_is_fresh(repo, payload) == "fresh"

    bad_schema = dict(payload)
    bad_schema["schema_version"] = "old"
    assert inventory_is_fresh(repo, bad_schema) == "stale_schema_changed"

    bad_branch = dict(payload)
    bad_branch["git_branch"] = "other"
    assert inventory_is_fresh(repo, bad_branch) == "stale_branch_changed"

    bad_head = dict(payload)
    bad_head["git_head"] = "0000000"
    assert inventory_is_fresh(repo, bad_head) == "stale_head_changed"

    _write(repo / "src" / "auth" / "untracked_file.py", "x = 1")
    assert inventory_is_fresh(repo, payload) == "stale_file_set_changed"

    refreshed = build_inventory(repo).inventory
    _write(repo / ".premodeignore", "tmp/\n")
    assert inventory_is_fresh(repo, refreshed) == "stale_ignore_changed"


def test_non_git_repo_falls_back_to_os_walk_and_reports_reason(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    _write(repo / "src" / "app.py", "print('hello')")

    result = build_inventory(repo)
    inventory = result.inventory
    assert inventory is not None
    assert inventory["inventory_source"] == "os_walk_fallback"
    assert inventory["fallback_reason"] == "non_git_repo"
    assert result.metrics.full_walk_performed is True


def test_warm_compile_with_fresh_inventory_does_not_full_walk_or_rglob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    cold = compile_prompt(repo, RAW_PROMPT, "lite", record_artifacts=True, **LITERAL_SYMBOL_KWARGS)
    assert cold["metrics"]["inventory_cache_miss"] is True
    assert cold["inventory"]["source"] == "git_ls_files"
    assert cold["packet"]

    def forbidden_walk(*_args: Any, **_kwargs: Any):
        raise AssertionError("os.walk forbidden after inventory is fresh")

    def forbidden_rglob(*_args: Any, **_kwargs: Any):
        raise AssertionError("Path.rglob forbidden after inventory is fresh")

    monkeypatch.setattr(os, "walk", forbidden_walk)
    monkeypatch.setattr(Path, "rglob", forbidden_rglob)

    warm = compile_prompt(repo, RAW_PROMPT, "lite", record_artifacts=False, **LITERAL_SYMBOL_KWARGS)
    assert warm["metrics"]["inventory_cache_hit"] is True
    assert warm["metrics"]["full_walk_performed"] is False
    assert warm["inventory"]["cache_hit"] is True
    assert warm["inventory"]["full_walk_performed"] is False
    assert warm["packet"] == cold["packet"]


def test_compile_json_metrics_and_status_doctor_inventory_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    compile_prompt(repo, RAW_PROMPT, "lite", record_artifacts=True, **LITERAL_SYMBOL_KWARGS)

    result = compile_prompt(repo, RAW_PROMPT, "lite", record_artifacts=False, **LITERAL_SYMBOL_KWARGS)
    metrics = result["metrics"]
    assert metrics["files_listed"] >= 1
    assert metrics["files_stat_checked"] >= 1
    assert metrics["bytes_read"] >= 0
    assert isinstance(metrics["compile_ms"], int)
    assert metrics["inventory_cache_hit"] is True
    assert metrics["full_walk_performed"] is False

    status = pcodex.status(repo)
    doctor = pcodex.doctor(repo)
    for payload in (status, doctor):
        inventory = payload["inventory"]
        assert inventory["state"] == "fresh"
        assert inventory["source"] == "git_ls_files"
        assert inventory["file_count"] >= 1
        assert "paths" not in inventory

    assert "Inventory: fresh, git_ls_files" in pcodex.format_status(status)
    assert "Inventory: fresh, git_ls_files" in pcodex.format_doctor(doctor)

    assert cli.main(["compile", RAW_PROMPT, "--repo", str(repo), "--plugin", "literal_symbol", "--profile", "lite", "--json", "--no-record"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metrics"]["inventory_cache_hit"] is True
    assert payload["inventory"]["state"] == "fresh"
    assert "paths" not in payload["inventory"]


def test_inventory_cache_is_content_free(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    secret_prompt = "SECRET_LCC_PROMPT_NEVER_STORE"
    compile_prompt(repo, secret_prompt, "lite", record_artifacts=True, **LITERAL_SYMBOL_KWARGS)
    text = inventory_cache_path(repo).read_text(encoding="utf-8")
    assert secret_prompt not in text
    assert "def login_user" not in text
    assert "<TASK>" not in text


def test_model_facing_v5_packet_and_explicit_flags_remain_stable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    before = compile_prompt(repo, RAW_PROMPT, "lite", record_artifacts=False, **LITERAL_SYMBOL_KWARGS)
    build_inventory(repo)
    after = compile_prompt(repo, RAW_PROMPT, "lite", record_artifacts=False, **LITERAL_SYMBOL_KWARGS)
    assert after["packet"] == before["packet"]
    assert RAW_PROMPT in after["packet"]
    assert "<TASK_CLASS>" not in after["packet"]
    assert "<SUPPORT_RELATIONS>" not in after["packet"]

    code = cli.main([
        "compile",
        RAW_PROMPT,
        "--repo",
        str(repo),
        "--packet-version",
        "v5",
        "--packet-variant",
        "tool_assisted_anchors_internal",
        "--packet-strategy",
        "literal_symbol",
        "--profile",
        "lite",
        "--json",
        "--no-record",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["packet_version"] == "v5"
    assert payload["packet_variant"] == "tool_assisted_anchors_internal"
