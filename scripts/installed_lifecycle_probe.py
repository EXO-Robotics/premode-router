#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from premode.product_contract import validate_payload_against_schema


MANAGED_ITEM = ".premode/pcodex-install.json"


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _run(pcodex: Path, repo: Path, env: dict[str, str], *args: str, expected: set[int] = {0}) -> tuple[dict[str, Any], float, int]:
    started = time.perf_counter()
    completed = subprocess.run(
        [str(pcodex), *args, "--repo-root", str(repo)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode not in expected:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(args)}: {completed.stderr}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command returned non-JSON: {' '.join(args)}: {completed.stdout}") from exc
    return payload, elapsed, completed.returncode


def _repo(parent: Path, name: str) -> Path:
    root = parent / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "unrelated.txt").write_text("preserve me\n", encoding="utf-8")
    return root


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p50 = ordered[(len(ordered) - 1) // 2]
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {"samples": len(values), "p50_seconds": round(p50, 6), "p95_seconds": round(p95, 6)}


def probe(*, pcodex: Path, control_root: Path) -> dict[str, Any]:
    package_path = Path(__import__("premode").__file__).resolve()
    prefix = Path(sys.prefix).resolve()
    if prefix not in package_path.parents:
        raise RuntimeError(f"probe imported premode outside installed environment: {package_path}")
    home = control_root / "home"
    temp_root = control_root / "tmp"
    for path in (home, temp_root):
        path.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "TMPDIR": str(temp_root),
        "XDG_CONFIG_HOME": str(home / "xdg-config"),
        "XDG_CACHE_HOME": str(home / "xdg-cache"),
        "CODEX_HOME": str(home / "codex-home"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    repo = _repo(control_root, "full-cycle")
    install, _, _ = _run(pcodex, repo, env, "install", "--apply", "--json")
    status_installed, status_installed_time, _ = _run(pcodex, repo, env, "status", "--advisory", "--json")
    target = repo / MANAGED_ITEM
    target.unlink()
    before_repair_preview = _tree(repo)
    repair_preview, _, _ = _run(pcodex, repo, env, "repair", "--dry-run", "--json")
    repair_preview_no_write = before_repair_preview == _tree(repo)
    repair_apply, _, _ = _run(pcodex, repo, env, "repair", "--yes", "--json")
    status_repaired, status_repaired_time, _ = _run(pcodex, repo, env, "status", "--advisory", "--json")
    before_uninstall_preview = _tree(repo)
    uninstall_preview, _, _ = _run(pcodex, repo, env, "uninstall", "--dry-run", "--json")
    uninstall_preview_no_write = before_uninstall_preview == _tree(repo)
    uninstall_apply, _, _ = _run(pcodex, repo, env, "uninstall", "--yes", "--json")
    status_uninstalled, status_uninstalled_time, _ = _run(pcodex, repo, env, "status", "--advisory", "--json")
    reinstall_started = time.perf_counter()
    reinstall, _, _ = _run(pcodex, repo, env, "install", "--apply", "--json")
    status_reinstalled, status_reinstalled_time, _ = _run(pcodex, repo, env, "status", "--advisory", "--json")
    reinstall_cycle = time.perf_counter() - reinstall_started

    modified_repo = _repo(control_root, "modified-cycle")
    _run(pcodex, modified_repo, env, "install", "--apply", "--json")
    modified_target = modified_repo / MANAGED_ITEM
    modified_content = b"user modification must survive\n"
    modified_target.write_bytes(modified_content)
    modified_repair_preview, _, _ = _run(pcodex, modified_repo, env, "repair", "--dry-run", "--json")
    modified_repair_apply, _, modified_repair_code = _run(pcodex, modified_repo, env, "repair", "--yes", "--json", expected={2})
    modified_uninstall_preview, _, _ = _run(pcodex, modified_repo, env, "uninstall", "--dry-run", "--json")
    modified_uninstall_apply, _, modified_uninstall_code = _run(pcodex, modified_repo, env, "uninstall", "--yes", "--json", expected={2})
    modified_preserved = modified_target.read_bytes() == modified_content
    modified_repair_classified = bool(modified_repair_preview.get("will_preserve_modified"))
    modified_uninstall_classified = bool(modified_uninstall_preview.get("will_preserve"))

    perf_repo = _repo(control_root, "performance-cycle")
    _run(pcodex, perf_repo, env, "install", "--apply", "--json")
    repair_preview_times: list[float] = []
    repair_apply_times: list[float] = []
    uninstall_preview_times: list[float] = []
    uninstall_apply_times: list[float] = []
    reinstall_times: list[float] = []
    for _ in range(5):
        (perf_repo / MANAGED_ITEM).unlink()
        for _sample in range(2):
            _, elapsed, _ = _run(pcodex, perf_repo, env, "repair", "--dry-run", "--json")
            repair_preview_times.append(elapsed)
        _, elapsed, _ = _run(pcodex, perf_repo, env, "repair", "--yes", "--json")
        repair_apply_times.append(elapsed)
        for _sample in range(2):
            _, preview_elapsed, _ = _run(pcodex, perf_repo, env, "uninstall", "--dry-run", "--json")
            uninstall_preview_times.append(preview_elapsed)
        _, uninstall_elapsed, _ = _run(pcodex, perf_repo, env, "uninstall", "--yes", "--json")
        uninstall_apply_times.append(uninstall_elapsed)
        reinstall_started = time.perf_counter()
        _run(pcodex, perf_repo, env, "install", "--apply", "--json")
        reinstall_times.append(time.perf_counter() - reinstall_started)

    schema_root = prefix / "share" / "premode-router" / "schemas"
    public_schema = json.loads((schema_root / "pcodex.lifecycle-operation-public.schema.json").read_text(encoding="utf-8"))
    repair_schema = json.loads((schema_root / "pcodex.repair-operation.schema.json").read_text(encoding="utf-8"))
    uninstall_schema = json.loads((schema_root / "pcodex.uninstall-operation.schema.json").read_text(encoding="utf-8"))
    reinstall_schema = json.loads((schema_root / "pcodex.reinstall-validation.schema.json").read_text(encoding="utf-8"))
    validate_payload_against_schema(repair_apply["public_receipt"], public_schema)
    validate_payload_against_schema(uninstall_apply["public_receipt"], public_schema)
    validate_payload_against_schema(repair_preview["preview_receipt"], public_schema)
    validate_payload_against_schema(uninstall_preview["preview_receipt"], public_schema)
    validate_payload_against_schema(repair_apply["operation"], repair_schema)
    validate_payload_against_schema(uninstall_apply["operation"], uninstall_schema)
    validate_payload_against_schema(reinstall["reinstall_validation"]["operation"], reinstall_schema)
    validate_payload_against_schema(reinstall["reinstall_validation"]["public_receipt"], public_schema)
    unrelated_preserved = (repo / "unrelated.txt").read_text(encoding="utf-8") == "preserve me\n"
    passed = all([
        install.get("lifecycle_after", {}).get("readiness") == "READY",
        status_installed.get("lifecycle", {}).get("readiness") == "READY",
        repair_preview_no_write,
        bool(repair_preview.get("preview_receipt", {}).get("authority_receipt_hash")),
        repair_apply.get("applied") is True,
        status_repaired.get("lifecycle", {}).get("readiness") == "READY",
        uninstall_preview_no_write,
        bool(uninstall_preview.get("preview_receipt", {}).get("authority_receipt_hash")),
        uninstall_apply.get("applied") is True,
        status_uninstalled.get("lifecycle", {}).get("state") == "complete_uninstall",
        reinstall.get("lifecycle_after", {}).get("readiness") == "READY",
        status_reinstalled.get("lifecycle", {}).get("readiness") == "READY",
        modified_repair_code == 2,
        modified_uninstall_code == 2,
        modified_repair_classified,
        modified_uninstall_classified,
        modified_preserved,
        unrelated_preserved,
    ])
    return {
        "schema_version": "pcodex.installed-lifecycle-probe.v1",
        "passed": passed,
        "installed_package_path": str(package_path),
        "environment_prefix": str(prefix),
        "full_cycle": {
            "install": install.get("status"),
            "status_installed": status_installed.get("lifecycle"),
            "repair_preview_no_write": repair_preview_no_write,
            "repair_preview": repair_preview.get("status"),
            "repair_apply": repair_apply.get("status"),
            "status_repaired": status_repaired.get("lifecycle"),
            "uninstall_preview_no_write": uninstall_preview_no_write,
            "uninstall_preview": uninstall_preview.get("status"),
            "uninstall_apply": uninstall_apply.get("status"),
            "status_uninstalled": status_uninstalled.get("lifecycle"),
            "reinstall": reinstall.get("status"),
            "status_reinstalled": status_reinstalled.get("lifecycle"),
            "unrelated_preserved": unrelated_preserved,
        },
        "modified_cycle": {
            "repair_preview_preserved": modified_repair_classified,
            "repair_apply": modified_repair_apply.get("status"),
            "uninstall_preview_preserved": modified_uninstall_classified,
            "uninstall_apply": modified_uninstall_apply.get("status"),
            "content_preserved": modified_preserved,
        },
        "receipts": {
            "repair_public": repair_apply["public_receipt"],
            "repair_preview_public": repair_preview["preview_receipt"],
            "uninstall_public": uninstall_apply["public_receipt"],
            "uninstall_preview_public": uninstall_preview["preview_receipt"],
            "reinstall_validation_public": reinstall["reinstall_validation"]["public_receipt"],
            "schemas_validated": True,
        },
        "private_receipts": {
            "repair": repair_apply["operation"],
            "uninstall": uninstall_apply["operation"],
            "reinstall_validation": reinstall["reinstall_validation"]["operation"],
        },
        "performance": {
            "repair_preview": _percentiles(repair_preview_times),
            "repair_apply": _percentiles(repair_apply_times),
            "uninstall_preview": _percentiles(uninstall_preview_times),
            "uninstall_apply": _percentiles(uninstall_apply_times),
            "reinstall_cycle": _percentiles(reinstall_times),
            "status_advisory_seconds": {
                "installed": round(status_installed_time, 6),
                "repaired": round(status_repaired_time, 6),
                "uninstalled": round(status_uninstalled_time, 6),
                "reinstalled": round(status_reinstalled_time, 6),
            },
            "initial_reinstall_cycle_seconds": round(reinstall_cycle, 6),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcodex", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    args = parser.parse_args()
    result = probe(pcodex=args.pcodex.resolve(), control_root=args.control_root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
