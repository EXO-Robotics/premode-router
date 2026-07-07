from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import __version__
from .lockfile import display_path, find_repo_root, git_branch, git_head, sha256_text, utc_now

CACHE_MANIFEST_SCHEMA_VERSION = "premode.lcc.cache_manifest.v1"
CACHE_MANIFEST_REL_PATH = Path(".premode") / "out" / "cache_manifest.json"


def cache_manifest_path(repo_root: Path | str) -> Path:
    return find_repo_root(repo_root) / CACHE_MANIFEST_REL_PATH


def _nullable_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _token_estimate(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def build_cache_manifest(repo_root: Path | str, resolved: dict[str, Any], compiled: dict[str, Any]) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    packet = str(compiled.get("packet") or "")
    static_prefix_hash = _nullable_string(compiled.get("cacheable_prefix_sha256"))
    if not static_prefix_hash:
        hashes = compiled.get("packet_hashes") if isinstance(compiled.get("packet_hashes"), dict) else {}
        static_prefix_hash = _nullable_string(hashes.get("cacheable_prefix_sha256"))
    first_1024_hash = sha256_text(packet[:1024]) if packet else None
    metrics = compiled.get("metrics") if isinstance(compiled.get("metrics"), dict) else {}
    profile_hash = _nullable_string(resolved.get("tuning_profile_hash")) or "general"
    repo_hash = sha256_text(str(root.resolve()))
    cache_candidate = bool(static_prefix_hash or first_1024_hash)
    return {
        "schema_version": CACHE_MANIFEST_SCHEMA_VERSION,
        "lcc_version": __version__,
        "repo_root_hash": repo_hash,
        "git_branch": git_branch(root),
        "git_head": git_head(root),
        "public_mode": _nullable_string(resolved.get("configured_mode") or resolved.get("mode")),
        "effective_state": _nullable_string(resolved.get("effective_state")),
        "plugin_alias": _nullable_string(resolved.get("plugin_alias")),
        "packet_version": _nullable_string(resolved.get("packet_version")),
        "packet_variant": _nullable_string(resolved.get("packet_variant")),
        "packet_strategy": _nullable_string(resolved.get("packet_strategy")),
        "static_prefix_hash": static_prefix_hash,
        "first_1024_hash": first_1024_hash,
        "static_prefix_tokens_estimate": _token_estimate(compiled.get("cacheable_prefix_tokens") or metrics.get("cacheable_prefix_tokens")),
        "dynamic_suffix_tokens_estimate": _token_estimate(compiled.get("dynamic_suffix_tokens") or metrics.get("dynamic_suffix_tokens")),
        "total_tokens_estimate": _token_estimate(compiled.get("model_facing_packet_tokens") or metrics.get("packet_total_tokens")),
        "cache_candidate": cache_candidate,
        "cache_break_reason": None if cache_candidate else "prefix_hash_unavailable",
        "provider_hint": {
            "prompt_cache_key": f"repo:{repo_hash}:profile:{profile_hash}",
            "guarantee": "none",
        },
        "created_at": utc_now(),
    }


def validate_cache_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid cache manifest: expected JSON object")
    if payload.get("schema_version") != CACHE_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Invalid cache manifest: unsupported schema_version")
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
        "static_prefix_hash",
        "first_1024_hash",
        "static_prefix_tokens_estimate",
        "dynamic_suffix_tokens_estimate",
        "total_tokens_estimate",
        "cache_candidate",
        "cache_break_reason",
        "provider_hint",
        "created_at",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError("Invalid cache manifest: missing " + ", ".join(missing))
    return dict(payload)


def read_cache_manifest(repo_root: Path | str) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    path = cache_manifest_path(root)
    if not path.exists():
        return {"status": "missing", "path": display_path(root, path), "valid": False, "payload": None, "error": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validated = validate_cache_manifest(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"status": "invalid", "path": display_path(root, path), "valid": False, "payload": None, "error": str(exc)}
    return {"status": "loaded", "path": display_path(root, path), "valid": True, "payload": validated, "error": None}


def write_cache_manifest(repo_root: Path | str, resolved: dict[str, Any], compiled: dict[str, Any]) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    payload = build_cache_manifest(root, resolved, compiled)
    path = cache_manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(validate_cache_manifest(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return {"status": "written", "path": display_path(root, path), "valid": True, "payload": payload, "error": None}
