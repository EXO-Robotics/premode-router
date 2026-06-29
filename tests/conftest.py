from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


def _child_process_summary() -> str:
    try:
        result = subprocess.run(
            ["ps", "-o", "pid,ppid,stat,command", "-ax"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return f"child process scan unavailable: {exc}"
    current = str(os.getpid())
    lines = [line for line in result.stdout.splitlines() if line.split()[1:2] == [current]]
    return "\n".join(lines) if lines else "no direct child processes still alive"


def pytest_configure(config: pytest.Config) -> None:
    faulthandler.enable(file=sys.stderr)
    timeout = int(os.environ.get("PREMODE_PYTEST_TRACE_TIMEOUT_SECS", "300"))
    if timeout > 0:
        faulthandler.dump_traceback_later(timeout, repeat=True, file=sys.stderr)
    config._premode_test_start = time.monotonic()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    faulthandler.cancel_dump_traceback_later()
    elapsed = time.monotonic() - getattr(session.config, "_premode_test_start", time.monotonic())
    if exitstatus != 0 or os.environ.get("PREMODE_TEST_DIAGNOSTICS"):
        print(f"\n[premode-test-diagnostics] elapsed={elapsed:.2f}s exitstatus={exitstatus}", file=sys.stderr)
        print("[premode-test-diagnostics] direct child processes:", file=sys.stderr)
        print(_child_process_summary(), file=sys.stderr)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True, timeout=30)
    (tmp_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Keep scope tight.\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.swift").write_text("struct App { let value = 1 }\n", encoding="utf-8")
    return tmp_path
