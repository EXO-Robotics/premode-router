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
import tomllib
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
    (root / "unrelated.txt").write_text("preserve\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, timeout=15)
    subprocess.run(["git", "config", "user.email", "fixture.invalid"], cwd=root, check=True, timeout=15)
    subprocess.run(["git", "config", "user.name", "pCodex Fixture"], cwd=root, check=True, timeout=15)
    subprocess.run(["git", "add", "unrelated.txt"], cwd=root, check=True, timeout=15)
    subprocess.run(["git", "commit", "-q", "-m", "fixture baseline"], cwd=root, check=True, timeout=15)
    return root


def _env(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home / "home"),
        "CODEX_HOME": str(home / "codex-home"),
        "XDG_CONFIG_HOME": str(home / "xdg-config"),
        "XDG_CACHE_HOME": str(home / "xdg-cache"),
        "XDG_DATA_HOME": str(home / "xdg-data"),
        "TMPDIR": str(home / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _seed_unrelated_workspace_state(repo: Path) -> bytes:
    marketplace = repo / ".agents/plugins/marketplace.json"
    marketplace.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        '{\n  "name": "local-premode-marketplace",\n'
        '  "interface": {"displayName": "Keep Me", "unknown": true},\n'
        '  "unknown_top_level": [1, 2, 3],\n'
        '  "plugins": [{"name": "unrelated", "source": {"source": "local", "path": "./plugins/unrelated"}}]\n}\n'
    ).encode("utf-8")
    marketplace.write_bytes(payload)
    unrelated = repo / "plugins/unrelated/README.md"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_text("preserve unrelated plugin\n", encoding="utf-8")
    return payload


def _seed_unrelated_codex_state(home: Path) -> dict[str, Any]:
    path = home / "codex-home/config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '# unrelated user configuration\nmodel = "gpt-5"\n\n'
        '[features]\nplugins = true\n\n'
        '[mcp_servers.unrelated]\ncommand = "/usr/bin/true"\n',
        encoding="utf-8",
    )
    return tomllib.loads(path.read_text(encoding="utf-8"))


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


def probe(
    *, pcodex: Path, control_root: Path, legacy_fixture: Path | None,
    force_codex_unavailable: bool = False,
) -> dict[str, Any]:
    import premode
    from premode.codex_plugin import SUPPORTED_CODEX_VERSIONS, canonical_manifest, canonical_source_root
    from premode.product_contract import validate_payload_against_schema

    package_path = Path(premode.__file__).resolve()
    if Path(sys.prefix).resolve() not in package_path.parents:
        raise RuntimeError(f"premode import escaped installed environment: {package_path}")
    source_root = canonical_source_root()
    if Path(sys.prefix).resolve() not in source_root.resolve().parents:
        raise RuntimeError(f"canonical plugin resources escaped installed environment: {source_root}")
    manifest = json.loads((source_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    expected_manifest = canonical_manifest()
    schema_root = Path(sys.prefix).resolve() / "share" / "premode-router" / "schemas"
    manifest_schema = json.loads((schema_root / "pcodex.plugin-manifest.v1.schema.json").read_text(encoding="utf-8"))
    plugin_state_schema = json.loads((schema_root / "pcodex.codex-plugin-state.v1.schema.json").read_text(encoding="utf-8"))
    native_state_schema = json.loads((schema_root / "pcodex.codex-native-state.v1.schema.json").read_text(encoding="utf-8"))
    operation_schemas = {
        name: json.loads((schema_root / name).read_text(encoding="utf-8"))
        for name in (
            "pcodex.codex-plugin-operation.v1.schema.json",
            "pcodex.codex-native-operation.v1.schema.json",
        )
    }
    operation_schema_documents_valid = all(
        isinstance(schema, dict) and schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
        for schema in operation_schemas.values()
    )
    validate_payload_against_schema(manifest, manifest_schema)
    source_resolver = source_root / "skills/pcodex/bin/resolve-pcodex.sh"
    static_env = {**os.environ, "PATH": str(pcodex.parent) + os.pathsep + os.environ.get("PATH", "")}
    static_resolved = subprocess.run(
        [str(source_resolver)], text=True, capture_output=True, check=True,
        timeout=15, env=static_env,
    ).stdout.strip()
    static_contract = {
        "manifest_matches_authority": manifest == expected_manifest,
        "manifest_schema_valid": True,
        "packaged_source_root": True,
        "helper_resolved": static_resolved == str(pcodex),
        "skills_root": (source_root / "skills").is_dir(),
        "operation_schema_documents_packaged": operation_schema_documents_valid,
    }
    codex = None if force_codex_unavailable else shutil.which("codex")
    if codex is None:
        control_root.mkdir(parents=True)
        missing_home = control_root / "missing-codex-env"
        for path in (missing_home / "home", missing_home / "codex-home", missing_home / "tmp"):
            path.mkdir(parents=True)
        env = _env(missing_home)
        env["PATH"] = str(pcodex.parent) + os.pathsep + "/usr/bin:/bin"
        repo = _repo(control_root, "repository without Codex β")
        before = {"repo": _tree(repo), "codex": _tree(missing_home / "codex-home")}
        preview, _ = _pcodex(pcodex, repo, env, "--dry-run")
        preview_no_write = before == {"repo": _tree(repo), "codex": _tree(missing_home / "codex-home")}
        installed, _ = _pcodex(pcodex, repo, env, "--write", expected={0, 1})
        repeat_before = {"repo": _tree(repo), "codex": _tree(missing_home / "codex-home")}
        installed_again, _ = _pcodex(pcodex, repo, env, "--write", expected={0, 1})
        repeat_no_write = repeat_before == {"repo": _tree(repo), "codex": _tree(missing_home / "codex-home")}
        status, _ = _pcodex(pcodex, repo, env, "--status", expected={1})
        installed_state = json.loads((repo / ".pcodex/codex-plugin-state.json").read_text(encoding="utf-8"))
        validate_payload_against_schema(installed_state, plugin_state_schema)
        installed_resolver = repo / "plugins/pcodex/skills/pcodex/bin/resolve-pcodex.sh"
        resolved = subprocess.run(
            [str(installed_resolver)], cwd=repo, env=env, text=True,
            capture_output=True, check=True, timeout=15,
        ).stdout.strip()
        removed, _ = _pcodex(pcodex, repo, env, "--uninstall")
        exact_migration = {"fixture_available": legacy_fixture is not None, "passed": legacy_fixture is None}
        if legacy_fixture is not None:
            exact_repo = _repo(control_root, "accepted historical without Codex")
            shutil.copytree(legacy_fixture, exact_repo, dirs_exist_ok=True)
            exact_before = _tree(exact_repo)
            exact_preview, _ = _pcodex(pcodex, exact_repo, env, "--dry-run", "--migrate")
            exact_preview_no_write = exact_before == _tree(exact_repo)
            exact_apply, _ = _pcodex(pcodex, exact_repo, env, "--write", "--migrate", expected={0, 1})
            legacy_roots = [
                ".agents/plugins/plugins/premode-router", ".agents/skills/pcodex",
                ".agents/skills/pcodex-dry-run", ".agents/skills/pcodex-status", ".agents/skills/pcodex-tune",
            ]
            exact_removed = not any((exact_repo / relative).exists() for relative in legacy_roots)
            exact_status, _ = _pcodex(pcodex, exact_repo, env, "--status", expected={1})
            exact_uninstall, _ = _pcodex(pcodex, exact_repo, env, "--uninstall")
            exact_migration = {
                "fixture_available": True,
                "preview_no_write": exact_preview_no_write,
                "preview_found_migratable": any(
                    item.get("classification") == "legacy_migratable"
                    for item in exact_preview.get("legacy_sources_found", [])
                ),
                "apply": exact_apply.get("status"), "legacy_removed": exact_removed,
                "status": exact_status.get("readiness"), "uninstall": exact_uninstall.get("status"),
            }
            exact_migration["passed"] = all([
                exact_migration["preview_no_write"], exact_migration["preview_found_migratable"],
                exact_migration["apply"] == "installed_needs_codex", exact_migration["legacy_removed"],
                exact_migration["status"] == "NEEDS_ACTION", exact_migration["uninstall"] == "uninstalled",
            ])
        passed = all([
            *static_contract.values(),
            preview.get("writes_performed") is False,
            preview_no_write,
            installed.get("status") == "installed_needs_codex",
            installed_again.get("status") == "installed_needs_codex",
            installed_again.get("writes_performed") is False,
            repeat_no_write,
            status.get("readiness") == "NEEDS_ACTION",
            status.get("reason") == "codex_missing",
            resolved == str(pcodex),
            removed.get("status") == "uninstalled",
            exact_migration.get("passed") is True,
        ])
        return {
            "schema_version": "pcodex.installed-codex-plugin-probe.v1",
            "passed": passed, "live_codex_available": False,
            "deferred_reason": "Codex CLI unavailable",
            "installed_import_isolated": True,
            "supported_codex_versions": SUPPORTED_CODEX_VERSIONS,
            "codex_version": None,
            "static_contract": static_contract,
            "schemas_validated": {
                "manifest_payload": True,
                "plugin_state_payload": True,
                "native_state_payload": False,
                "operation_schema_documents_packaged": operation_schema_documents_valid,
                "operation_payloads": False,
            },
            "lifecycle": {
                "preview_no_write": preview_no_write,
                "apply": installed.get("status"),
                "install_twice": installed_again.get("status"),
                "install_twice_no_write": repeat_no_write,
                "status": status.get("readiness"),
                "uninstall": removed.get("status"),
            },
            "discovery": {
                "plugin_list": False,
                "manifest": True,
                "skills_root": static_contract["skills_root"],
                "helper_resolution": static_contract["helper_resolved"],
                "model_visible_trigger_executed": False,
            },
            "migration": {"accepted_historical_fixture": exact_migration},
        }
    control_root.mkdir(parents=True)
    main_home = control_root / "main-env"
    for path in (main_home / "home", main_home / "codex-home", main_home / "tmp"):
        path.mkdir(parents=True)
    env = _env(main_home)
    env["PATH"] = str(pcodex.parent) + os.pathsep + env.get("PATH", "")
    repo = _repo(control_root, "repository with spaces β")
    marketplace_before = _seed_unrelated_workspace_state(repo)
    dirty_before_install = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, text=True,
            capture_output=True, check=True, timeout=15,
        ).stdout.strip()
    )
    codex_unrelated_before = _seed_unrelated_codex_state(main_home)
    before = {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    preview, preview_time = _pcodex(pcodex, repo, env, "--dry-run")
    preview_no_write = before == {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    installed, install_time = _pcodex(pcodex, repo, env, "--write")
    repeat_before = {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    installed_again, _ = _pcodex(pcodex, repo, env, "--write")
    repeat_no_write = repeat_before == {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    status_ready, status_time = _pcodex(pcodex, repo, env, "--status")
    native_state = json.loads((repo / ".pcodex/codex-native-state.json").read_text(encoding="utf-8"))
    plugin_state = json.loads((repo / ".pcodex/codex-plugin-state.json").read_text(encoding="utf-8"))
    cache = Path(native_state["cache"]["path"])
    installed_manifest = json.loads((cache / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    resolver = cache / "skills/pcodex/bin/resolve-pcodex.sh"
    resolver_started = time.perf_counter()
    resolved = subprocess.run([str(resolver)], cwd=repo, env=env, text=True, capture_output=True, check=True, timeout=15).stdout.strip()
    resolver_seconds = time.perf_counter() - resolver_started
    skills_discovered = (cache / "skills").is_dir()
    discovered, _ = _run([codex, "plugin", "list", "--json"], cwd=repo, env=env)
    helper = repo / "plugins/pcodex/skills/pcodex/bin/resolve-pcodex.sh"
    helper.unlink()
    repair_preview_before = {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    repair_preview, _ = _pcodex(pcodex, repo, env, "--repair", "--dry-run", expected={0, 1})
    repair_preview_no_write = repair_preview_before == {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    repaired_missing, repair_time = _pcodex(pcodex, repo, env, "--repair")
    disabled, disable_time = _pcodex(pcodex, repo, env, "--disable")
    status_disabled, _ = _pcodex(pcodex, repo, env, "--status", expected={1})
    reenabled, _ = _pcodex(pcodex, repo, env, "--repair")
    uninstall_preview_before = {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    uninstall_preview, _ = _pcodex(pcodex, repo, env, "--uninstall", "--dry-run")
    uninstall_preview_no_write = uninstall_preview_before == {"repo": _tree(repo), "codex": _tree(main_home / "codex-home")}
    removed, uninstall_time = _pcodex(pcodex, repo, env, "--uninstall")
    owned_removed = not any((repo / path).exists() for path in (
        "plugins/pcodex", ".pcodex/codex-plugin-state.json", ".pcodex/codex-native-state.json",
    ))
    config_after_payload = tomllib.loads((main_home / "codex-home/config.toml").read_text(encoding="utf-8"))
    marketplace_after = (repo / ".agents/plugins/marketplace.json").read_bytes()
    unrelated_plugin_preserved = (repo / "plugins/unrelated/README.md").read_text(encoding="utf-8") == "preserve unrelated plugin\n"
    reinstalled, _ = _pcodex(pcodex, repo, env, "--write")
    _pcodex(pcodex, repo, env, "--uninstall")

    mcp_home = control_root / "mcp-env"
    for path in (mcp_home / "home", mcp_home / "codex-home", mcp_home / "tmp"):
        path.mkdir(parents=True)
    mcp_env = _env(mcp_home)
    mcp_env["PATH"] = str(pcodex.parent) + os.pathsep + mcp_env.get("PATH", "")
    mcp_repo = _repo(control_root, "mcp-workspace")
    mcp_unrelated_before = _seed_unrelated_codex_state(mcp_home)
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
    mcp_unrelated_after = tomllib.loads((mcp_home / "codex-home/config.toml").read_text(encoding="utf-8"))

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

    exact_migration: dict[str, Any] = {"fixture_available": legacy_fixture is not None, "passed": False}
    if legacy_fixture is not None:
        exact_repo = _repo(control_root, "accepted-historical-legacy")
        shutil.copytree(legacy_fixture, exact_repo, dirs_exist_ok=True)
        exact_unrelated_before = _tree(exact_repo)["unrelated.txt"]
        exact_before = _tree(exact_repo)
        exact_preview, _ = _pcodex(pcodex, exact_repo, migration_env, "--dry-run", "--migrate")
        exact_preview_no_write = exact_before == _tree(exact_repo)
        exact_apply, _ = _pcodex(pcodex, exact_repo, migration_env, "--write", "--migrate")
        exact_status, _ = _pcodex(pcodex, exact_repo, migration_env, "--status")
        legacy_roots = [
            ".agents/plugins/plugins/premode-router", ".agents/skills/pcodex",
            ".agents/skills/pcodex-dry-run", ".agents/skills/pcodex-status", ".agents/skills/pcodex-tune",
        ]
        exact_removed = not any((exact_repo / relative).exists() for relative in legacy_roots)
        exact_unrelated_preserved = _tree(exact_repo).get("unrelated.txt") == exact_unrelated_before
        exact_uninstall, _ = _pcodex(pcodex, exact_repo, migration_env, "--uninstall")
        exact_migration = {
            "fixture_available": True,
            "preview_no_write": exact_preview_no_write,
            "preview_found_migratable": any(
                item.get("classification") == "legacy_migratable"
                for item in exact_preview.get("legacy_sources_found", [])
            ),
            "apply": exact_apply.get("status"),
            "legacy_removed": exact_removed,
            "status": exact_status.get("readiness"),
            "unrelated_preserved": exact_unrelated_preserved,
            "uninstall": exact_uninstall.get("status"),
        }
        exact_migration["passed"] = all([
            exact_migration["preview_no_write"], exact_migration["preview_found_migratable"],
            exact_migration["apply"] == "installed", exact_migration["legacy_removed"],
            exact_migration["status"] == "READY", exact_migration["unrelated_preserved"],
            exact_migration["uninstall"] == "uninstalled",
        ])

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
    validate_payload_against_schema(installed_manifest, manifest_schema)
    validate_payload_against_schema(plugin_state, plugin_state_schema)
    validate_payload_against_schema(native_state, native_state_schema)
    compatibility = (
        status_ready.get("codex_compatibility")
        if isinstance(status_ready.get("codex_compatibility"), dict) else {}
    )
    passed = all([
        *static_contract.values(),
        preview.get("writes_performed") is False, preview_no_write,
        installed.get("status") == "installed", status_ready.get("readiness") == "READY",
        installed_again.get("status") == "unchanged",
        installed_again.get("writes_performed") is False,
        repeat_no_write, dirty_before_install,
        installed_manifest == expected_manifest,
        compatibility.get("supported") is True,
        resolved == str(pcodex), discovered_ok, skills_discovered,
        repaired_missing.get("status") == "repaired", disabled.get("status") == "disabled",
        repair_preview.get("writes_performed") is False, repair_preview_no_write,
        status_disabled.get("reason") == "disabled", reenabled.get("status") == "repaired",
        uninstall_preview.get("writes_performed") is False, uninstall_preview_no_write,
        removed.get("status") == "uninstalled", owned_removed,
        config_after_payload == codex_unrelated_before,
        marketplace_after == marketplace_before, unrelated_plugin_preserved,
        reinstalled.get("status") == "installed",
        mcp_preview.get("writes_performed") is False, mcp_preview_no_write,
        mcp_installed.get("native_registration", {}).get("status") == "registered",
        mcp_get.get("name") == "pcodex", mcp_get.get("transport", {}).get("env", {}).get("PCODEX_WORKSPACE") == str(mcp_repo.resolve()),
        mcp_disabled.get("status") == "disabled", mcp_absent_while_disabled,
        mcp_repaired.get("status") == "repaired",
        mcp_unrelated_after == mcp_unrelated_before,
        migration_preview_no_write, migration_preview.get("legacy_sources_found"),
        migration_apply.get("status") == "installed", legacy_preserved,
        exact_migration.get("passed") is True,
        plugin_state.get("schema_version") == "pcodex.codex-plugin-state.v1",
        native_state.get("schema_version") == "pcodex.codex-native-state.v1",
    ])
    return {
        "schema_version": "pcodex.installed-codex-plugin-probe.v1",
        "passed": passed, "live_codex_available": True, "installed_import_isolated": True,
        "supported_codex_versions": SUPPORTED_CODEX_VERSIONS,
        "codex_version": compatibility.get("version"),
        "static_contract": static_contract,
        "schemas_validated": {
            "manifest_payload": True,
            "plugin_state_payload": True,
            "native_state_payload": True,
            "operation_schema_documents_packaged": operation_schema_documents_valid,
            "operation_payloads": False,
        },
        "installed_package_path": str(package_path),
        "lifecycle": {
            "preview_no_write": preview_no_write, "apply": installed.get("status"),
            "install_twice": installed_again.get("status"),
            "install_twice_no_write": repeat_no_write,
            "status": status_ready.get("readiness"), "repair": repaired_missing.get("status"),
            "repair_preview_no_write": repair_preview_no_write,
            "disable": disabled.get("status"), "reenable": reenabled.get("status"),
            "uninstall_preview_no_write": uninstall_preview_no_write,
            "uninstall": removed.get("status"), "owned_state_removed": owned_removed,
            "reinstall": reinstalled.get("status"),
        },
        "discovery": {"plugin_list": discovered_ok, "manifest": True, "skills_root": skills_discovered, "helper_resolution": resolved == str(pcodex), "model_visible_trigger_executed": False, "installed_skill_startup_seconds": round(resolver_seconds, 6)},
        "mcp": {"preview_no_write": mcp_preview_no_write, "registered": mcp_get.get("name") == "pcodex", "workspace_bound": True, "disabled_removed": mcp_absent_while_disabled, "repaired": mcp_repaired.get("status"), "unrelated_preserved": mcp_unrelated_after == mcp_unrelated_before},
        "migration": {
            "preview_no_write": migration_preview_no_write,
            "unknown_legacy_preserved": legacy_preserved,
            "apply": migration_apply.get("status"),
            "accepted_historical_fixture": exact_migration,
        },
        "preservation": {
            "dirty_git_fixture": dirty_before_install,
            "codex_unrelated_config": config_after_payload == codex_unrelated_before,
            "marketplace_byte_exact": marketplace_after == marketplace_before,
            "unrelated_plugin": unrelated_plugin_preserved,
        },
        "receipts": {"plugin": plugin_state, "native": native_state},
        "performance": {key: _percentiles(values) for key, values in perf.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcodex", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--legacy-fixture", type=Path)
    parser.add_argument("--force-codex-unavailable", action="store_true")
    args = parser.parse_args()
    result = probe(
        pcodex=args.pcodex.resolve(), control_root=args.control_root.resolve(),
        legacy_fixture=args.legacy_fixture.resolve() if args.legacy_fixture else None,
        force_codex_unavailable=args.force_codex_unavailable,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
