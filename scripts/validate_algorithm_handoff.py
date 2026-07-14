#!/usr/bin/env python3
"""Validate the sanitized algorithm freeze without opening private evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from premode.algorithm_handoff import validate_algorithm_handoff_files


ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def validate(root: Path = ROOT) -> dict[str, object]:
    handoff_path = root / "release/algorithm-handoff.v1.json"
    schema_path = root / "schemas/pcodex.algorithm-handoff.v1.schema.json"
    manifest_path = root / "premode.product.json"
    result = validate_algorithm_handoff_files(handoff_path, schema_path, manifest_path)
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    baseline = handoff["algorithm_baseline"]
    if handoff["approved_algorithm_commit"] != baseline["commit_sha"]:
        raise ValueError(
            "retained incumbent must bind the approved commit to the baseline"
        )
    actual_tree = _git(root, "show", "-s", "--format=%T", baseline["commit_sha"])
    if actual_tree != baseline["tree_sha"]:
        raise ValueError("algorithm baseline tree does not match the handoff")
    _git(root, "merge-base", "--is-ancestor", baseline["commit_sha"], "HEAD")
    return {
        **result,
        "baseline_commit": baseline["commit_sha"],
        "baseline_tree": baseline["tree_sha"],
        "baseline_is_ancestor": True,
        "private_evidence_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(validate(args.root.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
