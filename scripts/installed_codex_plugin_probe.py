#!/usr/bin/env python3
"""Installed-artifact proof for the canonical Codex plugin lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


def _tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    }


def _repo(parent: Path, name: str) -> Path:
    root = parent / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "unrelated.txt").write_text("preserve\n", encoding="utf-8")
    return root


def _env(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home / "home"),
        "CODEX_HOME": str(home / "codex-home"),
        "XDG_CONFIG_HOME": str(home / "xdg-config"),
        "XDG_CACHE_HOME": str(home / "xdg-cache"),
        "TMPDIR": str(home / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run(
    command: list[str], *, cwd: Path, env: dict[str, str], expected: set[int] = {0},
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False, timeout=90)
    elapsed = time.perf_counter() - started
    if completed.returncode not in expected:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command returned non-JSON: {' '.join(command)}\n{completed.stdout}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("command returned a non-object JSON result")
    return payload, elapsed


def _pcodex(
    executable: Path, repo: Path, env: dict[str, str], *args: str, expected: set[int] = {0},
) -> tuple[dict[str, Any], float]:
    return _run([str(executable), "integrate", "codex", *args, "--json", "--repo-root", str(repo)], cwd=repo, env=env, expected=expected)


def _percentiles(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "samples": len(values),
        "p50_seconds": round(ordered[(len(ordered) - 1) // 2], 6),
        "p95_seconds": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 6),
    }


def probe(*, pcodex: Path, control_root: Path) -> dict[str, Any]:
    package_path = Path(__import__("premode").__file__).resolve()
    if Path(sys.prefix).resolve() not in package_path.parents:
        raise RuntimeError(f"premode import escaped installed environment: {package_path}")
    codex = shutil.which("codex")
    if codex is None:
        return {
            "schema_version": "pcodex.installed-codex-plugin-probe.v1",
            "passed": True, "live_codex_available": False,
            "deferred_reason": "Codex CLI unavailable", "installed_import_isolated": True,
        }
    control_root.mkdir(parents=True)
    main_home = control_root / "main-env"
    for path in (main_home / "home", main_home / "codex-home", main_home / "tmp"):
        path.mkdir(parents=True)
    env = _env(main_home)
    env["PATH"] = str(pcodex.parent) + os.pathsep + env.get("PATH", "")
    repo = _repo(control_root, "repository with spaces β")
    before = {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    preview, preview_time = _pcodex(pcodex, repo, env, "--dry-run")
    preview_no_write = before == {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    installed, install_time = _pcodex(pcodex, repo, env, "--write")
    status_ready, status_time = _pcodex(pcodex, repo, env, "--status")
    native_state = json.loads((repo / ".pcodex/codex-native-state.json").read_text(encoding="utf-8"))
    plugin_state = json.loads((repo / ".pcodex/codex-plugin-state.json").read_text(encoding="utf-8"))
    cache = Path(native_state["cache"]["path"])
    manifest = json.loads((cache / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    resolver = cache / "skills/pcodex/bin/resolve-pcodex.sh"
    resolver_started = time.perf_counter()
    resolved = subprocess.run([str(resolver)], cwd=repo, env=env, text=True, capture_output=True, check=True, timeout=15).stdout.strip()
    resolver_seconds = time.perf_counter() - resolver_started
    skills_discovered = (cache / "skills").is_dir()
    discovered, _ = _run([codex, "plugin", "list", "--json"], cwd=repo, env=env)
    helper = repo / "plugins/pcodex/skills/pcodex/bin/resolve-pcodex.sh"
    helper.unlink()
    repaired_missing, repair_time = _pcodex(pcodex, repo, env, "--repair")
    disabled, disable_time = _pcodex(pcodex, repo, env, "--disable")
    status_disabled, _ = _pcodex(pcodex, repo, env, "--status", expected={1})
    reenabled, _ = _pcodex(pcodex, repo, env, "--repair")
    removed, uninstall_time = _pcodex(pcodex, repo, env, "--uninstall")
    owned_removed = not any((repo / path).exists() for path in (
        "plugins/pcodex", ".pcodex/codex-plugin-state.json", ".pcodex/codex-native-state.json",
        ".agents/plugins/marketplace.json",
    ))
    config_after = _tree(main_home / "codex-home")
    reinstalled, _ = _pcodex(pcodex, repo, env, "--write")
    _pcodex(pcodex, repo, env, "--uninstall")

    mcp_home = control_root / "mcp-env"
    for path in (mcp_home / "home", mcp_home / "codex-home", mcp_home / "tmp"):
        path.mkdir(parents=True)
    mcp_env = _env(mcp_home)
    mcp_env["PATH"] = str(pcodex.parent) + os.pathsep + mcp_env.get("PATH", "")
    mcp_repo = _repo(control_root, "mcp-workspace")
    mcp_preview_before = {"repo": _tree(mcp_repo), "codex": _tree(mcp_home / "codex-home")}
    mcp_preview, _ = _pcodex(pcodex, mcp_repo, mcp_env, "--dry-run", "--with-mcp")
    mcp_preview_no_write = mcp_preview_before == {"repo": _tree(mcp_repo), "codex": _tree(mcp_home / "codex-home")}
    mcp_installed, _ = _pcodex(pcodex, mcp_repo, mcp_env, "--write", "--with-mcp")
    mcp_get, _ = _run([codex, "mcp", "get", "pcodex", "--json"], cwd=mcp_repo, env=mcp_env)
    mcp_disabled, _ = _pcodex(pcodex, mcp_repo, mcp_env, "--disable")
    mcp_absent_while_disabled = subprocess.run(
        [codex, "mcp", "get", "pcodex", "--json"], cwd=mcp_repo, env=mcp_env,
        text=True, capture_output=True, check=False, timeout=30,
    ).returncode != 0
    mcp_repaired, _ = _pcodex(pcodex, mcp_repo, mcp_env, "--repair")
    _pcodex(pcodex, mcp_repo, mcp_env, "--uninstall")

    migration_home = control_root / "migration-env"
    for path in (migration_home / "home", migration_home / "codex-home", migration_home / "tmp"):
        path.mkdir(parents=True)
    migration_env = _env(migration_home)
    migration_env["PATH"] = str(pcodex.parent) + os.pathsep + migration_env.get("PATH", "")
    migration_repo = _repo(control_root, "legacy-workspace")
    legacy = migration_repo / ".agents/plugins/plugins/premode-router"
    legacy.mkdir(parents=True)
    (legacy / "user-owned.txt").write_text("preserve\n", encoding="utf-8")
    migration_before = _tree(migration_repo)
    migration_preview, migration_preview_time = _pcodex(pcodex, migration_repo, migration_env, "--dry-run", "--migrate")
    migration_preview_no_write = migration_before == _tree(migration_repo)
    migration_apply, migration_apply_time = _pcodex(pcodex, migration_repo, migration_env, "--write", "--migrate")
    legacy_preserved = (legacy / "user-owned.txt").read_text(encoding="utf-8") == "preserve\n"
    _pcodex(pcodex, migration_repo, migration_env, "--uninstall")

    perf: dict[str, list[float]] = {
        "preview": [preview_time], "install": [install_time], "status": [status_time],
        "repair": [repair_time], "disable": [disable_time], "uninstall": [uninstall_time],
        "migration_preview": [migration_preview_time], "migration_apply": [migration_apply_time],
    }
    for index in range(2):
        perf_home = control_root / f"perf-env-{index}"
        for path in (perf_home / "home", perf_home / "codex-home", perf_home / "tmp"):
            path.mkdir(parents=True)
        perf_env = _env(perf_home)
        perf_env["PATH"] = str(pcodex.parent) + os.pathsep + perf_env.get("PATH", "")
        perf_repo = _repo(control_root, f"perf-repo-{index}")
        _, elapsed = _pcodex(pcodex, perf_repo, perf_env, "--dry-run")
        perf["preview"].append(elapsed)
        _, elapsed = _pcodex(pcodex, perf_repo, perf_env, "--write")
        perf["install"].append(elapsed)
        _, elapsed = _pcodex(pcodex, perf_repo, perf_env, "--status")
        perf["status"].append(elapsed)
        _, elapsed = _pcodex(pcodex, perf_repo, perf_env, "--disable")
        perf["disable"].append(elapsed)
        _, elapsed = _pcodex(pcodex, perf_repo, perf_env, "--repair")
        perf["repair"].append(elapsed)
        _, elapsed = _pcodex(pcodex, perf_repo, perf_env, "--uninstall")
        perf["uninstall"].append(elapsed)

    installed_entries = discovered.get("installed") if isinstance(discovered.get("installed"), list) else []
    discovered_ok = any(item.get("pluginId") == "pcodex@local-premode-marketplace" and item.get("enabled") for item in installed_entries)
    passed = all([
        preview.get("writes_performed") is False, preview_no_write,
        installed.get("status") == "installed", status_ready.get("readiness") == "READY",
        manifest.get("name") == "pcodex", manifest.get("version") == "0.3.0-beta.1",
        resolved == str(pcodex), discovered_ok, skills_discovered,
        repaired_missing.get("status") == "repaired", disabled.get("status") == "disabled",
        status_disabled.get("reason") == "disabled", reenabled.get("status") == "repaired",
        removed.get("status") == "uninstalled", owned_removed, config_after == {},
        reinstalled.get("status") == "installed",
        mcp_preview.get("writes_performed") is False, mcp_preview_no_write,
        mcp_installed.get("native_registration", {}).get("status") == "registered",
        mcp_get.get("name") == "pcodex", mcp_get.get("transport", {}).get("env", {}).get("PCODEX_WORKSPACE") == str(mcp_repo.resolve()),
        mcp_disabled.get("status") == "disabled", mcp_absent_while_disabled,
        mcp_repaired.get("status") == "repaired",
        migration_preview_no_write, migration_preview.get("legacy_sources_found"),
        migration_apply.get("status") == "installed", legacy_preserved,
        plugin_state.get("schema_version") == "pcodex.codex-plugin-state.v1",
        native_state.get("schema_version") == "pcodex.codex-native-state.v1",
    ])
    return {
        "schema_version": "pcodex.installed-codex-plugin-probe.v1",
        "passed": passed, "live_codex_available": True, "installed_import_isolated": True,
        "installed_package_path": str(package_path),
        "lifecycle": {
            "preview_no_write": preview_no_write, "apply": installed.get("status"),
            "status": status_ready.get("readiness"), "repair": repaired_missing.get("status"),
            "disable": disabled.get("status"), "reenable": reenabled.get("status"),
            "uninstall": removed.get("status"), "owned_state_removed": owned_removed,
            "reinstall": reinstalled.get("status"),
        },
        "discovery": {"plugin_list": discovered_ok, "manifest": True, "skills_root": skills_discovered, "model_visible_trigger_executed": False, "installed_skill_startup_seconds": round(resolver_seconds, 6)},
        "mcp": {"preview_no_write": mcp_preview_no_write, "registered": mcp_get.get("name") == "pcodex", "workspace_bound": True, "disabled_removed": mcp_absent_while_disabled, "repaired": mcp_repaired.get("status")},
        "migration": {"preview_no_write": migration_preview_no_write, "unknown_legacy_preserved": legacy_preserved, "apply": migration_apply.get("status")},
        "receipts": {"plugin": plugin_state, "native": native_state},
        "performance": {key: _percentiles(values) for key, values in perf.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcodex", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    args = parser.parse_args()
    result = probe(pcodex=args.pcodex.resolve(), control_root=args.control_root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
