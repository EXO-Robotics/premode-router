from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import premode_dir, load_config
from .ignore import IgnoreMatcher
from .profiles import resolve_profile, ResourceCaps
from .paths import normalize_for_manifest
from .safe_reader import BINARY_EXTENSIONS
from .timeutil import timestamp_iso

SKIP_DIR_NAMES = {
    ".git", ".premode", ".codex", ".agents", "DerivedData", "build", "node_modules", ".venv",
    "dist", ".cache", ".next", ".swiftpm", ".build", "vendor", "Pods", "__pycache__", ".pytest_cache",
}
ASSET_DIR_NAMES = {"Assets.xcassets", "assets", "Images", "Fonts"}


def _kind(path: Path) -> str:
    lower = path.name.lower()
    suffix = path.suffix.lower()
    if lower in {"readme", "readme.md", "agents.md"}:
        return "guidance"
    if suffix in {".swift", ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".c", ".cpp", ".h", ".hpp"}:
        return "source"
    if suffix in {".log", ".trace"} or ("log" in lower and suffix in {".txt", ".out"}):
        return "log"
    if suffix in {".md", ".rst", ".txt"}:
        return "docs"
    if suffix in {".json", ".toml", ".yaml", ".yml", ".plist"}:
        return "config"
    return "other"


def index_project(repo_root: Path, profile_name: str | None = None) -> dict[str, Any]:
    cfg = load_config(repo_root)
    caps = resolve_profile(profile_name, cfg)
    ignore = IgnoreMatcher.from_repo(repo_root)
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for current, dirs, files in os.walk(repo_root):
        cur = Path(current)
        rel_cur = cur.relative_to(repo_root).as_posix() if cur != repo_root else ""
        kept_dirs = []
        for d in dirs:
            rel_d = f"{rel_cur}/{d}".strip("/")
            if d in SKIP_DIR_NAMES or d in ASSET_DIR_NAMES or ignore.is_ignored(rel_d, is_dir=True):
                skipped.append({"path": rel_d, "reason": "directory ignored/skipped"})
            else:
                kept_dirs.append(d)
        dirs[:] = kept_dirs

        for name in files:
            if len(entries) >= caps.max_index_files:
                skipped.append({"path": "<remaining>", "reason": "max_index_files reached"})
                break
            path = cur / name
            norm = normalize_for_manifest(path, repo_root)
            if not norm.ok or not norm.rel_path:
                skipped.append({"path": str(path), "reason": norm.reason or "unsafe path"})
                continue
            if ignore.is_ignored(norm.rel_path):
                skipped.append({"path": norm.rel_path, "reason": "ignored"})
                continue
            if "__pycache__" in norm.rel_path.split("/") or norm.rel_path.endswith(".egg-info/SOURCES.txt") or ".egg-info/" in norm.rel_path:
                skipped.append({"path": norm.rel_path, "reason": "generated metadata skipped"})
                continue
            if path.suffix.lower() in BINARY_EXTENSIONS:
                skipped.append({"path": norm.rel_path, "reason": "binary/asset extension"})
                continue
            try:
                stat = path.stat()
            except OSError as exc:
                skipped.append({"path": norm.rel_path, "reason": f"stat failed: {exc}"})
                continue
            entries.append({
                "path": norm.rel_path,
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "extension": path.suffix.lower(),
                "kind": _kind(path),
            })

    data = {
        "version": 1,
        "created_at": timestamp_iso(),
        "repo_root": str(repo_root.resolve()),
        "resource_profile": caps.name,
        "caps": caps.to_dict(),
        "entries": entries,
        "skipped": skipped[:1000],
        "entry_count": len(entries),
    }
    out = premode_dir(repo_root) / "index" / "index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def load_index(repo_root: Path) -> dict[str, Any] | None:
    path = premode_dir(repo_root) / "index" / "index.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
