#!/usr/bin/env python3
"""Qualify an exact local wheel through a controlled, offline pipx lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/pcodex.tool-install-qualification.v1.schema.json"


def _run(
    *args: str, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode:
        raise RuntimeError(
            f"controlled tool-install command failed ({completed.returncode}): {args[0]}"
        )
    return completed


def probe(wheel: Path, root: Path, *, python: str = sys.executable) -> dict[str, Any]:
    wheel = wheel.resolve()
    root = root.resolve()
    interpreter = Path(python).absolute()
    if wheel.is_symlink() or not wheel.is_file() or not wheel.name.endswith(".whl"):
        raise ValueError("tool-install probe requires one regular wheel")
    if root.exists():
        raise ValueError("tool-install probe root must not already exist")
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError("tool-install probe requires an absolute executable Python")
    root.mkdir(parents=True)
    home = root / "home"
    repo = root / "repository with spaces β"
    pipx_home = root / "pipx-home"
    pipx_bin = root / "pipx-bin"
    pipx_shared = root / "pipx-shared"
    for path in (home, repo, pipx_home, pipx_bin, root / "tmp"):
        path.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("# controlled pipx fixture\n", encoding="utf-8")
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("controlled tool-install probe requires git")
    blocked_proxy = "http://" + "127.0.0.1:9"
    controlled_path = os.pathsep.join(
        dict.fromkeys(
            (
                str(interpreter.parent),
                str(Path(git).resolve().parent),
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            )
        )
    )
    env = {
        "PATH": controlled_path,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(root / "xdg-config"),
        "XDG_CACHE_HOME": str(root / "xdg-cache"),
        "XDG_DATA_HOME": str(root / "xdg-data"),
        "TMPDIR": str(root / "tmp"),
        "PIPX_HOME": str(pipx_home),
        "PIPX_BIN_DIR": str(pipx_bin),
        "PIPX_MAN_DIR": str(root / "pipx-man"),
        "PIPX_SHARED_LIBS": str(pipx_shared),
        "PIPX_DEFAULT_PYTHON": str(interpreter),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PIP_CONFIG_FILE": os.devnull,
        "HTTP_PROXY": blocked_proxy,
        "HTTPS_PROXY": blocked_proxy,
        "ALL_PROXY": blocked_proxy,
        "NO_PROXY": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    _run(git, "init", "-q", cwd=repo, env=env)
    _run(git, "config", "user.email", "fixture.invalid", cwd=repo, env=env)
    _run(git, "config", "user.name", "pCodex Fixture", cwd=repo, env=env)
    _run(git, "add", "README.md", cwd=repo, env=env)
    _run(git, "commit", "-q", "-m", "fixture", cwd=repo, env=env)
    _run(str(interpreter), "-m", "venv", str(pipx_shared), cwd=root, env=env)
    tool_version = _run(
        str(interpreter), "-m", "pipx", "--version", cwd=root, env=env
    ).stdout.strip()
    if tool_version != "1.8.0":
        raise RuntimeError("unexpected pipx version")
    _run(
        str(interpreter),
        "-m",
        "pipx",
        "install",
        "--python",
        str(interpreter),
        "--pip-args=--no-index --no-deps --disable-pip-version-check",
        str(wheel),
        cwd=root,
        env=env,
    )
    pcodex = pipx_bin / "pcodex"
    if pcodex.is_symlink():
        resolved = pcodex.resolve()
        if pipx_home not in resolved.parents:
            raise RuntimeError("pipx console script escapes controlled installation")
    elif not pcodex.is_file():
        raise RuntimeError("pipx did not create the pcodex console script")
    installed_python = pipx_home / "venvs/premode-router/bin/python"
    origin_payload = json.loads(
        _run(
            str(installed_python),
            "-c",
            "import json,premode,sys; from premode.codex_plugin import canonical_source_root; "
            "print(json.dumps({'module':premode.__file__,'plugin':str(canonical_source_root()),'prefix':sys.prefix}))",
            cwd=repo,
            env=env,
        ).stdout
    )
    installed_root = (pipx_home / "venvs/premode-router").resolve()
    resolved_origins = {
        key: Path(origin_payload[key]).resolve()
        for key in ("module", "plugin", "prefix")
    }
    if (
        resolved_origins["prefix"] != installed_root
        or any(
            installed_root not in resolved_origins[key].parents
            for key in ("module", "plugin")
        )
        or any(
            repo in resolved_origins[key].parents
            or root not in resolved_origins[key].parents
            for key in ("module", "plugin")
        )
    ):
        raise RuntimeError(
            "pipx command or plugin resources did not resolve from the controlled installation"
        )
    help_result = _run(str(pcodex), "--help", cwd=repo, env=env)
    advisory = _run(str(pcodex), "status", "--advisory", "--json", cwd=repo, env=env)
    dry_run = _run(
        str(pcodex), "run", "--dry-run", "Inspect the repository", cwd=repo, env=env
    )
    advisory_payload = json.loads(advisory.stdout)
    if advisory_payload.get("writes_performed") is not False:
        raise RuntimeError("pipx advisory smoke did not prove literal no-write")
    if "pcodex" not in help_result.stdout.lower() or not dry_run.stdout.strip():
        raise RuntimeError("pipx installed command smoke was incomplete")
    _run(
        str(interpreter),
        "-m",
        "pipx",
        "uninstall",
        "premode-router",
        cwd=root,
        env=env,
    )
    listing = json.loads(
        _run(str(interpreter), "-m", "pipx", "list", "--json", cwd=root, env=env).stdout
    )
    venvs = listing.get("venvs", {})
    residue_free = (
        "premode-router" not in venvs
        and not os.path.lexists(pcodex)
        and not os.path.lexists(pipx_bin / "premode")
    )
    result = {
        "schema_version": "pcodex.tool-install-qualification.v1",
        "passed": True,
        "tool": "pipx",
        "tool_version": tool_version,
        "product_version": "0.3.0b1",
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "platform": platform.system(),
        "python": platform.python_version(),
        "network_independent_local_wheel_install": True,
        "help": True,
        "advisory": True,
        "dry_run": True,
        "uninstall": True,
        "residue_free": residue_free,
        "public_registry_used": False,
        "source_checkout_required": False,
        "installed_module_and_plugin_under_pipx_home": True,
    }
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)
    shutil.rmtree(root)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = probe(args.wheel, args.root, python=args.python)
    except Exception as exc:
        result = {
            "schema_version": "pcodex.tool-install-qualification-failure.v1",
            "passed": False,
            "stage": "controlled_local_wheel_install",
            "error_type": type(exc).__name__,
            "failure_root_preserved": args.root.exists(),
            "public_registry_used": False,
            "published": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, sort_keys=True))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
