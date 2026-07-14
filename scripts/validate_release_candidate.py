#!/usr/bin/env python3
"""Validate one public-safe, non-published pCodex release candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/pcodex.release-candidate.v1.schema.json"
ALLOWLIST = ROOT / "release/release-candidate-allowlist.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("release-candidate path must be a non-empty string")
    path = Path(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or "\\" in value
    ):
        raise ValueError(f"unsafe release-candidate path: {value!r}")
    return value


def _load_manifest(root: Path) -> dict[str, tuple[str, int]]:
    path = root / "SHA256-MANIFEST.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("release-candidate manifest must be a regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("release-candidate manifest must be an array")
    result: dict[str, tuple[str, int]] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("release-candidate manifest item must be an object")
        relative = _safe_relative(item.get("file"))
        digest = item.get("sha256")
        size = item.get("size")
        if relative in result:
            raise ValueError(f"duplicate release-candidate path: {relative}")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"invalid release-candidate digest: {relative}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"invalid release-candidate size: {relative}")
        result[relative] = (digest, size)
    return result


def _read_json(root: Path, relative: str) -> dict[str, Any]:
    path = root / _safe_relative(relative)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"release-candidate JSON is not regular: {relative}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"release-candidate JSON is not an object: {relative}")
    return payload


def _subject_map(items: object, *, label: str) -> dict[str, str]:
    if not isinstance(items, list):
        raise ValueError(f"{label} subjects must be an array")
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{label} subject must be an object")
        name = _safe_relative(item.get("name"))
        digest = item.get("digest")
        sha256 = digest.get("sha256") if isinstance(digest, dict) else None
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError(f"{label} subject has no valid SHA-256: {name}")
        if name in result:
            raise ValueError(f"{label} has duplicate subject: {name}")
        result[name] = sha256
    return result


def _sbom_subjects(sbom: dict[str, Any]) -> dict[str, tuple[str, int]]:
    result: dict[str, tuple[str, int]] = {}
    for component in sbom.get("components", []):
        if not isinstance(component, dict):
            raise ValueError("SBOM component must be an object")
        names = [
            item.get("value")
            for item in component.get("properties", [])
            if isinstance(item, dict) and item.get("name") == "pcodex:release-path"
        ]
        hashes = [
            item.get("content")
            for item in component.get("hashes", [])
            if isinstance(item, dict) and item.get("alg") == "SHA-256"
        ]
        sizes = [
            item.get("value")
            for item in component.get("properties", [])
            if isinstance(item, dict) and item.get("name") == "pcodex:size"
        ]
        if len(names) != 1 or len(hashes) != 1 or len(sizes) != 1:
            raise ValueError("SBOM component must bind one path, SHA-256, and size")
        name = _safe_relative(names[0])
        if name in result:
            raise ValueError(f"SBOM has duplicate subject: {name}")
        try:
            size = int(str(sizes[0]))
        except ValueError as exc:
            raise ValueError(f"SBOM subject has invalid size: {name}") from exc
        if size < 0 or str(size) != str(sizes[0]):
            raise ValueError(f"SBOM subject has invalid size: {name}")
        result[name] = (str(hashes[0]), size)
    return result


def validate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    policy = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    bundled_policy = root / "release/release-candidate-allowlist.json"
    if (
        bundled_policy.is_symlink()
        or bundled_policy.read_bytes() != ALLOWLIST.read_bytes()
    ):
        raise ValueError("bundled release-candidate allowlist differs from authority")
    receipt_path = root / "release/RELEASE-CANDIDATE.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    bundled_schema = root / "schemas/pcodex.release-candidate.v1.schema.json"
    if (
        bundled_schema.is_symlink()
        or bundled_schema.read_bytes() != SCHEMA.read_bytes()
    ):
        raise ValueError("bundled release-candidate schema differs from authority")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)

    matrix = {(item["system"], item["python"]) for item in receipt["supported_matrix"]}
    expected_matrix = {
        (system, python)
        for system in ("Darwin", "Linux")
        for python in ("3.11", "3.12", "3.13")
    }
    if matrix != expected_matrix:
        raise ValueError("release candidate does not cover the exact supported matrix")

    manifest = _load_manifest(root)
    checksums_path = root / "SHA256SUMS"
    if checksums_path.is_symlink() or not checksums_path.is_file():
        raise ValueError("SHA256SUMS must be a regular file")
    actual: set[str] = set()
    directories: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"release-candidate contains a symlink: {relative}")
        if path.is_dir():
            directories.add(relative)
        elif path.is_file():
            if relative not in {"SHA256-MANIFEST.json", "SHA256SUMS"}:
                actual.add(relative)
        else:
            raise ValueError(
                f"release-candidate contains an unsupported object: {relative}"
            )
    wheels = sorted(name for name in actual if name.endswith(".whl"))
    sdists = sorted(name for name in actual if name.endswith(".tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("release candidate requires exactly one wheel and one sdist")
    matrix_paths = {
        f"receipts/matrix/{system.lower()}-py{python}.json"
        for system in ("Darwin", "Linux")
        for python in ("3.11", "3.12", "3.13")
    }
    expected_paths = {
        *policy["source_documents"],
        *policy["source_authorities"],
        *policy["required_release_files"],
        wheels[0],
        sdists[0],
        "release/release-candidate-allowlist.json",
        "release/SUPPORTED-VERSIONS.json",
        "release/RELEASE-CANDIDATE.json",
        "schemas/pcodex.release-candidate.v1.schema.json",
        "schemas/pcodex.release-qualification.schema.json",
        "schemas/pcodex.release-provenance.schema.json",
        "receipts/reproducibility.json",
        "receipts/canonical-qualification.json",
        *matrix_paths,
    }
    if actual != expected_paths:
        raise ValueError("release candidate contains missing or unexpected files")
    expected_directories = {
        parent.as_posix()
        for relative in expected_paths | {"SHA256-MANIFEST.json", "SHA256SUMS"}
        for parent in Path(relative).parents
        if parent.as_posix() != "."
    }
    if directories != expected_directories:
        raise ValueError("release candidate contains missing or unexpected directories")
    if set(manifest) != actual:
        raise ValueError("release-candidate manifest does not exactly enumerate files")
    for relative, (expected_digest, expected_size) in manifest.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"release-candidate member is not regular: {relative}")
        resolved = path.resolve()
        if root not in resolved.parents:
            raise ValueError(f"release-candidate member escapes root: {relative}")
        if _digest(path) != expected_digest or path.stat().st_size != expected_size:
            raise ValueError(
                f"release-candidate bytes do not match manifest: {relative}"
            )

    checksum_lines = checksums_path.read_text(encoding="utf-8").splitlines()
    expected_lines = [
        f"{digest}  {relative}"
        for relative, (digest, _size) in sorted(manifest.items())
    ]
    if checksum_lines != expected_lines:
        raise ValueError("SHA256SUMS does not exactly mirror the JSON manifest")

    prohibited_parts = set(policy["prohibited_parts"])
    for relative in actual | {"SHA256-MANIFEST.json", "SHA256SUMS"}:
        if prohibited_parts.intersection(Path(relative).parts):
            raise ValueError(f"prohibited release-candidate member: {relative}")
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix in {".whl", ".gz", ".zip"}:
            continue
        if path.relative_to(root).as_posix() in set(
            policy["content_scan_exempt_exact_authorities"]
        ):
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in policy["prohibited_text"]:
            if pattern in text:
                raise ValueError(
                    f"prohibited public text in {path.relative_to(root)}: {pattern}"
                )
        for pattern in policy["prohibited_text_regex"]:
            if re.search(pattern, text):
                raise ValueError(
                    f"prohibited public text pattern in {path.relative_to(root)}"
                )
        if path.suffix in set(policy["prohibited_suffixes"]):
            raise ValueError(f"prohibited release-candidate suffix: {path.name}")

    source_bound = [*policy["source_documents"], *policy["source_authorities"]]
    for relative in source_bound:
        authority = ROOT / relative
        if (
            not authority.is_file()
            or (root / relative).read_bytes() != authority.read_bytes()
        ):
            raise ValueError(
                f"bundled source authority differs from checkout: {relative}"
            )

    source_checkout_only = set(policy["source_checkout_only_references"])
    external_evidence = set(policy["external_evidence_references"])
    for relative in policy["source_documents"]:
        text = (root / relative).read_text(encoding="utf-8")
        references = set(re.findall(r"docs/[A-Za-z0-9_./-]+\.md", text))
        references.update(
            re.findall(
                r"(?:scripts/[A-Za-z0-9_./-]+\.(?:py|sh)|(?:schemas|contracts/goldens|release)/[A-Za-z0-9_./-]+\.json)",
                text,
            )
        )
        for target in re.findall(r"\]\(([^)#?]+\.md)(?:#[^)]+)?\)", text):
            candidate = (Path(relative).parent / target).as_posix()
            references.add(candidate)
        missing = {
            target
            for target in references
            if target not in actual
            and target not in source_checkout_only
            and target not in external_evidence
        }
        if missing:
            raise ValueError(
                f"release-candidate documentation has missing references: {sorted(missing)}"
            )
    referenced_source_only = {
        target
        for relative in policy["source_documents"]
        for target in re.findall(
            r"scripts/[A-Za-z0-9_./-]+\.(?:py|sh)",
            (root / relative).read_text(encoding="utf-8"),
        )
    }
    if referenced_source_only != source_checkout_only:
        raise ValueError("source-checkout-only reference policy is stale or incomplete")
    referenced_external = {
        target
        for relative in policy["source_documents"]
        for target in re.findall(
            r"docs/[A-Za-z0-9_./-]+\.md",
            (root / relative).read_text(encoding="utf-8"),
        )
        if target not in actual
    }
    if referenced_external != external_evidence:
        raise ValueError("external evidence reference policy is stale or incomplete")

    qualification_schema_path = (
        ROOT / "schemas/pcodex.release-qualification.schema.json"
    )
    bundled_qualification_schema = (
        root / "schemas/pcodex.release-qualification.schema.json"
    )
    if (
        bundled_qualification_schema.read_bytes()
        != qualification_schema_path.read_bytes()
    ):
        raise ValueError("bundled qualification schema differs from authority")
    qualification_schema = json.loads(
        qualification_schema_path.read_text(encoding="utf-8")
    )
    qualification_validator = Draft202012Validator(qualification_schema)
    matrix_authority = {
        (item["system"], item["python"]): item for item in receipt["supported_matrix"]
    }
    matrix_qualifications: dict[tuple[str, str], dict[str, Any]] = {}
    qualification_subjects: dict[str, str] | None = None
    for system, python in expected_matrix:
        relative = f"receipts/matrix/{system.lower()}-py{python}.json"
        qualification = _read_json(root, relative)
        qualification_validator.validate(qualification)
        if (
            qualification["commit"] != receipt["candidate_commit"]
            or qualification["product_version"] != receipt["product_version"]
            or qualification["platform"]["system"] != system
            or not qualification["platform"]["python"].startswith(f"{python}.")
            or qualification["codex_plugin"]["live_codex_version"] != "0.143.0"
        ):
            raise ValueError(f"matrix qualification identity mismatch: {relative}")
        if (
            _digest(root / relative)
            != matrix_authority[(system, python)]["qualification_sha256"]
        ):
            raise ValueError(f"matrix qualification hash mismatch: {relative}")
        subjects_for_cell = _subject_map(
            qualification["artifacts"], label=f"qualification {system}/{python}"
        )
        if qualification_subjects is None:
            qualification_subjects = subjects_for_cell
        elif subjects_for_cell != qualification_subjects:
            raise ValueError("matrix qualification subjects are not reproducible")
        matrix_qualifications[(system, python)] = qualification
    canonical_path = root / "receipts/canonical-qualification.json"
    linux_path = root / "receipts/matrix/linux-py3.11.json"
    if canonical_path.read_bytes() != linux_path.read_bytes():
        raise ValueError("canonical qualification is not the Linux/Python 3.11 cell")

    reproducibility_path = root / "receipts/reproducibility.json"
    if _digest(reproducibility_path) != receipt["reproducibility_receipt_sha256"]:
        raise ValueError("reproducibility receipt hash mismatch")
    reproducibility = _read_json(root, "receipts/reproducibility.json")
    if (
        reproducibility.get("schema_version") != "pcodex.reproducibility.v1"
        or reproducibility.get("passed") is not True
        or reproducibility.get("matrix_receipts") != 6
        or not isinstance(reproducibility.get("artifacts"), dict)
        or qualification_subjects is None
    ):
        raise ValueError("invalid reproducibility receipt")
    expected_by_name = {
        Path(name).name: digest for name, digest in qualification_subjects.items()
    }
    if set(reproducibility["artifacts"]) != set(expected_by_name):
        raise ValueError("reproducibility artifacts disagree with qualification")
    for name, cell_hashes in reproducibility["artifacts"].items():
        if (
            not isinstance(cell_hashes, dict)
            or len(cell_hashes) != 6
            or set(cell_hashes.values()) != {expected_by_name[name]}
        ):
            raise ValueError(f"reproducibility hash mismatch: {name}")

    provenance_schema_path = ROOT / "schemas/pcodex.release-provenance.schema.json"
    if (
        root / "schemas/pcodex.release-provenance.schema.json"
    ).read_bytes() != provenance_schema_path.read_bytes():
        raise ValueError("bundled provenance schema differs from authority")
    provenance = _read_json(root, "release/provenance.intoto.json")
    Draft202012Validator(
        json.loads(provenance_schema_path.read_text(encoding="utf-8"))
    ).validate(provenance)
    sbom = _read_json(root, "release/SBOM.cyclonedx.json")
    build_definition = provenance["predicate"]["buildDefinition"]
    dependency = build_definition["resolvedDependencies"][0]
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
        build_definition["externalParameters"]["commit"] != receipt["candidate_commit"]
        or dependency["digest"]["gitCommit"] != receipt["candidate_commit"]
        or not isinstance(sbom_component, dict)
        or sbom_component.get("name") != "premode-router"
        or sbom_component.get("version") != receipt["product_version"]
        or sbom_commits != [receipt["candidate_commit"]]
    ):
        raise ValueError("release provenance or SBOM identity disagrees with RC")
    authority_hashes = build_definition["internalParameters"]["authority_file_sha256"]
    expected_authority_hashes = {
        relative: _digest(root / relative)
        for relative in policy["provenance_authorities"]
    }
    if authority_hashes != expected_authority_hashes:
        raise ValueError("provenance authority hashes disagree with RC bytes")
    sbom_subjects = _sbom_subjects(sbom)
    if not (
        _subject_map(provenance["subject"], label="provenance")
        == {name: digest for name, (digest, _size) in sbom_subjects.items()}
        == qualification_subjects
    ):
        raise ValueError("qualification, provenance, and SBOM subjects disagree")
    for relative, binding in sbom_subjects.items():
        if manifest.get(relative) != binding:
            raise ValueError(f"SBOM subject size or digest disagrees: {relative}")
    for relative, expected_digest in qualification_subjects.items():
        if manifest.get(relative, (None, None))[0] != expected_digest:
            raise ValueError(f"qualified subject bytes are not in RC: {relative}")

    supported = _read_json(root, "release/SUPPORTED-VERSIONS.json")
    if supported != {
        "schema_version": "pcodex.supported-versions.v1",
        "product_version": receipt["product_version"],
        "candidate_commit": receipt["candidate_commit"],
        "platforms": ["macos", "linux"],
        "python": ["3.11", "3.12", "3.13"],
        "codex": ["0.143.x"],
        "openclaw": ["2026.4.14"],
        "windows_supported": False,
        "public_registry_published": False,
    }:
        raise ValueError("supported-version authority disagrees with RC")

    subjects = {
        item["path"]: (item["sha256"], item["size"])
        for item in receipt["release_subjects"]
    }
    if len(subjects) != len(receipt["release_subjects"]):
        raise ValueError("release-candidate receipt has duplicate subjects")
    required_subjects = {
        wheels[0],
        sdists[0],
        *policy["required_release_files"],
    }
    if set(subjects) != required_subjects:
        raise ValueError("release-candidate receipt subjects are not exact")
    for relative, expected in subjects.items():
        if manifest.get(relative) != expected:
            raise ValueError(
                f"release-candidate subject is not manifest-bound: {relative}"
            )
    return {
        "schema_version": "pcodex.release-candidate-validation.v1",
        "passed": True,
        "candidate_commit": receipt["candidate_commit"],
        "product_version": receipt["product_version"],
        "matrix_cells": len(matrix),
        "manifest_file_count": len(manifest),
        "wheel_sha256": manifest[wheels[0]][0],
        "sdist_sha256": manifest[sdists[0]][0],
        "published": False,
    }


def validate_archive(archive: Path, expected_root: Path) -> dict[str, Any]:
    result = validate(expected_root)
    expected = {
        path.relative_to(expected_root).as_posix()
        for path in expected_root.rglob("*")
        if path.is_file()
    }
    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError(
                "release-candidate archive members disagree with directory"
            )
        if len(names) > 10_000:
            raise ValueError("release-candidate archive has too many members")
        total_size = 0
        for info in handle.infolist():
            _safe_relative(info.filename)
            unix_type = stat.S_IFMT(info.external_attr >> 16)
            if info.is_dir() or unix_type not in {0, stat.S_IFREG}:
                raise ValueError(
                    f"unsupported release-candidate archive member: {info.filename}"
                )
            if info.flag_bits & 0x1:
                raise ValueError(f"encrypted release-candidate member: {info.filename}")
            if info.file_size > 32 * 1024 * 1024:
                raise ValueError(f"oversized release-candidate member: {info.filename}")
            total_size += info.file_size
            if total_size > 256 * 1024 * 1024:
                raise ValueError("release-candidate archive is too large")
            if info.file_size / max(info.compress_size, 1) > 200.0:
                raise ValueError(
                    f"release-candidate compression ratio is unsafe: {info.filename}"
                )
            if handle.read(info) != (expected_root / info.filename).read_bytes():
                raise ValueError(
                    f"release-candidate archive bytes differ: {info.filename}"
                )
    result["archive_sha256"] = _digest(archive)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    result = (
        validate_archive(args.archive.resolve(), args.root.resolve())
        if args.archive
        else validate(args.root.resolve())
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
