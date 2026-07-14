#!/usr/bin/env python3
"""Bind macOS/Linux pipx receipts to one validated release-candidate wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_release_candidate import (  # noqa: E402
    validate as validate_release_candidate,
)


def validate(rc_root: Path, receipt_root: Path) -> dict[str, Any]:
    rc_result = validate_release_candidate(rc_root.resolve())
    rc = json.loads(
        (rc_root / "release/RELEASE-CANDIDATE.json").read_text(encoding="utf-8")
    )
    receipt_schema = json.loads(
        (ROOT / "schemas/pcodex.tool-install-qualification.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    receipts = sorted(receipt_root.resolve().glob("*/tool-install-qualification.json"))
    if len(receipts) != 2:
        raise ValueError("tool-install matrix requires exactly two receipts")
    platforms: dict[str, str] = {}
    for path in receipts:
        if path.is_symlink() or not path.is_file():
            raise ValueError("tool-install receipt must be a regular file")
        payload = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator(receipt_schema).validate(payload)
        if payload["wheel_sha256"] != rc_result["wheel_sha256"]:
            raise ValueError(
                "tool-install receipt wheel differs from release candidate"
            )
        platform = payload["platform"]
        if platform in platforms:
            raise ValueError(f"duplicate tool-install platform: {platform}")
        platforms[platform] = hashlib.sha256(path.read_bytes()).hexdigest()
    if set(platforms) != {"Darwin", "Linux"}:
        raise ValueError("tool-install matrix does not cover macOS and Linux")
    result = {
        "schema_version": "pcodex.tool-install-matrix.v1",
        "passed": True,
        "candidate_commit": rc["candidate_commit"],
        "product_version": rc["product_version"],
        "wheel_sha256": rc_result["wheel_sha256"],
        "tool": "pipx-1.8.0",
        "platform_receipts": [
            {"platform": platform, "receipt_sha256": platforms[platform]}
            for platform in sorted(platforms)
        ],
        "public_registry_used": False,
        "published": False,
    }
    schema = json.loads(
        (ROOT / "schemas/pcodex.tool-install-matrix.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-candidate", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.release_candidate, args.receipt_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
