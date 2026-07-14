#!/usr/bin/env python3
"""Review hash-locked release dependencies against an explicit baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)\s*\\?$")
HASH = re.compile(r"^--hash=sha256:([0-9a-f]{64})\s*\\?$")


def _parse(text: str, *, label: str) -> dict[str, dict[str, Any]]:
    packages: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        package = PACKAGE.fullmatch(stripped)
        if package:
            name = package.group(1).lower().replace("_", "-")
            if name in packages:
                raise ValueError(f"duplicate dependency in {label}: {name}")
            packages[name] = {"version": package.group(2), "hashes": []}
            current = name
            continue
        digest = HASH.fullmatch(stripped)
        if digest and current is not None:
            packages[current]["hashes"].append(digest.group(1))
            continue
        raise ValueError(f"unsupported lock syntax in {label} at line {number}")
    if not packages or any(not item["hashes"] for item in packages.values()):
        raise ValueError(f"every dependency in {label} must be pinned and hashed")
    return packages


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def review(base: str, paths: list[Path]) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("dependency review base must be a full commit SHA")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, "HEAD"],
        cwd=ROOT,
        check=True,
    )
    current_commit = _git("rev-parse", "HEAD").strip()
    files: list[dict[str, Any]] = []
    for path in paths:
        absolute = (ROOT / path).resolve()
        if ROOT not in absolute.parents or not absolute.is_file():
            raise ValueError(f"dependency lock is unavailable: {path}")
        relative = absolute.relative_to(ROOT).as_posix()
        current_text = absolute.read_text(encoding="utf-8")
        current = _parse(current_text, label=relative)
        baseline_result = subprocess.run(
            ["git", "show", f"{base}:{relative}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        baseline = (
            _parse(baseline_result.stdout, label=f"{base}:{relative}")
            if baseline_result.returncode == 0
            else {}
        )
        names = set(current) | set(baseline)
        files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(current_text.encode()).hexdigest(),
                "package_count": len(current),
                "added": sorted(name for name in names if name not in baseline),
                "removed": sorted(name for name in names if name not in current),
                "changed": sorted(
                    name
                    for name in names & set(current) & set(baseline)
                    if current[name] != baseline[name]
                ),
            }
        )
    return {
        "schema_version": "pcodex.dependency-lock-review.v1",
        "passed": True,
        "base_commit": base,
        "candidate_commit": current_commit,
        "files": files,
        "all_current_dependencies_exactly_pinned_and_hashed": True,
        "vulnerability_audit_separate": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("locks", nargs="+", type=Path)
    args = parser.parse_args()
    result = review(args.base, args.locks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
