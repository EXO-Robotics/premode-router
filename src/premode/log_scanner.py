from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .ignore import IgnoreMatcher
from .profiles import ResourceCaps
from .safe_reader import safe_read

ERROR_RE = re.compile(r"(?i)(error:|fatal:|traceback|exception|failed|failure|undefined symbol|cannot find|no such file|xcodebuild: error|swift compile error|module not found|assertionerror)")
PATH_RE = re.compile(r"((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:py|swift|ts|tsx|js|jsx|go|rs|java|kt|c|cpp|h|hpp))(?::(\d+))?")

NOISE_RE = re.compile(r"(?i)(warning:|deprecated|note:|\[info\]|\[debug\])")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SOURCE_SUFFIXES = {
    ".py", ".swift", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs",
    ".java", ".kt", ".c", ".cpp", ".h", ".hpp", ".m", ".mm",
}
LOG_TEXT_TERMS = {"build", "test", "error", "crash", "compile", "xcode", "pytest"}
EXACT_LOG_NAMES = {"build.log", "test.log", "xcodebuild.log", "pytest.log"}
STALE_LOG_PARTS = {"history", "archive", "archives", "generated", "_output", "_claw_output", "proof", "proofs"}


def clean_log_line(line: str) -> str:
    """Strip ANSI/control noise before log-error extraction."""
    line = ANSI_RE.sub("", line)
    line = CTRL_RE.sub("", line)
    return line.rstrip()


def is_stale_or_generated_log_path(rel_path: str) -> bool:
    parts = [p.lower() for p in rel_path.replace("\\", "/").split("/")]
    return any(part in STALE_LOG_PARTS for part in parts[:-1])


def is_log_like_path(rel_path: str, *, indexed_kind: str | None = None) -> bool:
    """Return True only for files that should be scanned as logs.

    This intentionally avoids the old loose `"log" in path` heuristic, which
    caused source files such as `src/premode/log_scanner.py` to be parsed as
    build logs when they contained regex strings like `error:`.
    """
    p = Path(rel_path.replace("\\", "/"))
    name = p.name.lower()
    suffix = p.suffix.lower()
    if suffix in SOURCE_SUFFIXES:
        return False
    if indexed_kind and indexed_kind not in {"log", "docs", "other"}:
        return False
    if suffix in {".log", ".trace"}:
        return True
    if name in EXACT_LOG_NAMES:
        return True
    if suffix == ".txt" and any(term in name for term in LOG_TEXT_TERMS):
        return True
    return False


def _classify_error(line: str) -> str:
    lower = line.lower()
    if "traceback" in lower or "exception" in lower or "assertionerror" in lower:
        return "runtime_or_test_failure"
    if "cannot find" in lower or "module not found" in lower or "no such file" in lower or "undefined symbol" in lower:
        return "missing_symbol_or_dependency"
    if "xcodebuild: error" in lower or "swift compile" in lower or "error:" in lower:
        return "compile_error"
    if "failed" in lower or "failure" in lower:
        return "failure"
    return "error"


def _context(lines: list[str], index: int, radius: int = 2) -> list[str]:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return [clean_log_line(lines[i])[:500] for i in range(start, end)]


def _source_hint(line: str) -> tuple[str | None, int | None]:
    match = PATH_RE.search(line)
    if not match:
        return None, None
    line_no = int(match.group(2)) if match.group(2) and match.group(2).isdigit() else None
    return match.group(1), line_no


def _error_key(line: str) -> str:
    # Normalize digits and spacing so repeated cascades collapse without losing the first instance.
    key = re.sub(r"\d+", "#", line.lower())
    key = re.sub(r"\s+", " ", key).strip()
    return key[:300]


def scan_logs(repo_root: Path, caps: ResourceCaps, entries: list[dict[str, Any]] | None = None, *, allow_root_evidence: bool = True) -> dict[str, Any]:
    ignore = IgnoreMatcher.from_repo(repo_root)
    candidates: list[str] = []
    stale_candidates: list[str] = []
    if entries is not None:
        for entry in entries:
            path = str(entry.get("path", ""))
            kind = str(entry.get("kind", "")) if entry.get("kind") is not None else None
            if is_log_like_path(path, indexed_kind=kind):
                (stale_candidates if is_stale_or_generated_log_path(path) else candidates).append(path)
    else:
        for path in repo_root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(repo_root).as_posix()
                if is_log_like_path(rel):
                    (stale_candidates if is_stale_or_generated_log_path(rel) else candidates).append(rel)
    seen: set[str] = set()
    repeated: dict[str, int] = {}
    logs: list[dict[str, Any]] = []
    meaningful_errors: list[dict[str, Any]] = []
    first_meaningful_error: dict[str, Any] | None = None

    # Current/non-generated logs become root evidence only when the task is actually
    # log/build/test/failure focused or the prompt named a log. Otherwise, logs are
    # only recorded as downgraded evidence candidates so stale CI/build artifacts do
    # not create false root-cause hypotheses for unrelated source tasks.
    active_candidates = candidates[:20] if allow_root_evidence else []
    for rel in active_candidates:
        if rel in seen:
            continue
        seen.add(rel)
        res = safe_read(repo_root, rel, caps, ignore, max_bytes=caps.max_log_bytes, purpose="log")
        if not res.allowed:
            continue
        log_record = {"path": res.path, "bytes_read": res.bytes_read, "truncated": res.truncated, "stale_or_generated": False}
        logs.append(log_record)
        raw_lines = res.content.splitlines()
        lines = [clean_log_line(line) for line in raw_lines]
        for index, line in enumerate(lines):
            if not ERROR_RE.search(line):
                continue
            if NOISE_RE.search(line) and "error" not in line.lower():
                continue
            key = _error_key(line)
            if key in repeated:
                repeated[key] += 1
                continue
            repeated[key] = 1
            source_path, source_line = _source_hint(line)
            err = {
                "path": res.path,
                "line": index + 1,
                "message": line[:500],
                "classification": _classify_error(line),
                "context": _context(lines, index, radius=2),
            }
            if source_path:
                err["source_path"] = source_path
            if source_line:
                err["source_line"] = source_line
            meaningful_errors.append(err)
            if first_meaningful_error is None:
                first_meaningful_error = err
            if len(meaningful_errors) >= caps.hard_log_line_count:
                break
        if len(meaningful_errors) >= caps.hard_log_line_count:
            break

    for rel in (stale_candidates + ([] if allow_root_evidence else candidates))[:40]:
        if rel in seen:
            continue
        seen.add(rel)
        res = safe_read(repo_root, rel, caps, ignore, max_bytes=min(caps.max_log_bytes, 4096), purpose="log")
        if not res.allowed:
            continue
        logs.append({"path": res.path, "bytes_read": res.bytes_read, "truncated": res.truncated, "stale_or_generated": True, "downgraded": True})

    duplicate_error_families = sum(1 for count in repeated.values() if count > 1)
    duplicate_error_count = sum(count - 1 for count in repeated.values() if count > 1)
    return {
        "logs_scanned": logs,
        "first_meaningful_error": first_meaningful_error,
        "meaningful_errors": meaningful_errors[:caps.hard_log_line_count],
        "log_dedupe_summary": {
            "unique_error_families": len(repeated),
            "duplicate_error_families": duplicate_error_families,
            "duplicate_error_count": duplicate_error_count,
            "stale_or_generated_logs_downgraded": len(stale_candidates) + (0 if allow_root_evidence else len(candidates)),
            "root_evidence_enabled": bool(allow_root_evidence),
        },
    }
