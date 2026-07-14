#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

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
    instances: dict[str, Any] = {}
    for schema_path, instance_path in pairs:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        instance = json.loads(instance_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(instance)
        instances[instance_path.name] = instance
        validated.append(instance_path.relative_to(output).as_posix())
    sbom = json.loads(
        (output / "release/SBOM.cyclonedx.json").read_text(encoding="utf-8")
    )
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
        raise ValueError("unsupported SBOM contract")
    handoff_path = output / "release/algorithm-handoff.v1.json"
    handoff_schema_path = output / "release/pcodex.algorithm-handoff.v1.schema.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff_schema = json.loads(handoff_schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(handoff_schema)
    Draft202012Validator(handoff_schema).validate(handoff)

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    authority_digests = {
        "release/algorithm-handoff.v1.json": digest(handoff_path),
        "release/pcodex.algorithm-handoff.v1.schema.json": digest(handoff_schema_path),
    }
    qualification = instances["qualification-summary.json"]
    qualification_subjects = {
        str(item["name"]): str(item["digest"]["sha256"])
        for item in qualification["artifacts"]
    }
    provenance = instances["provenance.intoto.json"]
    provenance_subjects = {
        str(item["name"]): str(item["digest"]["sha256"])
        for item in provenance["subject"]
    }
    sbom_components = {
        next(
            prop["value"]
            for prop in item.get("properties", [])
            if prop.get("name") == "pcodex:release-path"
        ): next(
            value["content"]
            for value in item.get("hashes", [])
            if value.get("alg") == "SHA-256"
        )
        for item in sbom.get("components", [])
    }
    manifest = {
        item["file"]: item["sha256"]
        for item in json.loads(
            (output / "SHA256-MANIFEST.json").read_text(encoding="utf-8")
        )
    }
    for relative, expected in authority_digests.items():
        if qualification_subjects.get(relative) != expected:
            raise ValueError(f"qualification does not bind {relative}")
        if provenance_subjects.get(relative) != expected:
            raise ValueError(f"provenance does not bind {relative}")
        if sbom_components.get(relative) != expected:
            raise ValueError(f"SBOM does not bind {relative}")
        if manifest.get(relative) != expected:
            raise ValueError(f"SHA256 manifest does not bind {relative}")
    validated.extend(authority_digests)
    return {
        "passed": True,
        "validated": validated,
        "sbom": "CycloneDX-1.5",
        "algorithm_authorities": authority_digests,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
