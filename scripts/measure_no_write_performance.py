#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time

from premode.no_write import GovernedRoot, snapshot_roots


def _summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "runs": len(values),
        "p50_seconds": round(statistics.median(ordered), 6),
        "p95_seconds": round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcodex", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()
    repo = args.repo.resolve()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GIT_OPTIONAL_LOCKS": "0"}
    commands = {
        "status_advisory": [str(args.pcodex), "status", "--advisory", "--json", "--repo-root", str(repo)],
        "doctor_advisory": [str(args.pcodex), "doctor", "--advisory", "--json", "--repo-root", str(repo)],
        "run_dry_run": [str(args.pcodex), "run", "Performance measurement task", "--dry-run", "--json", "--repo", str(repo)],
        "uninstall_preview": [str(args.pcodex), "uninstall", "--dry-run", "--json", "--repo-root", str(repo)],
    }
    report: dict[str, object] = {"schema_version": "pcodex.no-write-performance.v1", "iterations": args.iterations, "commands": {}}
    for name, command in commands.items():
        timings = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            completed = subprocess.run(command, cwd=repo, env=env, text=True, capture_output=True, check=False, timeout=120)
            timings.append(time.perf_counter() - started)
            if completed.returncode:
                raise RuntimeError(f"{name} failed with {completed.returncode}")
        report["commands"][name] = _summary(timings)  # type: ignore[index]
    snapshot_timings = []
    for _ in range(args.iterations):
        started = time.perf_counter()
        snapshot = snapshot_roots([GovernedRoot("repository", repo)])
        snapshot_timings.append(time.perf_counter() - started)
        if not snapshot["complete"]:
            raise RuntimeError("snapshot was incomplete")
    report["snapshot_framework"] = _summary(snapshot_timings)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
