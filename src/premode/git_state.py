from __future__ import annotations

import subprocess
import os
from pathlib import Path
from typing import Any


def _run_git(repo_root: Path, args: list[str], *, timeout: int = 5, cap: int = 200000) -> tuple[bool, str]:
    try:
        cp = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=timeout, check=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except Exception as exc:
        return False, str(exc)
    text = (cp.stdout or cp.stderr or "")
    data = text.encode("utf-8", errors="replace")[:cap]
    return cp.returncode == 0, data.decode("utf-8", errors="ignore")


def scan_git_state(repo_root: Path, max_diff_bytes: int = 200000, *, include_diff: bool = True) -> dict[str, Any]:
    state: dict[str, Any] = {"available": False, "errors": []}
    ok, inside = _run_git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    if not ok or inside.strip() != "true":
        state["errors"].append("not inside a git work tree")
        return state
    state["available"] = True

    ok, branch = _run_git(repo_root, ["branch", "--show-current"])
    state["branch"] = branch.strip() if ok and branch.strip() else "DETACHED_OR_UNKNOWN"
    ok, commit = _run_git(repo_root, ["rev-parse", "--short", "HEAD"])
    state["head_commit"] = commit.strip() if ok else None
    ok, status = _run_git(repo_root, ["status", "--short"], cap=50000)
    dirty = [line.strip() for line in status.splitlines() if line.strip()] if ok else []

    def _dirty_path(line: str) -> str:
        candidate = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in candidate:
            candidate = candidate.split(" -> ")[-1].strip()
        return candidate

    state["dirty_files"] = [line for line in dirty if not _dirty_path(line).startswith(".premode/") and _dirty_path(line) not in {".premode", ".premodeignore"}]
    ok, log = _run_git(repo_root, ["log", "--oneline", "-5"], cap=50000)
    state["recent_commits"] = [line.strip() for line in log.splitlines() if line.strip()] if ok else []
    state["last_good_commit"] = state.get("recent_commits", [None])[0] if state.get("recent_commits") else state.get("head_commit")
    if include_diff:
        ok, diff = _run_git(repo_root, ["diff", "--", ":!*.png", ":!*.jpg", ":!*.zip", ":!.premode", ":!.premode/*", ":!.premodeignore"], cap=max_diff_bytes)
        state["diff_summary"] = diff if ok else ""
        state["diff_truncated"] = len((diff or "").encode("utf-8")) >= max_diff_bytes
    else:
        state["diff_summary"] = ""
        state["diff_truncated"] = False
        state["diff_observation"] = "omitted_for_read_only_operation"
    return state
