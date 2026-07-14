#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def validate(output: Path) -> dict[str, object]:
    pairs = (
        (
            ROOT / "schemas/pcodex.release-qualification.schema.json",
            output / "receipts/qualification-summary.json",
        ),
        (
            ROOT / "schemas/pcodex.release-provenance.schema.json",
            output / "release/provenance.intoto.json",
        ),
    )
    validated: list[str] = []
    for schema_path, instance_path in pairs:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        instance = json.loads(instance_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(instance)
        validated.append(instance_path.relative_to(output).as_posix())
    sbom = json.loads(
        (output / "release/SBOM.cyclonedx.json").read_text(encoding="utf-8")
    )
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
        raise ValueError("unsupported SBOM contract")
    return {"passed": True, "validated": validated, "sbom": "CycloneDX-1.5"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
