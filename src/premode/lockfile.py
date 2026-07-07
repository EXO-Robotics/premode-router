from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from . import __version__

LOCKFILE_SCHEMA_VERSION = "premode.lcc.lock.v1"
LOCKFILE_REL_PATH = Path(".premode") / "lcc.lock.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_repo_root(start: Path | str | None = None) -> Path:
    current = Path.cwd() if start is None else Path(start)
    current = current.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def lockfile_path(repo_root: Path | str) -> Path:
    return find_repo_root(repo_root) / LOCKFILE_REL_PATH


def display_path(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def git_branch(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def git_head(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _nullable_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def lock_payload_from_resolver(
    repo_root: Path | str,
    resolved: dict[str, Any],
    *,
    cache_prefix_hash: str | None = None,
) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    return {
        "schema_version": LOCKFILE_SCHEMA_VERSION,
        "lcc_version": __version__,
        "repo_root_hash": sha256_text(str(root.resolve())),
        "git_branch": git_branch(root),
        "git_head": git_head(root),
        "public_mode": _nullable_string(resolved.get("configured_mode") or resolved.get("mode")),
        "effective_state": _nullable_string(resolved.get("effective_state")),
        "plugin_alias": _nullable_string(resolved.get("plugin_alias")),
        "packet_version": _nullable_string(resolved.get("packet_version")),
        "packet_variant": _nullable_string(resolved.get("packet_variant")),
        "packet_strategy": _nullable_string(resolved.get("packet_strategy")),
        "tuning_profile_hash": _nullable_string(resolved.get("tuning_profile_hash")),
        "verify_results_hash": _nullable_string(resolved.get("verify_results_hash")),
        "cache_prefix_hash": _nullable_string(cache_prefix_hash),
        "last_verified_at": _nullable_string(resolved.get("last_verified_at")),
        "stale_reason": _nullable_string(resolved.get("stale_reason")),
        "fallback_reason": _nullable_string(resolved.get("fallback_reason")),
        "safe_passthrough_reason": _nullable_string(resolved.get("safe_passthrough_reason")),
        "updated_at": utc_now(),
    }


def validate_lock_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid LCC lockfile: expected JSON object")
    if payload.get("schema_version") != LOCKFILE_SCHEMA_VERSION:
        raise ValueError("Invalid LCC lockfile: unsupported schema_version")
    required = {
        "schema_version",
        "lcc_version",
        "repo_root_hash",
        "git_branch",
        "git_head",
        "public_mode",
        "effective_state",
        "plugin_alias",
        "packet_version",
        "packet_variant",
        "packet_strategy",
        "tuning_profile_hash",
        "verify_results_hash",
        "cache_prefix_hash",
        "last_verified_at",
        "stale_reason",
        "fallback_reason",
        "safe_passthrough_reason",
        "updated_at",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError("Invalid LCC lockfile: missing " + ", ".join(missing))
    return dict(payload)


def read_lockfile(repo_root: Path | str) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    path = lockfile_path(root)
    if not path.exists():
        return {"status": "missing", "path": display_path(root, path), "valid": False, "payload": None, "error": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validated = validate_lock_payload(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"status": "invalid", "path": display_path(root, path), "valid": False, "payload": None, "error": str(exc)}
    return {"status": "loaded", "path": display_path(root, path), "valid": True, "payload": validated, "error": None}


def write_lockfile(repo_root: Path | str, payload: dict[str, Any]) -> Path:
    root = find_repo_root(repo_root)
    validated = validate_lock_payload(payload)
    path = lockfile_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(validated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def update_lockfile_from_resolver(
    repo_root: Path | str,
    resolved: dict[str, Any],
    *,
    cache_prefix_hash: str | None = None,
) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    payload = lock_payload_from_resolver(root, resolved, cache_prefix_hash=cache_prefix_hash)
    path = write_lockfile(root, payload)
    return {"status": "written", "path": display_path(root, path), "valid": True, "payload": payload, "error": None}
