from __future__ import annotations

from pathlib import Path

import pytest

from premode import codex_exec
from premode.codex_exec import CodexOptions
from premode.no_write import ProcessMonitor, classify_process


def test_forbidden_process_classification_is_exact() -> None:
    assert classify_process("/usr/local/bin/codex exec -") == "codex"
    assert classify_process("/opt/openclaw-agent run") == "openclaw"
    assert classify_process("/tmp/mcp-server") == "mcp"
    assert classify_process("/bin/sh /tmp/codex exec -") == "codex"
    assert classify_process("/usr/bin/env FLAG=1 /tmp/openclaw-agent run") == "openclaw"
    assert classify_process("/usr/bin/node /tmp/codex.js") == "codex"
    assert classify_process("/usr/bin/python -m premode.pcodex_mcp_server") == "mcp"
    assert classify_process("/usr/bin/python -m my_mcp_server") == "mcp"
    assert classify_process("/venv/bin/premode codex Exact-task --dry-run") is None
    assert classify_process("/venv/bin/pcodex integrate codex --dry-run") is None
    assert classify_process("/usr/bin/git status") is None
    assert classify_process("/usr/bin/python test_codex_parser.py") is None


def test_process_monitor_reports_launch_during_window(monkeypatch: pytest.MonkeyPatch) -> None:
    samples = iter(
        [
            {1: {"pid": 1, "ppid": 0, "start_time": "a", "command": "init"}},
            {
                1: {"pid": 1, "ppid": 0, "start_time": "a", "command": "init"},
                22: {"pid": 22, "ppid": 1, "start_time": "b", "command": "/usr/local/bin/codex exec -"},
            },
            {1: {"pid": 1, "ppid": 0, "start_time": "a", "command": "init"}},
        ]
    )
    monkeypatch.setattr("premode.no_write._read_process_table", lambda: next(samples, {1: {"pid": 1, "ppid": 0, "start_time": "a", "command": "init"}}))
    monitor = ProcessMonitor(interval_seconds=0)
    monitor.root_pid = 1
    with monitor:
        for _ in range(10000):
            if monitor.observed:
                break
    assert monitor.forbidden and monitor.forbidden[0]["classification"] == "codex"


def test_codex_dry_run_forces_all_write_and_capability_probes_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    compiled = {
        "packet": "PREMODE_CONTEXT_PACKET_V5\nTASK\nExact task",
        "compiled_packet_sha256": "packet-sha",
        "packet_version": "v5",
        "saved_artifacts": None,
        "production_ranking": {"routing_mode": "abstain"},
    }
    observed = {}

    def fake_compile(*args, **kwargs):
        observed.update(kwargs)
        return compiled

    monkeypatch.setattr(codex_exec, "compile_prompt", fake_compile)
    monkeypatch.setattr(codex_exec, "detect_codex_capabilities", lambda: pytest.fail("dry-run executed Codex capability probe"))
    monkeypatch.setattr(codex_exec, "write_external_payload_manifest", lambda *a, **k: pytest.fail("dry-run wrote external manifest"))
    monkeypatch.setattr(codex_exec, "write_audit", lambda *a, **k: pytest.fail("dry-run wrote audit"))
    monkeypatch.setattr(codex_exec, "append_metric", lambda *a, **k: pytest.fail("dry-run wrote metric"))

    result = codex_exec.run_codex(repo, "Exact task", options=CodexOptions(dry_run=True, save=True, record=True))
    assert observed["save"] is False
    assert observed["record_artifacts"] is False
    assert result["compile_settings"]["save"] is False
    assert result["compile_settings"]["record"] is False
    assert result["external_payload_manifest"] is None


def test_real_run_retains_apply_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    observed = {}
    monkeypatch.setattr(
        codex_exec,
        "compile_prompt",
        lambda *args, **kwargs: observed.update(kwargs) or {
            "packet": "PREMODE_CONTEXT_PACKET_V5\nTASK\nExact task",
            "compiled_packet_sha256": "packet-sha",
            "production_ranking": {"routing_mode": "abstain"},
        },
    )
    monkeypatch.setattr(codex_exec, "write_external_payload_manifest", lambda **kwargs: {"manifest_path": "receipt", "manifest": {"launch_allowed": False, "block_reasons": ["test"]}})
    monkeypatch.setattr(codex_exec, "write_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(codex_exec, "append_metric", lambda *args, **kwargs: None)
    monkeypatch.setattr(codex_exec, "detect_codex_capabilities", lambda: codex_exec.codex_capabilities_from_help(""))
    result = codex_exec.run_codex(repo, "Exact task", options=CodexOptions(dry_run=False, execute=True, save=True, record=True))
    assert observed["save"] is True
    assert observed["record_artifacts"] is True
    assert result["external_launch_allowed"] is False
