from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from .timeutil import timestamp_iso

REQUIRED_EXTERNAL_PAYLOAD_FIELDS = (
    "run_id",
    "repo",
    "lane",
    "cwd",
    "cwd_git_root",
    "intended_worktree",
    "git_root_equals_intended_worktree",
    "final_stdin_path",
    "final_stdin_sha256",
    "final_stdin_bytes",
    "packet_mode",
    "packet_path",
    "packet_bytes",
    "contains_source_snippets",
    "contains_private_file_paths",
    "contains_absolute_paths",
    "contains_private_project_names",
    "memory_content_included",
    "exposure_level",
    "policy_safe_recommendation",
    "launch_allowed",
)

PRIVATE_PROJECT_RE = re.compile(r"(?i)\b(GoldpineValley(?:-iOS)?|Rich-CLI|RoboTriage)\b")
ABSOLUTE_PATH_RE = re.compile(r"(?m)(?:^|[\s'\"(])(?:/Users/|/private/|/tmp/|[A-Za-z]:[\\/])")
PRIVATE_FILE_PATH_RE = re.compile(
    r"(?i)(?:/Users/[^/\s]+/(?:Documents|Desktop|Downloads)/|/private/tmp/|GoldpineValley-iOS|Rich-CLI|robotriage)"
)


class RootGuardError(ValueError):
    def __init__(self, guard: dict[str, Any]):
        self.guard = guard
        super().__init__(guard.get("error") or "root escalation blocked")


@dataclass(frozen=True)
class RepoResolution:
    repo: Path
    guard: dict[str, Any]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_root_for(path: Path) -> Path | None:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path if path.is_dir() else path.parent,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return _nearest_dot_git_root(path)
    if cp.returncode == 0 and cp.stdout.strip():
        return Path(cp.stdout.strip()).resolve()
    return _nearest_dot_git_root(path)


def _nearest_dot_git_root(path: Path) -> Path | None:
    start = path.resolve()
    cur = start if start.is_dir() else start.parent
    for parent in [cur, *cur.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _count_files(root: Path | None, *, scan_budget: int) -> dict[str, Any]:
    if root is None or not root.exists() or not root.is_dir():
        return {"file_count": 0, "truncated": False}
    count = 0
    truncated = False
    skip = {".git", ".premode", ".codex", ".agents", ".venv", "node_modules", ".cache", "__pycache__"}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        count += len(files)
        if count >= scan_budget:
            count = scan_budget
            truncated = True
            break
    return {"file_count": count, "truncated": truncated}


def root_guard_record(
    cwd: Path,
    intended_worktree: Path,
    *,
    explicit_repo: bool,
    scan_budget: int = 5000,
    fail_on_root_escalation: bool = False,
) -> dict[str, Any]:
    intended = intended_worktree.resolve()
    cwd_resolved = cwd.resolve()
    detected = git_root_for(cwd_resolved)
    root_escalated = detected is not None and detected != intended
    intended_count = _count_files(intended, scan_budget=scan_budget)
    detected_count = _count_files(detected, scan_budget=scan_budget)
    guard = {
        "cwd": str(cwd_resolved),
        "cwd_git_root": str(detected) if detected else None,
        "intended_worktree": str(intended),
        "explicit_repo": explicit_repo,
        "root_escalated": root_escalated,
        "git_root_equals_intended_worktree": detected == intended if detected else False,
        "scan_budget": scan_budget,
        "intended_file_count": intended_count["file_count"],
        "intended_file_count_truncated": intended_count["truncated"],
        "detected_file_count": detected_count["file_count"],
        "detected_file_count_truncated": detected_count["truncated"],
        "error": None,
    }
    if fail_on_root_escalation and root_escalated:
        guard["error"] = "detected git root differs from intended worktree"
        raise RootGuardError(guard)
    return guard


def resolve_cli_repo(
    cwd: Path,
    explicit_repo: str | Path | None = None,
    *,
    fail_on_root_escalation: bool = False,
    scan_budget: int = 5000,
) -> RepoResolution:
    if explicit_repo is not None:
        repo = Path(explicit_repo).expanduser().resolve()
        guard = root_guard_record(
            repo,
            repo,
            explicit_repo=True,
            scan_budget=scan_budget,
            fail_on_root_escalation=fail_on_root_escalation,
        )
        return RepoResolution(repo=repo, guard=guard)

    start = cwd.resolve()
    detected = git_root_for(start) or start
    guard = root_guard_record(
        start,
        start,
        explicit_repo=False,
        scan_budget=scan_budget,
        fail_on_root_escalation=fail_on_root_escalation,
    )
    return RepoResolution(repo=detected, guard=guard)


def _compiled_packet_mode(compiled: dict[str, Any]) -> str | None:
    return (
        compiled.get("packet_detail_mode_selected")
        or compiled.get("packet_detail_mode")
        or compiled.get("packet_mode")
        or (compiled.get("metrics") or {}).get("packet_detail_mode")
    )


def _contains_source_snippets(packet_mode: str | None, compiled: dict[str, Any]) -> bool:
    normalized = str(packet_mode or "").replace("-", "_")
    if normalized == "evidence_snippets":
        return True
    manifest = compiled.get("manifest") if isinstance(compiled.get("manifest"), dict) else compiled
    return bool(manifest.get("evidence_snippet_packet"))


def _memory_content_included(packet: str, compiled: dict[str, Any]) -> bool:
    manifest = compiled.get("manifest") if isinstance(compiled.get("manifest"), dict) else compiled
    rules_memory = manifest.get("rules_memory") if isinstance(manifest, dict) else None
    if isinstance(rules_memory, dict):
        for key in ("project_memory", "memory", "content"):
            value = rules_memory.get(key)
            if isinstance(value, str) and value.strip():
                return True
    return "Project Memory" in packet or "rules_memory" in packet


def build_external_payload_manifest(
    *,
    run_id: str,
    repo: Path,
    lane: str,
    cwd: Path,
    intended_worktree: Path,
    final_stdin_path: Path,
    packet: str,
    compiled: dict[str, Any] | None = None,
    packet_path: Path | None = None,
    repo_is_private: bool = False,
    private_paths_forbidden: bool = False,
    scan_budget: int = 5000,
) -> dict[str, Any]:
    compiled = compiled or {}
    guard = root_guard_record(cwd, intended_worktree, explicit_repo=False, scan_budget=scan_budget)
    packet_bytes = packet.encode("utf-8")
    packet_mode = _compiled_packet_mode(compiled)
    text_to_scan = "\n".join([str(repo), str(cwd), str(intended_worktree), packet])
    contains_source_snippets = _contains_source_snippets(packet_mode, compiled)
    contains_absolute_paths = bool(ABSOLUTE_PATH_RE.search(text_to_scan))
    contains_private_file_paths = bool(PRIVATE_FILE_PATH_RE.search(text_to_scan))
    contains_private_project_names = bool(PRIVATE_PROJECT_RE.search(text_to_scan))
    effective_private_repo = repo_is_private or contains_private_project_names
    block_reasons: list[str] = []
    if not guard["git_root_equals_intended_worktree"]:
        block_reasons.append("cwd_git_root_mismatch")
    if effective_private_repo and contains_source_snippets:
        block_reasons.append("private_repo_source_snippets")
    if effective_private_repo and private_paths_forbidden and (contains_private_file_paths or contains_absolute_paths):
        block_reasons.append("private_repo_paths_forbidden")

    if block_reasons:
        exposure_level = "blocked:" + ",".join(block_reasons)
        recommendation = "Do not launch externally; use local-only compile/review or remove disallowed payload exposure."
        launch_allowed = False
    elif effective_private_repo:
        exposure_level = "private_repo_paths_only"
        recommendation = "External launch is allowed only if tenant policy permits path/project-name disclosure."
        launch_allowed = not private_paths_forbidden
    else:
        exposure_level = "paths_only" if not contains_source_snippets else "source_snippets"
        recommendation = "External launch allowed by current root guard and payload policy."
        launch_allowed = True

    manifest = {
        "run_id": run_id,
        "repo": str(repo.resolve()),
        "lane": lane,
        "cwd": str(cwd.resolve()),
        "cwd_git_root": guard["cwd_git_root"],
        "intended_worktree": str(intended_worktree.resolve()),
        "git_root_equals_intended_worktree": guard["git_root_equals_intended_worktree"],
        "final_stdin_path": str(final_stdin_path),
        "final_stdin_sha256": sha256_bytes(packet_bytes),
        "final_stdin_bytes": len(packet_bytes),
        "packet_mode": packet_mode,
        "packet_path": str(packet_path) if packet_path else None,
        "packet_bytes": len(packet_bytes),
        "contains_source_snippets": contains_source_snippets,
        "contains_private_file_paths": contains_private_file_paths,
        "contains_absolute_paths": contains_absolute_paths,
        "contains_private_project_names": contains_private_project_names,
        "memory_content_included": _memory_content_included(packet, compiled),
        "exposure_level": exposure_level,
        "policy_safe_recommendation": recommendation,
        "launch_allowed": launch_allowed,
        "block_reasons": block_reasons,
        "root_guard": guard,
        "generated_at": timestamp_iso(),
    }
    missing = [field for field in REQUIRED_EXTERNAL_PAYLOAD_FIELDS if field not in manifest]
    if missing:
        raise AssertionError(f"external payload manifest missing required fields: {missing}")
    return manifest


def write_external_payload_manifest(
    *,
    repo: Path,
    packet: str,
    compiled: dict[str, Any],
    lane: str = "codex",
    cwd: Path | None = None,
    intended_worktree: Path | None = None,
    out_dir: Path | None = None,
    repo_is_private: bool = False,
    private_paths_forbidden: bool = False,
    scan_budget: int = 5000,
) -> dict[str, Any]:
    root = repo.resolve()
    out = out_dir or root / ".premode" / "out"
    out.mkdir(parents=True, exist_ok=True)
    run_id = hashlib.sha256(f"{timestamp_iso()}:{root}:{lane}".encode("utf-8")).hexdigest()[:16]
    stdin_path = out / "external_payload_stdin.txt"
    stdin_path.write_text(packet, encoding="utf-8")
    saved = compiled.get("saved_artifacts") if isinstance(compiled.get("saved_artifacts"), dict) else {}
    packet_path_raw = saved.get("packet_json") or saved.get("audit_path")
    packet_path = Path(packet_path_raw) if packet_path_raw else None
    manifest = build_external_payload_manifest(
        run_id=run_id,
        repo=root,
        lane=lane,
        cwd=(cwd or root),
        intended_worktree=(intended_worktree or root),
        final_stdin_path=stdin_path,
        packet=packet,
        compiled=compiled,
        packet_path=packet_path,
        repo_is_private=repo_is_private,
        private_paths_forbidden=private_paths_forbidden,
        scan_budget=scan_budget,
    )
    manifest_path = out / "external_payload_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"manifest_path": str(manifest_path), "stdin_path": str(stdin_path), "manifest": manifest}
