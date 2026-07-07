from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .config import premode_dir
from .ignore import IgnoreMatcher
from .paths import normalize_for_manifest
from .safe_reader import is_secret_name
from .timeutil import timestamp_iso
from .write_policy import WritePolicy, resolve_write_policy

INVENTORY_SCHEMA_VERSION = "premode.git_file_inventory.v1"
INVENTORY_REL_PATH = Path(".premode") / "inventory" / "files.json"

RUNTIME_DIR_NAMES = {
    ".git",
    ".premode",
    ".pcodex",
    ".codex",
    ".agents",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
GENERATED_DIR_NAMES = {
    "node_modules",
    "build",
    "dist",
    ".cache",
    ".next",
    ".swiftpm",
    ".build",
    "DerivedData",
    "Pods",
    "vendor",
}
MARKER_DIR_NAMES = {"Assets", "ProjectSettings"}
MARKER_DIR_SUFFIXES = (".xcodeproj", ".xcworkspace")


@dataclass
class InventoryMetrics:
    files_walked: int = 0
    files_listed: int = 0
    files_stat_checked: int = 0
    files_content_read: int = 0
    bytes_read: int = 0
    git_commands_run: int = 0
    inventory_cache_hit: bool = False
    inventory_cache_miss: bool = False
    inventory_source: str | None = None
    inventory_freshness: str | None = None
    repo_map_cache_hit: bool | None = None
    repo_map_rebuilt: bool | None = None
    compile_ms: int | None = None
    full_walk_performed: bool = False
    full_walk_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_walked": self.files_walked,
            "files_listed": self.files_listed,
            "files_stat_checked": self.files_stat_checked,
            "files_content_read": self.files_content_read,
            "bytes_read": self.bytes_read,
            "git_commands_run": self.git_commands_run,
            "inventory_cache_hit": self.inventory_cache_hit,
            "inventory_cache_miss": self.inventory_cache_miss,
            "inventory_source": self.inventory_source,
            "inventory_freshness": self.inventory_freshness,
            "repo_map_cache_hit": self.repo_map_cache_hit,
            "repo_map_rebuilt": self.repo_map_rebuilt,
            "compile_ms": self.compile_ms,
            "full_walk_performed": self.full_walk_performed,
            "full_walk_reason": self.full_walk_reason,
        }


@dataclass
class InventoryBuildResult:
    inventory: dict[str, Any] | None
    freshness: str
    metrics: InventoryMetrics = field(default_factory=InventoryMetrics)


def inventory_cache_path(repo_root: Path | str) -> Path:
    return premode_dir(Path(repo_root)) / "inventory" / "files.json"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    tmp = Path(handle.name)
    try:
        with handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _run_git(repo_root: Path, args: list[str], metrics: InventoryMetrics | None = None) -> tuple[bool, bytes, str | None]:
    if metrics is not None:
        metrics.git_commands_run += 1
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired, TypeError) as exc:
        return False, b"", f"{type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        return False, completed.stdout or b"", stderr or f"git exited {completed.returncode}"
    return True, completed.stdout or b"", None


def _git_text(repo_root: Path, args: list[str], metrics: InventoryMetrics | None = None) -> str | None:
    ok, data, _err = _run_git(repo_root, args, metrics)
    if not ok:
        return None
    return data.decode("utf-8", errors="replace").strip()


def _split_nul(data: bytes) -> list[str]:
    out: list[str] = []
    for item in data.split(b"\x00"):
        if not item:
            continue
        text = item.decode("utf-8", errors="surrogateescape").replace("\\", "/").strip("/")
        if text:
            out.append(text)
    return out


def _list_git_files(repo_root: Path, metrics: InventoryMetrics) -> tuple[list[str] | None, list[str], list[str], str | None]:
    ok_cached, cached_raw, cached_err = _run_git(repo_root, ["ls-files", "-z", "--cached"], metrics)
    if not ok_cached:
        return None, [], [], cached_err or "git_ls_files_cached_failed"
    ok_other, other_raw, other_err = _run_git(repo_root, ["ls-files", "-z", "--others", "--exclude-standard"], metrics)
    if not ok_other:
        return None, [], [], other_err or "git_ls_files_others_failed"
    tracked = _split_nul(cached_raw)
    untracked = _split_nul(other_raw)
    return list(dict.fromkeys([*tracked, *untracked])), tracked, untracked, None


def _ignore_signature(repo_root: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name in (".gitignore", ".premodeignore"):
        path = repo_root / name
        if not path.exists() or not path.is_file():
            payload[name] = None
            continue
        try:
            data = path.read_bytes()
            payload[name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        except OSError:
            payload[name] = {"error": "unreadable"}
    return payload


def _git_index_signature(repo_root: Path, metrics: InventoryMetrics | None = None) -> dict[str, Any] | None:
    files, tracked, untracked, err = _list_git_files(repo_root, metrics or InventoryMetrics())
    if files is None:
        return None
    return {
        "tracked_count": len(tracked),
        "tracked_hash": _sha256_text("\n".join(tracked)),
        "untracked_count": len(untracked),
        "untracked_hash": _sha256_text("\n".join(untracked)),
        "file_set_hash": _sha256_text("\n".join(files)),
        "marker_paths_hash": _sha256_text("\n".join(_bounded_marker_dirs(repo_root))),
        "error": err,
    }


def _bounded_marker_dirs(repo_root: Path, *, max_depth: int = 3, max_dirs: int = 2000) -> list[str]:
    markers: list[str] = []
    stack: list[tuple[Path, int]] = [(repo_root, 0)]
    visited = 0
    while stack and visited < max_dirs:
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            if visited >= max_dirs:
                break
            if not child.is_dir():
                continue
            visited += 1
            rel = child.relative_to(repo_root).as_posix()
            parts = rel.split("/")
            if any(part in RUNTIME_DIR_NAMES or part in GENERATED_DIR_NAMES for part in parts):
                continue
            if child.name in MARKER_DIR_NAMES or child.name.endswith(MARKER_DIR_SUFFIXES):
                markers.append(rel)
                if child.name.endswith(MARKER_DIR_SUFFIXES):
                    continue
            if depth + 1 < max_depth:
                stack.append((child, depth + 1))
    return sorted(dict.fromkeys(markers))


def _skip_reason(rel_path: str, ignore: IgnoreMatcher, *, is_dir: bool = False) -> str | None:
    parts = rel_path.split("/")
    if any(part in RUNTIME_DIR_NAMES for part in parts):
        return "runtime"
    if any(part in GENERATED_DIR_NAMES for part in parts):
        return "generated"
    if rel_path.endswith(".egg-info/SOURCES.txt") or ".egg-info/" in rel_path:
        return "generated"
    if ignore.is_ignored(rel_path, is_dir=is_dir):
        return "premodeignore"
    if is_secret_name(rel_path):
        return "secret"
    return None


def _filter_paths(repo_root: Path, paths: Iterable[str], ignore: IgnoreMatcher) -> tuple[list[str], dict[str, int]]:
    kept: list[str] = []
    counts = {
        "ignored_by_premode_count": 0,
        "skipped_runtime_count": 0,
        "skipped_generated_count": 0,
        "skipped_secret_count": 0,
        "skipped_unsafe_count": 0,
    }
    for raw in paths:
        norm = normalize_for_manifest(raw, repo_root)
        if not norm.ok or not norm.rel_path:
            counts["skipped_unsafe_count"] += 1
            continue
        rel = norm.rel_path
        reason = _skip_reason(rel, ignore)
        if reason == "runtime":
            counts["skipped_runtime_count"] += 1
            continue
        if reason == "generated":
            counts["skipped_generated_count"] += 1
            continue
        if reason == "premodeignore":
            counts["ignored_by_premode_count"] += 1
            continue
        if reason == "secret":
            counts["skipped_secret_count"] += 1
            continue
        kept.append(rel)
    return sorted(dict.fromkeys(kept)), counts


def _walk_files(repo_root: Path, ignore: IgnoreMatcher, metrics: InventoryMetrics) -> tuple[list[str], dict[str, int]]:
    paths: list[str] = []
    counts = {
        "ignored_by_premode_count": 0,
        "skipped_runtime_count": 0,
        "skipped_generated_count": 0,
        "skipped_secret_count": 0,
        "skipped_unsafe_count": 0,
    }
    for current, dirs, files in os.walk(repo_root):
        metrics.full_walk_performed = True
        metrics.full_walk_reason = metrics.full_walk_reason or "os_walk_inventory_fallback"
        cur = Path(current)
        rel_cur = cur.relative_to(repo_root).as_posix() if cur != repo_root else ""
        kept_dirs: list[str] = []
        for name in dirs:
            rel = f"{rel_cur}/{name}".strip("/")
            reason = _skip_reason(rel, ignore, is_dir=True)
            if reason == "runtime":
                counts["skipped_runtime_count"] += 1
                continue
            if reason == "generated":
                counts["skipped_generated_count"] += 1
                continue
            if reason == "premodeignore":
                counts["ignored_by_premode_count"] += 1
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in files:
            metrics.files_walked += 1
            rel = f"{rel_cur}/{name}".strip("/")
            paths.append(rel)
    filtered, filtered_counts = _filter_paths(repo_root, paths, ignore)
    for key, value in filtered_counts.items():
        counts[key] += value
    return filtered, counts


def _build_payload(
    repo_root: Path,
    *,
    paths: list[str],
    tracked: list[str],
    untracked: list[str],
    source: str,
    fallback_reason: str | None,
    counts: dict[str, int],
    metrics: InventoryMetrics,
) -> dict[str, Any]:
    branch = _git_text(repo_root, ["branch", "--show-current"], metrics)
    head = _git_text(repo_root, ["rev-parse", "HEAD"], metrics)
    signature = _git_index_signature(repo_root, metrics) if source == "git_ls_files" else None
    marker_paths = _bounded_marker_dirs(repo_root) if source == "git_ls_files" else []
    repo_root_hash = _sha256_text(str(repo_root.resolve()))
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "lcc_version": __version__,
        "repo_root_hash": repo_root_hash,
        "git_branch": branch,
        "git_head": head,
        "git_index_signature": signature,
        "ignore_signature": _ignore_signature(repo_root),
        "inventory_source": source,
        "fallback_reason": fallback_reason,
        "created_at": timestamp_iso(),
        "file_count": len(paths),
        "marker_paths": marker_paths,
        "marker_count": len(marker_paths),
        "tracked_count": len([p for p in tracked if p in set(paths)]),
        "untracked_count": len([p for p in untracked if p in set(paths)]),
        "ignored_by_premode_count": counts.get("ignored_by_premode_count", 0),
        "skipped_runtime_count": counts.get("skipped_runtime_count", 0),
        "skipped_generated_count": counts.get("skipped_generated_count", 0),
        "skipped_secret_count": counts.get("skipped_secret_count", 0),
        "skipped_unsafe_count": counts.get("skipped_unsafe_count", 0),
        "paths": paths,
    }


def build_inventory(
    repo_root: Path | str,
    force: bool = False,
    *,
    write: bool = True,
    policy: WritePolicy | str | None = None,
) -> InventoryBuildResult:
    resolved_policy = resolve_write_policy(policy)
    write = write and resolved_policy.can_write_inventory
    root = Path(repo_root)
    metrics = InventoryMetrics(inventory_cache_miss=True)
    ignore = IgnoreMatcher.from_repo(root)
    source = "git_ls_files"
    fallback_reason: str | None = None
    tracked: list[str] = []
    untracked: list[str] = []
    raw_paths: list[str] | None = None

    if not (root / ".git").exists():
        source = "os_walk_fallback"
        fallback_reason = "non_git_repo"
    else:
        raw_paths, tracked, untracked, fallback_reason = _list_git_files(root, metrics)
        if raw_paths is None:
            source = "os_walk_fallback"
            tracked = []
            untracked = []

    if source == "git_ls_files" and raw_paths is not None:
        paths, counts = _filter_paths(root, raw_paths, ignore)
        metrics.files_listed = len(raw_paths)
    else:
        paths, counts = _walk_files(root, ignore, metrics)
        metrics.files_listed = len(paths)

    metrics.inventory_source = source
    metrics.inventory_freshness = "fresh"
    payload = _build_payload(
        root,
        paths=paths,
        tracked=tracked,
        untracked=untracked,
        source=source,
        fallback_reason=fallback_reason,
        counts=counts,
        metrics=metrics,
    )
    if write:
        path = inventory_cache_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, payload)
    return InventoryBuildResult(payload, "fresh", metrics)


def load_inventory(repo_root: Path | str) -> dict[str, Any] | None:
    path = inventory_cache_path(repo_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def inventory_is_fresh(repo_root: Path | str, inventory: dict[str, Any] | None) -> str:
    root = Path(repo_root)
    if inventory is None:
        return "missing"
    if not isinstance(inventory, dict):
        return "invalid"
    if inventory.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        return "stale_schema_changed"
    if inventory.get("lcc_version") != __version__:
        return "stale_schema_changed"
    if inventory.get("repo_root_hash") != _sha256_text(str(root.resolve())):
        return "invalid"
    branch = _git_text(root, ["branch", "--show-current"])
    head = _git_text(root, ["rev-parse", "HEAD"])
    if branch != inventory.get("git_branch"):
        return "stale_branch_changed"
    if head != inventory.get("git_head"):
        return "stale_head_changed"
    if _ignore_signature(root) != inventory.get("ignore_signature"):
        return "stale_ignore_changed"
    current_sig = _git_index_signature(root)
    if current_sig != inventory.get("git_index_signature"):
        return "stale_file_set_changed"
    paths = inventory.get("paths")
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        return "invalid"
    return "fresh"


def refresh_inventory_if_needed(repo_root: Path | str, policy: WritePolicy | str = "write") -> InventoryBuildResult:
    root = Path(repo_root)
    policy_name = str(policy).strip().lower().replace("-", "_")
    if policy_name not in {"write", "read_only", "no_write"}:
        resolved_policy = resolve_write_policy(policy)
        policy_name = "write" if resolved_policy.can_write_inventory else "no_write"
    existing = load_inventory(root)
    freshness = inventory_is_fresh(root, existing)
    metrics = InventoryMetrics(inventory_freshness=freshness)
    if freshness == "fresh" and existing is not None:
        metrics.inventory_cache_hit = True
        metrics.inventory_source = str(existing.get("inventory_source") or "unknown")
        metrics.files_listed = int(existing.get("file_count") or 0)
        return InventoryBuildResult(existing, freshness, metrics)
    if policy_name in {"read_only", "no_write"}:
        metrics.inventory_cache_miss = True
        metrics.inventory_source = str((existing or {}).get("inventory_source") or "missing")
        return InventoryBuildResult(existing, freshness, metrics)
    result = build_inventory(root, write=policy_name != "no_write")
    result.freshness = "fresh"
    result.metrics.inventory_freshness = "fresh"
    return result


def summarize_inventory(repo_root: Path | str, inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(repo_root)
    payload = load_inventory(root) if inventory is None else inventory
    freshness = inventory_is_fresh(root, payload)
    source = None
    file_count = 0
    fallback_reason = None
    if isinstance(payload, dict):
        source = payload.get("inventory_source")
        file_count = int(payload.get("file_count") or 0)
        fallback_reason = payload.get("fallback_reason")
    return {
        "state": freshness,
        "source": source,
        "file_count": file_count,
        "cache_hit": freshness == "fresh",
        "full_walk_performed": False,
        "freshness": freshness,
        "fallback_reason": fallback_reason,
        "cache_path": str(INVENTORY_REL_PATH),
    }
