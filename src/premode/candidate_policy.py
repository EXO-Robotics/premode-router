from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from .ignore import IgnoreMatcher
from .paths import normalize_for_manifest
from .safe_reader import is_secret_name


class CandidateClass(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_IF_EXPLICIT = "ALLOW_IF_EXPLICIT"
    SUPPORT_ONLY = "SUPPORT_ONLY"
    GENERATED_EXCEPTION = "GENERATED_EXCEPTION"
    DENY_RUNTIME = "DENY_RUNTIME"
    DENY_SECRET = "DENY_SECRET"
    DENY_IGNORED = "DENY_IGNORED"
    DENY_OUTSIDE_ROOT = "DENY_OUTSIDE_ROOT"
    DENY_SYMLINK_ESCAPE = "DENY_SYMLINK_ESCAPE"
    DENY_UNSAFE_SURFACE = "DENY_UNSAFE_SURFACE"


RUNTIME_SEGMENTS = frozenset({
    ".git", ".premode", ".pcodex", ".codex", ".agents", ".venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})
GENERATED_SEGMENTS = frozenset({
    "node_modules", "build", "dist", ".cache", ".next", ".swiftpm",
    ".build", "deriveddata", "pods", "vendor", "target",
})
SUPPORT_NAMES = frozenset({
    "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml",
    "yarn.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
})


def is_generated_candidate_path(path: str | Path) -> bool:
    rel = str(path).replace("\\", "/").casefold()
    return any(part in GENERATED_SEGMENTS for part in rel.split("/")) or ".egg-info" in rel


@dataclass(frozen=True)
class CandidateIntent:
    explicit: bool = False
    generated_required: bool = False
    support_only: bool = False


@dataclass(frozen=True)
class CandidateDecision:
    raw_path: str
    normalized_path: str | None
    classification: CandidateClass
    admitted: bool
    editable: bool
    reason: str
    provenance: tuple[str, ...] = ()


def classify_candidate(
    repo_root: Path,
    raw_path: str | Path,
    *,
    intent: CandidateIntent | None = None,
    ignore: IgnoreMatcher | None = None,
    provenance: Iterable[str] = (),
) -> CandidateDecision:
    root = repo_root.resolve()
    raw = str(raw_path)
    requested = intent or CandidateIntent()
    lexical = Path(raw) if Path(raw).is_absolute() else root / raw
    try:
        if lexical.is_symlink():
            try:
                lexical.resolve(strict=True).relative_to(root)
            except (OSError, ValueError):
                return CandidateDecision(raw, None, CandidateClass.DENY_SYMLINK_ESCAPE, False, False, "symlink target escapes repository root or cannot be resolved", tuple(provenance))
    except OSError:
        return CandidateDecision(raw, None, CandidateClass.DENY_SYMLINK_ESCAPE, False, False, "symlink cannot be resolved safely", tuple(provenance))
    normalized = normalize_for_manifest(raw, root)
    if not normalized.ok or not normalized.rel_path:
        return CandidateDecision(raw, None, CandidateClass.DENY_OUTSIDE_ROOT, False, False, normalized.reason or "outside repository root", tuple(provenance))
    rel = normalized.rel_path
    try:
        if lexical.exists():
            mode = os.stat(lexical, follow_symlinks=True).st_mode
            if not stat.S_ISREG(mode):
                return CandidateDecision(raw, rel, CandidateClass.DENY_UNSAFE_SURFACE, False, False, "candidate is not a regular file", tuple(provenance))
    except OSError:
        return CandidateDecision(raw, rel, CandidateClass.DENY_UNSAFE_SURFACE, False, False, "candidate filesystem surface is unreadable", tuple(provenance))

    parts = tuple(part.casefold() for part in rel.split("/"))
    if any(part in RUNTIME_SEGMENTS for part in parts):
        return CandidateDecision(raw, rel, CandidateClass.DENY_RUNTIME, False, False, "runtime or tool-state path", tuple(provenance))
    if is_secret_name(rel):
        return CandidateDecision(raw, rel, CandidateClass.DENY_SECRET, False, False, "secret-like path", tuple(provenance))
    matcher = ignore or IgnoreMatcher.from_repo(root)
    if matcher.is_ignored(rel):
        return CandidateDecision(raw, rel, CandidateClass.DENY_IGNORED, False, False, "ignored by repository policy", tuple(provenance))
    generated = is_generated_candidate_path(rel)
    if generated:
        if requested.explicit and requested.generated_required:
            return CandidateDecision(raw, rel, CandidateClass.GENERATED_EXCEPTION, True, requested.explicit, "task requires generated material", tuple(provenance))
        return CandidateDecision(raw, rel, CandidateClass.ALLOW_IF_EXPLICIT, requested.explicit, requested.explicit, "generated path requires explicit task intent", tuple(provenance))
    support = requested.support_only or Path(rel).name.casefold() in SUPPORT_NAMES
    if support:
        return CandidateDecision(raw, rel, CandidateClass.SUPPORT_ONLY, True, False, "qualified support candidate", tuple(provenance))
    return CandidateDecision(raw, rel, CandidateClass.ALLOW, True, True, "ordinary repository candidate", tuple(provenance))


def admitted_paths(repo_root: Path, paths: Iterable[str], *, provenance: str) -> tuple[list[str], list[CandidateDecision]]:
    ignore = IgnoreMatcher.from_repo(repo_root)
    accepted: list[str] = []
    decisions: list[CandidateDecision] = []
    for path in paths:
        decision = classify_candidate(repo_root, path, ignore=ignore, provenance=(provenance,))
        decisions.append(decision)
        if decision.admitted and decision.normalized_path:
            accepted.append(decision.normalized_path)
    return sorted(dict.fromkeys(accepted)), decisions
