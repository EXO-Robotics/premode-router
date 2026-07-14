#!/usr/bin/env python3
"""Validate five private first-run receipts and emit a content-free decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import shlex
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/pcodex.first-run-study-receipt.v1.schema.json"
FIXTURES = {f"fixture-{index:02d}" for index in range(1, 6)}


def _transcript_covers_claims(receipt: dict[str, Any]) -> bool:
    parsed: list[list[str]] = []
    try:
        parsed = [shlex.split(command) for command in receipt["commands"]]
    except ValueError:
        return False
    dry_run = any(command[:3] == ["pcodex", "run", "--dry-run"] for command in parsed)
    installs = [
        index
        for index, command in enumerate(parsed)
        if command[:4] == ["pcodex", "integrate", "codex", "--write"]
    ]
    uninstalls = [
        index
        for index, command in enumerate(parsed)
        if command[:4] == ["pcodex", "integrate", "codex", "--uninstall"]
        and "--dry-run" not in command
    ]
    ordered_reinstall = bool(
        len(installs) >= 3
        and uninstalls
        and installs[0] < installs[1] < uninstalls[0]
        and any(index > uninstalls[0] for index in installs[2:])
    )
    managed_uninstall = any(
        command[:3] == ["pcodex", "uninstall", "--yes"] for command in parsed
    )
    fixture_id = receipt["fixture"]["id"]
    fixture_specific = True
    if fixture_id == "fixture-01":
        fixture_specific = receipt["runtime"]["codex_version"] == "absent"
    elif fixture_id == "fixture-03":
        fixture_specific = str(receipt["runtime"]["codex_version"]).startswith("0.143.")
    elif fixture_id == "fixture-04":
        fixture_specific = (
            any(
                index > uninstalls[0]
                and parsed[index][:4] == ["pcodex", "integrate", "codex", "--write"]
                and "--migrate" in parsed[index]
                for index in installs
            )
            if uninstalls
            else False
        )
    elif fixture_id == "fixture-05":
        fixture_specific = (
            any(
                index > uninstalls[0]
                and parsed[index][:4] == ["pcodex", "integrate", "codex", "--write"]
                and "--with-mcp" in parsed[index]
                for index in installs
            )
            if uninstalls
            else False
        )
    return dry_run and ordered_reinstall and managed_uninstall and fixture_specific


def validate_receipts(
    paths: list[Path], study_kit: Path, schema_path: Path = SCHEMA
) -> dict[str, Any]:
    from jsonschema import Draft202012Validator

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    study_kit_bytes = study_kit.read_bytes()
    kit = json.loads(study_kit_bytes)
    kit_fixtures = {item["id"]: item["sha256"] for item in kit.get("fixtures", [])}
    expected_wheel = kit.get("wheel", {})
    expected_commit = kit.get("candidate_commit")
    validator = Draft202012Validator(schema)
    receipts: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            invalid.append({"file": path.name, "reason": type(exc).__name__})
            continue
        errors = list(validator.iter_errors(payload))
        if errors:
            invalid.append(
                {
                    "file": path.name,
                    "reason": "schema_validation_failed",
                    "error_count": len(errors),
                }
            )
        else:
            receipts.append(payload)

    tester_ids = {item["anonymous_tester_id"] for item in receipts}
    fixtures = {item["fixture"]["id"] for item in receipts}
    artifact_hashes = {item["artifact"]["sha256"] for item in receipts}
    commits = {item["artifact"]["candidate_commit"] for item in receipts}
    activated = [
        item
        for item in receipts
        if item["completed"] and item["lifecycle"]["first_dry_run"]
    ]
    times = [float(item["timing"]["first_use_seconds"]) for item in activated]
    median_seconds = statistics.median(times) if times else None
    undocumented_help_count = sum(len(item["undocumented_help"]) for item in receipts)
    uninstall_successes = sum(bool(item["lifecycle"]["uninstall"]) for item in receipts)
    reinstall_successes = sum(bool(item["lifecycle"]["reinstall"]) for item in receipts)
    install_twice_successes = sum(
        bool(item["lifecycle"]["install_twice"]) for item in receipts
    )
    preservation_successes = sum(
        bool(item["lifecycle"]["unrelated_state_preserved"]) for item in receipts
    )
    documentation_successes = sum(
        bool(item["documentation"]["sufficient"]) for item in receipts
    )
    transcript_successes = sum(_transcript_covers_claims(item) for item in receipts)
    monotonic_timing_successes = sum(
        float(item["timing"]["completion_seconds"])
        >= float(item["timing"]["first_use_seconds"])
        for item in receipts
    )
    kit_bindings_valid = all(
        item["artifact"]["filename"] == expected_wheel.get("filename")
        and item["artifact"]["sha256"] == expected_wheel.get("sha256")
        and item["artifact"]["candidate_commit"] == expected_commit
        and item["fixture"]["sha256"] == kit_fixtures.get(item["fixture"]["id"])
        for item in receipts
    )
    study_complete = all(
        (
            len(paths) == 5,
            not invalid,
            len(receipts) == 5,
            len(tester_ids) == 5,
            fixtures == FIXTURES,
            len(artifact_hashes) == 1,
            len(commits) == 1,
            set(kit_fixtures) == FIXTURES,
            kit_bindings_valid,
        )
    )
    activation_rate = len(activated) / 5 if study_complete else 0.0
    passed = all(
        (
            study_complete,
            activation_rate >= 0.95,
            median_seconds is not None and median_seconds < 600,
            undocumented_help_count == 0,
            uninstall_successes == 5,
            reinstall_successes == 5,
            install_twice_successes == 5,
            preservation_successes == 5,
            documentation_successes == 5,
            transcript_successes == 5,
            monotonic_timing_successes == 5,
        )
    )
    return {
        "schema_version": "pcodex.first-run-study-summary.v1",
        "status": "passed" if passed else "failed",
        "receipt_count": len(receipts),
        "invalid_receipts": invalid,
        "unique_tester_count": len(tester_ids),
        "fixture_coverage": sorted(fixtures),
        "activation_rate": activation_rate,
        "median_first_use_seconds": median_seconds,
        "first_use_seconds_range": [min(times), max(times)] if times else None,
        "product_target_under_five_minutes": bool(
            median_seconds is not None and median_seconds < 300
        ),
        "g1_minimum_under_ten_minutes": bool(
            median_seconds is not None and median_seconds < 600
        ),
        "undocumented_help_count": undocumented_help_count,
        "uninstall_successes": uninstall_successes,
        "reinstall_successes": reinstall_successes,
        "install_twice_successes": install_twice_successes,
        "unrelated_state_preservation_successes": preservation_successes,
        "documentation_sufficient_count": documentation_successes,
        "transcript_evidence_successes": transcript_successes,
        "monotonic_timing_successes": monotonic_timing_successes,
        "study_kit_sha256": hashlib.sha256(study_kit_bytes).hexdigest(),
        "study_kit_bindings_valid": kit_bindings_valid,
        "private_receipt_content_included": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", nargs="+", type=Path)
    parser.add_argument("--study-kit", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=SCHEMA)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = validate_receipts(args.receipts, args.study_kit, args.schema)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"first-run study: {result['status']}")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
