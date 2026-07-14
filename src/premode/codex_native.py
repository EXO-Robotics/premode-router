"""Exact, receipt-bound registration of the canonical plugin with Codex.

Codex owns the syntax and cache layout it writes.  pCodex snapshots the parsed
target values before and after each Codex CLI operation, verifies that unrelated
configuration values did not change, and later mutates only receipt-proven
values.  Read-only preview and status never invoke Codex.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__


STATE_RELATIVE = Path(".pcodex/codex-native-state.json")
JOURNAL_RELATIVE = Path(".pcodex/codex-native-operation.json")
STATE_SCHEMA = "pcodex.codex-native-state.v1"
JOURNAL_SCHEMA = "pcodex.codex-native-operation.v1"
MARKETPLACE = "local-premode-marketplace"
PLUGIN_ID = f"pcodex@{MARKETPLACE}"


class NativeCodexError(RuntimeError):
    """Fail-closed native Codex registration error."""


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json(value: Any) -> str:
    return _hash_bytes(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _owned_registration_value(key: str, value: Any) -> Any:
    """Return the exact fields pCodex owns for one Codex registration.

    Codex owns its marketplace ``last_updated`` timestamp. It may change when
    Codex recreates the same directory registration, so it is deliberately
    preserved rather than adopted into pCodex authority.
    """
    if key == "codex_marketplace" and isinstance(value, dict):
        return {name: item for name, item in value.items() if name != "last_updated"}
    return value


def _registration_hash(key: str, value: Any) -> str:
    return _hash_json(_owned_registration_value(key, value))


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.parent.name != ".pcodex":
        raise NativeCodexError("native authority writes are confined to the workspace .pcodex directory")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(path.parent.parent, directory_flags)
    parent_fd: int | None = None
    temporary = f".{path.name}.{os.getpid()}.tmp"
    temporary_created = False
    try:
        try:
            parent_fd = os.open(".pcodex", directory_flags, dir_fd=root_fd)
        except FileNotFoundError:
            os.mkdir(".pcodex", 0o700, dir_fd=root_fd)
            parent_fd = os.open(".pcodex", directory_flags, dir_fd=root_fd)
        try:
            existing = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and (not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1):
            raise NativeCodexError("native authority leaf is not an unlinked regular file")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600, dir_fd=parent_fd,
        )
        temporary_created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temporary_created = False
        try:
            os.fsync(parent_fd)
        except OSError:
            pass
    except NativeCodexError:
        if temporary_created and parent_fd is not None:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        raise
    except OSError as exc:
        if temporary_created and parent_fd is not None:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        raise NativeCodexError("native authority path is unsafe or unavailable") from exc
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()


def _config_path() -> Path:
    return codex_home() / "config.toml"


def _read_config() -> tuple[dict[str, Any], bytes | None]:
    path = _config_path()
    if not path.exists() and not path.is_symlink():
        return {}, None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise NativeCodexError("Codex config is not an unlinked regular file")
    try:
        content = path.read_bytes()
        payload = tomllib.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise NativeCodexError("Codex config is malformed or unreadable") from exc
    if not isinstance(payload, dict):
        raise NativeCodexError("Codex config must contain a TOML table")
    return payload, content


def _target_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    containers: dict[str, dict[str, Any]] = {}
    for table in ("marketplaces", "plugins", "mcp_servers"):
        raw = payload.get(table)
        if raw is not None and not isinstance(raw, dict):
            raise NativeCodexError(f"Codex config {table} has an unsupported shape")
        containers[table] = raw or {}
    marketplaces = containers["marketplaces"]
    plugins = containers["plugins"]
    servers = containers["mcp_servers"]
    for label, value in (
        ("marketplace", marketplaces.get(MARKETPLACE)),
        ("plugin", plugins.get(PLUGIN_ID)),
        ("MCP", servers.get("pcodex")),
    ):
        if value is not None and not isinstance(value, dict):
            raise NativeCodexError(f"Codex {label} registration has an unsupported shape")
    return {
        "codex_marketplace": marketplaces.get(MARKETPLACE),
        "codex_plugin_enable": plugins.get(PLUGIN_ID),
        "codex_mcp": servers.get("pcodex"),
    }


def _without_targets(payload: Mapping[str, Any]) -> dict[str, Any]:
    copy = json.loads(json.dumps(payload))
    for table, key in (("marketplaces", MARKETPLACE), ("plugins", PLUGIN_ID), ("mcp_servers", "pcodex")):
        container = copy.get(table)
        if isinstance(container, dict):
            container.pop(key, None)
            if not container:
                copy.pop(table, None)
    return copy


def _tree_hashes(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise NativeCodexError("Codex plugin cache root is not a regular directory")
    result: dict[str, str] = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in list(directory_names):
            candidate = current / name
            if candidate.is_symlink():
                raise NativeCodexError("Codex plugin cache contains a symlink")
        for name in file_names:
            path = current / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise NativeCodexError("Codex plugin cache contains an alternate filesystem object")
            result[path.relative_to(root).as_posix()] = _hash_bytes(path.read_bytes())
    return dict(sorted(result.items()))


def _run_codex(*args: str) -> dict[str, Any]:
    executable = shutil.which("codex")
    if executable is None:
        raise NativeCodexError("Codex CLI is unavailable")
    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home())
    completed = subprocess.run(
        [executable, *args], text=True, capture_output=True, check=False,
        timeout=60, env=env,
    )
    if completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise NativeCodexError(f"Codex command failed ({completed.returncode}): {message[:500]}")
    if "--json" not in args:
        return {"stdout": completed.stdout.strip()}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise NativeCodexError("Codex returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise NativeCodexError("Codex JSON result was not an object")
    return payload


def _receipt(
    *, authority_key: str, kind: str, key: str, ownership_id: str, installed: Any,
    managed_fields: list[str], preserved_fields: list[str],
) -> dict[str, Any]:
    return {
        "registration_type": kind,
        "registration_scope": str(_config_path()),
        "registration_key": key,
        "preexisting_value_hash": None,
        "installed_value_hash": _registration_hash(authority_key, installed),
        "current_value_hash": _registration_hash(authority_key, installed),
        "ownership_id": ownership_id,
        "source_plugin_version": __version__,
        "target_plugin_version": __version__,
        "managed_fields": managed_fields,
        "preserved_fields": preserved_fields,
        "user_modified": False,
        "conflict_state": None,
        "cleanup_policy": "remove_only_if_exact_value_matches",
        "repair_policy": "restore_only_if_receipt_and_unrelated_state_match",
    }


def preview(*, marketplace_root: Path, with_mcp: bool) -> dict[str, Any]:
    marketplace_root = marketplace_root.resolve()
    try:
        state = _load_state(marketplace_root)
        journal = _load_journal(marketplace_root)
        payload, _ = _read_config()
        targets = _target_values(payload)
    except NativeCodexError as exc:
        return {"readiness": "BLOCKED", "conflicts": [{"reason": str(exc)}], "writes_performed": False}
    if journal is not None:
        return {"readiness": "BLOCKED", "conflicts": [{"reason": "interrupted_native_operation"}], "writes_performed": False}
    if state is not None:
        if bool(state["with_mcp"]) != with_mcp:
            return {"readiness": "BLOCKED", "conflicts": [{"reason": "mcp_mode_change_requires_uninstall"}], "writes_performed": False}
        current = status(marketplace_root)
        conflicts = list(current.get("conflicts", []))
        if current["readiness"] != "READY" and not conflicts:
            conflicts.append({"reason": "native_lifecycle_requires_repair"})
        return {
            "schema_version": "pcodex.codex-native-plan.v1",
            "readiness": current["readiness"], "codex_home": str(codex_home()),
            "marketplace_root": str(marketplace_root), "planned_registrations": [],
            "optional_mcp": {"authorized": with_mcp, "would_register": False},
            "conflicts": conflicts, "preserved_unrelated_state": True,
            "writes_performed": False,
        }
    conflicts = [{"registration": key, "reason": "unknown_owner"} for key, value in targets.items() if value is not None]
    return {
        "schema_version": "pcodex.codex-native-plan.v1",
        "readiness": "BLOCKED" if conflicts else "NEEDS_ACTION",
        "codex_home": str(codex_home()),
        "marketplace_root": str(marketplace_root.resolve()),
        "planned_registrations": ["codex_marketplace", "codex_plugin_enable"] + (["codex_mcp"] if with_mcp else []),
        "optional_mcp": {"authorized": with_mcp, "would_register": with_mcp},
        "conflicts": conflicts,
        "preserved_unrelated_state": True,
        "writes_performed": False,
    }


def _load_state(workspace: Path) -> dict[str, Any] | None:
    path = workspace / STATE_RELATIVE
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise NativeCodexError("native Codex authority is not an unlinked regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeCodexError("native Codex authority is malformed") from exc
    required = {
        "schema_version", "ownership_id", "plugin_version", "codex_home", "config_path",
        "config_preexisting_hash", "with_mcp", "workspace", "registrations", "cache",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != STATE_SCHEMA:
        raise NativeCodexError("native Codex authority is malformed or future-versioned")
    if (
        value.get("plugin_version") != __version__
        or value.get("codex_home") != str(codex_home())
        or value.get("config_path") != str(_config_path())
        or value.get("workspace") != str(workspace.resolve())
        or not isinstance(value.get("with_mcp"), bool)
    ):
        raise NativeCodexError("native Codex authority belongs to another version or Codex home")
    if not isinstance(value.get("ownership_id"), str) or re.fullmatch(r"[0-9a-f-]{36}", value["ownership_id"]) is None:
        raise NativeCodexError("native Codex ownership identity is invalid")
    before_hash = value.get("config_preexisting_hash")
    if before_hash is not None and (not isinstance(before_hash, str) or re.fullmatch(r"[0-9a-f]{64}", before_hash) is None):
        raise NativeCodexError("native Codex preexisting config hash is invalid")
    expected_keys = {"codex_marketplace", "codex_plugin_enable"} | ({"codex_mcp"} if value.get("with_mcp") else set())
    registrations = value.get("registrations")
    if not isinstance(registrations, dict) or set(registrations) != expected_keys:
        raise NativeCodexError("native Codex registration set is invalid")
    receipt_required = {
        "registration_type", "registration_scope", "registration_key", "preexisting_value_hash",
        "installed_value_hash", "current_value_hash", "ownership_id", "source_plugin_version",
        "target_plugin_version", "managed_fields", "preserved_fields", "user_modified",
        "conflict_state", "cleanup_policy", "repair_policy",
    }
    receipt_allowed = receipt_required | {"disabled_value_hash"}
    workspace_value = str(workspace.resolve())
    expected_installed_values: dict[str, Any] = {
        "codex_marketplace": {
            "source": workspace_value,
            "source_type": "local",
        },
        "codex_plugin_enable": {"enabled": True},
    }
    if value.get("with_mcp"):
        expected_installed_values["codex_mcp"] = {
            "command": str(Path(sys.executable).resolve()),
            "args": ["-m", "premode.pcodex_bootstrap", "mcp-server"],
            "env": {"PCODEX_WORKSPACE": workspace_value},
        }
    expected_semantics = {
        "codex_marketplace": {
            "registration_type": "codex_marketplace_source",
            "registration_key": MARKETPLACE,
            "managed_fields": [f"marketplaces.{MARKETPLACE}"],
            "preserved_fields": [f"marketplaces.{MARKETPLACE}.last_updated", "all_other_codex_configuration"],
            "disabled_value": None,
        },
        "codex_plugin_enable": {
            "registration_type": "codex_plugin_enable_state",
            "registration_key": PLUGIN_ID,
            "managed_fields": [f"plugins.{PLUGIN_ID}"],
            "preserved_fields": ["all_other_codex_configuration"],
            "disabled_value": {"enabled": False},
        },
        "codex_mcp": {
            "registration_type": "codex_mcp_server",
            "registration_key": "pcodex",
            "managed_fields": ["mcp_servers.pcodex"],
            "preserved_fields": ["all_other_mcp_servers", "all_other_codex_configuration"],
            "disabled_value": None,
        },
    }
    for authority_key, receipt in registrations.items():
        if not isinstance(receipt, dict) or (set(receipt) != receipt_required and set(receipt) != receipt_allowed):
            raise NativeCodexError("native Codex registration authority is malformed")
        semantics = expected_semantics[authority_key]
        expected_installed_hash = _registration_hash(authority_key, expected_installed_values[authority_key])
        expected_disabled_hash = (
            _registration_hash(authority_key, semantics["disabled_value"])
            if authority_key != "codex_marketplace" else None
        )
        if (
            receipt.get("ownership_id") != value["ownership_id"]
            or receipt.get("registration_scope") != str(_config_path())
            or receipt.get("registration_type") != semantics["registration_type"]
            or receipt.get("registration_key") != semantics["registration_key"]
            or receipt.get("source_plugin_version") != __version__
            or receipt.get("target_plugin_version") != __version__
            or receipt.get("preexisting_value_hash") is not None
            or receipt.get("installed_value_hash") != expected_installed_hash
            or receipt.get("current_value_hash") not in {expected_installed_hash, expected_disabled_hash}
            or receipt.get("managed_fields") != semantics["managed_fields"]
            or receipt.get("preserved_fields") != semantics["preserved_fields"]
            or receipt.get("user_modified") is not False
            or receipt.get("conflict_state") is not None
            or receipt.get("cleanup_policy") != "remove_only_if_exact_value_matches"
            or receipt.get("repair_policy") != "restore_only_if_receipt_and_unrelated_state_match"
        ):
            raise NativeCodexError("native Codex registration authority is incompatible")
        disabled_hash = receipt.get("disabled_value_hash")
        if disabled_hash is not None and disabled_hash != expected_disabled_hash:
            raise NativeCodexError("native Codex disabled registration hash is invalid")
    cache = value.get("cache")
    cache_required = {"registration_type", "path", "files", "installed_value_hash", "ownership_id", "cleanup_policy", "repair_policy"}
    if not isinstance(cache, dict) or set(cache) != cache_required or cache.get("ownership_id") != value["ownership_id"]:
        raise NativeCodexError("native Codex cache authority is malformed")
    try:
        cache_path = Path(str(cache["path"])).resolve()
        cache_path.relative_to(codex_home() / "plugins" / "cache")
    except (KeyError, ValueError):
        raise NativeCodexError("native Codex cache path is outside the Codex cache root")
    files = cache.get("files")
    if not isinstance(files, dict) or not files:
        raise NativeCodexError("native Codex cache file authority is empty")
    for relative, digest in files.items():
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
            raise NativeCodexError("native Codex cache authority contains an unsafe path")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise NativeCodexError("native Codex cache authority contains an invalid hash")
    if cache.get("installed_value_hash") != _hash_json(files):
        raise NativeCodexError("native Codex cache authority hash is invalid")
    return value


def _load_journal(workspace: Path) -> dict[str, Any] | None:
    path = workspace / JOURNAL_RELATIVE
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise NativeCodexError("native Codex operation journal is not an unlinked regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeCodexError("native Codex operation journal is malformed") from exc
    required = {
        "schema_version", "operation", "ownership_id", "plugin_version", "with_mcp",
        "workspace", "marketplace_root", "codex_home", "config_path",
        "config_preexisting_hash", "unrelated_value_hash", "phase",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != JOURNAL_SCHEMA:
        raise NativeCodexError("native Codex operation journal is malformed or future-versioned")
    if (
        value.get("plugin_version") != __version__
        or value.get("workspace") != str(workspace.resolve())
        or value.get("marketplace_root") != str(workspace.resolve())
        or value.get("codex_home") != str(codex_home())
        or value.get("config_path") != str(_config_path())
        or not isinstance(value.get("with_mcp"), bool)
        or not isinstance(value.get("ownership_id"), str)
        or re.fullmatch(r"[0-9a-f-]{36}", value["ownership_id"]) is None
    ):
        raise NativeCodexError("native Codex operation journal has incompatible authority")
    before_hash = value.get("config_preexisting_hash")
    if before_hash is not None and (not isinstance(before_hash, str) or re.fullmatch(r"[0-9a-f]{64}", before_hash) is None):
        raise NativeCodexError("native Codex operation journal has an invalid preexisting hash")
    if not isinstance(value.get("unrelated_value_hash"), str) or re.fullmatch(r"[0-9a-f]{64}", value["unrelated_value_hash"]) is None:
        raise NativeCodexError("native Codex operation journal has an invalid unrelated-value hash")
    allowed_phases = {
        "install": {"started", "marketplace_registered", "plugin_registered", "mcp_registered", "manual_recovery_required"},
        "disable": {"started", "plugin_disabled", "mcp_disabled"},
        "uninstall": {"started", "plugin_removed", "mcp_removed", "marketplace_removed"},
    }
    if value.get("operation") not in allowed_phases or value.get("phase") not in allowed_phases[value["operation"]]:
        raise NativeCodexError("native Codex operation journal has an invalid operation phase")
    return value


def _write_state(
    workspace: Path, *, ownership_id: str, with_mcp: bool,
    before_hash: str | None, targets: Mapping[str, Any], cache_path: Path,
) -> dict[str, Any]:
    registrations = {
        "codex_marketplace": _receipt(
            authority_key="codex_marketplace", kind="codex_marketplace_source", key=MARKETPLACE, ownership_id=ownership_id,
            installed=targets["codex_marketplace"], managed_fields=[f"marketplaces.{MARKETPLACE}"],
            preserved_fields=[f"marketplaces.{MARKETPLACE}.last_updated", "all_other_codex_configuration"],
        ),
        "codex_plugin_enable": _receipt(
            authority_key="codex_plugin_enable", kind="codex_plugin_enable_state", key=PLUGIN_ID, ownership_id=ownership_id,
            installed=targets["codex_plugin_enable"], managed_fields=[f"plugins.{PLUGIN_ID}"],
            preserved_fields=["all_other_codex_configuration"],
        ),
    }
    if with_mcp:
        registrations["codex_mcp"] = _receipt(
            authority_key="codex_mcp", kind="codex_mcp_server", key="pcodex", ownership_id=ownership_id,
            installed=targets["codex_mcp"], managed_fields=["mcp_servers.pcodex"],
            preserved_fields=["all_other_mcp_servers", "all_other_codex_configuration"],
        )
    files = _tree_hashes(cache_path)
    state = {
        "schema_version": STATE_SCHEMA,
        "ownership_id": ownership_id,
        "plugin_version": __version__,
        "codex_home": str(codex_home()),
        "config_path": str(_config_path()),
        "config_preexisting_hash": before_hash,
        "with_mcp": with_mcp,
        "workspace": str(workspace.resolve()),
        "registrations": registrations,
        "cache": {
            "registration_type": "codex_plugin_cache",
            "path": str(cache_path),
            "files": files,
            "installed_value_hash": _hash_json(files),
            "ownership_id": ownership_id,
            "cleanup_policy": "remove_via_codex_only_if_exact_tree_matches",
            "repair_policy": "restore_via_codex_only_if_missing",
        },
    }
    _atomic_json(workspace / STATE_RELATIVE, state)
    return state


def apply(
    workspace: Path, *, marketplace_root: Path, ownership_id: str,
    with_mcp: bool, inject: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    existing = _load_state(workspace)
    if existing is not None:
        current = status(workspace)
        if current["readiness"] == "READY":
            return {"status": "unchanged", "writes_performed": False, "receipt": STATE_RELATIVE.as_posix()}
        return {"status": "blocked", "reason": current.get("reason"), "writes_performed": False}
    plan = preview(marketplace_root=marketplace_root, with_mcp=with_mcp)
    if plan["conflicts"]:
        return {"status": "blocked", "conflicts": plan["conflicts"], "writes_performed": False}
    before, before_bytes = _read_config()
    journal = {
        "schema_version": JOURNAL_SCHEMA, "operation": "install", "ownership_id": ownership_id,
        "plugin_version": __version__, "with_mcp": with_mcp,
        "workspace": str(workspace), "marketplace_root": str(marketplace_root.resolve()),
        "codex_home": str(codex_home()), "config_path": str(_config_path()),
        "config_preexisting_hash": _hash_bytes(before_bytes) if before_bytes is not None else None,
        "unrelated_value_hash": _hash_json(_without_targets(before)),
        "phase": "started",
    }
    _atomic_json(workspace / JOURNAL_RELATIVE, journal)
    added = _run_codex("plugin", "marketplace", "add", str(marketplace_root.resolve()), "--json")
    if added.get("marketplaceName") != MARKETPLACE or Path(str(added.get("installedRoot"))).resolve() != marketplace_root.resolve():
        raise NativeCodexError("Codex registered an unexpected marketplace")
    journal["phase"] = "marketplace_registered"
    _atomic_json(workspace / JOURNAL_RELATIVE, journal)
    if inject:
        inject("codex_configuration_update")
    installed = _run_codex("plugin", "add", PLUGIN_ID, "--json")
    if installed.get("pluginId") != PLUGIN_ID or installed.get("version") is None:
        raise NativeCodexError("Codex installed an unexpected plugin")
    cache_path = Path(str(installed.get("installedPath"))).resolve()
    journal["phase"] = "plugin_registered"
    _atomic_json(workspace / JOURNAL_RELATIVE, journal)
    if with_mcp:
        _run_codex(
            "mcp", "add", "pcodex", "--env", f"PCODEX_WORKSPACE={workspace}", "--",
            str(Path(sys.executable).resolve()), "-m", "premode.pcodex_bootstrap", "mcp-server",
        )
        journal["phase"] = "mcp_registered"
        _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        if inject:
            inject("mcp_registration_update")
    after, after_bytes = _read_config()
    targets = _target_values(after)
    if targets["codex_marketplace"] is None or targets["codex_plugin_enable"] != {"enabled": True}:
        raise NativeCodexError("Codex native registration is incomplete")
    if with_mcp and targets["codex_mcp"] is None:
        raise NativeCodexError("Codex MCP registration is incomplete")
    if not with_mcp and targets["codex_mcp"] is not None:
        raise NativeCodexError("Codex created an unauthorized MCP registration")
    if _without_targets(before) != _without_targets(after):
        journal["phase"] = "manual_recovery_required"
        _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        raise NativeCodexError("Codex changed unrelated configuration values")
    if before_bytes is not None and (after_bytes is None or not after_bytes.startswith(before_bytes)):
        journal["phase"] = "manual_recovery_required"
        _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        raise NativeCodexError("Codex reformatted unrelated configuration bytes")
    state = _write_state(
        workspace, ownership_id=ownership_id, with_mcp=with_mcp,
        before_hash=journal["config_preexisting_hash"], targets=targets, cache_path=cache_path,
    )
    (workspace / JOURNAL_RELATIVE).unlink()
    return {
        "status": "registered", "writes_performed": True,
        "receipt": STATE_RELATIVE.as_posix(), "cache_path": str(cache_path),
        "registration_receipts": sorted(state["registrations"]),
    }


def status(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    try:
        journal = _load_journal(workspace)
        state = _load_state(workspace)
        config, _ = _read_config()
        targets = _target_values(config)
    except NativeCodexError as exc:
        return {"readiness": "BLOCKED", "reason": "corrupt_or_future_native_authority", "error": str(exc), "writes_performed": False}
    if journal is not None:
        return {"readiness": "BLOCKED", "reason": "interrupted_native_operation", "operation": journal["operation"], "phase": journal["phase"], "writes_performed": False}
    if state is None:
        unknown = [key for key, value in targets.items() if value is not None]
        return {
            "readiness": "BLOCKED" if unknown else "NEEDS_ACTION",
            "reason": "unknown_native_registration" if unknown else "native_registration_absent",
            "conflicts": unknown, "writes_performed": False,
        }
    if (workspace / JOURNAL_RELATIVE).exists():
        return {"readiness": "BLOCKED", "reason": "interrupted_native_operation", "writes_performed": False}
    conflicts: list[dict[str, str]] = []
    for key, receipt in state["registrations"].items():
        value = targets[key]
        allowed = {receipt["installed_value_hash"], receipt.get("disabled_value_hash")}
        if value is None:
            if _registration_hash(key, None) not in allowed:
                conflicts.append({"registration": key, "reason": "missing"})
        elif _registration_hash(key, value) not in allowed:
            conflicts.append({"registration": key, "reason": "user_modified"})
    if not state["with_mcp"] and targets["codex_mcp"] is not None:
        conflicts.append({"registration": "codex_mcp", "reason": "unknown_owner"})
    cache = state["cache"]
    cache_path = Path(cache["path"])
    if not cache_path.exists() and not cache_path.is_symlink():
        conflicts.append({"registration": "codex_cache", "reason": "missing"})
    else:
        try:
            current_files = _tree_hashes(cache_path)
        except (NativeCodexError, OSError) as exc:
            conflicts.append({"registration": "codex_cache", "reason": str(exc)})
        else:
            expected_files = cache["files"]
            if current_files != expected_files and all(
                expected_files.get(name) == digest for name, digest in current_files.items()
            ) and set(current_files) < set(expected_files):
                conflicts.append({"registration": "codex_cache", "reason": "missing"})
            elif current_files != expected_files:
                conflicts.append({"registration": "codex_cache", "reason": "user_modified"})
    enabled = targets["codex_plugin_enable"] == {"enabled": True}
    only_missing = bool(conflicts) and all(item["reason"] == "missing" for item in conflicts)
    readiness = "READY" if not conflicts and enabled else ("NEEDS_ACTION" if not conflicts or only_missing else "BLOCKED")
    return {
        "readiness": readiness,
        "reason": "healthy" if readiness == "READY" else ("disabled" if not conflicts else "conflict"),
        "enabled": enabled,
        "optional_mcp": (
            "healthy" if state["with_mcp"] and enabled and targets["codex_mcp"] is not None and not conflicts
            else "disabled" if not state["with_mcp"] or (not enabled and targets["codex_mcp"] is None)
            else "conflict"
        ),
        "conflicts": conflicts, "writes_performed": False,
    }


def repair_preview(workspace: Path) -> dict[str, Any]:
    """Return an exact, receipt-bound native repair plan without writes."""
    workspace = workspace.resolve()
    try:
        state = _load_state(workspace)
    except NativeCodexError as exc:
        return {
            "schema_version": "pcodex.codex-native-repair-preview.v1",
            "readiness": "BLOCKED", "will_restore": [],
            "conflicts": [{"reason": str(exc)}], "writes_performed": False,
        }
    current = status(workspace)
    if state is None:
        return {
            "schema_version": "pcodex.codex-native-repair-preview.v1",
            "readiness": current["readiness"], "will_restore": [],
            "conflicts": current.get("conflicts", [{"reason": current.get("reason")}]),
            "writes_performed": False,
        }
    if current["readiness"] == "BLOCKED":
        return {
            "schema_version": "pcodex.codex-native-repair-preview.v1",
            "readiness": "BLOCKED", "will_restore": [],
            "conflicts": current.get("conflicts", [{"reason": current.get("reason")}]),
            "writes_performed": False,
        }
    will_restore = [
        {
            "path": str(state["cache"]["path"]) if item.get("registration") == "codex_cache"
            else f"{state['registrations'][item['registration']]['registration_scope']}#{item['registration']}",
            "authority": "native_registration_receipt",
        }
        for item in current.get("conflicts", [])
        if item.get("reason") == "missing"
    ]
    if not current.get("enabled"):
        receipt = state["registrations"]["codex_plugin_enable"]
        will_restore.append({
            "path": f"{receipt['registration_scope']}#codex_plugin_enable",
            "authority": "native_registration_receipt",
        })
    return {
        "schema_version": "pcodex.codex-native-repair-preview.v1",
        "readiness": "NEEDS_ACTION" if will_restore else "READY",
        "will_restore": will_restore, "conflicts": [], "writes_performed": False,
    }


def uninstall_preview(workspace: Path) -> dict[str, Any]:
    """Return every receipt-proven native removal target without writes."""
    workspace = workspace.resolve()
    try:
        state = _load_state(workspace)
    except NativeCodexError as exc:
        return {
            "schema_version": "pcodex.codex-native-uninstall-preview.v1",
            "readiness": "BLOCKED", "already_absent": False, "will_remove": [],
            "conflicts": [{"reason": str(exc)}], "writes_performed": False,
        }
    current = status(workspace)
    if state is None:
        return {
            "schema_version": "pcodex.codex-native-uninstall-preview.v1",
            "readiness": current["readiness"], "already_absent": current["readiness"] == "NEEDS_ACTION",
            "will_remove": [], "conflicts": current.get("conflicts", []), "writes_performed": False,
        }
    if current["readiness"] == "BLOCKED":
        return {
            "schema_version": "pcodex.codex-native-uninstall-preview.v1",
            "readiness": "BLOCKED", "already_absent": False, "will_remove": [],
            "conflicts": current.get("conflicts", [{"reason": current.get("reason")}]),
            "writes_performed": False,
        }
    will_remove = [
        {
            "path": f"{receipt['registration_scope']}#{key}",
            "authority": "native_registration_receipt",
        }
        for key, receipt in sorted(state["registrations"].items())
    ]
    will_remove.extend([
        {"path": str(state["cache"]["path"]), "authority": "native_cache_receipt"},
        {"path": STATE_RELATIVE.as_posix(), "authority": "native_state_receipt"},
    ])
    return {
        "schema_version": "pcodex.codex-native-uninstall-preview.v1",
        "readiness": "READY", "already_absent": False,
        "will_remove": will_remove, "conflicts": [], "writes_performed": False,
    }


def _patch_enabled(workspace: Path, state: dict[str, Any], enabled: bool) -> None:
    path = _config_path()
    before_payload, before_bytes = _read_config()
    assert before_bytes is not None
    targets = _target_values(before_payload)
    receipt = state["registrations"]["codex_plugin_enable"]
    if _registration_hash("codex_plugin_enable", targets["codex_plugin_enable"]) not in {receipt["installed_value_hash"], receipt.get("disabled_value_hash")}:
        raise NativeCodexError("Codex plugin enable value was modified")
    text = before_bytes.decode("utf-8")
    header = re.compile(r'^\[plugins\."pcodex@local-premode-marketplace"\][ \t]*$', re.MULTILINE)
    match = header.search(text)
    if match is None:
        raise NativeCodexError("Codex plugin enable table is missing")
    next_table = re.search(r"^\[", text[match.end():], re.MULTILINE)
    end = match.end() + (next_table.start() if next_table else len(text[match.end():]))
    block = text[match.end():end]
    desired = "true" if enabled else "false"
    replaced, count = re.subn(r"(?m)^(enabled[ \t]*=[ \t]*)(?:true|false)([ \t]*)$", rf"\g<1>{desired}\g<2>", block)
    if count != 1:
        raise NativeCodexError("Codex plugin enable table has an unsupported shape")
    after_bytes = (text[:match.end()] + replaced + text[end:]).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        stat.S_IMODE(path.stat().st_mode),
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(after_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != before_bytes:
            raise NativeCodexError("Codex config changed concurrently before enable commit")
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    after_payload, _ = _read_config()
    if _without_targets(before_payload) != _without_targets(after_payload):
        raise NativeCodexError("native enable edit changed unrelated configuration")


def disable(workspace: Path, *, inject: Callable[[str], None] | None = None) -> dict[str, Any]:
    workspace = workspace.resolve()
    try:
        state = _load_state(workspace)
        if state is None:
            raise NativeCodexError("native Codex authority is absent")
        current = status(workspace)
        if current["readiness"] == "BLOCKED":
            return {"status": "blocked", "reason": current["reason"], "writes_performed": False}
        if not current.get("enabled"):
            return {"status": "disabled", "writes_performed": False, "idempotent": True}
        config, config_bytes = _read_config()
        journal = {
            "schema_version": JOURNAL_SCHEMA, "operation": "disable", "ownership_id": state["ownership_id"],
            "plugin_version": __version__, "with_mcp": state["with_mcp"], "workspace": str(workspace),
            "marketplace_root": str(workspace),
            "codex_home": str(codex_home()), "config_path": str(_config_path()),
            "config_preexisting_hash": _hash_bytes(config_bytes) if config_bytes is not None else None,
            "unrelated_value_hash": _hash_json(_without_targets(config)), "phase": "started",
        }
        _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        _patch_enabled(workspace, state, False)
        journal["phase"] = "plugin_disabled"
        _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        if state["with_mcp"]:
            _run_codex("mcp", "remove", "pcodex")
            journal["phase"] = "mcp_disabled"
            _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        if inject:
            inject("codex_disable_update")
        config, _ = _read_config()
        disabled_value = _target_values(config)["codex_plugin_enable"]
        receipt = state["registrations"]["codex_plugin_enable"]
        receipt["disabled_value_hash"] = _registration_hash("codex_plugin_enable", disabled_value)
        receipt["current_value_hash"] = receipt["disabled_value_hash"]
        if state["with_mcp"]:
            mcp_receipt = state["registrations"]["codex_mcp"]
            mcp_receipt["disabled_value_hash"] = _registration_hash("codex_mcp", None)
            mcp_receipt["current_value_hash"] = mcp_receipt["disabled_value_hash"]
        _atomic_json(workspace / STATE_RELATIVE, state)
        (workspace / JOURNAL_RELATIVE).unlink()
        return {"status": "disabled", "writes_performed": True}
    except NativeCodexError as exc:
        return {"status": "blocked", "reason": str(exc), "writes_performed": False}


def _complete_native_registration(workspace: Path, journal: Mapping[str, Any]) -> dict[str, Any]:
    if journal.get("phase") == "manual_recovery_required":
        raise NativeCodexError("native Codex operation requires manual configuration recovery")
    before, _ = _read_config()
    targets = _target_values(before)
    marketplace_root = Path(str(journal["marketplace_root"]))
    if targets["codex_marketplace"] is None:
        _run_codex("plugin", "marketplace", "add", str(marketplace_root), "--json")
    installed = _run_codex("plugin", "add", PLUGIN_ID, "--json")
    cache_path = Path(str(installed.get("installedPath"))).resolve()
    if journal["with_mcp"] and _target_values(_read_config()[0])["codex_mcp"] is None:
        _run_codex(
            "mcp", "add", "pcodex", "--env", f"PCODEX_WORKSPACE={workspace}", "--",
            str(Path(sys.executable).resolve()), "-m", "premode.pcodex_bootstrap", "mcp-server",
        )
    after, _ = _read_config()
    if _hash_json(_without_targets(after)) != journal["unrelated_value_hash"]:
        raise NativeCodexError("native recovery detected unrelated configuration changes")
    targets = _target_values(after)
    state = _write_state(
        workspace, ownership_id=str(journal["ownership_id"]), with_mcp=bool(journal["with_mcp"]),
        before_hash=journal["config_preexisting_hash"], targets=targets, cache_path=cache_path,
    )
    (workspace / JOURNAL_RELATIVE).unlink()
    return state


def repair(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    try:
        journal = _load_journal(workspace)
        state = _load_state(workspace)
        if journal is not None:
            if state is not None and (
                journal["ownership_id"] != state["ownership_id"]
                or journal["with_mcp"] != state["with_mcp"]
            ):
                raise NativeCodexError("native operation journal does not match current authority")
            if state is None and journal["operation"] in {"disable", "uninstall"}:
                raise NativeCodexError("native mutation journal has no matching authority")
            if journal["operation"] == "disable" and state is not None:
                config, _ = _read_config()
                interrupted_targets = _target_values(config)
                disabled_value = interrupted_targets["codex_plugin_enable"]
                if disabled_value != {"enabled": False}:
                    raise NativeCodexError("interrupted disable has an unexpected plugin state")
                receipt = state["registrations"]["codex_plugin_enable"]
                receipt["disabled_value_hash"] = _registration_hash("codex_plugin_enable", disabled_value)
                if state["with_mcp"] and interrupted_targets["codex_mcp"] is None:
                    mcp_receipt = state["registrations"]["codex_mcp"]
                    mcp_receipt["disabled_value_hash"] = _registration_hash("codex_mcp", None)
                    mcp_receipt["current_value_hash"] = mcp_receipt["disabled_value_hash"]
                    _run_codex(
                        "mcp", "add", "pcodex", "--env", f"PCODEX_WORKSPACE={workspace}", "--",
                        str(Path(sys.executable).resolve()), "-m", "premode.pcodex_bootstrap", "mcp-server",
                    )
                    mcp_receipt["current_value_hash"] = mcp_receipt["installed_value_hash"]
                _patch_enabled(workspace, state, True)
                receipt["current_value_hash"] = receipt["installed_value_hash"]
                _atomic_json(workspace / STATE_RELATIVE, state)
                (workspace / JOURNAL_RELATIVE).unlink()
                return {"status": "recovered", "operation": "disable", "writes_performed": True}
            if journal["operation"] in {"install", "uninstall"}:
                _complete_native_registration(workspace, journal)
                return {"status": "recovered", "operation": journal["operation"], "writes_performed": True}
            raise NativeCodexError("native operation journal is not recoverable")
        if state is None:
            raise NativeCodexError("native Codex authority is absent")
        current = status(workspace)
        if current["readiness"] == "BLOCKED":
            return {"status": "blocked", "reason": current["reason"], "conflicts": current.get("conflicts", []), "writes_performed": False}
        if current["readiness"] == "READY":
            return {"status": "healthy", "writes_performed": False}
        config, _ = _read_config()
        unrelated_before = _without_targets(config)
        targets = _target_values(config)
        missing = {item["registration"] for item in current.get("conflicts", []) if item["reason"] == "missing"}
        if "codex_marketplace" in missing:
            _run_codex("plugin", "marketplace", "add", state["workspace"], "--json")
        installed: dict[str, Any] | None = None
        if {"codex_plugin_enable", "codex_cache"} & missing:
            installed = _run_codex("plugin", "add", PLUGIN_ID, "--json")
        if "codex_mcp" in missing:
            _run_codex(
                "mcp", "add", "pcodex", "--env", f"PCODEX_WORKSPACE={workspace}", "--",
                str(Path(sys.executable).resolve()), "-m", "premode.pcodex_bootstrap", "mcp-server",
            )
        elif state["with_mcp"] and targets["codex_mcp"] is None:
            _run_codex(
                "mcp", "add", "pcodex", "--env", f"PCODEX_WORKSPACE={workspace}", "--",
                str(Path(sys.executable).resolve()), "-m", "premode.pcodex_bootstrap", "mcp-server",
            )
        config, _ = _read_config()
        targets = _target_values(config)
        if targets["codex_plugin_enable"] == {"enabled": False}:
            _patch_enabled(workspace, state, True)
            config, _ = _read_config()
            targets = _target_values(config)
        if _without_targets(config) != unrelated_before:
            raise NativeCodexError("native repair changed unrelated configuration")
        for key, receipt in state["registrations"].items():
            if _registration_hash(key, targets[key]) != receipt["installed_value_hash"]:
                raise NativeCodexError(f"native repair did not exactly restore {key}")
            receipt["current_value_hash"] = receipt["installed_value_hash"]
        if installed is not None:
            cache_path = Path(str(installed.get("installedPath"))).resolve()
            files = _tree_hashes(cache_path)
            if str(cache_path) != state["cache"]["path"] or files != state["cache"]["files"]:
                raise NativeCodexError("native repair did not exactly restore the owned cache")
        _atomic_json(workspace / STATE_RELATIVE, state)
        return {"status": "repaired", "writes_performed": True}
    except NativeCodexError as exc:
        return {"status": "blocked", "reason": str(exc), "writes_performed": False}


def uninstall(workspace: Path, *, inject: Callable[[str], None] | None = None) -> dict[str, Any]:
    workspace = workspace.resolve()
    try:
        state = _load_state(workspace)
        if state is None:
            return {"status": "absent", "writes_performed": False}
        current = status(workspace)
        if current["readiness"] == "BLOCKED":
            return {"status": "blocked", "reason": current["reason"], "conflicts": current.get("conflicts", []), "writes_performed": False}
        before, before_bytes = _read_config()
        journal = {
            "schema_version": JOURNAL_SCHEMA, "operation": "uninstall", "ownership_id": state["ownership_id"],
            "plugin_version": __version__, "with_mcp": state["with_mcp"], "workspace": str(workspace),
            "marketplace_root": state["workspace"],
            "codex_home": str(codex_home()), "config_path": str(_config_path()),
            "config_preexisting_hash": state["config_preexisting_hash"],
            "unrelated_value_hash": _hash_json(_without_targets(before)), "phase": "started",
        }
        _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        _run_codex("plugin", "remove", PLUGIN_ID, "--json")
        journal["phase"] = "plugin_removed"
        _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        if inject:
            inject("codex_uninstall_plugin_update")
        if state["with_mcp"] and _target_values(_read_config()[0])["codex_mcp"] is not None:
            _run_codex("mcp", "remove", "pcodex")
            journal["phase"] = "mcp_removed"
            _atomic_json(workspace / JOURNAL_RELATIVE, journal)
            if inject:
                inject("codex_uninstall_mcp_update")
        _run_codex("plugin", "marketplace", "remove", MARKETPLACE, "--json")
        journal["phase"] = "marketplace_removed"
        _atomic_json(workspace / JOURNAL_RELATIVE, journal)
        if inject:
            inject("codex_uninstall_marketplace_update")
        after, after_bytes = _read_config()
        if any(value is not None for value in _target_values(after).values()):
            raise NativeCodexError("Codex left owned registration values behind")
        if _without_targets(before) != _without_targets(after):
            raise NativeCodexError("Codex uninstall changed unrelated configuration")
        config_path = _config_path()
        if state["config_preexisting_hash"] is not None and (
            after_bytes is None or _hash_bytes(after_bytes) != state["config_preexisting_hash"]
        ):
            raise NativeCodexError("Codex uninstall did not restore the preexisting config bytes")
        if state["config_preexisting_hash"] is None and not after and after_bytes is not None:
            if config_path.read_bytes().strip():
                raise NativeCodexError("installer-created Codex config is not empty")
            config_path.unlink()
        cache_path = Path(state["cache"]["path"])
        if cache_path.exists():
            raise NativeCodexError("Codex left the owned plugin cache behind")
        (workspace / STATE_RELATIVE).unlink()
        (workspace / JOURNAL_RELATIVE).unlink()
        return {"status": "uninstalled", "writes_performed": True}
    except NativeCodexError as exc:
        return {"status": "blocked", "reason": str(exc), "writes_performed": False}
