#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("release path must be a non-empty string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"unsafe release path: {value!r}")
    return value


def _regular_digest(output: Path, relative: str) -> tuple[str, int]:
    relative = _safe_relative(relative)
    path = output / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"release subject is not a regular file: {relative}")
    resolved_output = output.resolve()
    resolved = path.resolve()
    if resolved_output not in resolved.parents:
        raise ValueError(f"release subject escapes output root: {relative}")
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _subject_map(items: object, *, label: str) -> dict[str, str]:
    if not isinstance(items, list):
        raise ValueError(f"{label} subjects must be a list")
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{label} subject must be an object")
        name = _safe_relative(item.get("name"))
        digest = item.get("digest")
        sha256 = digest.get("sha256") if isinstance(digest, dict) else None
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise ValueError(f"{label} subject has no SHA-256: {name}")
        if name in result:
            raise ValueError(f"{label} has duplicate subject: {name}")
        result[name] = sha256
    return result


def _sbom_map(sbom: dict[str, Any]) -> dict[str, tuple[str, int]]:
    result: dict[str, tuple[str, int]] = {}
    for item in sbom.get("components", []):
        if not isinstance(item, dict):
            raise ValueError("SBOM component must be an object")
        paths = [
            prop.get("value")
            for prop in item.get("properties", [])
            if isinstance(prop, dict) and prop.get("name") == "pcodex:release-path"
        ]
        hashes = [
            value.get("content")
            for value in item.get("hashes", [])
            if isinstance(value, dict) and value.get("alg") == "SHA-256"
        ]
        sizes = [
            prop.get("value")
            for prop in item.get("properties", [])
            if isinstance(prop, dict) and prop.get("name") == "pcodex:size"
        ]
        if len(paths) != 1 or len(hashes) != 1 or len(sizes) != 1:
            raise ValueError("SBOM component must bind one path, SHA-256, and size")
        name = _safe_relative(paths[0])
        if name in result:
            raise ValueError(f"SBOM has duplicate component: {name}")
        try:
            size = int(str(sizes[0]))
        except ValueError as exc:
            raise ValueError(f"SBOM component has invalid size: {name}") from exc
        if size < 0 or str(size) != str(sizes[0]):
            raise ValueError(f"SBOM component has invalid size: {name}")
        result[name] = (str(hashes[0]), size)
    return result


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

    authority_digests = {
        "release/algorithm-handoff.v1.json": hashlib.sha256(
            handoff_path.read_bytes()
        ).hexdigest(),
        "release/pcodex.algorithm-handoff.v1.schema.json": hashlib.sha256(
            handoff_schema_path.read_bytes()
        ).hexdigest(),
    }
    qualification = instances["qualification-summary.json"]
    qualification_subjects = _subject_map(
        qualification["artifacts"], label="qualification"
    )
    provenance = instances["provenance.intoto.json"]
    commit = qualification["commit"]
    product_version = qualification["product_version"]
    build_definition = provenance["predicate"]["buildDefinition"]
    dependency = build_definition["resolvedDependencies"][0]
    if (
        build_definition["externalParameters"]["commit"] != commit
        or dependency["digest"]["gitCommit"] != commit
    ):
        raise ValueError("provenance commit identity disagrees with qualification")
    policy = json.loads(
        (ROOT / "release/release-candidate-allowlist.json").read_text(encoding="utf-8")
    )
    expected_authority_hashes = {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in policy["provenance_authorities"]
    }
    if (
        build_definition["internalParameters"]["authority_file_sha256"]
        != expected_authority_hashes
    ):
        raise ValueError("provenance authority hashes disagree with checkout")
    sbom_metadata = sbom.get("metadata")
    sbom_component = (
        sbom_metadata.get("component") if isinstance(sbom_metadata, dict) else None
    )
    sbom_commits = [
        item.get("value")
        for item in (
            sbom_metadata.get("properties", [])
            if isinstance(sbom_metadata, dict)
            else []
        )
        if isinstance(item, dict) and item.get("name") == "pcodex:commit"
    ]
    if (
        not isinstance(sbom_component, dict)
        or sbom_component.get("name") != "premode-router"
        or sbom_component.get("version") != product_version
        or sbom_commits != [commit]
    ):
        raise ValueError("SBOM product or commit identity disagrees with qualification")
    provenance_subjects = _subject_map(provenance["subject"], label="provenance")
    sbom_components = _sbom_map(sbom)
    if not (
        qualification_subjects
        == provenance_subjects
        == {name: digest for name, (digest, _size) in sbom_components.items()}
    ):
        raise ValueError(
            "qualification, provenance, and SBOM release subjects disagree"
        )
    expected_suffixes = {".whl", ".tar.gz"}
    package_subjects = {
        name
        for name in qualification_subjects
        if name.endswith(".whl") or name.endswith(".tar.gz")
    }
    if (
        len(package_subjects) != 2
        or {".whl" if name.endswith(".whl") else ".tar.gz" for name in package_subjects}
        != expected_suffixes
    ):
        raise ValueError(
            "release subjects must contain exactly one wheel and one sdist"
        )
    if set(qualification_subjects) != package_subjects | set(authority_digests):
        raise ValueError("release subjects contain missing or unexpected authorities")

    manifest_items = json.loads(
        (output / "SHA256-MANIFEST.json").read_text(encoding="utf-8")
    )
    if not isinstance(manifest_items, list):
        raise ValueError("SHA256 manifest must be an array")
    manifest: dict[str, tuple[str, int]] = {}
    for item in manifest_items:
        if not isinstance(item, dict):
            raise ValueError("SHA256 manifest item must be an object")
        relative = _safe_relative(item.get("file"))
        if relative == "SHA256-MANIFEST.json" or relative in manifest:
            raise ValueError(f"invalid or duplicate SHA256 manifest path: {relative}")
        digest_value = item.get("sha256")
        size = item.get("size")
        if not isinstance(digest_value, str) or len(digest_value) != 64:
            raise ValueError(f"invalid SHA256 manifest digest: {relative}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"invalid SHA256 manifest size: {relative}")
        manifest[relative] = (digest_value, size)

    actual_files: set[str] = set()
    for path in output.rglob("*"):
        relative = path.relative_to(output).as_posix()
        if path.is_symlink():
            raise ValueError(f"release output contains a symlink: {relative}")
        if path.is_file() and relative != "SHA256-MANIFEST.json":
            actual_files.add(relative)
        elif not path.is_file() and not path.is_dir():
            raise ValueError(
                f"release output contains an unsupported object: {relative}"
            )
    if set(manifest) != actual_files:
        raise ValueError("SHA256 manifest does not exactly enumerate release output")
    for relative, manifest_binding in manifest.items():
        if _regular_digest(output, relative) != manifest_binding:
            raise ValueError(
                f"SHA256 manifest does not match release bytes: {relative}"
            )
    for relative, subject_digest in qualification_subjects.items():
        actual, size = _regular_digest(output, relative)
        if (
            actual != subject_digest
            or manifest.get(relative, (None, None))[0] != subject_digest
            or sbom_components.get(relative) != (subject_digest, size)
        ):
            raise ValueError(f"release metadata does not bind actual bytes: {relative}")
    for relative, authority_digest in authority_digests.items():
        if qualification_subjects.get(relative) != authority_digest:
            raise ValueError(f"release authority digest mismatch: {relative}")
    validated.extend(authority_digests)
    return {
        "passed": True,
        "validated": validated,
        "sbom": "CycloneDX-1.5",
        "algorithm_authorities": authority_digests,
        "release_subjects": qualification_subjects,
        "manifest_file_count": len(manifest),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
