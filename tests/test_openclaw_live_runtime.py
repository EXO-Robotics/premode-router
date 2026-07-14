from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import premode.openclaw_lifecycle as lifecycle
from premode.openclaw_integration import openclaw_compatibility
from premode.openclaw_lifecycle import (
    install_integration,
    integration_status,
    uninstall_integration,
)


def _write(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")


def test_live_openclaw_2026_4_14_discovers_exact_registration(
    tmp_path: Path,
) -> None:
    executable = shutil.which("openclaw")
    if executable is None and Path("/opt/homebrew/bin/openclaw").is_file():
        executable = "/opt/homebrew/bin/openclaw"
    compatibility = openclaw_compatibility()
    if executable is None or compatibility.get("version") != "2026.4.14":
        pytest.skip("live OpenClaw 2026.4.14 runtime is unavailable")
    if not lifecycle._installed_helper_authority_available(Path(sys.executable)):
        pytest.skip("live source checkout is not installed helper authority")

    workspace = tmp_path / "OpenClaw workspace Ω with spaces"
    workspace.mkdir()
    for marker in (
        "AGENTS.md",
        "PROJECT/tasks.json",
        "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    ):
        _write(workspace, marker)
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".openclaw/openclaw.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "OPENCLAW_CONFIG_PATH": str(config),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "TMPDIR": str(tmp_path / "tmp"),
    }
    Path(env["TMPDIR"]).mkdir()

    install_integration(workspace, environ=env)
    assert integration_status(workspace, environ=env)["readiness"] == "READY"

    validated = subprocess.run(
        [executable, "config", "validate", "--json"],
        env=env,
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout)["valid"] is True

    shown = subprocess.run(
        [executable, "mcp", "show", "pcodex", "--json"],
        env=env,
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert shown.returncode == 0, shown.stderr
    registration = json.loads(shown.stdout)
    assert registration["command"] == sys.executable
    assert registration["args"] == [
        "-m",
        "premode.pcodex_bootstrap",
        "openclaw-mcp-server",
    ]
    assert registration["env"] == {"PCODEX_WORKSPACE": str(workspace)}

    listed = subprocess.run(
        [executable, "mcp", "list", "--json"],
        env=env,
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert listed.returncode == 0, listed.stderr
    payload = json.loads(listed.stdout)
    assert payload["pcodex"] == registration

    uninstall_integration(workspace, environ=env)
    assert not config.exists()
