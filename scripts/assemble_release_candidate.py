#!/usr/bin/env python3
"""Assemble one deterministic, public-safe RC from six qualified matrix cells."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_release_artifacts import compare  # noqa: E402
from scripts.validate_release_candidate import validate, validate_archive  # noqa: E402
from scripts.validate_release_metadata import (  # noqa: E402
    validate as validate_release_metadata,
)


ALLOWLIST = ROOT / "release/release-candidate-allowlist.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_regular(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"release-candidate source is not regular: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def _assert_source(source: Path, commit: str) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    if head != commit or dirty:
        raise ValueError("release-candidate source must be the exact clean commit")


def assemble(
    matrix_root: Path,
    reproducibility_path: Path,
    source: Path,
    output: Path,
    *,
    enforce_clean_source: bool = True,
) -> dict[str, Any]:
    matrix_root = matrix_root.resolve()
    source = source.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("release-candidate output must not already exist")
    reproducibility_bytes = reproducibility_path.resolve().read_bytes()
    reproducibility = json.loads(reproducibility_bytes)
    compared = compare(matrix_root)
    if reproducibility != compared or reproducibility.get("passed") is not True:
        raise ValueError("reproducibility receipt does not match matrix bytes")

    cells: list[tuple[dict[str, Any], Path]] = []
    for receipt_path in sorted(
        matrix_root.glob("*/receipts/qualification-summary.json")
    ):
        cell_root = receipt_path.parents[1]
        validate_release_metadata(cell_root)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        cells.append((receipt, cell_root))
    if len(cells) != 6:
        raise ValueError("release candidate requires exactly six qualified cells")
    commits = {receipt["commit"] for receipt, _root in cells}
    versions = {receipt["product_version"] for receipt, _root in cells}
    if len(commits) != 1 or versions != {"0.3.0b1"}:
        raise ValueError("matrix cells disagree on candidate commit or version")
    commit = next(iter(commits))
    if enforce_clean_source:
        _assert_source(source, commit)

    matrix_entries: list[dict[str, str]] = []
    canonical: Path | None = None
    for receipt, cell_root in cells:
        system = receipt["platform"]["system"]
        python = ".".join(receipt["platform"]["python"].split(".")[:2])
        matrix_entries.append(
            {
                "system": system,
                "python": python,
                "qualification_sha256": _digest(
                    cell_root / "receipts/qualification-summary.json"
                ),
            }
        )
        if system == "Linux" and python == "3.11":
            canonical = cell_root
    if canonical is None:
        raise ValueError("matrix has no canonical Linux/Python 3.11 cell")

    policy = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    output.mkdir(parents=True)
    artifacts = sorted((canonical / "artifacts").iterdir())
    if (
        len([path for path in artifacts if path.name.endswith(".whl")]) != 1
        or len([path for path in artifacts if path.name.endswith(".tar.gz")]) != 1
        or len(artifacts) != 2
    ):
        raise ValueError("canonical cell does not contain one wheel and one sdist")
    for path in artifacts:
        _copy_regular(path, output / "artifacts" / path.name)
    for relative in policy["required_release_files"]:
        _copy_regular(canonical / relative, output / relative)
    for relative in policy["source_documents"]:
        _copy_regular(source / relative, output / relative)
    for relative in policy["source_authorities"]:
        _copy_regular(source / relative, output / relative)
    for relative in (
        "schemas/pcodex.release-candidate.v1.schema.json",
        "schemas/pcodex.release-qualification.schema.json",
        "schemas/pcodex.release-provenance.schema.json",
        "release/release-candidate-allowlist.json",
    ):
        _copy_regular(source / relative, output / relative)

    _copy_regular(
        reproducibility_path.resolve(), output / "receipts/reproducibility.json"
    )
    _copy_regular(
        canonical / "receipts/qualification-summary.json",
        output / "receipts/canonical-qualification.json",
    )
    for receipt, cell_root in cells:
        system = receipt["platform"]["system"].lower()
        python = ".".join(receipt["platform"]["python"].split(".")[:2])
        _copy_regular(
            cell_root / "receipts/qualification-summary.json",
            output / "receipts/matrix" / f"{system}-py{python}.json",
        )

    supported = {
        "schema_version": "pcodex.supported-versions.v1",
        "product_version": "0.3.0b1",
        "candidate_commit": commit,
        "platforms": ["macos", "linux"],
        "python": ["3.11", "3.12", "3.13"],
        "codex": ["0.143.x"],
        "openclaw": ["2026.4.14"],
        "windows_supported": False,
        "public_registry_published": False,
    }
    supported_path = output / "release/SUPPORTED-VERSIONS.json"
    supported_path.write_text(
        json.dumps(supported, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    subject_paths = [
        *sorted((output / "artifacts").iterdir()),
        *(output / relative for relative in policy["required_release_files"]),
    ]
    receipt = {
        "schema_version": "pcodex.release-candidate.v1",
        "status": "qualified_not_published",
        "product_version": "0.3.0b1",
        "candidate_commit": commit,
        "supported_matrix": sorted(
            matrix_entries, key=lambda item: (item["system"], item["python"])
        ),
        "canonical_source_cell": {"system": "Linux", "python": "3.11"},
        "release_subjects": [
            {
                "path": path.relative_to(output).as_posix(),
                "sha256": _digest(path),
                "size": path.stat().st_size,
            }
            for path in subject_paths
        ],
        "reproducibility_receipt_sha256": hashlib.sha256(
            reproducibility_bytes
        ).hexdigest(),
        "provenance_authentication": "unsigned_commit_and_sha256_bound",
        "public_registry_published": False,
        "release_authorized": False,
    }
    rc_path = output / "release/RELEASE-CANDIDATE.json"
    rc_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = [
        {
            "file": path.relative_to(output).as_posix(),
            "sha256": _digest(path),
            "size": path.stat().st_size,
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
    ]
    (output / "SHA256-MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{item['sha256']}  {item['file']}\n" for item in manifest),
        encoding="utf-8",
    )
    result = validate(output)

    archive = output.parent / f"{output.name}.zip"
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as handle:
        for path in sorted(output.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(output).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            handle.writestr(info, path.read_bytes())
    result = validate_archive(archive, output)
    result["archive"] = str(archive)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-root", type=Path, required=True)
    parser.add_argument("--reproducibility", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(
        args.matrix_root,
        args.reproducibility,
        args.source,
        args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
