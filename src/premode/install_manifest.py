from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import __version__
from .lockfile import sha256_text, utc_now

INSTALL_MANIFEST_SCHEMA_VERSION = "pcodex.install_manifest.v1"
INSTALLER_VERSION = "pcodex-source-installer.v1"
DEFAULT_INSTALL_MANIFEST_NAME = "install_manifest.json"
SOURCE_INSTALL_EXCLUDE_NAMES = {
    ".agents",
    ".codex",
    ".git",
    ".mypy_cache",
    ".pcodex",
    ".premode",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
SOURCE_INSTALL_EXCLUDE_SUFFIXES = (".egg-info",)
SOURCE_INSTALL_EXCLUDE_PATHS = {
    "private/tmp",
    ".premode/inventory",
    ".premode/topology",
    ".premode/out",
    ".premode/lcc.lock.json",
}


def _git_text(repo: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _git_dirty(repo: Path) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return bool(completed.stdout.strip())


def _count_files(root: Path) -> int:
    if not root.exists():
        return 0
    count = 0
    for path in root.rglob("*"):
        if path.is_file():
            count += 1
    return count


def build_install_manifest(
    *,
    install_root: Path,
    source_repo: Path,
    build_repo: Path | None = None,
    python_executable: str | None = None,
    installer_script: str = "scripts/install_pcodex_from_source.sh",
    install_channel: str = "source_checkout",
    source_type: str = "git_checkout",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    source_repo = source_repo.resolve()
    install_root = install_root.expanduser().resolve()
    branch = _git_text(source_repo, ["branch", "--show-current"])
    head = _git_text(source_repo, ["rev-parse", "HEAD"])
    dirty = _git_dirty(source_repo)
    warning_items = list(warnings or [])
    if dirty is True:
        warning_items.append("source_checkout_dirty")
    if head is None:
        warning_items.append("source_head_unavailable")
    return {
        "schema_version": INSTALL_MANIFEST_SCHEMA_VERSION,
        "package_name": "premode-router",
        "lcc_version": __version__,
        "install_channel": install_channel,
        "source_type": source_type,
        "source_repo": str(source_repo),
        "source_repo_hash": sha256_text(str(source_repo)),
        "source_branch": branch,
        "source_head": head,
        "source_dirty": dirty,
        "installed_at": utc_now(),
        "install_root": str(install_root),
        "install_root_hash": sha256_text(str(install_root)),
        "python_executable": python_executable or sys.executable,
        "python_version": platform.python_version(),
        "console_scripts": ["premode", "pcodex"],
        "plugin_packages": [],
        "builtin_strategies": ["literal_symbol"],
        "files_installed_count": _count_files(build_repo or install_root),
        "installer_version": INSTALLER_VERSION,
        "installer_script": installer_script,
        "provenance_status": "dirty_source" if dirty else "clean_source" if dirty is False else "unknown",
        "warnings": warning_items,
    }


def validate_install_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid install manifest: expected JSON object")
    if payload.get("schema_version") != INSTALL_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Invalid install manifest: unsupported schema_version")
    required = {
        "schema_version",
        "package_name",
        "lcc_version",
        "install_channel",
        "source_type",
        "source_repo",
        "source_branch",
        "source_head",
        "source_dirty",
        "installed_at",
        "install_root",
        "python_executable",
        "python_version",
        "console_scripts",
        "plugin_packages",
        "files_installed_count",
        "installer_version",
        "installer_script",
        "provenance_status",
        "warnings",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError("Invalid install manifest: missing " + ", ".join(missing))
    if payload.get("install_channel") not in {"source_checkout", "private_bundle", "future_public_package"}:
        raise ValueError("Invalid install manifest: unsupported install_channel")
    if not isinstance(payload.get("warnings"), list):
        raise ValueError("Invalid install manifest: warnings must be a list")
    if not isinstance(payload.get("console_scripts"), list):
        raise ValueError("Invalid install manifest: console_scripts must be a list")
    if not isinstance(payload.get("plugin_packages"), list):
        raise ValueError("Invalid install manifest: plugin_packages must be a list")
    if "builtin_strategies" in payload and not isinstance(payload.get("builtin_strategies"), list):
        raise ValueError("Invalid install manifest: builtin_strategies must be a list")
    validated = dict(payload)
    validated.setdefault("builtin_strategies", [])
    return validated


def install_manifest_path(install_root: Path | str | None = None) -> Path:
    root = Path(sys.prefix if install_root is None else install_root).expanduser()
    return root / DEFAULT_INSTALL_MANIFEST_NAME


def read_install_manifest(path: Path | str | None = None) -> dict[str, Any]:
    manifest_path = Path(path) if path is not None else install_manifest_path()
    if not manifest_path.exists():
        return {"status": "missing", "path": str(manifest_path), "valid": False, "payload": None, "error": None}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        validated = validate_install_manifest(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"status": "invalid", "path": str(manifest_path), "valid": False, "payload": None, "error": str(exc)}
    return {"status": "loaded", "path": str(manifest_path), "valid": True, "payload": validated, "error": None}


def write_install_manifest(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    validated = validate_install_manifest(payload)
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
            handle.write(json.dumps(validated, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def should_exclude_source_install_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    parts = normalized.split("/") if normalized else []
    if any(part in SOURCE_INSTALL_EXCLUDE_NAMES for part in parts):
        return True
    if any(part.endswith(SOURCE_INSTALL_EXCLUDE_SUFFIXES) for part in parts):
        return True
    if normalized in {path.strip("/") for path in SOURCE_INSTALL_EXCLUDE_PATHS if not path.startswith("/")}:
        return True
    return normalized.startswith("private/tmp/")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m premode.install_manifest")
    parser.add_argument("--write", required=True)
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--build-repo", default=None)
    parser.add_argument("--installer-script", default="scripts/install_pcodex_from_source.sh")
    args = parser.parse_args(argv)
    payload = build_install_manifest(
        install_root=Path(args.install_root),
        source_repo=Path(args.source_repo),
        build_repo=Path(args.build_repo) if args.build_repo else None,
        python_executable=sys.executable,
        installer_script=args.installer_script,
    )
    write_install_manifest(Path(args.write), payload)
    print(json.dumps({"status": "written", "path": args.write, "schema_version": INSTALL_MANIFEST_SCHEMA_VERSION}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
