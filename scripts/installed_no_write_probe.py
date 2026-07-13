#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import premode
from premode.no_write import evidence_receipt, governed_roots_from_product, verify_no_write
from premode.product_contract import validate_payload_against_schema


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False, timeout=60)
    return {
        "returncode": completed.returncode,
        "stdout_sha256": __import__("hashlib").sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": __import__("hashlib").sha256(completed.stderr.encode()).hexdigest(),
    }


def probe(*, pcodex: Path, repository: Path, control_root: Path, commit_sha: str, timestamp: str) -> dict[str, object]:
    package_path = Path(premode.__file__).resolve()
    prefix = Path(sys.prefix).resolve()
    if prefix not in package_path.parents:
        raise RuntimeError(f"installed probe imported premode outside its environment: {package_path}")
    home = control_root / "home"
    temp_root = control_root / "tmp"
    binary_root = control_root / "fake-bin"
    for path in (home, temp_root, binary_root):
        path.mkdir(parents=True, exist_ok=True)
    marker = home / "forbidden-agent-invocation"
    for name in ("codex", "openclaw", "mcp-server"):
        executable = binary_root / name
        executable.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n", encoding="utf-8")
        executable.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "TMPDIR": str(temp_root),
        "XDG_CONFIG_HOME": str(home / "xdg-config"),
        "XDG_CACHE_HOME": str(home / "xdg-cache"),
        "CODEX_HOME": str(home / "codex-home"),
        "PATH": str(binary_root) + os.pathsep + os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    roots = governed_roots_from_product(repository, home=home, temp_root=temp_root, environ=env)
    premode_cli = pcodex.with_name("premode")
    damaged_repository = control_root / "damaged-installation"
    damaged_repository.mkdir(parents=True, exist_ok=True)
    (damaged_repository / ".git").mkdir()
    install_result = subprocess.run(
        [str(pcodex), "install", "--apply", "--json", "--repo-root", str(damaged_repository)],
        cwd=damaged_repository,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if install_result.returncode != 0:
        raise RuntimeError(f"could not prepare damaged installed fixture: {install_result.stderr}")
    (damaged_repository / ".premode" / "pcodex-install.json").unlink()
    damaged_roots = governed_roots_from_product(damaged_repository, home=home, temp_root=temp_root, environ=env)
    commands = {
        "status_advisory": [str(pcodex), "status", "--advisory", "--json", "--repo-root", str(repository)],
        "doctor_advisory": [str(pcodex), "doctor", "--advisory", "--json", "--repo-root", str(repository)],
        "repair_preview": [str(pcodex), "repair", "--dry-run", "--json", "--repo-root", str(damaged_repository)],
        "uninstall_preview": [str(pcodex), "uninstall", "--dry-run", "--json", "--repo-root", str(repository)],
        "run_dry_run": [str(pcodex), "run", "Installed exact task", "--dry-run", "--json", "--repo", str(repository)],
        "integrate_codex_preview": [str(pcodex), "integrate", "codex", "--dry-run", "--json", "--repo-root", str(repository)],
        "cleanup_preview": [str(pcodex), "cleanup", "--local-state", "--dry-run", "--json", "--repo-root", str(repository)],
        "install_preview": [str(pcodex), "install", "--repo-root", str(repository)],
        "first_run_advisory": [str(pcodex), "first-run", "--advisory", "--json", "--repo-root", str(repository)],
        "plugin_init_preview": [str(pcodex), "plugin", "init", "--local-marketplace", "--dry-run", "--json", "--repo-root", str(repository)],
        "compile_preview": [str(pcodex), "compile", "Installed exact task", "--dry-run", "--json", "--repo", str(repository)],
        "premode_codex_dry_run": [str(premode_cli), "codex", "Installed exact task", "--dry-run", "--no-save", "--repo", str(repository)],
    }
    results: dict[str, object] = {}
    public_receipts: dict[str, object] = {}
    private_receipts: dict[str, object] = {}
    for name, command in commands.items():
        command_repository = damaged_repository if name == "repair_preview" else repository
        command_roots = damaged_roots if name == "repair_preview" else roots
        verification = verify_no_write(
            lambda command=command, command_repository=command_repository: _run(command, cwd=command_repository, env=env),
            roots=command_roots,
            monitor_processes=True,
            monitor_filesystem=True,
        )
        value = verification.pop("value")
        returncode = value.get("returncode") if isinstance(value, dict) else None
        results[name] = {
            "passed": verification["passed"] and returncode == 0,
            "returncode": returncode,
            "before_snapshot_hash": verification["before"]["snapshot_sha256"],
            "after_snapshot_hash": verification["after"]["snapshot_sha256"],
            "changes": verification["comparison"]["changes"],
            "exceptions": list(verification.get("exceptions") or []),
        }
        receipt_fields = {
            "product_version": premode.__version__,
            "commit_sha": commit_sha,
            "command": name,
            "arguments": command[1:],
            "scenario_id": f"installed-{name}",
            "timestamp": timestamp,
        }
        public_receipts[name] = evidence_receipt(verification, sanitized=True, **receipt_fields)
        private_receipts[name] = evidence_receipt(verification, sanitized=False, **receipt_fields)
    schema_root = prefix / "share" / "premode-router" / "schemas"
    public_schema = json.loads((schema_root / "pcodex.no-write-evidence.schema.json").read_text(encoding="utf-8"))
    private_schema = json.loads((schema_root / "pcodex.no-write-evidence.private.schema.json").read_text(encoding="utf-8"))
    for receipt in public_receipts.values():
        validate_payload_against_schema(receipt, public_schema)
    for receipt in private_receipts.values():
        validate_payload_against_schema(receipt, private_schema)
    return {
        "schema_version": "pcodex.installed-no-write-probe.v1",
        "commands": results,
        "public_receipts": public_receipts,
        "private_receipts": private_receipts,
        "installed_package_path": str(package_path),
        "environment_prefix": str(prefix),
        "receipts_validated": True,
        "forbidden_agent_marker_created": marker.exists(),
        "passed": all(bool(item["passed"]) for item in results.values()) and not marker.exists(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcodex", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()
    result = probe(pcodex=args.pcodex.resolve(), repository=args.repository.resolve(), control_root=args.control_root.resolve(), commit_sha=args.commit_sha, timestamp=args.timestamp)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
