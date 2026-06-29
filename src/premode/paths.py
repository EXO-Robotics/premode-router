from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import os


@dataclass(frozen=True)
class NormalizedPath:
    ok: bool
    rel_path: str | None = None
    reason: str | None = None


def find_repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    cur = start if start.is_dir() else start.parent
    for parent in [cur, *cur.parents]:
        if (parent / ".git").exists():
            return parent
    return cur


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def normalize_for_manifest(path: str | Path, repo_root: Path) -> NormalizedPath:
    """Return a normalized repo-relative POSIX path, or a safe exclusion reason."""
    root = repo_root.resolve()
    raw = str(path)
    s = raw.replace("\\", "/")

    # Existing filesystem path: use realpath so symlink escapes are caught.
    candidate = Path(raw)
    try:
        fs_path = candidate if candidate.is_absolute() else root / candidate
        if fs_path.exists():
            resolved = fs_path.resolve()
            if not is_within(resolved, root):
                return NormalizedPath(False, reason="path escapes repo root")
            return NormalizedPath(True, resolved.relative_to(root).as_posix())
    except OSError:
        return NormalizedPath(False, reason="path cannot be resolved")

    # Lexical support for Windows paths supplied on non-Windows hosts.
    if len(s) >= 3 and s[1] == ":" and s[2] == "/":
        # C:/repo/src/App.swift -> src/App.swift when repo folder name matches.
        parts = [p for p in s[3:].split("/") if p]
        root_name = root.name
        if root_name in parts:
            rel_parts = parts[parts.index(root_name) + 1 :]
        else:
            return NormalizedPath(False, reason="absolute path outside repo root")
    elif s.startswith("/"):
        root_s = root.as_posix().rstrip("/")
        if s == root_s or s.startswith(root_s + "/"):
            rel_parts = [p for p in s[len(root_s) :].strip("/").split("/") if p]
        else:
            return NormalizedPath(False, reason="absolute path outside repo root")
    else:
        rel_parts = [p for p in s.strip("/").split("/") if p and p != "."]
        if rel_parts and rel_parts[0] == root.name:
            rel_parts = rel_parts[1:]

    if not rel_parts:
        return NormalizedPath(False, reason="empty relative path")
    if any(p == ".." for p in rel_parts):
        return NormalizedPath(False, reason="path traversal is not allowed")
    return NormalizedPath(True, "/".join(rel_parts))


def safe_repo_path(repo_root: Path, rel_path: str | Path) -> tuple[Path | None, str | None]:
    norm = normalize_for_manifest(rel_path, repo_root)
    if not norm.ok or not norm.rel_path:
        return None, norm.reason
    candidate = (repo_root.resolve() / norm.rel_path)
    try:
        resolved = candidate.resolve()
    except OSError:
        return None, "path cannot be resolved"
    if not is_within(resolved, repo_root.resolve()):
        return None, "path escapes repo root"
    return resolved, None
