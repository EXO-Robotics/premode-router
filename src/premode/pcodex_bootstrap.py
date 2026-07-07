from __future__ import annotations

import argparse
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any

from . import __version__
from .codex_exec import CodexOptions, build_codex_invocation, run_codex
from .compiler import compile_prompt
from .cache_manifest import read_cache_manifest, write_cache_manifest
from .install_manifest import read_install_manifest
from .inventory import load_inventory, refresh_inventory_if_needed, summarize_inventory
from .lockfile import read_lockfile, sha256_text, update_lockfile_from_resolver
from .topology import refresh_topology_if_needed, summarize_topology
from .write_policy import ADVISORY, NORMAL, WritePolicy, resolve_write_policy
from .pcodex_state import (
    DEFAULT_TUNING_PROFILE,
    EFFECTIVE_OFF_RAW,
    EFFECTIVE_ON_GENERALIZED,
    EFFECTIVE_SAFE_PASSTHROUGH,
    PcodexStateError,
    record_runtime_telemetry,
    resolve_effective_mode,
    set_mode_off,
    set_mode_on,
    set_mode_tuned,
)
from .plugins import PluginAliasError, available_plugin_aliases, resolve_packet_plugin

PCODEX_PLUGIN_ALIAS = "literal_symbol"
PCODEX_PACKET_VERSION = "v5"
PCODEX_PACKET_VARIANT = "tool_assisted_anchors_internal"
PCODEX_PACKET_STRATEGY = "literal_symbol"
PCODEX_FALLBACK_VARIANT = "ranked_paths_plus_anchors"
CONFIG_ENV = "PCODEX_ENABLED"
CONFIG_PATH_ENV = "PCODEX_CONFIG"
CONFIG_PATH_ALIAS_ENV = "PCODEX_CONFIG_PATH"
ALGORITHM_ENV = "PCODEX_ALGORITHM"
PROJECT_ROOT_ENV = "PCODEX_PROJECT_ROOT"
PACKET_STRATEGY_ENV = "PCODEX_PACKET_STRATEGY"
MIN_CODEX_CLI_VERSION = (0, 142, 5)
MIN_CODEX_CLI_VERSION_TEXT = ".".join(str(part) for part in MIN_CODEX_CLI_VERSION)
LOCAL_STATE_CLEANUP_TARGETS = [
    ".premode/pcodex_state.json",
    ".premode/lcc.lock.json",
    ".premode/out/cache_manifest.json",
    ".premode/out/",
    ".premode/inventory/files.json",
    ".premode/inventory/",
    ".premode/topology/repo_topology.json",
    ".premode/topology/",
    ".premode/audit/",
    ".premode/metrics/",
    ".premode/pcodex_codex_home/",
]


@dataclass(frozen=True)
class PcodexConfig:
    enabled: bool = False
    source: str = "default"
    path: str | None = None
    algorithm: str = PCODEX_PACKET_STRATEGY


def _repo_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def _repo_config_path(repo_root: Path) -> Path:
    return repo_root / ".pcodex" / "config.toml"


def _user_config_path() -> Path:
    return Path.home() / ".pcodex" / "config.toml"


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _parse_algorithm(value: Any) -> str | None:
    if value is None:
        return PCODEX_PACKET_STRATEGY
    text = str(value).strip()
    return text if text == PCODEX_PACKET_STRATEGY else None


def _read_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    pcodex = data.get("pcodex")
    return pcodex if isinstance(pcodex, dict) else data


def resolve_config(cwd: Path | None = None, env: dict[str, str] | None = None) -> PcodexConfig:
    env = dict(os.environ if env is None else env)
    cwd = Path.cwd() if cwd is None else cwd
    env_algorithm = _parse_algorithm(env.get(ALGORITHM_ENV))
    if env_algorithm is None:
        return PcodexConfig(enabled=False, source=f"{ALGORITHM_ENV}:invalid", path=None)

    env_raw_value = env.get(CONFIG_ENV)
    env_value = _parse_bool(env_raw_value)
    if env_raw_value is not None and env_value is None:
        return PcodexConfig(enabled=False, source=f"{CONFIG_ENV}:invalid", path=None, algorithm=env_algorithm)
    if env_value is not None:
        return PcodexConfig(enabled=env_value, source=CONFIG_ENV, path=None, algorithm=env_algorithm)

    paths: list[tuple[str, Path]] = []
    config_path_value = env.get(CONFIG_PATH_ENV) or env.get(CONFIG_PATH_ALIAS_ENV)
    if config_path_value:
        source = CONFIG_PATH_ENV if env.get(CONFIG_PATH_ENV) else CONFIG_PATH_ALIAS_ENV
        paths.append((source, Path(config_path_value).expanduser()))
    repo_root = _repo_root(cwd)
    paths.extend([("repo", _repo_config_path(repo_root)), ("user", _user_config_path())])
    for source, path in paths:
        data = _read_config(path)
        enabled = _parse_bool(data.get("enabled"))
        algorithm = _parse_algorithm(data.get("algorithm"))
        if algorithm is None:
            return PcodexConfig(enabled=False, source=f"{source}:invalid", path=str(path))
        if enabled is not None:
            return PcodexConfig(
                enabled=enabled,
                source=source,
                path=str(path),
                algorithm=algorithm,
            )
        if path.exists():
            return PcodexConfig(enabled=False, source=f"{source}:invalid", path=str(path))
    return PcodexConfig()


def write_repo_config(cwd: Path, *, enabled: bool) -> Path:
    repo_root = _repo_root(cwd)
    path = _repo_config_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[pcodex]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        f"algorithm = \"{PCODEX_PACKET_STRATEGY}\"\n",
        encoding="utf-8",
    )
    return path


def _command_available(name: str) -> bool:
    if shutil.which(name) is not None:
        return True
    sibling = Path(sys.executable).with_name(name)
    return sibling.exists() and os.access(sibling, os.X_OK)


def _command_path(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    sibling = Path(sys.executable).with_name(name)
    if sibling.exists() and os.access(sibling, os.X_OK):
        return str(sibling)
    return None


def plugin_alias_available() -> bool:
    try:
        resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
    except PluginAliasError:
        return False
    return True


def _git_check_ignored(repo_root: Path, relative_path: str) -> bool:
    try:
        completed = subprocess.run(
            ["git", "check-ignore", relative_path],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def generated_state_path_status(repo_root: Path) -> dict[str, Any]:
    paths = [
        ".premode/pcodex_state.json",
        ".premode/lcc.lock.json",
        ".premode/out/cache_manifest.json",
        ".premode/out/",
        ".premode/audit/",
        ".premode/metrics/",
        ".premode/tuning/",
        ".premode/inventory/",
        ".premode/topology/",
        ".pcodex/",
    ]
    return {
        path: {
            "exists": (repo_root / path).exists(),
            "git_ignored": _git_check_ignored(repo_root, path),
        }
        for path in paths
    }


def _relative_cleanup_path(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _safe_cleanup_target(repo_root: Path, relative_path: str) -> Path:
    normalized = relative_path.strip().replace("\\", "/").strip("/")
    allowed = {item.strip("/") for item in LOCAL_STATE_CLEANUP_TARGETS}
    if normalized not in allowed:
        raise ValueError(f"unsupported cleanup target: {relative_path}")
    target = (repo_root / normalized).resolve()
    root = repo_root.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"cleanup target escapes repo root: {relative_path}")
    if not normalized.startswith(".premode/"):
        raise ValueError(f"cleanup target is not repo-local generated state: {relative_path}")
    return target


def cleanup_local_state_plan(repo_root: Path | str) -> dict[str, Any]:
    root = _repo_root(Path(repo_root))
    actions: list[dict[str, Any]] = []
    for relative in LOCAL_STATE_CLEANUP_TARGETS:
        target = _safe_cleanup_target(root, relative)
        exists = target.exists()
        kind = "directory" if relative.endswith("/") or target.is_dir() else "file"
        actions.append(
            {
                "path": _relative_cleanup_path(root, target),
                "exists": exists,
                "kind": kind,
                "action": "remove" if exists else "skip_missing",
            }
        )
    return {
        "schema_version": "pcodex.cleanup_local_state.v1",
        "repo_root_hash": sha256_text(str(root.resolve())),
        "scope": "repo_local_generated_state",
        "dry_run": True,
        "actions": actions,
        "writes_or_deletes": False,
        "source_config_preserved": [".pcodex/", ".gitignore", ".premodeignore"],
        "user_source_files_preserved": True,
    }


def cleanup_local_state(repo_root: Path | str, *, dry_run: bool = True) -> dict[str, Any]:
    root = _repo_root(Path(repo_root))
    plan = cleanup_local_state_plan(root)
    if dry_run:
        return plan
    removed: list[str] = []
    for action in plan["actions"]:
        if action["action"] != "remove":
            continue
        target = _safe_cleanup_target(root, str(action["path"]))
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(str(action["path"]))
        elif target.exists():
            target.unlink()
            removed.append(str(action["path"]))
    return {
        **plan,
        "dry_run": False,
        "writes_or_deletes": bool(removed),
        "removed": removed,
    }


def _manifest_summary() -> dict[str, Any]:
    manifest = read_install_manifest()
    payload = manifest.get("payload") if isinstance(manifest.get("payload"), dict) else {}
    return {
        "status": manifest.get("status"),
        "valid": manifest.get("valid"),
        "path_summary": _display_home_path(Path(str(manifest.get("path")))) if manifest.get("path") else None,
        "package_name": payload.get("package_name") or "premode-router",
        "lcc_version": payload.get("lcc_version") or __version__,
        "install_channel": payload.get("install_channel"),
        "source_type": payload.get("source_type"),
        "source_branch": payload.get("source_branch"),
        "source_head": payload.get("source_head"),
        "source_dirty": payload.get("source_dirty"),
        "source_repo_hash": payload.get("source_repo_hash"),
        "install_root_hash": payload.get("install_root_hash"),
        "files_installed_count": payload.get("files_installed_count"),
        "installer_version": payload.get("installer_version"),
        "provenance_status": payload.get("provenance_status") or ("missing_manifest" if manifest.get("status") == "missing" else "unknown"),
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
    }


def _read_inventory_skip_summary(repo_root: Path) -> dict[str, Any]:
    payload = load_inventory(repo_root)
    if not isinstance(payload, dict):
        return {
            "available": False,
            "ignored_by_premode_count": 0,
            "skipped_runtime_count": 0,
            "skipped_generated_count": 0,
            "skipped_secret_count": 0,
            "skipped_unsafe_count": 0,
        }
    return {
        "available": True,
        "ignored_by_premode_count": int(payload.get("ignored_by_premode_count") or 0),
        "skipped_runtime_count": int(payload.get("skipped_runtime_count") or 0),
        "skipped_generated_count": int(payload.get("skipped_generated_count") or 0),
        "skipped_secret_count": int(payload.get("skipped_secret_count") or 0),
        "skipped_unsafe_count": int(payload.get("skipped_unsafe_count") or 0),
    }


def _state_needs_refresh(summary: dict[str, Any]) -> bool:
    state = str(summary.get("state") or "missing")
    return state != "fresh"


def advisory_summary(
    repo_root: Path,
    *,
    command: str,
    inventory: dict[str, Any],
    topology: dict[str, Any],
    lockfile: dict[str, Any],
    cache_manifest: dict[str, Any],
    write_policy: WritePolicy | str | None = ADVISORY,
) -> dict[str, Any]:
    policy = resolve_write_policy(write_policy)
    would_refresh: list[str] = []
    would_write: list[str] = []
    if _state_needs_refresh(inventory):
        would_refresh.append("inventory")
        would_write.append("inventory")
    if _state_needs_refresh(topology):
        would_refresh.append("topology")
        would_write.append("topology")
    if command == "status":
        would_write.append("lockfile")
    if cache_manifest.get("status") != "loaded" or _state_needs_refresh(inventory) or _state_needs_refresh(topology):
        would_write.append("cache_manifest")
    missing_or_stale: list[str] = []
    if lockfile.get("status") != "loaded":
        missing_or_stale.append("lockfile")
    if cache_manifest.get("status") != "loaded":
        missing_or_stale.append("cache_manifest")
    if _state_needs_refresh(inventory):
        missing_or_stale.append("inventory")
    if _state_needs_refresh(topology):
        missing_or_stale.append("topology")
    return {
        "enabled": policy.name == "advisory",
        "writes_performed": False,
        "write_policy": policy.name,
        "would_refresh": sorted(dict.fromkeys(would_refresh)),
        "would_write": sorted(dict.fromkeys(would_write)),
        "missing_or_stale": sorted(dict.fromkeys(missing_or_stale)),
        "no_write_contract": {
            "repo_state": True,
            "global_state": True,
            "install_state": True,
            "generated_state": True,
            "temp_packets": True,
            "telemetry": True,
            "codex_launch": True,
            "mcp_registration": True,
        },
        "next_action": "run without --advisory to repair state" if missing_or_stale or would_write else "no repair needed",
        "paste_safe": True,
        "repo_root_hash": sha256_text(str(repo_root.resolve())),
        "repo_path_summary": repo_root.name,
    }


def paste_safe_receipt(
    payload: dict[str, Any],
    *,
    command: str,
    repo_root: Path,
    inventory: dict[str, Any],
    topology: dict[str, Any],
    lockfile: dict[str, Any],
    cache_manifest: dict[str, Any],
) -> dict[str, Any]:
    generated_paths = payload.get("generated_state_paths") if isinstance(payload.get("generated_state_paths"), dict) else {}
    generated_counts = {
        "known_path_count": len(generated_paths),
        "existing_count": sum(1 for item in generated_paths.values() if isinstance(item, dict) and item.get("exists")),
        "git_ignored_count": sum(1 for item in generated_paths.values() if isinstance(item, dict) and item.get("git_ignored")),
    }
    mode_payload = payload.get("mode") if isinstance(payload.get("mode"), dict) else {}
    if not mode_payload:
        packet = payload.get("packet") if isinstance(payload.get("packet"), dict) else {}
        mode_payload = {
            "public_mode": payload.get("configured_mode") or payload.get("mode"),
            "lcc_on": payload.get("enabled"),
            "plugin_alias": packet.get("plugin_alias") or payload.get("algorithm"),
        }
    first_run = payload.get("first_run") if isinstance(payload.get("first_run"), dict) else {}
    install = payload.get("install") if isinstance(payload.get("install"), dict) else {}
    advisory = advisory_summary(
        repo_root,
        command=command,
        inventory=inventory,
        topology=topology,
        lockfile=lockfile,
        cache_manifest=cache_manifest,
    )
    return {
        "schema_version": "pcodex.advisory_receipt.v1",
        "command": command,
        "advisory": advisory,
        "lcc_version": payload.get("lcc_version") or __version__,
        "install": {
            "status": install.get("status"),
            "valid": install.get("valid"),
            "install_channel": install.get("install_channel"),
            "source_branch": install.get("source_branch"),
            "source_head": install.get("source_head"),
            "source_dirty": install.get("source_dirty"),
            "provenance_status": install.get("provenance_status"),
        },
        "repo": {
            "root_hash": sha256_text(str(repo_root.resolve())),
            "path_summary": repo_root.name,
            "git_repo": (repo_root / ".git").exists(),
        },
        "mode": {
            "public_mode": mode_payload.get("public_mode"),
            "lcc_on": mode_payload.get("lcc_on"),
            "plugin_alias": mode_payload.get("plugin_alias") or PCODEX_PLUGIN_ALIAS,
        },
        "state": {
            "lockfile": {key: value for key, value in lockfile.items() if key in {"status", "path", "valid", "error"}},
            "cache_manifest": {key: value for key, value in cache_manifest.items() if key in {"status", "path", "valid", "error"}},
            "inventory": inventory,
            "topology": topology,
            "generated_state_counts": generated_counts,
        },
        "read_counters": {
            "inventory_file_count": inventory.get("file_count"),
            "topology_node_count": topology.get("node_count"),
            "full_walk_performed": bool(inventory.get("full_walk_performed")) or False,
        },
        "readiness": first_run.get("readiness") or first_run_summary({"enabled": bool(mode_payload.get("lcc_on")), "inventory": inventory, "topology": topology}).get("readiness"),
        "next_action": advisory["next_action"],
        "caveats": ["read_only_inspection_only", "missing_or_stale_state_not_repaired"],
        "unsupported_unproven": [
            "native_installed_codex_auto_interception",
            "guaranteed_prompt_cache_hits",
            "pypi_or_pipx_package_availability",
        ],
        "privacy": {
            "content_free": True,
            "raw_prompts": False,
            "prompt_excerpts": False,
            "source_bodies": False,
            "source_snippets": False,
            "environment_values": False,
            "secrets": False,
            "packet_text": False,
            "inventory_path_list": False,
            "topology_path_list": False,
            "full_filesystem_path_list": False,
            "raw_command_logs": False,
            "tracebacks": False,
        },
    }


def first_run_summary(payload: dict[str, Any]) -> dict[str, str]:
    enabled = bool(payload.get("enabled"))
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
    topology = payload.get("topology") if isinstance(payload.get("topology"), dict) else {}
    if not enabled:
        return {"readiness": "not_ready", "next_action": "pcodex on"}
    if inventory.get("state") not in {"fresh"} or topology.get("state") not in {"fresh"}:
        return {"readiness": "ready_for_dry_run_refresh", "next_action": "pcodex run --dry-run \"<task>\""}
    return {"readiness": "ready_for_dry_run", "next_action": "pcodex run --dry-run \"<task>\""}


def first_run_receipt(cwd: Path | None = None, *, advisory: bool = False) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    state = resolve_effective_mode(repo_root)
    public_mode = str(state.get("configured_mode") or state.get("mode") or "on")
    effective_mode = str(state.get("effective_mode") or public_mode)
    enabled = effective_mode != "off" and state.get("effective_state") != EFFECTIVE_OFF_RAW
    lockfile = read_lockfile(repo_root)
    cache_manifest = read_cache_manifest(repo_root)
    inventory = summarize_inventory(repo_root)
    topology = summarize_topology(repo_root)
    generated_state = generated_state_path_status(repo_root)
    install = _manifest_summary()
    receipt: dict[str, Any] = {
        "schema_version": "pcodex.first_run_receipt.v1",
        "lcc_installed": _command_available("pcodex") or _command_available("premode"),
        "lcc_version": __version__,
        "install": install,
        "repo": {
            "root_hash": sha256_text(str(repo_root.resolve())),
            "path_summary": repo_root.name,
            "git_repo": (repo_root / ".git").exists(),
        },
        "mode": {
            "public_mode": public_mode,
            "lcc_on": enabled,
            "effective_state": state.get("effective_state"),
            "plugin_alias": state.get("plugin_alias") or PCODEX_PLUGIN_ALIAS,
            "packet_version": state.get("packet_version") or PCODEX_PACKET_VERSION,
            "packet_variant": state.get("packet_variant") or PCODEX_PACKET_VARIANT,
            "packet_strategy": state.get("packet_strategy") or PCODEX_PACKET_STRATEGY,
        },
        "next_prompt": {
            "will_transform": enabled,
            "preflight_available": True,
            "codex_launch_on_dry_run": "not_executed",
            "prompt_preservation": "exact_user_prompt_preserved_by_compile_contract",
            "raw_prompt_stored": False,
        },
        "state": {
            "lockfile": {key: value for key, value in lockfile.items() if key != "payload"},
            "cache_manifest": {key: value for key, value in cache_manifest.items() if key != "payload"},
            "inventory": inventory,
            "topology": topology,
            "inventory_skip_summary": _read_inventory_skip_summary(repo_root),
            "generated_state_paths": generated_state,
        },
        "privacy": {
            "content_free": True,
            "raw_prompts": False,
            "source_bodies": False,
            "source_snippets": False,
            "secrets": False,
            "packet_text": False,
            "inventory_path_list": False,
            "topology_path_list": False,
            "environment_values": False,
        },
        "cache_behavior": {
            "fresh_inventory_avoids_full_repo_walk": inventory.get("cache_hit") if inventory.get("state") == "fresh" else None,
            "fresh_topology_avoids_full_repo_walk": not bool(topology.get("fallback_used")) if topology.get("state") == "fresh" else None,
            "prompt_cache_guarantee": "none",
        },
        "cleanup": {
            "dry_run_command": "pcodex cleanup --local-state --dry-run",
            "apply_command": "pcodex cleanup --local-state --yes",
            "scope": "repo_local_generated_state",
        },
    }
    receipt["first_run"] = first_run_summary(
        {
            "enabled": enabled,
            "inventory": inventory,
            "topology": topology,
        }
    )
    if advisory:
        return paste_safe_receipt(
            receipt,
            command="first-run",
            repo_root=repo_root,
            inventory=inventory,
            topology=topology,
            lockfile={key: value for key, value in lockfile.items() if key != "payload"},
            cache_manifest={key: value for key, value in cache_manifest.items() if key != "payload"},
        )
    return receipt


def format_first_run_receipt(payload: dict[str, Any]) -> str:
    if payload.get("schema_version") == "pcodex.advisory_receipt.v1":
        return format_advisory_receipt(payload, title="pCodex first-run advisory receipt")
    install = payload.get("install") if isinstance(payload.get("install"), dict) else {}
    mode = payload.get("mode") if isinstance(payload.get("mode"), dict) else {}
    first_run = payload.get("first_run") if isinstance(payload.get("first_run"), dict) else {}
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    inventory = state.get("inventory") if isinstance(state.get("inventory"), dict) else {}
    topology = state.get("topology") if isinstance(state.get("topology"), dict) else {}
    return "\n".join(
        [
            "pCodex first-run receipt",
            f"LCC installed: {'yes' if payload.get('lcc_installed') else 'no'}",
            f"Version: {payload.get('lcc_version')}",
            f"Install channel: {install.get('install_channel') or 'unknown'} ({install.get('provenance_status') or 'unknown'})",
            f"Mode: {mode.get('public_mode')} ({'on' if mode.get('lcc_on') else 'off'})",
            f"Plugin: {mode.get('plugin_alias')}",
            f"Inventory: {inventory.get('state') or 'unknown'}, {inventory.get('source') or 'none'}, {inventory.get('file_count') or 0} files",
            f"Topology: {topology.get('state') or 'unknown'}, {topology.get('repo_shape') or 'unknown'}, {topology.get('node_count') or 0} nodes",
            f"Readiness: {first_run.get('readiness') or 'unknown'}",
            f"Next action: {first_run.get('next_action') or 'pcodex doctor'}",
            "Receipt is content-free: no prompts, source bodies, snippets, secrets, packet text, or environment values.",
            "Cleanup: pcodex cleanup --local-state --dry-run",
        ]
    )


def parse_codex_cli_version(text: str) -> str | None:
    match = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)\b", text)
    if not match:
        return None
    return ".".join(match.groups())


def _version_tuple(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    parts = version.split(".")
    if len(parts) != 3:
        return None
    try:
        parsed = tuple(int(part) for part in parts)
    except ValueError:
        return None
    return parsed if len(parsed) == 3 else None


def codex_cli_version_warning(version: str | None) -> str | None:
    parsed = _version_tuple(version)
    if parsed is None:
        return "Could not parse Codex CLI version; run codex --version and test direct codex exec before pCodex real runs."
    if parsed < MIN_CODEX_CLI_VERSION:
        return (
            f"Codex CLI {version} appears older than {MIN_CODEX_CLI_VERSION_TEXT}; "
            "update Codex CLI and test direct codex exec before pCodex real runs."
        )
    return None


def inspect_codex_cli() -> dict[str, Any]:
    if not _command_available("codex"):
        return {
            "available": False,
            "version": None,
            "path": None,
            "version_warning": "Codex CLI is not available on PATH; install or fix Codex before pCodex real runs.",
        }
    path = _command_path("codex")
    if path is None:
        return {
            "available": False,
            "version": None,
            "path": None,
            "version_warning": "Codex CLI is not available on PATH; install or fix Codex before pCodex real runs.",
        }
    try:
        completed = subprocess.run(
            [path, "--version"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except OSError as exc:
        return {
            "available": True,
            "version": None,
            "path": path,
            "version_warning": f"Could not execute codex --version: {type(exc).__name__}",
        }
    except subprocess.TimeoutExpired:
        return {
            "available": True,
            "version": None,
            "path": path,
            "version_warning": "codex --version timed out; test direct codex exec before pCodex real runs.",
        }
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    version = parse_codex_cli_version(output)
    return {
        "available": True,
        "version": version,
        "path": path,
        "version_warning": codex_cli_version_warning(version),
    }


def _display_home_path(path: Path) -> str:
    try:
        home = Path.home().resolve()
        resolved = path.expanduser().resolve()
        if resolved == home:
            return "~"
        if home in resolved.parents:
            return "~/" + resolved.relative_to(home).as_posix()
    except OSError:
        pass
    return str(path)


def _find_service_tier(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "service_tier":
                return str(item)
            nested = _find_service_tier(item)
            if nested is not None:
                return nested
    if isinstance(value, list):
        for item in value:
            nested = _find_service_tier(item)
            if nested is not None:
                return nested
    return None


def codex_service_tier_warning(service_tier: str | None) -> str | None:
    if not service_tier:
        return None
    normalized = service_tier.strip().lower()
    if normalized in {"flex", "auto"}:
        return None
    if normalized == "default":
        return 'Codex config service_tier = "default" may be incompatible with current Codex CLI real runs.'
    return f'Codex config service_tier = "{service_tier}" may be incompatible with current Codex CLI real runs.'


def inspect_codex_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or (Path.home() / ".codex" / "config.toml")
    display_path = _display_home_path(config_path)
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {
            "path": display_path,
            "exists": False,
            "readable": False,
            "service_tier": None,
            "service_tier_warning": None,
        }
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {
            "path": display_path,
            "exists": True,
            "readable": False,
            "service_tier": None,
            "service_tier_warning": f"Could not read Codex config safely: {type(exc).__name__}",
        }
    service_tier = _find_service_tier(data)
    return {
        "path": display_path,
        "exists": True,
        "readable": True,
        "service_tier": service_tier,
        "service_tier_warning": codex_service_tier_warning(service_tier),
    }


def _literal_symbol_kwargs() -> dict[str, str]:
    return {
        "packet_version": PCODEX_PACKET_VERSION,
        "packet_variant": PCODEX_PACKET_VARIANT,
        "packet_strategy": PCODEX_PACKET_STRATEGY,
    }


def _append_tuning_command(cmd: list[str], tuning_profile: str | None) -> list[str]:
    if tuning_profile:
        cmd.extend(["--tuning", tuning_profile])
    return cmd


def _premode_alias_command(prompt: str, repo_root: Path, profile: str | None, tuning_profile: str | None = None) -> list[str]:
    cmd = ["premode", "compile", prompt, "--repo", str(repo_root), "--plugin", PCODEX_PLUGIN_ALIAS]
    if profile:
        cmd.extend(["--profile", profile])
    return _append_tuning_command(cmd, tuning_profile)


def _premode_explicit_command(prompt: str, repo_root: Path, profile: str | None, tuning_profile: str | None = None) -> list[str]:
    cmd = [
        "premode",
        "compile",
        prompt,
        "--repo",
        str(repo_root),
        "--packet-version",
        PCODEX_PACKET_VERSION,
        "--packet-variant",
        PCODEX_PACKET_VARIANT,
        "--packet-strategy",
        PCODEX_PACKET_STRATEGY,
    ]
    if profile:
        cmd.extend(["--profile", profile])
    return _append_tuning_command(cmd, tuning_profile)


def _compile_runner_accepts_tuning(compile_runner: Any) -> bool:
    try:
        signature = inspect.signature(compile_runner)
    except (TypeError, ValueError):
        return False
    return "tuning_profile" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def run_compile_runner(
    compile_runner: Any,
    repo_root: Path,
    prompt: str,
    profile: str | None,
    *,
    tuning_profile: str | None = None,
) -> dict[str, Any]:
    if tuning_profile and _compile_runner_accepts_tuning(compile_runner):
        return compile_runner(repo_root, prompt, profile, tuning_profile=tuning_profile)
    return compile_runner(repo_root, prompt, profile)


def compile_pcodex_packet(
    repo_root: Path,
    prompt: str,
    profile: str | None = "lite",
    *,
    tuning_profile: str | None = None,
    mode_state: dict[str, Any] | None = None,
    write_policy: WritePolicy | str | None = NORMAL,
) -> dict[str, Any]:
    policy = resolve_write_policy(write_policy)
    resolved_state = mode_state or resolve_effective_mode(repo_root)
    try:
        resolved = resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
        route = "plugin_alias"
        command = _premode_alias_command(prompt, repo_root, profile, tuning_profile)
        kwargs = resolved.as_compile_kwargs()
        plugin_resolution = resolved.as_dict()
    except PluginAliasError as exc:
        route = "explicit_fallback"
        command = _premode_explicit_command(prompt, repo_root, profile, tuning_profile)
        kwargs = _literal_symbol_kwargs()
        plugin_resolution = None
        fallback_reason = str(exc)
    else:
        fallback_reason = None
    compiled = compile_prompt(
        repo_root,
        prompt,
        profile,
        use_repo_map=True,
        cache_optimized=True,
        save=False,
        record_artifacts=False,
        tuning_profile=tuning_profile,
        **kwargs,
    )
    result = {
        "status": "compiled",
        "route": route,
        "premode_command": command,
        "plugin_alias_resolution": plugin_resolution,
        "fallback_reason": fallback_reason,
        "packet": compiled["packet"],
        "packet_sha256": compiled.get("compiled_packet_sha256"),
        "packet_version": compiled.get("packet_version"),
        "packet_variant": compiled.get("packet_variant"),
        "packet_strategy": compiled.get("strategy_selected") or kwargs.get("packet_strategy"),
        "model_facing_sections": ["TASK", "PRIMARY_FILES", "RELATED_TESTS", "END_PREMODE_CONTEXT_PACKET_V5"],
        "tuning_profile": tuning_profile,
    }
    cache_manifest = write_cache_manifest(repo_root, resolved_state, {**compiled, **result}, policy=policy)
    result["cache_manifest"] = {key: value for key, value in cache_manifest.items() if key != "payload"}
    result["lockfile"] = update_lockfile_from_resolver(
        repo_root,
        resolved_state,
        cache_prefix_hash=cache_manifest.get("payload", {}).get("static_prefix_hash")
        if isinstance(cache_manifest.get("payload"), dict)
        else None,
        policy=policy,
    )
    return result


def redact_text(text: str, limit: int = 800) -> str:
    redacted = re.sub(r"\b\S*(?:SECRET|TOKEN|PASSWORD|API[_-]?KEY)\S*\b", "<redacted>", text, flags=re.IGNORECASE)
    return redacted[:limit] + ("..." if len(redacted) > limit else "")


def compose_final_prompt(raw_task: str, packet: str | None) -> str:
    if packet:
        return packet
    return raw_task


def doctor(cwd: Path | None = None, *, advisory: bool = False) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    config = resolve_config(cwd)
    codex_cli = inspect_codex_cli()
    codex_config = inspect_codex_config()
    state = resolve_effective_mode(repo_root)
    lockfile = read_lockfile(repo_root)
    cache_manifest = read_cache_manifest(repo_root)
    inventory = summarize_inventory(repo_root)
    topology = summarize_topology(repo_root)
    tuning = state.get("tuning") if isinstance(state.get("tuning"), dict) else {}
    cache_payload = cache_manifest.get("payload") if isinstance(cache_manifest.get("payload"), dict) else {}
    enabled = str(state.get("effective_mode") or state.get("configured_mode") or state.get("mode")) != "off"
    first_run = first_run_summary({"enabled": enabled, "inventory": inventory, "topology": topology})
    payload = {
        "status": "ok",
        "repo_root": str(repo_root),
        "premode_executable_available": _command_available("premode"),
        "pcodex_executable_available": _command_available("pcodex"),
        "codex_executable_available": bool(codex_cli.get("available")),
        "codex_cli": codex_cli,
        "codex_config": codex_config,
        "plugin_alias_available": plugin_alias_available(),
        "available_plugin_aliases": available_plugin_aliases(),
        "fallback_explicit_literal_symbol_available": True,
        "git_repo": (repo_root / ".git").exists(),
        "config": config.__dict__,
        "configured_mode": state.get("configured_mode"),
        "effective_mode": state.get("effective_mode"),
        "effective_state": state.get("effective_state"),
        "state_summary": state.get("user_visible_summary"),
        "lockfile": {key: value for key, value in lockfile.items() if key != "payload"},
        "cache_manifest": {key: value for key, value in cache_manifest.items() if key != "payload"},
        "inventory": inventory,
        "topology": topology,
        "cache_shape": {
            "cache_candidate": cache_payload.get("cache_candidate"),
            "static_prefix_hash_present": bool(cache_payload.get("static_prefix_hash")),
            "total_tokens_estimate": cache_payload.get("total_tokens_estimate"),
            "provider_guarantee": cache_payload.get("provider_hint", {}).get("guarantee")
            if isinstance(cache_payload.get("provider_hint"), dict)
            else None,
        },
        "tuning": {
            "profile": tuning.get("profile"),
            "validation": tuning.get("validation"),
            "verify": tuning.get("verify"),
        },
        "fallback": state.get("fallback") if isinstance(state.get("fallback"), dict) else {},
        "safe_passthrough_reason": state.get("safe_passthrough_reason"),
        "stale_reason": state.get("stale_reason"),
        "mcp": {"status": "unknown", "config_scope": "unknown"},
        "savings": {"available": False, "reason": "not_enough_data"},
        "generated_state_paths": generated_state_path_status(repo_root),
        "install": _manifest_summary(),
        "first_run": first_run,
        "native_codex_integration": {
            "slash_commands": "not_native",
            "installed_schema_discovery": "not_proven",
            "automatic_internal_subagent_interception": "not_proven",
            "automatic_mcp_invocation": "not_guaranteed",
        },
        "algorithm": PCODEX_PACKET_STRATEGY,
        "secrets_printed": False,
    }
    if advisory:
        return paste_safe_receipt(
            payload,
            command="doctor",
            repo_root=repo_root,
            inventory=inventory,
            topology=topology,
            lockfile={key: value for key, value in lockfile.items() if key != "payload"},
            cache_manifest={key: value for key, value in cache_manifest.items() if key != "payload"},
        )
    return payload


def format_doctor(payload: dict[str, Any]) -> str:
    if payload.get("schema_version") == "pcodex.advisory_receipt.v1":
        return format_advisory_receipt(payload, title="pCodex doctor advisory receipt")
    codex_cli = payload.get("codex_cli") if isinstance(payload.get("codex_cli"), dict) else {}
    lockfile = payload.get("lockfile") if isinstance(payload.get("lockfile"), dict) else {}
    cache_manifest = payload.get("cache_manifest") if isinstance(payload.get("cache_manifest"), dict) else {}
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
    topology = payload.get("topology") if isinstance(payload.get("topology"), dict) else {}
    cache_shape = payload.get("cache_shape") if isinstance(payload.get("cache_shape"), dict) else {}
    generated_paths = payload.get("generated_state_paths") if isinstance(payload.get("generated_state_paths"), dict) else {}
    first_run = payload.get("first_run") if isinstance(payload.get("first_run"), dict) else {}
    install = payload.get("install") if isinstance(payload.get("install"), dict) else {}
    ignored_count = sum(1 for item in generated_paths.values() if isinstance(item, dict) and item.get("git_ignored"))
    lines = [
        "pCodex doctor",
        f"Repo root: {payload.get('repo_root')}",
        f"Readiness: {first_run.get('readiness') or 'unknown'}",
        f"Next action: {first_run.get('next_action') or 'pcodex status'}",
        f"Install provenance: {install.get('provenance_status') or 'unknown'}",
        f"Configured mode: {payload.get('configured_mode')}",
        f"Effective mode: {payload.get('effective_mode')}",
        f"Effective state: {payload.get('effective_state')}",
        f"Summary: {payload.get('state_summary')}",
        f"premode executable: {'available' if payload.get('premode_executable_available') else 'missing'}",
        f"pcodex executable: {'available' if payload.get('pcodex_executable_available') else 'missing'}",
        f"codex executable: {'available' if payload.get('codex_executable_available') else 'missing'}",
        f"Codex CLI version: {codex_cli.get('version') or 'unknown'}",
        f"literal_symbol plugin: {'available' if payload.get('plugin_alias_available') else 'missing'}",
        f"LCC lockfile: {lockfile.get('status') or 'unknown'} ({lockfile.get('path') or '.premode/lcc.lock.json'})",
        f"Cache manifest: {cache_manifest.get('status') or 'unknown'} ({cache_manifest.get('path') or '.premode/out/cache_manifest.json'})",
        f"Inventory: {inventory.get('state') or 'unknown'}, {inventory.get('source') or 'none'}, {inventory.get('file_count') or 0} files",
        f"Topology: {topology.get('state') or 'unknown'}, {topology.get('repo_shape') or 'unknown'}, {topology.get('node_count') or 0} nodes, primary {topology.get('primary_node') or 'none'}",
        f"Cache candidate: {cache_shape.get('cache_candidate') if cache_shape else 'unknown'}",
        f"Generated state git-ignore: {ignored_count}/{len(generated_paths)} paths ignored",
        "Native Codex integration: slash commands, schema discovery, internal interception, and automatic MCP invocation are not assumed.",
    ]
    if codex_cli.get("version_warning"):
        lines.append(f"Codex CLI warning: {codex_cli.get('version_warning')}")
    return "\n".join(lines)


def run_one_step_tune(repo_root: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    from .tuning import validate_tuning_artifacts, verify_tuning_profile, write_tuning_artifacts

    generation = write_tuning_artifacts(repo_root, out_dir=out_dir)
    validation = validate_tuning_artifacts(repo_root, out_dir=out_dir)
    verification = verify_tuning_profile(repo_root, out_dir=out_dir)
    verdict = str(verification.get("verdict") or "FAIL")
    if verdict == "PASS":
        status = "tuning_ready"
        next_step = "pcodex setup or pcodex tuned"
    elif verdict == "NEEDS_ADJUSTMENT":
        status = "needs_adjustment"
        next_step = "keep general literal_symbol mode and inspect VERIFY_REPORT.md"
    else:
        status = "failed"
        next_step = "keep general literal_symbol mode and repair tuning artifacts"
    return {
        "status": status,
        "repo_root": str(repo_root),
        "out_dir": str(out_dir or (repo_root / ".premode" / "tuning")),
        "generation_status": generation.get("status"),
        "validation_status": "PASS" if validation.get("status") == "pass" else "FAIL",
        "validation_failures": validation.get("failures", []),
        "verdict": verdict,
        "profile_validation_status": verification.get("profile_validation_status"),
        "evaluation_prompt_count": verification.get("evaluation_prompt_count"),
        "notes": verification.get("notes", []),
        "artifacts": {
            "repo_profile": str((out_dir or (repo_root / ".premode" / "tuning")) / "repo_profile.json"),
            "VALIDATION": str((out_dir or (repo_root / ".premode" / "tuning")) / "VALIDATION.json"),
            "VERIFY_RESULTS": str((out_dir or (repo_root / ".premode" / "tuning")) / "VERIFY_RESULTS.json"),
            "VERIFY_REPORT": str((out_dir or (repo_root / ".premode" / "tuning")) / "VERIFY_REPORT.md"),
        },
        "safety_summary": {
            "local_only": True,
            "source_edits": False,
            "model_facing_packet_expansion": False,
            "live_codex_tasks": False,
            "real_codex_config_mutation": False,
        },
        "next": next_step,
        "generation": generation,
        "validation": validation,
        "verification": verification,
    }


def _one_step_tune_exit_code(result: dict[str, Any]) -> int:
    verdict = result.get("verdict")
    if verdict in {"PASS", "NEEDS_ADJUSTMENT"}:
        return 0
    return 2


def _isolated_codex_home(repo_root: Path) -> Path:
    return repo_root / ".premode" / "pcodex_codex_home"


def _run_codex_mcp_command(args: list[str], *, codex_home: Path | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    if codex_home is not None:
        codex_home.mkdir(parents=True, exist_ok=True)
        env["CODEX_HOME"] = str(codex_home)
    completed = subprocess.run(
        ["codex", "mcp", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    return {
        "args": ["codex", "mcp", *args],
        "returncode": completed.returncode,
        "stdout": redact_text(completed.stdout, limit=1200),
        "stderr": redact_text(completed.stderr, limit=1200),
    }


def register_mcp_for_setup(
    repo_root: Path,
    *,
    no_mcp: bool = False,
    isolated: bool = True,
    real_codex_registration: bool = False,
) -> dict[str, Any]:
    if no_mcp:
        return {"status": "skipped", "reason": "no_mcp", "registered": False, "config_scope": "none"}
    if not _command_available("codex"):
        return {"status": "skipped", "reason": "codex_cli_missing", "registered": False, "config_scope": "none"}
    if real_codex_registration:
        codex_home = None
        config_scope = "real"
        warning = "This mutates real local Codex MCP config because --real-codex-registration was explicitly provided."
    else:
        codex_home = _isolated_codex_home(repo_root) if isolated else _isolated_codex_home(repo_root)
        config_scope = "isolated"
        warning = None
    pcodex_command = _command_path("pcodex") or "pcodex"
    add_result = _run_codex_mcp_command(["add", "pcodex", "--", pcodex_command, "mcp-server"], codex_home=codex_home)
    list_result = _run_codex_mcp_command(["list"], codex_home=codex_home)
    registered = add_result["returncode"] == 0
    status_value = "registered" if registered else "failed"
    return {
        "status": status_value,
        "registered": registered,
        "config_scope": config_scope,
        "codex_home": str(codex_home) if codex_home is not None else None,
        "warning": warning,
        "command": add_result,
        "list": list_result,
        "rollback": "codex mcp remove pcodex",
        "fatal": False,
    }


def setup(
    cwd: Path | None = None,
    *,
    skip_tune: bool = False,
    no_mcp: bool = False,
    isolated: bool = True,
    real_codex_registration: bool = False,
    tune_runner: Any | None = None,
    mcp_registrar: Any | None = None,
) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    doctor_result = doctor(repo_root)
    checks = {
        "premode_available": bool(doctor_result.get("premode_executable_available")),
        "pcodex_available": bool(doctor_result.get("pcodex_executable_available")),
        "literal_symbol_plugin_available": bool(doctor_result.get("plugin_alias_available")),
        "codex_available": bool(doctor_result.get("codex_executable_available")),
    }
    blocking = [name for name in ("premode_available", "literal_symbol_plugin_available") if not checks[name]]
    if blocking:
        mode_result = set_enabled(repo_root, True)
        return {
            "setup_status": "failed",
            "repo_root": str(repo_root),
            "checks": checks,
            "blocking_checks": blocking,
            "doctor": doctor_result,
            "mode": mode_result.get("mode"),
            "tuning_verdict": "SKIPPED",
            "mcp_status": "not_attempted",
            "fallback": "using general literal_symbol",
            "next_steps": ["repair local pCodex prerequisites", "rerun pcodex setup"],
            "codex_launch": "not_executed",
        }
    tune_result: dict[str, Any] | None = None
    tuning_verdict = "SKIPPED"
    if not skip_tune:
        runner = tune_runner or run_one_step_tune
        try:
            tune_result = runner(repo_root)
            tuning_verdict = str(tune_result.get("verdict") or "FAIL")
        except Exception as exc:
            tune_result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            tuning_verdict = "FAIL"
    if tuning_verdict == "PASS":
        try:
            mode_result = set_tuned(repo_root)
        except PcodexStateError as exc:
            mode_result = set_enabled(repo_root, True)
            tuning_verdict = "FAIL"
            tune_result = {**(tune_result or {}), "mode_error": str(exc)}
    else:
        mode_result = set_enabled(repo_root, True)
    registrar = mcp_registrar or register_mcp_for_setup
    mcp_result = registrar(
        repo_root,
        no_mcp=no_mcp,
        isolated=isolated,
        real_codex_registration=real_codex_registration,
    )
    mode = str(mode_result.get("mode") or "on")
    fallback = "general mode available" if mode == "tuned" else "using general literal_symbol"
    return {
        "setup_status": "complete",
        "repo_root": str(repo_root),
        "checks": checks,
        "blocking_checks": [],
        "doctor": doctor_result,
        "mode": mode,
        "tuning_verdict": tuning_verdict,
        "tune": tune_result,
        "mcp": mcp_result,
        "mcp_status": _format_mcp_status(mcp_result),
        "fallback": fallback,
        "next_steps": ["pcodex status", "pcodex run --dry-run \"Hypothetical dummy task: inspect login flow. Do not modify files.\""],
        "codex_launch": "not_executed",
    }


def status(cwd: Path | None = None, *, advisory: bool = False) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    config = resolve_config(cwd)
    codex_cli = inspect_codex_cli()
    codex_config = inspect_codex_config()
    state = resolve_effective_mode(repo_root)
    configured_mode = str(state.get("configured_mode") or state.get("mode") or "on")
    effective_mode = str(state.get("effective_mode") or configured_mode)
    if config.source in {CONFIG_ENV, CONFIG_PATH_ENV, CONFIG_PATH_ALIAS_ENV, "repo", "user"} and not state["state_exists"]:
        configured_mode = "on" if config.enabled else "off"
        effective_mode = configured_mode
        state["enabled"] = config.enabled
        state["mode"] = configured_mode
        state["configured_mode"] = configured_mode
        state["effective_mode"] = effective_mode
        state["effective_state"] = EFFECTIVE_ON_GENERALIZED if config.enabled else EFFECTIVE_OFF_RAW
        state["tuning_profile"] = None
        state["effective_tuning_profile"] = None
    tuning = state.get("tuning") if isinstance(state.get("tuning"), dict) else {}
    fallback = state.get("fallback") if isinstance(state.get("fallback"), dict) else {}
    telemetry = state.get("telemetry") if isinstance(state.get("telemetry"), dict) else {}
    mcp = {
        "codex_cli_available": bool(codex_cli.get("available")),
        "registered": False,
        "config_scope": "unknown",
        "status": "unknown",
    }
    if advisory:
        lockfile = read_lockfile(repo_root)
    else:
        try:
            lockfile = update_lockfile_from_resolver(repo_root, state)
        except Exception as exc:  # lockfile must not make status unusable
            lockfile = {"status": "error", "path": ".premode/lcc.lock.json", "valid": False, "error": f"{type(exc).__name__}: {exc}"}
    cache_manifest = read_cache_manifest(repo_root)
    inventory = summarize_inventory(repo_root)
    topology = summarize_topology(repo_root)
    first_run = first_run_summary(
        {
            "enabled": effective_mode != "off",
            "inventory": inventory,
            "topology": topology,
        }
    )
    payload = {
        "schema_version": "pcodex.status.v1",
        "enabled": bool(state.get("enabled")),
        "configured_mode": configured_mode,
        "effective_mode": effective_mode,
        "effective_state": state.get("effective_state"),
        "state_summary": state.get("user_visible_summary"),
        "mode": configured_mode,
        "algorithm": state.get("algorithm") or PCODEX_PACKET_STRATEGY,
        "packet": {
            "plugin_alias": state.get("plugin_alias"),
            "version": state.get("packet_version"),
            "variant": state.get("packet_variant"),
            "strategy": state.get("packet_strategy"),
        },
        "tuning": {
            "profile": tuning.get("profile"),
            "validation": tuning.get("validation"),
            "verify": tuning.get("verify"),
            "results_path": tuning.get("results_path"),
        },
        "mcp": mcp,
        "fallback": {
            "active": bool(fallback.get("active")),
            "last_reason": fallback.get("last_reason"),
            "last_at": fallback.get("last_at"),
        },
        "telemetry": telemetry,
        "savings": {"available": False, "reason": "not_enough_data"},
        "lockfile": {key: value for key, value in lockfile.items() if key != "payload"},
        "cache_manifest": {key: value for key, value in cache_manifest.items() if key != "payload"},
        "inventory": inventory,
        "topology": topology,
        "state_path": state.get("state_path"),
        "state_exists": state.get("state_exists"),
        "state_status": state.get("state_status"),
        "state_error": state.get("state_error"),
        "state_schema_version": "pcodex.state.v1",
        "install": _manifest_summary(),
        "first_run": first_run,
        "codex_cli": codex_cli,
        "codex_config": codex_config,
        "tuning_profile": tuning.get("profile"),
        "tuning_profile_valid": tuning.get("profile_valid"),
        "tuning_validation_status": tuning.get("validation"),
        "config_source": config.source,
        "config_path": config.path,
        "legacy_enabled": config.enabled,
        "premode_available": _command_available("premode"),
        "codex_available": mcp["codex_cli_available"],
        "plugin_alias_available": plugin_alias_available(),
    }
    if advisory:
        return paste_safe_receipt(
            payload,
            command="status",
            repo_root=repo_root,
            inventory=inventory,
            topology=topology,
            lockfile={key: value for key, value in lockfile.items() if key != "payload"},
            cache_manifest={key: value for key, value in cache_manifest.items() if key != "payload"},
        )
    return payload


def _format_mcp_status(mcp_result: dict[str, Any]) -> str:
    status_value = str(mcp_result.get("status") or "unknown")
    scope = str(mcp_result.get("config_scope") or "none")
    if status_value == "registered":
        return f"registered in {scope} config"
    if status_value == "skipped":
        reason = mcp_result.get("reason")
        return f"skipped ({reason})" if reason else "skipped"
    if status_value == "failed":
        return f"registration failed in {scope} config"
    return status_value


def child_env_for(repo_root: Path, config: PcodexConfig | None = None) -> dict[str, str]:
    config = resolve_config(repo_root) if config is None else config
    env = {
        CONFIG_ENV: "1" if config.enabled else "0",
        ALGORITHM_ENV: PCODEX_PACKET_STRATEGY,
        PACKET_STRATEGY_ENV: PCODEX_PACKET_STRATEGY,
        PROJECT_ROOT_ENV: str(repo_root.resolve()),
    }
    if config.path and config.source in {"repo", CONFIG_PATH_ENV, CONFIG_PATH_ALIAS_ENV}:
        env[CONFIG_PATH_ENV] = config.path
        env[CONFIG_PATH_ALIAS_ENV] = config.path
    return env


def child_env_for_mode_state(repo_root: Path, mode_state: dict[str, Any]) -> dict[str, str]:
    effective_state = str(mode_state.get("effective_state") or "")
    enabled = effective_state != EFFECTIVE_OFF_RAW and str(mode_state.get("effective_mode") or mode_state.get("mode")) != "off"
    return {
        CONFIG_ENV: "1" if enabled else "0",
        ALGORITHM_ENV: PCODEX_PACKET_STRATEGY,
        PACKET_STRATEGY_ENV: PCODEX_PACKET_STRATEGY,
        PROJECT_ROOT_ENV: str(repo_root.resolve()),
    }


def resolve_mode_state(repo_root: Path, *, validate_tuned: bool = True, require_runnable: bool = False) -> dict[str, Any]:
    mode_state = resolve_effective_mode(repo_root, validate_tuned=validate_tuned)
    if mode_state.get("state_status") == "invalid_default":
        return mode_state
    tuning = mode_state.get("tuning") if isinstance(mode_state.get("tuning"), dict) else {}
    if require_runnable and mode_state.get("configured_mode") == "tuned" and (
        not tuning.get("profile_valid") or tuning.get("verify") != "PASS"
    ):
        message = tuning.get("profile_error") or tuning.get("fallback_reason") or "Verified pCodex tuning profile is required"
        raise PcodexStateError(str(message))
    return mode_state


def _state_tuning_profile(mode_state: dict[str, Any]) -> str | None:
    if mode_state.get("effective_mode") != "tuned":
        return None
    profile = mode_state.get("effective_tuning_profile") or mode_state.get("tuning_profile")
    return str(profile) if profile else None


def install(cwd: Path | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    path = _repo_config_path(repo_root)
    result = {
        "status": "dry_run" if dry_run else "installed",
        "repo_root": str(repo_root),
        "config_path": str(path),
        "would_write": not path.exists(),
        "doctor": doctor(cwd),
    }
    if not dry_run and not path.exists():
        write_repo_config(cwd, enabled=False)
        result["written"] = True
    else:
        result["written"] = False
    return result


def set_enabled(cwd: Path | None, enabled: bool) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    path = write_repo_config(cwd, enabled=enabled)
    mode_result = set_mode_on(cwd) if enabled else set_mode_off(cwd)
    inventory = None
    topology = None
    if enabled:
        inventory_result = refresh_inventory_if_needed(repo_root, policy="write")
        inventory = summarize_inventory(repo_root, inventory_result.inventory)
        topology_result = refresh_topology_if_needed(repo_root, inventory=inventory_result.inventory, policy="write")
        topology = summarize_topology(repo_root, topology_result.topology)
    lockfile = update_lockfile_from_resolver(repo_root, resolve_effective_mode(cwd))
    return {
        "status": "enabled" if enabled else "disabled",
        **mode_result,
        "config_path": str(path),
        "legacy_config_path": str(path),
        "inventory": inventory,
        "topology": topology,
        "lockfile": {key: value for key, value in lockfile.items() if key != "payload"},
    }


def set_tuned(cwd: Path | None, profile: str | None = None) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    inventory = summarize_inventory(repo_root)
    if str(inventory.get("state") or "").startswith("stale_") or inventory.get("state") == "invalid":
        raise PcodexStateError(f"Inventory is {inventory.get('state')}; refresh inventory before enabling strict tuned mode")
    result = set_mode_tuned(cwd, profile or DEFAULT_TUNING_PROFILE)
    path = write_repo_config(cwd, enabled=True)
    lockfile = update_lockfile_from_resolver(repo_root, resolve_effective_mode(cwd))
    topology = summarize_topology(repo_root)
    return {
        "status": "tuned",
        **result,
        "config_path": str(path),
        "legacy_config_path": str(path),
        "inventory": inventory,
        "topology": topology,
        "lockfile": {key: value for key, value in lockfile.items() if key != "payload"},
    }


def format_status(payload: dict[str, Any]) -> str:
    if payload.get("schema_version") == "pcodex.advisory_receipt.v1":
        return format_advisory_receipt(payload, title="pCodex status advisory receipt")
    tuning = payload.get("tuning") if isinstance(payload.get("tuning"), dict) else {}
    fallback = payload.get("fallback") if isinstance(payload.get("fallback"), dict) else {}
    telemetry = payload.get("telemetry") if isinstance(payload.get("telemetry"), dict) else {}
    mcp = payload.get("mcp") if isinstance(payload.get("mcp"), dict) else {}
    savings = payload.get("savings") if isinstance(payload.get("savings"), dict) else {}
    codex_cli = payload.get("codex_cli") if isinstance(payload.get("codex_cli"), dict) else {}
    codex_config = payload.get("codex_config") if isinstance(payload.get("codex_config"), dict) else {}
    first_run = payload.get("first_run") if isinstance(payload.get("first_run"), dict) else {}
    install = payload.get("install") if isinstance(payload.get("install"), dict) else {}
    fallback_text = "active"
    if not fallback.get("active"):
        fallback_text = "none"
    elif fallback.get("last_reason"):
        fallback_text = f"active ({fallback.get('last_reason')})"
    mcp_status = str(mcp.get("status") or "unknown")
    if mcp_status == "unknown":
        mcp_text = "unknown"
    elif mcp.get("registered"):
        mcp_text = f"registered in {mcp.get('config_scope') or 'unknown'} config"
    else:
        mcp_text = "not registered"
    savings_text = "unavailable"
    if not savings.get("available"):
        savings_text = f"unavailable ({savings.get('reason') or 'unknown'})"
    codex_cli_text = "unavailable"
    if codex_cli.get("available"):
        codex_cli_text = f"available ({codex_cli.get('version') or 'version unknown'})"
    lines = [
        f"pCodex: {'on' if payload.get('enabled') else 'off'}",
        f"Readiness: {first_run.get('readiness') or 'unknown'}",
        f"Next action: {first_run.get('next_action') or 'pcodex doctor'}",
        f"Install provenance: {install.get('provenance_status') or 'unknown'}",
        f"Configured mode: {payload.get('configured_mode')}",
        f"Effective mode: {payload.get('effective_mode')}",
        f"Effective state: {payload.get('effective_state')}",
        f"Algorithm: {payload.get('algorithm')}",
        f"Tuning: {tuning.get('verify') or tuning.get('validation') or 'missing'}",
        f"Tuning profile: {tuning.get('profile') or 'none'}",
        f"MCP: {mcp_text}",
        f"Codex CLI: {codex_cli_text}",
        f"Fallback: {fallback_text}",
        f"Telemetry: compile_count={telemetry.get('compile_count', 0)} fallback_count={telemetry.get('fallback_count', 0)}",
        f"Savings estimate: {savings_text}",
        f"State path: {payload.get('state_path')}",
    ]
    lockfile = payload.get("lockfile") if isinstance(payload.get("lockfile"), dict) else {}
    cache_manifest = payload.get("cache_manifest") if isinstance(payload.get("cache_manifest"), dict) else {}
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
    topology = payload.get("topology") if isinstance(payload.get("topology"), dict) else {}
    lines.append(f"LCC lockfile: {lockfile.get('status') or 'unknown'}")
    lines.append(f"Cache manifest: {cache_manifest.get('status') or 'unknown'}")
    lines.append(
        f"Inventory: {inventory.get('state') or 'unknown'}, {inventory.get('source') or 'none'}, "
        f"{inventory.get('file_count') or 0} files"
    )
    lines.append(
        f"Topology: {topology.get('state') or 'unknown'}, {topology.get('repo_shape') or 'unknown'}, "
        f"{topology.get('node_count') or 0} nodes, primary {topology.get('primary_node') or 'none'}"
    )
    if payload.get("state_status") != "loaded":
        lines.append(f"State status: {payload.get('state_status')}")
    if codex_cli.get("version_warning"):
        lines.append(f"Codex CLI warning: {codex_cli.get('version_warning')}")
    if codex_config.get("service_tier_warning"):
        lines.append(f"Codex config warning: {codex_config.get('service_tier_warning')}")
    return "\n".join(lines)


def format_advisory_receipt(payload: dict[str, Any], *, title: str = "pCodex advisory receipt") -> str:
    advisory = payload.get("advisory") if isinstance(payload.get("advisory"), dict) else {}
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    inventory = state.get("inventory") if isinstance(state.get("inventory"), dict) else {}
    topology = state.get("topology") if isinstance(state.get("topology"), dict) else {}
    lockfile = state.get("lockfile") if isinstance(state.get("lockfile"), dict) else {}
    cache_manifest = state.get("cache_manifest") if isinstance(state.get("cache_manifest"), dict) else {}
    missing = advisory.get("missing_or_stale") if isinstance(advisory.get("missing_or_stale"), list) else []
    would_write = advisory.get("would_write") if isinstance(advisory.get("would_write"), list) else []
    would_refresh = advisory.get("would_refresh") if isinstance(advisory.get("would_refresh"), list) else []
    return "\n".join(
        [
            title,
            "Advisory mode: enabled",
            "Writes performed: no",
            f"Readiness: {payload.get('readiness') or 'unknown'}",
            f"Missing/stale state: {', '.join(missing) if missing else 'none'}",
            f"Would refresh without advisory: {', '.join(would_refresh) if would_refresh else 'none'}",
            f"Would write without advisory: {', '.join(would_write) if would_write else 'none'}",
            f"Lockfile: {lockfile.get('status') or 'unknown'}",
            f"Cache manifest: {cache_manifest.get('status') or 'unknown'}",
            f"Inventory: {inventory.get('state') or 'unknown'}, {inventory.get('file_count') or 0} files",
            f"Topology: {topology.get('state') or 'unknown'}, {topology.get('node_count') or 0} nodes",
            f"Next action: {advisory.get('next_action') or payload.get('next_action') or 'none'}",
            "Receipt is paste-safe: no prompts, source bodies, snippets, secrets, packet text, path lists, environment values, or command logs.",
        ]
    )


def format_setup_dashboard(payload: dict[str, Any], *, verbose: bool = False) -> str:
    lines = [
        "pCodex setup complete." if payload.get("setup_status") == "complete" else "pCodex setup failed.",
        f"Mode: {payload.get('mode')}",
        f"Tuning: {payload.get('tuning_verdict')}",
        f"MCP: {payload.get('mcp_status')}",
        f"Fallback: {payload.get('fallback')}",
    ]
    if verbose:
        checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
        lines.append("Checks:")
        for key in sorted(checks):
            lines.append(f"  {key}: {str(checks[key]).lower()}")
        next_steps = payload.get("next_steps") if isinstance(payload.get("next_steps"), list) else []
        if next_steps:
            lines.append("Next steps:")
            lines.extend(f"  {step}" for step in next_steps)
        mcp = payload.get("mcp") if isinstance(payload.get("mcp"), dict) else {}
        warning = mcp.get("warning")
        if warning:
            lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def _write_temp_packet(packet: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="pcodex_packet_", suffix=".md", delete=False)
    with handle:
        handle.write(packet)
    return handle.name


def run_dry_run(
    repo_root: Path,
    prompt: str,
    profile: str | None = "lite",
    *,
    compile_runner: Any | None = None,
) -> dict[str, Any]:
    mode_state = resolve_mode_state(repo_root, validate_tuned=True, require_runnable=True)
    mode = str(mode_state.get("configured_mode") or mode_state["mode"])
    effective_mode = str(mode_state.get("effective_mode") or mode)
    effective_state = str(mode_state.get("effective_state") or "")
    tuning_profile = _state_tuning_profile(mode_state)
    child_env = child_env_for_mode_state(repo_root, mode_state)
    fallback = mode_state.get("fallback") if isinstance(mode_state.get("fallback"), dict) else {}
    fallback_reason = str(fallback.get("last_reason")) if fallback.get("active") and fallback.get("last_reason") else None
    base = {
        "status": "dry_run",
        "enabled": effective_mode != "off",
        "mode": mode,
        "configured_mode": mode,
        "effective_mode": effective_mode,
        "effective_state": effective_state,
        "transform_applied": effective_mode != "off" and effective_state != EFFECTIVE_SAFE_PASSTHROUGH,
        "tuning_profile": tuning_profile,
        "tuning": mode_state.get("tuning"),
        "fallback": fallback,
        "state_status": mode_state.get("state_status"),
        "state_error": mode_state.get("state_error"),
        "config_source": "pcodex_state",
        "algorithm": PCODEX_PACKET_STRATEGY,
        "child_env": child_env,
        "child_env_keys": sorted(child_env),
        "raw_task_preview": redact_text(prompt),
        "codex_launch": "not_executed",
    }
    if effective_state == EFFECTIVE_SAFE_PASSTHROUGH:
        telemetry = record_runtime_telemetry(
            repo_root,
            configured_mode=mode,
            effective_mode="safe_passthrough",
            fallback_reason=mode_state.get("safe_passthrough_reason") or "safe_passthrough",
        )
        lockfile = update_lockfile_from_resolver(repo_root, mode_state)
        invocation = build_codex_invocation(repo_root, CodexOptions(dry_run=True))
        return {
            **base,
            "enabled": False,
            "premode_command": None,
            "codex_command": invocation.args,
            "packet_path": None,
            "final_prompt_preview": redact_text(prompt),
            "telemetry": telemetry.get("telemetry"),
            "lockfile": {key: value for key, value in lockfile.items() if key != "payload"},
            "safe_passthrough_reason": mode_state.get("safe_passthrough_reason"),
        }
    if effective_mode != "off":
        runner = compile_runner or compile_pcodex_packet
        try:
            if runner is compile_pcodex_packet:
                compiled = run_compile_runner(
                    runner,
                    repo_root,
                    prompt,
                    profile,
                    tuning_profile=tuning_profile,
                )
            else:
                compiled = run_compile_runner(runner, repo_root, prompt, profile, tuning_profile=tuning_profile)
        except Exception as exc:
            if mode == "tuned":
                raise
            fallback_state = {
                **mode_state,
                "effective_mode": "off",
                "effective_state": EFFECTIVE_SAFE_PASSTHROUGH,
                "safe_passthrough_reason": f"compile_failed:{type(exc).__name__}",
            }
            telemetry = record_runtime_telemetry(
                repo_root,
                configured_mode=mode,
                effective_mode="safe_passthrough",
                fallback_reason=f"compile_failed:{type(exc).__name__}",
            )
            lockfile = update_lockfile_from_resolver(repo_root, fallback_state)
            invocation = build_codex_invocation(repo_root, CodexOptions(dry_run=True))
            return {
                **base,
                "enabled": False,
                "effective_mode": "off",
                "effective_state": EFFECTIVE_SAFE_PASSTHROUGH,
                "transform_applied": False,
                "premode_command": None,
                "codex_command": invocation.args,
                "packet_path": None,
                "final_prompt_preview": redact_text(prompt),
                "telemetry": telemetry.get("telemetry"),
                "lockfile": {key: value for key, value in lockfile.items() if key != "payload"},
                "safe_passthrough_reason": f"compile_failed:{type(exc).__name__}",
            }
        if "cache_manifest" not in compiled:
            cache_manifest = write_cache_manifest(repo_root, mode_state, compiled)
            compiled["cache_manifest"] = {key: value for key, value in cache_manifest.items() if key != "payload"}
            compiled["lockfile"] = update_lockfile_from_resolver(
                repo_root,
                mode_state,
                cache_prefix_hash=cache_manifest.get("payload", {}).get("static_prefix_hash")
                if isinstance(cache_manifest.get("payload"), dict)
                else None,
            )
        telemetry = record_runtime_telemetry(repo_root, configured_mode=mode, effective_mode=effective_mode, fallback_reason=fallback_reason)
        packet_path = _write_temp_packet(compiled["packet"])
        final_prompt = compose_final_prompt(prompt, compiled["packet"])
        invocation = build_codex_invocation(repo_root, CodexOptions(dry_run=True))
        return {
            **base,
            "premode_command": compiled["premode_command"],
            "codex_command": invocation.args,
            "packet_path": packet_path,
            "final_prompt_preview": redact_text(final_prompt),
            "packet_sha256": compiled["packet_sha256"],
            "route": compiled["route"],
            "telemetry": telemetry.get("telemetry"),
            "cache_manifest": compiled.get("cache_manifest"),
            "lockfile": {key: value for key, value in compiled.get("lockfile", {}).items() if key != "payload"}
            if isinstance(compiled.get("lockfile"), dict)
            else None,
        }
    telemetry = record_runtime_telemetry(repo_root, configured_mode=mode, effective_mode=effective_mode)
    invocation = build_codex_invocation(repo_root, CodexOptions(dry_run=True))
    return {
        **base,
        "premode_command": None,
        "codex_command": invocation.args,
        "packet_path": None,
        "final_prompt_preview": redact_text(prompt),
        "telemetry": telemetry.get("telemetry"),
        "lockfile": {key: value for key, value in update_lockfile_from_resolver(repo_root, mode_state).items() if key != "payload"},
    }


def run_enabled(repo_root: Path, prompt: str, profile: str | None = "lite") -> dict[str, Any]:
    mode_state = resolve_mode_state(repo_root, validate_tuned=True, require_runnable=True)
    tuning_profile = _state_tuning_profile(mode_state)
    configured_mode = str(mode_state.get("configured_mode") or mode_state.get("mode") or "on")
    effective_mode = str(mode_state.get("effective_mode") or configured_mode)
    fallback = mode_state.get("fallback") if isinstance(mode_state.get("fallback"), dict) else {}
    fallback_reason = str(fallback.get("last_reason")) if fallback.get("active") and fallback.get("last_reason") else None
    update_lockfile_from_resolver(repo_root, mode_state)
    record_runtime_telemetry(repo_root, configured_mode=configured_mode, effective_mode=effective_mode, fallback_reason=fallback_reason)
    child_env = child_env_for_mode_state(repo_root, mode_state)
    return run_codex(
        repo_root,
        prompt,
        profile,
        CodexOptions(
            dry_run=False,
            execute=True,
            json=True,
            packet_version=PCODEX_PACKET_VERSION,
            packet_variant=PCODEX_PACKET_VARIANT,
            packet_strategy=PCODEX_PACKET_STRATEGY,
            lane="pcodex",
            tuning_profile=tuning_profile,
            child_env=child_env,
        ),
    )


def run_disabled(repo_root: Path, prompt: str, mode_state: dict[str, Any] | None = None) -> dict[str, Any]:
    mode_state = mode_state or resolve_mode_state(repo_root, validate_tuned=False)
    child_env = child_env_for_mode_state(repo_root, mode_state)
    completed = subprocess.run(["codex", "exec", "-"], input=prompt, text=True, capture_output=True, check=False, cwd=repo_root, env={**os.environ, **child_env})
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "enabled": False,
        "mode": str(mode_state.get("mode") or "off"),
        "transform_applied": False,
        "child_env": child_env,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcodex")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable doctor result.")
    doctor_parser.add_argument("--advisory", action="store_true", help="Read-only, no-write, paste-safe advisory receipt.")
    doctor_parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    first_run_parser = sub.add_parser("first-run")
    first_run_parser.add_argument("--json", action="store_true", help="Print machine-readable first-run receipt.")
    first_run_parser.add_argument("--advisory", action="store_true", help="Read-only, no-write, paste-safe advisory receipt.")
    first_run_parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    cleanup_parser = sub.add_parser("cleanup")
    cleanup_parser.add_argument("--local-state", action="store_true", help="Limit cleanup to repo-local generated pCodex/LCC state.")
    cleanup_mode = cleanup_parser.add_mutually_exclusive_group()
    cleanup_mode.add_argument("--dry-run", action="store_true", help="List generated local state that would be removed.")
    cleanup_mode.add_argument("--yes", action="store_true", help="Remove generated local state.")
    cleanup_parser.add_argument("--json", action="store_true", help="Print machine-readable cleanup result.")
    cleanup_parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--apply", action="store_true", help="Write repo-local pCodex config. Default is dry-run.")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--json", action="store_true", help="Print machine-readable pCodex mode state.")
    status_parser.add_argument("--advisory", action="store_true", help="Read-only, no-write, paste-safe advisory receipt.")
    status_parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    setup_parser = sub.add_parser("setup")
    setup_parser.add_argument("--skip-tune", action="store_true", help="Skip tune/validate/verify and enable general mode.")
    setup_parser.add_argument("--no-mcp", action="store_true", help="Skip Codex MCP registration.")
    setup_parser.add_argument("--isolated", action="store_true", help="Use isolated Codex config for MCP registration. This is the default.")
    setup_parser.add_argument("--real-codex-registration", action="store_true", help="Explicitly mutate real local Codex MCP config.")
    setup_parser.add_argument("--verbose", action="store_true", help="Print detailed setup checks.")
    setup_parser.add_argument("--json", action="store_true", help="Print machine-readable setup result.")
    setup_parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    on = sub.add_parser("on")
    on.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    off = sub.add_parser("off")
    off.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    tuned = sub.add_parser("tuned")
    tuned.add_argument("--profile", default=DEFAULT_TUNING_PROFILE, help="Validated tuning profile to use for tuned mode.")
    tuned.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    tune = sub.add_parser("tune")
    tune_group = tune.add_mutually_exclusive_group()
    tune_group.add_argument("--static-only", action="store_true", help="Generate static local tuning artifacts only.")
    tune_group.add_argument("--validate", action="store_true", help="Validate existing .premode/tuning artifacts without regenerating them.")
    tune_group.add_argument("--verify", action="store_true", help="Verify static tuning profile quality with compile-only local selection.")
    tune.add_argument("--repo-root", default=None, help="Repository root to tune. Defaults to the current repo.")
    tune.add_argument("--out-dir", default=None, help="Artifact directory. Must remain under .premode/tuning/.")
    sub.add_parser("mcp-server")
    comp = sub.add_parser("compile")
    comp.add_argument("prompt")
    comp.add_argument("--repo", default=None)
    comp.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    comp.add_argument("--dry-run", action="store_true")
    comp.add_argument("--json", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("prompt")
    run.add_argument("--repo", default=None)
    run.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    cwd = Path.cwd()
    repo_arg = getattr(args, "repo", None) or getattr(args, "repo_root", None)
    repo_root = _repo_root(Path(repo_arg).resolve() if repo_arg else cwd)
    if args.command == "doctor":
        payload = doctor(repo_root, advisory=args.advisory)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(format_doctor(payload))
        return 0
    if args.command == "first-run":
        payload = first_run_receipt(repo_root, advisory=args.advisory)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(format_first_run_receipt(payload))
        return 0
    if args.command == "cleanup":
        if not args.local_state:
            print(json.dumps({"status": "error", "error": "--local-state is required", "scope": "none"}, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        payload = cleanup_local_state(repo_root, dry_run=not args.yes)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            planned = [item for item in payload.get("actions", []) if isinstance(item, dict) and item.get("action") == "remove"]
            print("pCodex cleanup local state")
            print(f"Mode: {'dry-run' if payload.get('dry_run') else 'apply'}")
            print(f"Scope: {payload.get('scope')}")
            for item in planned:
                print(f"  remove {item.get('path')}")
            if payload.get("dry_run"):
                print("No files were removed.")
            else:
                print(f"Removed: {len(payload.get('removed') or [])}")
        return 0
    if args.command == "install":
        print(json.dumps(install(repo_root, dry_run=not args.apply), indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        payload = status(repo_root, advisory=args.advisory)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(format_status(payload))
        return 0
    if args.command == "setup":
        payload = setup(
            repo_root,
            skip_tune=args.skip_tune,
            no_mcp=args.no_mcp,
            isolated=True,
            real_codex_registration=args.real_codex_registration,
        )
        if args.real_codex_registration and not args.json:
            mcp = payload.get("mcp") if isinstance(payload.get("mcp"), dict) else {}
            warning = mcp.get("warning")
            if warning:
                print(f"Warning: {warning}", file=sys.stderr)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(format_setup_dashboard(payload, verbose=args.verbose))
        return 0 if payload.get("setup_status") == "complete" else 2
    if args.command == "on":
        print(json.dumps(set_enabled(repo_root, True), indent=2, sort_keys=True))
        return 0
    if args.command == "off":
        print(json.dumps(set_enabled(repo_root, False), indent=2, sort_keys=True))
        return 0
    if args.command == "tuned":
        try:
            print(json.dumps(set_tuned(repo_root, args.profile), indent=2, sort_keys=True))
        except PcodexStateError as exc:
            print(json.dumps({"status": "error", "error": str(exc), "mode": "tuned"}, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        return 0
    if args.command == "tune":
        from .tuning import validate_tuning_artifacts, verify_tuning_profile, write_tuning_artifacts

        try:
            if args.verify:
                result = verify_tuning_profile(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result.get("verdict") in {"PASS", "NEEDS_ADJUSTMENT"} else 1
            if args.validate:
                result = validate_tuning_artifacts(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result.get("status") == "pass" else 1
            if args.static_only:
                result = write_tuning_artifacts(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result.get("validation_status") == "pass" else 1
            result = run_one_step_tune(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
        except ValueError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2, sort_keys=True))
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return _one_step_tune_exit_code(result)
    if args.command == "mcp-server":
        from . import pcodex_mcp_server

        return pcodex_mcp_server.serve()
    if args.command == "compile":
        if args.dry_run:
            try:
                resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
                command = _premode_alias_command(args.prompt, repo_root, args.profile)
                route = "plugin_alias"
            except PluginAliasError as exc:
                command = _premode_explicit_command(args.prompt, repo_root, args.profile)
                route = "explicit_fallback"
                fallback_reason = str(exc)
            else:
                fallback_reason = None
            print(json.dumps({"status": "dry_run", "route": route, "premode_command": command, "fallback_reason": fallback_reason}, indent=2, sort_keys=True))
            return 0
        compiled = compile_pcodex_packet(repo_root, args.prompt, args.profile)
        if args.json:
            payload = {key: value for key, value in compiled.items() if key != "packet"}
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(compiled["packet"])
        return 0
    if args.command == "run":
        try:
            mode_state = resolve_mode_state(repo_root, validate_tuned=True, require_runnable=True)
        except PcodexStateError as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": str(exc),
                        "codex_launch": "not_executed",
                        "transform_applied": False,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        if args.dry_run:
            print(json.dumps(run_dry_run(repo_root, args.prompt, args.profile), indent=2, sort_keys=True))
            return 0
        if mode_state.get("effective_mode") != "off":
            result = run_enabled(repo_root, args.prompt, args.profile)
        else:
            result = run_disabled(repo_root, args.prompt, mode_state)
        print(json.dumps(result, indent=2, sort_keys=True))
        return int(result.get("returncode", 0) or 0)
    return 2
