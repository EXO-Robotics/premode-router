from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
import tempfile

from .config import load_config, premode_dir
from .ignore import DEFAULT_PREMODEIGNORE
from .profiles import recommend_profile, resolve_profile
from .safe_reader import SECRET_PATTERNS, safe_read
from .profiles import PROFILES
from .ignore import IgnoreMatcher


def _json_valid(path: Path) -> dict:
    if not path.exists():
        return {"present": False, "valid": False, "reason": "missing"}
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return {"present": True, "valid": True}
    except Exception as exc:
        return {"present": True, "valid": False, "reason": str(exc)}


def _command_found(name: str) -> dict:
    path = shutil.which(name)
    return {"found": bool(path), "path": path}


def _inside_git_repo(repo_root: Path) -> bool:
    try:
        cp = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_root, capture_output=True, text=True, timeout=5, check=False)
        return cp.returncode == 0 and cp.stdout.strip() == "true"
    except Exception:
        return False


def _plugin_checks(repo_root: Path) -> dict:
    root = repo_root / ".agents" / "plugins" / "plugins" / "premode-router"
    manifest = root / ".codex-plugin" / "plugin.json"
    hooks = root / "hooks" / "hooks.json"
    mcp = root / ".mcp.json"
    skills_dir = root / "skills"
    return {
        "installed": root.exists(),
        "manifest": _json_valid(manifest),
        "hooks": _json_valid(hooks),
        "mcp": _json_valid(mcp),
        "skills": sorted(p.name for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.exists() else [],
        "hook_script_executable": (root / "hooks" / "premode_hook.py").exists() and bool((root / "hooks" / "premode_hook.py").stat().st_mode & 0o111),
    }


def _symlink_protection_smoke(repo_root: Path) -> dict:
    # Uses only a temporary directory and .premodeignore-independent safe_reader behavior.
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        local_repo = tmp / "repo"
        local_repo.mkdir()
        (local_repo / ".premodeignore").write_text(DEFAULT_PREMODEIGNORE, encoding="utf-8")
        outside = tmp / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = local_repo / "escape.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            return {"supported": False, "blocked": None, "reason": "symlink unavailable"}
        res = safe_read(local_repo, "escape.txt", PROFILES["lite"], IgnoreMatcher.from_repo(local_repo))
        return {"supported": True, "blocked": not res.allowed, "reason": res.reason}


def doctor(repo_root: Path, recommend: bool = False) -> dict:
    cfg = load_config(repo_root)
    active = resolve_profile(None, cfg)
    cfg_path = repo_root / ".premode" / "config.json"
    result = {
        "repo_root": str(repo_root.resolve()),
        "commands": {
            "git": _command_found("git"),
            "codex": _command_found("codex"),
        },
        "inside_git_repo": _inside_git_repo(repo_root),
        "config": _json_valid(cfg_path),
        "premodeignore_present": (repo_root / ".premodeignore").exists(),
        "schema": _json_valid(premode_dir(repo_root) / "schemas" / "codex_final_report.schema.json"),
        "task_packet_schema": _json_valid(premode_dir(repo_root) / "schemas" / "task_packet.schema.json"),
        "plugin": _plugin_checks(repo_root),
        "tiktoken": {"available": bool(shutil.which("tiktoken")), "fallback_active": True},
        "symlink_protection": _symlink_protection_smoke(repo_root),
        "secret_deny_paths_configured": SECRET_PATTERNS,
        "active_profile": active.name,
        "active_caps": active.to_dict(),
        "memory_guard": cfg.get("memory_guard", {}),
    }
    if recommend:
        result["recommendation"] = recommend_profile()
    return result
