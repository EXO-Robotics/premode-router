#!/usr/bin/env python3
"""Validate five private first-run receipts and emit a content-free decision."""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import statistics
import subprocess
import sys
from typing import Any
import zipfile


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from first_run_study_authority import (  # noqa: E402
    ARTIFACT_HASH_CODE,
    expected_fixture_members,
    expected_fixture_surfaces,
    runbook_text,
    task_card_text,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/pcodex.first-run-study-receipt.v1.schema.json"
KIT_SCHEMA = ROOT / "schemas/pcodex.first-run-study-kit.v1.schema.json"
EVIDENCE_SCHEMA = ROOT / "schemas/pcodex.first-run-study-evidence.v1.schema.json"
SUMMARY_SCHEMA = ROOT / "schemas/pcodex.first-run-study-summary.v1.schema.json"
QUALIFICATION_SCHEMA = ROOT / "schemas/pcodex.release-qualification.schema.json"
PRODUCT_SCHEMA = ROOT / "schemas/premode.product.schema.json"
PROTOCOL = ROOT / "docs/FIRST_RUN_STUDY_PROTOCOL.md"
RESTORER = ROOT / "scripts/restore_first_run_fixture.py"
RECORDER = ROOT / "scripts/record_first_run_study.py"
STUDY_AUTHORITY = ROOT / "scripts/first_run_study_authority.py"
FIXTURES = {f"fixture-{index:02d}" for index in range(1, 6)}
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200.0

COMMON_OPERATIONS = [
    "artifact_verify",
    "venv_create",
    "package_install",
    "help",
    "doctor_advisory",
    "status_advisory",
    "run_dry_run",
    "managed_install_preview",
    "managed_install_apply",
]
CODEX_LIFECYCLE = [
    "codex_preview",
    "codex_install",
    "codex_status",
    "codex_install_idempotent",
    "codex_repair_preview",
    "codex_disable",
    "codex_reenable",
    "codex_uninstall_preview",
    "codex_uninstall_apply",
    "codex_reinstall",
    "codex_status_final",
    "codex_final_uninstall",
]
EXPECTED_OPERATIONS = {
    "fixture-01": [
        *COMMON_OPERATIONS,
        "missing_codex_status",
        "managed_uninstall_preview",
        "managed_uninstall_apply",
    ],
    "fixture-02": [
        *COMMON_OPERATIONS,
        *CODEX_LIFECYCLE,
        "managed_uninstall_preview",
        "managed_uninstall_apply",
    ],
    "fixture-03": [
        *COMMON_OPERATIONS,
        *CODEX_LIFECYCLE,
        "managed_uninstall_preview",
        "managed_uninstall_apply",
    ],
    "fixture-04": [
        *COMMON_OPERATIONS,
        "migration_preview",
        "migration_apply",
        "codex_status",
        "codex_install_idempotent",
        "codex_repair_preview",
        "codex_disable",
        "codex_reenable",
        "codex_uninstall_preview",
        "codex_uninstall_apply",
        "codex_reinstall",
        "codex_status_final",
        "codex_final_uninstall",
        "managed_uninstall_preview",
        "managed_uninstall_apply",
    ],
    "fixture-05": [
        *COMMON_OPERATIONS,
        "mcp_preview",
        "mcp_apply",
        "mcp_status",
        "mcp_install_idempotent",
        "mcp_disable",
        "mcp_repair_preview",
        "mcp_repair",
        "mcp_uninstall_preview",
        "mcp_uninstall_apply",
        "mcp_reinstall",
        "codex_status_final",
        "mcp_final_uninstall",
        "managed_uninstall_preview",
        "managed_uninstall_apply",
    ],
}
EXPECTED_CONDITIONS = {
    "fixture-01": ["clean_repository", "missing_codex", "mcp_absent"],
    "fixture-02": ["dirty_repository", "unrelated_agents"],
    "fixture-03": ["unrelated_codex_config", "supported_codex_0.143.x"],
    "fixture-04": ["path_with_spaces", "unicode_path", "supported_legacy_plugin"],
    "fixture-05": ["optional_mcp", "install_twice", "uninstall_reinstall"],
}
EXPECTED_CHECKPOINTS = {
    "fixture-01": ["before", "after_expected_missing_codex", "after_managed_uninstall"],
    "fixture-02": [
        "before",
        "after_integration_uninstall",
        "after_reinstall",
        "after_final_integration_uninstall",
        "after_managed_uninstall",
    ],
    "fixture-03": [
        "before",
        "after_integration_uninstall",
        "after_final_integration_uninstall",
        "after_managed_uninstall",
    ],
    "fixture-04": [
        "before",
        "after_integration_uninstall",
        "after_reinstall",
        "after_final_integration_uninstall",
        "after_managed_uninstall",
    ],
    "fixture-05": [
        "before",
        "after_mcp_uninstall",
        "after_final_integration_uninstall",
        "after_managed_uninstall",
    ],
}

_ALL_INTEGRATE_FLAGS = {
    "--dry-run",
    "--write",
    "--status",
    "--repair",
    "--disable",
    "--uninstall",
    "--migrate",
    "--with-mcp",
}
INTEGRATE_FLAGS = {
    "codex_preview": {"--dry-run"},
    "codex_install": {"--write"},
    "codex_status": {"--status"},
    "codex_install_idempotent": {"--write"},
    "codex_repair_preview": {"--repair", "--dry-run"},
    "codex_disable": {"--disable"},
    "codex_reenable": {"--repair"},
    "codex_uninstall_preview": {"--uninstall", "--dry-run"},
    "codex_uninstall_apply": {"--uninstall"},
    "codex_reinstall": {"--write"},
    "codex_status_final": {"--status"},
    "codex_final_uninstall": {"--uninstall"},
    "missing_codex_status": {"--status"},
    "migration_preview": {"--dry-run", "--migrate"},
    "migration_apply": {"--write", "--migrate"},
    "mcp_preview": {"--dry-run", "--with-mcp"},
    "mcp_apply": {"--write", "--with-mcp"},
    "mcp_status": {"--status"},
    "mcp_install_idempotent": {"--write", "--with-mcp"},
    "mcp_disable": {"--disable"},
    "mcp_repair_preview": {"--repair", "--dry-run"},
    "mcp_repair": {"--repair"},
    "mcp_uninstall_preview": {"--uninstall", "--dry-run"},
    "mcp_uninstall_apply": {"--uninstall"},
    "mcp_reinstall": {"--write", "--with-mcp"},
    "mcp_final_uninstall": {"--uninstall"},
}

# operation -> allowed operation status, expected writes, structured, readiness
EXPECTED_RESULTS = {
    "artifact_verify": ({"passed"}, False, False, {"not_applicable"}),
    "venv_create": ({"installed"}, True, False, {"not_applicable"}),
    "package_install": ({"installed"}, True, False, {"not_applicable"}),
    "help": ({"passed"}, False, False, {"not_applicable"}),
    "doctor_advisory": ({"completed"}, False, True, {"READY", "NEEDS_ACTION"}),
    "status_advisory": ({"completed"}, False, True, {"READY", "NEEDS_ACTION"}),
    "run_dry_run": ({"completed"}, False, True, {"READY"}),
    "managed_install_preview": ({"dry_run"}, False, True, {"NEEDS_ACTION"}),
    "managed_install_apply": ({"installed"}, True, True, {"READY"}),
    "missing_codex_status": ({"completed"}, False, True, {"NEEDS_ACTION"}),
    "codex_preview": ({"dry_run"}, False, True, {"READY", "NEEDS_ACTION"}),
    "codex_install": ({"installed"}, True, True, {"READY"}),
    "codex_status": ({"completed"}, False, True, {"READY"}),
    "codex_install_idempotent": ({"unchanged"}, False, True, {"READY"}),
    "codex_repair_preview": ({"dry_run"}, False, True, {"READY", "NEEDS_ACTION"}),
    "codex_disable": ({"disabled"}, True, True, {"NEEDS_ACTION"}),
    "codex_reenable": ({"repaired"}, True, True, {"READY"}),
    "codex_uninstall_preview": ({"dry_run"}, False, True, {"READY", "NEEDS_ACTION"}),
    "codex_uninstall_apply": ({"uninstalled"}, True, True, {"NEEDS_ACTION"}),
    "codex_reinstall": ({"installed"}, True, True, {"READY"}),
    "codex_status_final": ({"completed"}, False, True, {"READY"}),
    "codex_final_uninstall": ({"uninstalled"}, True, True, {"NEEDS_ACTION"}),
    "migration_preview": ({"dry_run"}, False, True, {"READY", "NEEDS_ACTION"}),
    "migration_apply": ({"installed"}, True, True, {"READY"}),
    "mcp_preview": ({"dry_run"}, False, True, {"READY", "NEEDS_ACTION"}),
    "mcp_apply": ({"installed"}, True, True, {"READY"}),
    "mcp_status": ({"completed"}, False, True, {"READY"}),
    "mcp_install_idempotent": ({"unchanged"}, False, True, {"READY"}),
    "mcp_disable": ({"disabled"}, True, True, {"NEEDS_ACTION"}),
    "mcp_repair_preview": ({"dry_run"}, False, True, {"READY", "NEEDS_ACTION"}),
    "mcp_repair": ({"repaired"}, True, True, {"READY"}),
    "mcp_uninstall_preview": ({"dry_run"}, False, True, {"READY", "NEEDS_ACTION"}),
    "mcp_uninstall_apply": ({"uninstalled"}, True, True, {"NEEDS_ACTION"}),
    "mcp_reinstall": ({"installed"}, True, True, {"READY"}),
    "mcp_final_uninstall": ({"uninstalled"}, True, True, {"NEEDS_ACTION"}),
    "managed_uninstall_preview": ({"preview"}, False, True, {"READY", "NEEDS_ACTION"}),
    "managed_uninstall_apply": ({"applied"}, True, True, {"NEEDS_ACTION"}),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _receipt_claims_sha256(receipt: dict[str, Any]) -> str:
    return _canonical_json_sha256(
        {
            key: receipt[key]
            for key in (
                "no_prior_knowledge_attested",
                "artifact",
                "runtime",
                "fixture",
                "timing",
                "undocumented_help",
                "failures",
                "documentation",
                "completed",
            )
        }
    )


def _installed_runtime_authority(venv_root: Path) -> str:
    roots = [
        *venv_root.glob("lib/python*/site-packages"),
        venv_root / "Lib/site-packages",
    ]
    records = [
        path
        for root in roots
        if root.is_dir()
        for path in root.glob("premode_router-0.3.0b1.dist-info/RECORD")
    ]
    if len(records) != 1:
        raise ValueError("installed distribution RECORD authority is missing")
    record = records[0]
    site_packages = record.parent.parent
    files: dict[str, str] = {}
    with record.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            candidate = (site_packages / row[0]).resolve()
            candidate.relative_to(venv_root.resolve())
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError("installed distribution member authority is invalid")
            files[candidate.relative_to(venv_root.resolve()).as_posix()] = _sha256(
                candidate
            )
    for name in ("python", "pcodex", "premode"):
        candidate = venv_root / "bin" / name
        if candidate.exists():
            resolved = candidate.resolve()
            if not resolved.is_file():
                raise ValueError("installed executable authority is invalid")
            files[f"bin/{name}"] = _sha256(resolved)
    if "bin/pcodex" not in files or "bin/python" not in files:
        raise ValueError("installed command authority is incomplete")
    return _canonical_json_sha256(files)


def _read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("invalid bounded JSON input")
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_kit_file(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative:
        raise ValueError("unsafe kit path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("unsafe kit path")
    candidate = (root / Path(*pure.parts)).resolve()
    candidate.relative_to(root.resolve())
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("kit member is not a regular file")
    return candidate


def _archive_members(path: Path) -> dict[str, bytes]:
    if path.stat().st_size > MAX_ARCHIVE_BYTES or not zipfile.is_zipfile(path):
        raise ValueError("invalid fixture archive")
    result: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if (
            len(infos) > MAX_ARCHIVE_MEMBERS
            or len(names) != len(set(names))
            or len(names) != len({name.casefold() for name in names})
        ):
            raise ValueError("unsafe fixture member set")
        for info in infos:
            pure = PurePosixPath(info.filename)
            raw_parts = info.filename.split("/")
            unix_type = stat.S_IFMT(info.external_attr >> 16)
            permissions = (info.external_attr >> 16) & 0o777
            total += info.file_size
            if (
                not info.filename
                or "\x00" in info.filename
                or "\\" in info.filename
                or any(part in {"", "."} for part in raw_parts)
                or info.filename != pure.as_posix()
                or pure.is_absolute()
                or ".." in pure.parts
                or any(part.casefold() == ".git" for part in pure.parts)
                or pure.name.casefold() in {".gitattributes", ".gitmodules"}
                or info.is_dir()
                or unix_type not in {0, stat.S_IFREG}
                or permissions != 0o644
                or info.flag_bits & 0x1
                or info.file_size > MAX_MEMBER_BYTES
                or total > MAX_ARCHIVE_BYTES
                or info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO
                or info.date_time != (1980, 1, 1, 0, 0, 0)
            ):
                raise ValueError("unsafe fixture archive member")
            result[info.filename] = archive.read(info)
    return result


def _surface_hash_from_members(
    members: dict[str, bytes], relative: str, kind: str
) -> str:
    if kind == "file_bytes":
        if relative not in members:
            raise ValueError("missing fixture preservation file")
        return hashlib.sha256(members[relative]).hexdigest()
    prefix = relative.rstrip("/") + "/"
    entries = [
        {
            "path": name[len(prefix) :],
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for name, data in sorted(members.items())
        if name.startswith(prefix)
    ]
    if not entries:
        raise ValueError("missing fixture preservation directory")
    return _canonical_json_sha256(entries)


def _canonical_docs() -> list[str]:
    from jsonschema import Draft202012Validator

    product_schema = _read_json(PRODUCT_SCHEMA)
    product = _read_json(ROOT / "premode.product.json")
    Draft202012Validator.check_schema(product_schema)
    Draft202012Validator(product_schema).validate(product)
    return list(product["documentation_contract"]["canonical_docs"])


def _validate_wheel_archive(wheel: Path, *, default_deny: bool) -> None:
    if wheel.is_symlink() or not wheel.is_file() or not zipfile.is_zipfile(wheel):
        raise ValueError("invalid wheel")
    if default_deny:
        from build_release_artifacts import (
            members,
            validate_archive_content,
            validate_archive_structure,
            validate_names,
        )

        policy = _read_json(ROOT / "release/artifact-allowlist.json")
        failures = validate_archive_structure(wheel, policy)
        failures.extend(
            validate_names(
                members(wheel),
                allowed_prefixes=list(policy["wheel_allowed_prefixes"]),
                policy=policy,
                exact_wheel=True,
            )
        )
        failures.extend(validate_archive_content(wheel, policy))
        if failures:
            raise ValueError("wheel default-deny validation failed")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
        required = (
            ".data/data/share/premode-router/premode.product.json",
            ".data/data/share/premode-router/plugins/pcodex/.codex-plugin/plugin.json",
            ".data/data/share/premode-router/plugins/pcodex/skills/pcodex/SKILL.md",
        )
        if len(metadata) != 1 or not all(
            any(n.endswith(s) for n in names) for s in required
        ):
            raise ValueError("wheel is missing canonical resources")
        text = archive.read(metadata[0]).decode("utf-8", errors="strict")
        if "\nVersion: 0.3.0b1\n" not in f"\n{text}":
            raise ValueError("wheel version mismatch")


def _kit_integrity(
    kit: dict[str, Any],
    study_kit: Path,
    qualification_root: Path | None,
    wheel: Path | None,
    *,
    verify_release_root: bool,
) -> tuple[bool, dict[str, Any]]:
    from jsonschema import Draft202012Validator

    try:
        if study_kit.is_symlink() or study_kit.name != "study-kit.json":
            raise ValueError("invalid study-kit path")
        kit_root = study_kit.resolve().parent.parent
        if study_kit.resolve() != kit_root / "coordinator/study-kit.json":
            raise ValueError("study-kit must use canonical kit layout")
        kit_schema = _read_json(KIT_SCHEMA)
        Draft202012Validator.check_schema(kit_schema)
        Draft202012Validator(kit_schema).validate(kit)
        if qualification_root is None or wheel is None:
            raise ValueError("qualification root and wheel are required")
        if wheel.is_symlink():
            raise ValueError("wheel must not be a symlink")
        wheel = wheel.resolve()
        if verify_release_root:
            from validate_release_metadata import validate

            release_result = validate(qualification_root.resolve())
            release_subjects = release_result["release_subjects"]
            wheel_relatives = [
                name for name in release_subjects if name.endswith(".whl")
            ]
            if len(wheel_relatives) != 1:
                raise ValueError("qualification must bind exactly one wheel")
            qualified_wheel = (
                qualification_root.resolve() / wheel_relatives[0]
            ).resolve()
            if qualified_wheel != wheel:
                raise ValueError("supplied wheel is not qualification wheel")
            qualification = _read_json(
                qualification_root.resolve() / "receipts/qualification-summary.json"
            )
            qualification_path = (
                qualification_root.resolve() / "receipts/qualification-summary.json"
            )
        else:
            qualification_path = qualification_root.resolve()
            qualification = _read_json(qualification_path)
        qualification_schema = _read_json(QUALIFICATION_SCHEMA)
        Draft202012Validator.check_schema(qualification_schema)
        if verify_release_root:
            Draft202012Validator(qualification_schema).validate(qualification)
        qualified_wheels = {
            item.get("digest", {}).get("sha256")
            for item in qualification.get("artifacts", [])
            if str(item.get("name", "")).endswith(".whl")
        }
        if not all(
            (
                _sha256(qualification_path) == kit["qualification_receipt_sha256"],
                qualification.get("schema_version")
                == "pcodex.release-qualification.v1",
                qualification.get("status") == "passed",
                qualification.get("commit") == kit["candidate_commit"],
                qualification.get("product_version") == "0.3.0b1",
                qualification.get("package_content_allowlist") == "passed",
                qualification.get("wheel_sdist_parity") == "passed",
                kit["wheel"]["sha256"] in qualified_wheels,
                wheel.name == kit["wheel"]["filename"],
                _sha256(wheel) == kit["wheel"]["sha256"],
            )
        ):
            raise ValueError("qualification binding mismatch")
        _validate_wheel_archive(wheel, default_deny=verify_release_root)

        docs = _canonical_docs()
        declared_docs = kit["canonical_document_sha256"]
        if set(declared_docs) != set(docs):
            raise ValueError("canonical document set mismatch")
        local_docs = {relative: _sha256(ROOT / relative) for relative in docs}
        if (
            declared_docs != local_docs
            or _canonical_json_sha256(local_docs)
            != kit["canonical_document_manifest_sha256"]
        ):
            raise ValueError("canonical document authority mismatch")

        expected_files = {
            "coordinator/study-kit.json",
            "coordinator/RUNBOOK.md",
            f"coordinator/{PROTOCOL.name}",
            f"coordinator/{SCHEMA.name}",
            f"coordinator/{KIT_SCHEMA.name}",
            f"coordinator/{EVIDENCE_SCHEMA.name}",
            f"coordinator/{RESTORER.name}",
            f"coordinator/{RECORDER.name}",
            f"coordinator/{Path(__file__).name}",
            "coordinator/first_run_study_authority.py",
            f"blind-tester-payload/artifacts/{wheel.name}",
            "blind-tester-payload/artifacts/SHA256SUMS",
        }
        expected_files.update(f"blind-tester-payload/{relative}" for relative in docs)
        expected_files.update(
            f"coordinator/fixtures/{fixture_id}.zip" for fixture_id in FIXTURES
        )
        expected_files.update(
            f"coordinator/task-cards/{fixture_id}.md" for fixture_id in FIXTURES
        )
        actual_files: set[str] = set()
        for path in kit_root.rglob("*"):
            relative = path.relative_to(kit_root).as_posix()
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise ValueError("unsupported kit filesystem object")
            if path.is_file():
                actual_files.add(relative)
        if actual_files != expected_files:
            raise ValueError("kit file set mismatch")

        payload_wheel = _safe_kit_file(
            kit_root, f"blind-tester-payload/artifacts/{wheel.name}"
        )
        if payload_wheel.read_bytes() != wheel.read_bytes():
            raise ValueError("blind payload wheel mismatch")
        sums = _safe_kit_file(
            kit_root, "blind-tester-payload/artifacts/SHA256SUMS"
        ).read_text(encoding="utf-8")
        if sums != f"{kit['wheel']['sha256']}  {wheel.name}\n":
            raise ValueError("SHA256SUMS mismatch")
        for relative in docs:
            payload_doc = _safe_kit_file(kit_root, f"blind-tester-payload/{relative}")
            if payload_doc.read_bytes() != (ROOT / relative).read_bytes():
                raise ValueError("blind payload document mismatch")

        source_hashes = {
            "receipt_schema_sha256": _sha256(SCHEMA),
            "kit_schema_sha256": _sha256(KIT_SCHEMA),
            "evidence_schema_sha256": _sha256(EVIDENCE_SCHEMA),
            "study_protocol_sha256": _sha256(PROTOCOL),
            "validator_sha256": _sha256(Path(__file__).resolve()),
            "restorer_sha256": _sha256(RESTORER),
            "recorder_sha256": _sha256(RECORDER),
            "study_authority_sha256": _sha256(STUDY_AUTHORITY),
            "canonical_document_manifest_sha256": _canonical_json_sha256(local_docs),
        }
        copied = {
            PROTOCOL.name: PROTOCOL,
            SCHEMA.name: SCHEMA,
            KIT_SCHEMA.name: KIT_SCHEMA,
            EVIDENCE_SCHEMA.name: EVIDENCE_SCHEMA,
            RESTORER.name: RESTORER,
            RECORDER.name: RECORDER,
            Path(__file__).name: Path(__file__).resolve(),
            STUDY_AUTHORITY.name: STUDY_AUTHORITY,
        }
        for name, authority in copied.items():
            if (
                _safe_kit_file(kit_root, f"coordinator/{name}").read_bytes()
                != authority.read_bytes()
            ):
                raise ValueError("coordinator authority copy mismatch")
        if any(kit[key] != value for key, value in source_hashes.items()):
            raise ValueError("study authority hash mismatch")
        runbook = _safe_kit_file(kit_root, "coordinator/RUNBOOK.md")
        if (
            runbook.read_bytes() != runbook_text().encode("utf-8")
            or _sha256(runbook) != kit["runbook_sha256"]
        ):
            raise ValueError("coordinator runbook authority mismatch")

        runtime_tools: dict[str, Path] = {}
        for label in ("python", "git"):
            declared = kit["runtime_tools"][label]
            raw = Path(declared["path"])
            if (
                not raw.is_absolute()
                or raw.is_symlink()
                or not raw.is_file()
                or not os.access(raw, os.X_OK)
                or _sha256(raw) != declared["sha256"]
            ):
                raise ValueError("runtime tool authority mismatch")
            runtime_tools[label] = raw.resolve()

        fixtures = kit["fixtures"]
        by_id = {item["id"]: item for item in fixtures}
        if len(by_id) != 5 or set(by_id) != FIXTURES:
            raise ValueError("fixture coverage mismatch")
        for fixture_id, item in by_id.items():
            if (
                item["conditions"] != EXPECTED_CONDITIONS[fixture_id]
                or item["required_operations"] != EXPECTED_OPERATIONS[fixture_id]
                or item["required_preservation_checkpoints"]
                != EXPECTED_CHECKPOINTS[fixture_id]
            ):
                raise ValueError("fixture contract mismatch")
            expected_snapshot = f"coordinator/fixtures/{fixture_id}.zip"
            if item["snapshot"] != expected_snapshot:
                raise ValueError("fixture snapshot path mismatch")
            expected_restore = [
                str(runtime_tools["python"]),
                "coordinator/restore_first_run_fixture.py",
                "--snapshot",
                expected_snapshot,
                "--sha256",
                item["sha256"],
                "--destination",
                "/new/empty/destination",
                "--git",
                str(runtime_tools["git"]),
                "--fixture-id",
                fixture_id,
            ]
            if item["restore_argv"] != expected_restore:
                raise ValueError("fixture restore argv mismatch")
            snapshot = _safe_kit_file(kit_root, expected_snapshot)
            if _sha256(snapshot) != item["sha256"]:
                raise ValueError("fixture snapshot digest mismatch")
            members = _archive_members(snapshot)
            member_hashes = {
                name: hashlib.sha256(data).hexdigest()
                for name, data in sorted(members.items())
            }
            expected_members = expected_fixture_members(
                fixture_id, runtime_tools["git"]
            )
            if (
                member_hashes != item["member_sha256"]
                or member_hashes != expected_members
            ):
                raise ValueError("fixture member authority mismatch")
            if item["preservation_surfaces"] != expected_fixture_surfaces(
                fixture_id, runtime_tools["git"]
            ):
                raise ValueError("preservation surface authority mismatch")
            task_card_path = f"coordinator/task-cards/{fixture_id}.md"
            task_card = _safe_kit_file(kit_root, task_card_path)
            expected_card = task_card_text(
                fixture_id, EXPECTED_OPERATIONS[fixture_id]
            ).encode("utf-8")
            if (
                item["task_card"] != task_card_path
                or task_card.read_bytes() != expected_card
                or _sha256(task_card) != item["task_card_sha256"]
            ):
                raise ValueError("task card authority mismatch")

        study = {
            **source_hashes,
            "study_kit_sha256": _sha256(study_kit),
            "qualification_receipt_sha256": kit["qualification_receipt_sha256"],
        }
        return True, {
            "fixtures": by_id,
            "study": study,
            "wheel": payload_wheel,
            "runtime_tools": runtime_tools,
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ):
        return False, {}


def _flag_value(argv: list[str], flag: str) -> str | None:
    if argv.count(flag) != 1:
        return None
    index = argv.index(flag)
    return argv[index + 1] if index + 1 < len(argv) else None


def _argv_matches(
    operation: str,
    argv: list[str],
    resolved_executable: str,
    wheel: Path,
    repository_root: str,
    venv_root: Path,
    base_python: Path,
) -> bool:
    if not argv or not Path(resolved_executable).is_absolute():
        return False
    resolved = Path(resolved_executable)
    expected_python = venv_root / "bin/python"
    expected_pcodex = venv_root / "bin/pcodex"
    if operation == "artifact_verify":
        return resolved == base_python and argv == [
            resolved_executable,
            "-c",
            ARTIFACT_HASH_CODE,
            str(wheel),
        ]
    if operation == "venv_create":
        return resolved == base_python and argv == [
            resolved_executable,
            "-m",
            "venv",
            str(venv_root),
        ]
    if operation == "package_install":
        return resolved == expected_python and argv == [
            str(expected_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            str(wheel),
        ]
    if resolved != expected_pcodex or Path(argv[0]).name != "pcodex":
        return False
    if "--repo-root" in argv and _flag_value(argv, "--repo-root") != repository_root:
        return False
    if operation == "help":
        return argv == ["pcodex", "--help"]
    if operation == "doctor_advisory":
        return argv == ["pcodex", "doctor", "--advisory", "--json"]
    if operation == "status_advisory":
        return argv == ["pcodex", "status", "--advisory", "--json"]
    if operation == "run_dry_run":
        return (
            len(argv) == 5
            and argv[:2] == ["pcodex", "run"]
            and argv[2] == "--dry-run"
            and argv[3] == "Fix the failing test"
            and argv[4] == "--json"
        )
    if operation == "managed_install_preview":
        return argv == ["pcodex", "install", "--json"]
    if operation == "managed_install_apply":
        return argv == ["pcodex", "install", "--apply", "--json"]
    if operation in INTEGRATE_FLAGS:
        flags = set(argv[3:]) - {"--json"}
        return (
            argv[:3] == ["pcodex", "integrate", "codex"]
            and argv[-1] == "--json"
            and flags == INTEGRATE_FLAGS[operation]
            and len(argv[3:-1]) == len(INTEGRATE_FLAGS[operation])
        )
    if operation == "managed_uninstall_preview":
        return argv == ["pcodex", "uninstall", "--dry-run", "--json"]
    if operation == "managed_uninstall_apply":
        return argv == ["pcodex", "uninstall", "--yes", "--json"]
    return False


def _decode(value: str) -> bytes:
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid base64 evidence") from exc
    if len(data) > 1024 * 1024:
        raise ValueError("evidence stream exceeds limit")
    return data


def _controlled_environment_valid(
    environment: dict[str, str], venv_root: Path, fixture_id: str
) -> bool:
    try:
        sandbox = Path(environment["sandbox_root"])
        if not sandbox.is_absolute():
            return False
        for key in (
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME",
            "XDG_DATA_HOME",
            "TMPDIR",
            "CODEX_HOME",
        ):
            value = Path(environment[key])
            if not value.is_absolute() or value == sandbox:
                return False
            value.relative_to(sandbox)
        path_parts = [str(venv_root / "bin")]
        if fixture_id != "fixture-01":
            path_parts.append(str(sandbox / "bin"))
        path_parts.extend(("/usr/bin", "/bin"))
        expected_path = os.pathsep.join(path_parts)
        return environment["PATH"] == expected_path
    except (KeyError, ValueError, TypeError):
        return False


def _load_evidence(
    directory: Path,
    digest: str,
    suffix: str,
    validator: Any,
    expected_kind: str,
) -> dict[str, Any]:
    path = directory / f"{digest}{suffix}"
    payload = _read_json(path)
    if _sha256(path) != digest:
        raise ValueError("content-addressed evidence mismatch")
    validator.validate(payload)
    if payload["kind"] != expected_kind:
        raise ValueError("evidence kind mismatch")
    return payload


def _derived_result(operation: str, stdout: bytes) -> dict[str, Any]:
    outcomes, _writes, structured, _statuses = EXPECTED_RESULTS[operation]
    if not structured:
        return {
            "structured": False,
            "result_sha256": None,
            "status": "not_applicable",
            "operation_status": sorted(outcomes)[0],
            "writes_performed": operation in {"venv_create", "package_install"},
        }
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("structured command stdout is not JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("structured command stdout must be an object")
    if payload.get("status") in {"error", "blocked", "BLOCKED"}:
        raise ValueError("structured command reported a blocking result")

    readiness: str
    operation_status: str
    if operation in {"doctor_advisory", "status_advisory"}:
        if not all(
            (
                payload.get("schema_version") == "pcodex.advisory_receipt.v1",
                payload.get("command")
                == ("doctor" if operation == "doctor_advisory" else "status"),
                payload.get("writes_performed") is False,
                payload.get("codex_launch") == "not_executed",
                payload.get("global_codex_config_mutation") is False,
                isinstance(payload.get("lifecycle"), dict),
                isinstance(payload.get("next_action"), str),
                payload.get("readiness") in {"READY", "NEEDS_ACTION"},
            )
        ):
            raise ValueError("invalid advisory receipt")
        readiness = str(payload["readiness"])
        operation_status = "completed"
    elif operation == "run_dry_run":
        if not all(
            (
                payload.get("status") == "dry_run",
                payload.get("codex_launch") == "not_executed",
                payload.get("raw_task_preview") == "Fix the failing test",
                payload.get("final_prompt_preview") is not None,
                payload.get("packet_path") is None,
                isinstance(payload.get("transform_applied"), bool),
            )
        ):
            raise ValueError("invalid run dry-run receipt")
        readiness = "READY"
        operation_status = "completed"
    elif operation in {"managed_install_preview", "managed_install_apply"}:
        expected_status = "dry_run" if operation.endswith("preview") else "installed"
        if not all(
            (
                payload.get("status") == expected_status,
                payload.get("writes_performed")
                is (operation == "managed_install_apply"),
                payload.get("written") is (operation == "managed_install_apply"),
                isinstance(
                    payload.get(
                        "lifecycle_before"
                        if operation.endswith("preview")
                        else "lifecycle_after"
                    ),
                    dict,
                ),
            )
        ):
            raise ValueError("invalid managed install receipt")
        readiness = "NEEDS_ACTION" if operation.endswith("preview") else "READY"
        operation_status = expected_status
    elif operation in {"managed_uninstall_preview", "managed_uninstall_apply"}:
        preview = operation.endswith("preview")
        expected_status = "preview" if preview else "applied"
        if not all(
            (
                payload.get("status") == expected_status,
                payload.get("writes_performed") is (not preview),
                payload.get("dry_run") is True
                if preview
                else payload.get("applied") is True,
                isinstance(
                    payload.get("preview_receipt" if preview else "public_receipt"),
                    dict,
                ),
            )
        ):
            raise ValueError("invalid managed uninstall receipt")
        readiness = "READY" if preview else "NEEDS_ACTION"
        operation_status = expected_status
    else:
        actual_status = payload.get("status")
        status_operations = {
            "missing_codex_status",
            "codex_status",
            "codex_status_final",
            "mcp_status",
        }
        plan_operations = {"codex_preview", "migration_preview", "mcp_preview"}
        repair_previews = {"codex_repair_preview", "mcp_repair_preview"}
        uninstall_previews = {"codex_uninstall_preview", "mcp_uninstall_preview"}
        if operation in status_operations:
            expected_readiness = (
                "NEEDS_ACTION" if operation == "missing_codex_status" else "READY"
            )
            if not all(
                (
                    payload.get("schema_version") == "pcodex.codex-plugin-status.v1",
                    payload.get("readiness") == expected_readiness,
                    payload.get("writes_performed") is False,
                    payload.get("reason")
                    == (
                        "plugin_absent"
                        if operation == "missing_codex_status"
                        else "healthy"
                    ),
                )
            ):
                raise ValueError("invalid plugin status receipt")
            if operation == "missing_codex_status":
                compatibility = payload.get("codex_compatibility")
                if not (
                    isinstance(compatibility, dict)
                    and compatibility.get("installed") is False
                    and compatibility.get("supported") is False
                    and compatibility.get("version") is None
                    and compatibility.get("reason") == "codex_missing"
                ):
                    raise ValueError("missing-Codex status lacks compatibility proof")
            if operation != "missing_codex_status" and not all(
                (
                    payload.get("enabled") is True,
                    payload.get("conflicts") == [],
                    isinstance(payload.get("native_registration"), dict),
                    payload["native_registration"].get("readiness") == "READY",
                )
            ):
                raise ValueError("healthy plugin status authority is incomplete")
            if operation == "mcp_status" and payload.get("optional_mcp") != "healthy":
                raise ValueError("MCP status did not prove healthy MCP authority")
            readiness = expected_readiness
            operation_status = "completed"
        elif operation in plan_operations:
            if not isinstance(actual_status, str):
                raise ValueError("plugin plan receipt missing status")
            if not all(
                (
                    payload.get("schema_version") == "pcodex.codex-plugin-plan.v1",
                    actual_status == "dry_run",
                    payload.get("dry_run") is True,
                    payload.get("writes_performed") is False,
                    payload.get("conflicts") == [],
                )
            ):
                raise ValueError("invalid plugin plan receipt")
            migration = payload.get("migration")
            optional_mcp = payload.get("optional_mcp")
            if operation == "migration_preview" and not (
                isinstance(migration, dict) and migration.get("requested") is True
            ):
                raise ValueError("migration preview did not request migration")
            if operation == "mcp_preview" and not (
                isinstance(optional_mcp, dict)
                and optional_mcp.get("authorized") is True
            ):
                raise ValueError("MCP preview did not authorize MCP")
            readiness = str(payload.get("readiness", "READY"))
            operation_status = actual_status
        elif operation in repair_previews | uninstall_previews:
            if not isinstance(actual_status, str):
                raise ValueError("plugin preview receipt missing status")
            expected_schema = (
                "pcodex.codex-plugin-repair-preview.v1"
                if operation in repair_previews
                else "pcodex.codex-plugin-uninstall-preview.v1"
            )
            if not all(
                (
                    payload.get("schema_version") == expected_schema,
                    actual_status == "dry_run",
                    payload.get("dry_run") is True,
                    payload.get("writes_performed") is False,
                )
            ):
                raise ValueError("invalid plugin lifecycle preview")
            readiness = str(payload.get("readiness", "READY"))
            operation_status = actual_status
        else:
            if not isinstance(actual_status, str):
                raise ValueError("plugin lifecycle receipt missing status")
            expected_writes = EXPECTED_RESULTS[operation][1]
            if payload.get("writes_performed") is not expected_writes:
                raise ValueError("plugin lifecycle write result mismatch")
            mcp_operations = {
                "mcp_apply",
                "mcp_install_idempotent",
                "mcp_disable",
                "mcp_repair",
                "mcp_uninstall_apply",
                "mcp_reinstall",
                "mcp_final_uninstall",
            }
            standard_operations = {
                "codex_install",
                "codex_install_idempotent",
                "codex_disable",
                "codex_reenable",
                "codex_uninstall_apply",
                "codex_reinstall",
                "codex_final_uninstall",
            }
            if operation in mcp_operations | standard_operations:
                if payload.get("optional_mcp_enabled") is (
                    operation not in mcp_operations
                ):
                    raise ValueError("plugin lifecycle mode authority mismatch")
            install_operations = {
                "codex_install",
                "migration_apply",
                "mcp_apply",
                "codex_reinstall",
                "mcp_reinstall",
            }
            if operation in install_operations:
                if not all(
                    (
                        payload.get("schema_version")
                        == "pcodex.codex-plugin-result.v1",
                        isinstance(payload.get("ownership_id"), str),
                        isinstance(payload.get("receipt"), str),
                        isinstance(payload.get("registration_receipts"), list),
                        "marketplace" in payload.get("registration_receipts", []),
                        isinstance(payload.get("native_registration"), dict),
                        payload["native_registration"].get("status") == "registered",
                    )
                ):
                    raise ValueError("plugin installation authority is incomplete")
                native_receipts = payload["native_registration"].get(
                    "registration_receipts", []
                )
                if not all(
                    item in native_receipts
                    for item in ("codex_marketplace", "codex_plugin_enable")
                ):
                    raise ValueError(
                        "native Codex registration authority is incomplete"
                    )
                if ("codex_mcp" in native_receipts) is (
                    operation not in {"mcp_apply", "mcp_reinstall"}
                ):
                    raise ValueError("native MCP registration authority mismatch")
                if payload.get("migration_applied") is (operation != "migration_apply"):
                    raise ValueError("legacy migration authority mismatch")
            if operation in {
                "codex_install_idempotent",
                "mcp_install_idempotent",
            } and not all(
                (
                    payload.get("schema_version") == "pcodex.codex-plugin-result.v1",
                    isinstance(payload.get("ownership_id"), str),
                    isinstance(payload.get("registration_receipts"), list),
                )
            ):
                raise ValueError("idempotent installation authority is incomplete")
            if operation in {"codex_disable", "mcp_disable"} and not isinstance(
                payload.get("native_registration"), dict
            ):
                raise ValueError("disable result lacks native registration authority")
            if operation in {"codex_reenable", "mcp_repair"} and not isinstance(
                payload.get("repaired_files"), list
            ):
                raise ValueError("repair result lacks repaired-file authority")
            if operation in {
                "codex_uninstall_apply",
                "codex_final_uninstall",
                "mcp_uninstall_apply",
                "mcp_final_uninstall",
            } and not all(
                (
                    isinstance(payload.get("removed_files"), list),
                    isinstance(payload.get("legacy_preserved"), list),
                    isinstance(payload.get("native_registration"), dict),
                )
            ):
                raise ValueError("uninstall result lacks removal authority")
            readiness = (
                "READY"
                if actual_status in {"installed", "unchanged", "repaired"}
                else "NEEDS_ACTION"
            )
            operation_status = actual_status
    return {
        "structured": True,
        "result_sha256": hashlib.sha256(stdout).hexdigest(),
        "status": readiness,
        "operation_status": operation_status,
        "writes_performed": bool(payload.get("writes_performed", False)),
    }


def _successful_command(
    command: dict[str, Any], evidence: dict[str, Any], wheel_hash: str
) -> bool:
    operation = command["operation"]
    result = _derived_result(operation, _decode(evidence["stdout_base64"]))
    allowed_outcomes, expected_writes, structured, statuses = EXPECTED_RESULTS[
        operation
    ]
    allowed_exit = {1} if operation == "missing_codex_status" else {0}
    if operation == "mcp_repair_preview" and result["status"] == "NEEDS_ACTION":
        allowed_exit = {1}
    if operation == "artifact_verify":
        stdout = _decode(evidence["stdout_base64"])
        if stdout != f"{wheel_hash}\n".encode("ascii"):
            return False
    return all(
        (
            command["exit_code"] in allowed_exit,
            evidence["exit_code"] == command["exit_code"],
            result == command["result"] == evidence["normalized_result"],
            result["structured"] is structured,
            result["operation_status"] in allowed_outcomes,
            result["writes_performed"] is expected_writes,
            result["status"] in statuses,
        )
    )


def _timing_matches(receipt: dict[str, Any]) -> bool:
    commands = receipt["commands"]
    if len(commands) < 3 or any(
        command["sequence"] != index for index, command in enumerate(commands, start=1)
    ):
        return False
    if any(
        command["started_seconds"] is not None
        or command["completed_seconds"] is not None
        for command in commands[:2]
    ):
        return False
    timed = commands[2:]
    if timed[0]["operation"] != "package_install" or timed[0]["started_seconds"] != 0:
        return False
    previous = 0.0
    for command in timed:
        start = command["started_seconds"]
        end = command["completed_seconds"]
        if start is None or end is None or start < previous or end < start:
            return False
        previous = float(end)
    successful_dry_runs = [
        command
        for command in commands
        if command["operation"] == "run_dry_run" and command["exit_code"] == 0
    ]
    return bool(
        successful_dry_runs
        and float(successful_dry_runs[0]["completed_seconds"])
        == float(receipt["timing"]["first_use_seconds"])
        and float(commands[-1]["completed_seconds"])
        == float(receipt["timing"]["completion_seconds"])
    )


def _verify_attestation(
    receipt: dict[str, Any],
    evidence: dict[str, Any],
    key: bytes,
    command_hashes: list[str],
    condition_hashes: list[str],
    preservation_hashes: list[str],
) -> bool:
    unsigned = {key_: value for key_, value in evidence.items() if key_ != "signature"}
    signature = hmac.new(
        key, _canonical_json_bytes(unsigned), hashlib.sha256
    ).hexdigest()
    return all(
        (
            evidence["tester_id"] == receipt["anonymous_tester_id"],
            evidence["fixture_id"] == receipt["fixture"]["id"],
            evidence["study_kit_sha256"] == receipt["study"]["study_kit_sha256"],
            evidence["command_evidence_manifest_sha256"]
            == _canonical_json_sha256(command_hashes),
            evidence["condition_evidence_manifest_sha256"]
            == _canonical_json_sha256(condition_hashes),
            evidence["preservation_evidence_manifest_sha256"]
            == _canonical_json_sha256(preservation_hashes),
            evidence["receipt_claims_sha256"] == _receipt_claims_sha256(receipt),
            evidence["signature"]["algorithm"] == "hmac-sha256",
            hmac.compare_digest(evidence["signature"]["value"], signature),
        )
    )


def _receipt_evidence_matches(
    receipt: dict[str, Any],
    fixture: dict[str, Any],
    expected_study: dict[str, str],
    wheel: Path,
    evidence_dir: Path,
    attestation_dir: Path,
    attestation_key: bytes,
    evidence_validator: Any,
    used_hashes: set[str],
    runtime_tools: dict[str, Path],
) -> tuple[bool, bool, bool, bool]:
    tester = receipt["anonymous_tester_id"]
    fixture_id = receipt["fixture"]["id"]
    commands = receipt["commands"]
    venv_commands = [item for item in commands if item["operation"] == "venv_create"]
    if len(venv_commands) != 1 or len(venv_commands[0]["argv"]) != 4:
        return False, False, False, False
    venv_root = Path(venv_commands[0]["argv"][3])
    if not venv_root.is_absolute():
        return False, False, False, False
    command_hashes: list[str] = []
    successful_operations: list[str] = []
    command_valid = receipt["study"] == expected_study
    environment_binding: dict[str, str] | None = None
    for command in commands:
        digest = command["evidence_sha256"]
        if digest in used_hashes:
            command_valid = False
            continue
        used_hashes.add(digest)
        command_hashes.append(digest)
        try:
            evidence = _load_evidence(
                evidence_dir, digest, ".evidence", evidence_validator, "command"
            )
            stdout = _decode(evidence["stdout_base64"])
            stderr = _decode(evidence["stderr_base64"])
            environment = evidence["controlled_environment"]
            if environment_binding is None:
                environment_binding = environment
            bound = all(
                (
                    evidence["tester_id"] == tester,
                    evidence["fixture_id"] == fixture_id,
                    evidence["study_kit_sha256"] == expected_study["study_kit_sha256"],
                    evidence["sequence"] == command["sequence"],
                    evidence["operation"] == command["operation"],
                    evidence["argv"] == command["argv"],
                    evidence["resolved_executable"] == command["resolved_executable"],
                    evidence["cwd"] == receipt["runtime"]["repository_root"],
                    evidence["venv_root"] == str(venv_root),
                    evidence["runtime_authority_sha256"]
                    == (
                        None
                        if command["operation"] in {"artifact_verify", "venv_create"}
                        else _installed_runtime_authority(venv_root)
                    ),
                    (evidence["no_write_observation_sha256"] is None)
                    is EXPECTED_RESULTS[command["operation"]][1],
                    environment == environment_binding,
                    _controlled_environment_valid(environment, venv_root, fixture_id),
                    evidence["started_seconds"] == command["started_seconds"],
                    evidence["completed_seconds"] == command["completed_seconds"],
                    evidence["exit_code"] == command["exit_code"],
                    evidence["sensitivity_reviewed"] is True,
                    command["sensitivity_reviewed"] is True,
                    hashlib.sha256(stdout).hexdigest() == command["stdout_sha256"],
                    hashlib.sha256(stderr).hexdigest() == command["stderr_sha256"],
                    _argv_matches(
                        command["operation"],
                        command["argv"],
                        command["resolved_executable"],
                        wheel,
                        receipt["runtime"]["repository_root"],
                        venv_root,
                        runtime_tools["python"],
                    ),
                )
            )
            if bound and _successful_command(
                command, evidence, receipt["artifact"]["sha256"]
            ):
                if command["operation"] in {
                    "codex_status",
                    "codex_status_final",
                    "mcp_status",
                }:
                    status_payload = json.loads(stdout.decode("utf-8"))
                    expected_mcp = (
                        fixture_id == "fixture-05"
                        and command["operation"] != "codex_status"
                    )
                    if (
                        status_payload.get("optional_mcp") == "healthy"
                    ) is not expected_mcp:
                        command_valid = False
                        continue
                successful_operations.append(command["operation"])
            else:
                referenced = [
                    failure
                    for failure in receipt["failures"]
                    if failure["command_sequence"] == command["sequence"]
                ]
                if not (
                    bound
                    and len(referenced) == 1
                    and referenced[0]["final_disposition"] == "recovered"
                    and bool(referenced[0]["repair"])
                ):
                    command_valid = False
        except (OSError, ValueError, KeyError, TypeError):
            command_valid = False
    command_valid = all(
        (
            command_valid,
            successful_operations == fixture["required_operations"],
            receipt["fixture"]["conditions"] == fixture["conditions"],
            _timing_matches(receipt),
            not any(
                f["final_disposition"] == "unresolved" for f in receipt["failures"]
            ),
        )
    )

    condition_hashes: list[str] = []
    condition_valid = True
    condition_items = {
        item["condition"]: item for item in receipt["condition_evidence"]
    }
    if len(condition_items) != len(receipt["condition_evidence"]) or set(
        condition_items
    ) != set(fixture["conditions"]):
        condition_valid = False
    for condition, item in condition_items.items():
        digest = item["evidence_sha256"]
        if digest in used_hashes:
            condition_valid = False
            continue
        used_hashes.add(digest)
        condition_hashes.append(digest)
        try:
            evidence = _load_evidence(
                evidence_dir, digest, ".evidence", evidence_validator, "condition"
            )
            observation = _decode(evidence["observation_base64"])
            if not all(
                (
                    evidence["tester_id"] == tester,
                    evidence["fixture_id"] == fixture_id,
                    evidence["study_kit_sha256"] == expected_study["study_kit_sha256"],
                    evidence["condition"] == condition,
                    evidence["observation_sha256"]
                    == hashlib.sha256(observation).hexdigest(),
                    evidence["observed"] is True,
                    evidence["sensitivity_reviewed"] is True,
                )
            ):
                condition_valid = False
            if (
                condition == "missing_codex"
                and observation != b"codex_version=absent\n"
            ):
                condition_valid = False
            if condition == "supported_codex_0.143.x" and observation != (
                f"codex_version={receipt['runtime']['codex_version']}\n".encode()
            ):
                condition_valid = False
            if condition == "clean_repository" and observation != b"git_status=clean\n":
                condition_valid = False
            if condition == "dirty_repository" and observation != (
                b"git_status=dirty_untracked_fixture_only\n"
            ):
                condition_valid = False
            if condition == "mcp_absent" and observation != b"mcp_state=absent\n":
                condition_valid = False
            if condition == "unrelated_agents":
                expected_hash = next(
                    surface["initial_sha256"]
                    for surface in fixture["preservation_surfaces"]
                    if surface["name"] == "unrelated_agents"
                )
                if observation != f"unrelated_agents_sha256={expected_hash}\n".encode():
                    condition_valid = False
            if condition == "unrelated_codex_config":
                expected_hash = next(
                    surface["initial_sha256"]
                    for surface in fixture["preservation_surfaces"]
                    if surface["name"] == "unrelated_codex_config"
                )
                if observation != f"codex_config_sha256={expected_hash}\n".encode():
                    condition_valid = False
            if (
                condition == "path_with_spaces"
                and " " not in receipt["runtime"]["repository_root"]
            ):
                condition_valid = False
            if (
                condition == "unicode_path"
                and receipt["runtime"]["repository_root"].isascii()
            ):
                condition_valid = False
            if condition == "path_with_spaces" and observation != (
                b"path_contains_space=true\n"
            ):
                condition_valid = False
            if condition == "unicode_path" and observation != (
                b"path_contains_unicode=true\n"
            ):
                condition_valid = False
            if condition == "supported_legacy_plugin":
                legacy = [
                    name
                    for name in fixture["member_sha256"]
                    if name.startswith(".agents/")
                ]
                expected = (
                    "legacy_member_manifest_sha256="
                    + _canonical_json_sha256(legacy)
                    + "\n"
                ).encode()
                if observation != expected:
                    condition_valid = False
            postconditions = {
                "optional_mcp": ("mcp_apply", "mcp_status", "mcp_final_uninstall"),
                "install_twice": ("mcp_apply", "mcp_install_idempotent"),
                "uninstall_reinstall": (
                    "mcp_uninstall_apply",
                    "mcp_reinstall",
                    "codex_status_final",
                ),
            }
            if condition in postconditions:
                expected = (
                    f"condition={condition};operations="
                    + ",".join(postconditions[condition])
                    + "\n"
                ).encode()
                if observation != expected:
                    condition_valid = False
        except (OSError, ValueError, KeyError, TypeError):
            condition_valid = False

    surfaces = {
        item["name"]: item["initial_sha256"]
        for item in fixture["preservation_surfaces"]
    }
    expected_pairs = {
        (surface, checkpoint)
        for surface in surfaces
        for checkpoint in fixture["required_preservation_checkpoints"]
    }
    preservation_items = {
        (item["surface"], item["checkpoint"]): item
        for item in receipt["preservation_evidence"]
    }
    preservation_valid = (
        len(preservation_items) == len(receipt["preservation_evidence"])
        and set(preservation_items) == expected_pairs
    )
    preservation_hashes: list[str] = []
    for pair, item in preservation_items.items():
        digest = item["evidence_sha256"]
        if digest in used_hashes:
            preservation_valid = False
            continue
        used_hashes.add(digest)
        preservation_hashes.append(digest)
        try:
            evidence = _load_evidence(
                evidence_dir, digest, ".evidence", evidence_validator, "preservation"
            )
            measurement = _decode(evidence["measurement_base64"])
            measured = hashlib.sha256(measurement).hexdigest()
            if not all(
                (
                    evidence["tester_id"] == tester,
                    evidence["fixture_id"] == fixture_id,
                    evidence["study_kit_sha256"] == expected_study["study_kit_sha256"],
                    evidence["surface"] == pair[0],
                    evidence["checkpoint"] == pair[1],
                    evidence["measurement_sha256"] == measured,
                    item["sha256"] == measured == surfaces[pair[0]],
                    evidence["sensitivity_reviewed"] is True,
                    item["sensitivity_reviewed"] is True,
                )
            ):
                preservation_valid = False
        except (OSError, ValueError, KeyError, TypeError):
            preservation_valid = False

    attestation_valid = False
    attestation_hash = receipt["attestation_evidence_sha256"]
    if attestation_hash not in used_hashes:
        used_hashes.add(attestation_hash)
        try:
            attestation = _load_evidence(
                attestation_dir,
                attestation_hash,
                ".attestation",
                evidence_validator,
                "attestation",
            )
            attestation_valid = _verify_attestation(
                receipt,
                attestation,
                attestation_key,
                command_hashes,
                condition_hashes,
                preservation_hashes,
            )
        except (OSError, ValueError, KeyError, TypeError):
            attestation_valid = False
    runtime_valid = (
        receipt["runtime"]["codex_version"] == "absent"
        if fixture_id == "fixture-01"
        else str(receipt["runtime"]["codex_version"]).startswith("0.143.")
    )
    expected_python_version = subprocess.run(
        (
            str(runtime_tools["python"]),
            "-c",
            "import platform; print(platform.python_version())",
        ),
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    runtime_valid = runtime_valid and (
        receipt["runtime"]["python_version"] == expected_python_version
    )
    return (
        command_valid,
        preservation_valid,
        condition_valid and runtime_valid,
        attestation_valid,
    )


def _validate_session_set(
    session_dir: Path | None,
    key: bytes,
    study_kit_sha256: str | None,
    fixtures: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int], int]:
    invalid: dict[str, int] = {}
    sessions: dict[str, dict[str, Any]] = {}
    failed_count = 0
    expected_sessions = {f"{fixture}.session.json" for fixture in FIXTURES}
    expected_locks = {f"{fixture}.session.lock" for fixture in FIXTURES}
    try:
        if (
            session_dir is None
            or session_dir.is_symlink()
            or not session_dir.is_dir()
            or stat.S_IMODE(session_dir.stat().st_mode) & 0o077
        ):
            raise ValueError("session_directory_invalid")
        entries = list(session_dir.iterdir())
        if {item.name for item in entries} != expected_sessions | expected_locks:
            raise ValueError("session_set_incomplete")
        for lock_name in expected_locks:
            lock = session_dir / lock_name
            if (
                lock.is_symlink()
                or not lock.is_file()
                or lock.stat().st_size != 0
                or stat.S_IMODE(lock.stat().st_mode) & 0o077
            ):
                raise ValueError("session_lock_invalid")
        for name in sorted(expected_sessions):
            path = session_dir / name
            fixture_id = path.name.removesuffix(".session.json")
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > MAX_JSON_BYTES
                or stat.S_IMODE(path.stat().st_mode) & 0o077
            ):
                raise ValueError("session_file_invalid")
            state = _read_json(path)
            signature = state.get("signature")
            unsigned = {
                name: value for name, value in state.items() if name != "signature"
            }
            expected_signature = hmac.new(
                key, _canonical_json_bytes(unsigned), hashlib.sha256
            ).hexdigest()
            if not isinstance(signature, str) or not hmac.compare_digest(
                signature, expected_signature
            ):
                raise ValueError("session_signature_invalid")
            fixture = state.get("fixture")
            events = state.get("events")
            required_operations = fixtures.get(fixture_id, {}).get(
                "required_operations", []
            )
            actual_operations = (
                [item.get("operation") for item in events]
                if isinstance(events, list)
                else []
            )
            status = state.get("status")
            if not all(
                (
                    state.get("schema_version") == "pcodex.first-run-recorder-state.v1",
                    state.get("study_kit_sha256") == study_kit_sha256,
                    isinstance(fixture, dict),
                    fixture.get("id") == fixture_id,
                    fixture_id in fixtures,
                    fixture.get("sha256") == fixtures.get(fixture_id, {}).get("sha256"),
                    isinstance(events, list),
                    status
                    in {
                        "recording",
                        "failed_closed",
                        "reviewed",
                        "finalizing",
                        "finalized",
                    },
                    actual_operations == required_operations[: len(actual_operations)],
                    status in {"recording", "failed_closed"}
                    or actual_operations == required_operations,
                    state.get("cursor") == len(events),
                    isinstance(state.get("tester_id"), str),
                )
            ):
                raise ValueError("session_authority_invalid")
            if status == "failed_closed" and not state.get("failed_attempts"):
                raise ValueError("failed_session_lacks_failure_evidence")
            if status != "finalized" or state.get("failed_attempts"):
                failed_count += 1
            state["_session_file_sha256"] = _sha256(path)
            sessions[fixture_id] = state
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        candidate = str(exc)
        reason = (
            candidate
            if isinstance(exc, ValueError) and re.fullmatch(r"[A-Za-z0-9_]+", candidate)
            else type(exc).__name__
        )
        invalid[reason] = invalid.get(reason, 0) + 1
        sessions = {}
    return sessions, invalid, failed_count


def _validate_attempt_ledger(
    ledger_path: Path | None,
    key: bytes,
    sessions: dict[str, dict[str, Any]],
) -> tuple[bool, dict[str, int], int, int]:
    invalid: dict[str, int] = {}
    failed_fixtures: set[str] = set()
    attempts: set[str] = set()
    try:
        if (
            ledger_path is None
            or ledger_path.is_symlink()
            or not ledger_path.is_file()
            or ledger_path.stat().st_size > MAX_JSON_BYTES
            or stat.S_IMODE(ledger_path.stat().st_mode) & 0o077
        ):
            raise ValueError("attempt_ledger_invalid")
        entries: list[dict[str, Any]] = []
        previous = "0" * 64
        for sequence, line in enumerate(ledger_path.read_bytes().splitlines(), start=1):
            entry = json.loads(line)
            signature = entry.get("signature")
            unsigned = {
                name: value for name, value in entry.items() if name != "signature"
            }
            if not all(
                (
                    entry.get("schema_version") == "pcodex.first-run-attempt-ledger.v1",
                    entry.get("sequence") == sequence,
                    entry.get("previous_entry_sha256") == previous,
                    entry.get("fixture_id") in FIXTURES,
                    isinstance(entry.get("tester_id"), str),
                    isinstance(entry.get("cursor"), int),
                    isinstance(entry.get("failed_attempt_count"), int),
                    isinstance(entry.get("state_sha256"), str),
                    isinstance(signature, str),
                    hmac.compare_digest(
                        signature,
                        hmac.new(
                            key, _canonical_json_bytes(unsigned), hashlib.sha256
                        ).hexdigest(),
                    ),
                )
            ):
                raise ValueError("attempt_ledger_chain_invalid")
            fixture_id = entry["fixture_id"]
            prior = [item for item in entries if item["fixture_id"] == fixture_id]
            if not prior:
                if not (
                    entry["state_status"] == "recording"
                    and entry["cursor"] == 0
                    and entry["failed_attempt_count"] == 0
                ):
                    raise ValueError("attempt_initialization_missing")
                attempts.add(fixture_id)
            elif (
                entry["state_status"] == "recording"
                and entry["cursor"] == 0
                and entry["failed_attempt_count"] == 0
            ):
                raise ValueError("attempt_reinitialized")
            if prior and entry["tester_id"] != prior[0]["tester_id"]:
                raise ValueError("attempt_tester_changed")
            if (
                entry["state_status"] == "failed_closed"
                or entry["failed_attempt_count"] > 0
            ):
                failed_fixtures.add(fixture_id)
            entries.append(entry)
            previous = _canonical_json_sha256(entry)
        if attempts != FIXTURES:
            raise ValueError("attempt_fixture_set_incomplete")
        for fixture_id in FIXTURES:
            last = next(
                item for item in reversed(entries) if item["fixture_id"] == fixture_id
            )
            session = sessions.get(fixture_id)
            if (
                session is None
                or last["state_sha256"] != session.get("_session_file_sha256")
                or last["tester_id"] != session.get("tester_id")
            ):
                raise ValueError("attempt_session_binding_invalid")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        candidate = str(exc)
        reason = (
            candidate
            if isinstance(exc, ValueError) and re.fullmatch(r"[A-Za-z0-9_]+", candidate)
            else type(exc).__name__
        )
        invalid[reason] = invalid.get(reason, 0) + 1
    return not invalid, invalid, len(attempts), len(failed_fixtures)


def validate_receipts(
    paths: list[Path],
    study_kit: Path,
    qualification_root: Path | None = None,
    wheel: Path | None = None,
    attestation_dir: Path | None = None,
    evidence_dir: Path | None = None,
    attestation_key: Path | None = None,
    session_dir: Path | None = None,
    attempt_ledger: Path | None = None,
    *,
    verify_release_root: bool = True,
    verify_git: bool = True,
) -> dict[str, Any]:
    from jsonschema import Draft202012Validator, FormatChecker

    try:
        schema = _read_json(SCHEMA)
        evidence_schema = _read_json(EVIDENCE_SCHEMA)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator.check_schema(evidence_schema)
        receipt_validator = Draft202012Validator(schema)
        evidence_validator = Draft202012Validator(
            evidence_schema, format_checker=FormatChecker()
        )
        kit = _read_json(study_kit)
    except (OSError, ValueError, json.JSONDecodeError):
        kit = {}
        receipt_validator = None
        evidence_validator = None
    kit_integrity_valid, trusted = _kit_integrity(
        kit,
        study_kit,
        qualification_root,
        wheel,
        verify_release_root=verify_release_root,
    )
    if verify_git and kit_integrity_valid:
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout.strip()
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout.strip()
            if head != kit["candidate_commit"] or dirty:
                kit_integrity_valid = False
                trusted = {}
        except (OSError, subprocess.SubprocessError):
            kit_integrity_valid = False
            trusted = {}
    key = b""
    if attestation_key is not None:
        try:
            if attestation_key.is_symlink() or not attestation_key.is_file():
                raise ValueError
            if stat.S_IMODE(attestation_key.stat().st_mode) & 0o077:
                raise ValueError
            key = attestation_key.read_bytes()
            if len(key) < 32 or len(key) > 4096:
                raise ValueError
        except (OSError, ValueError):
            key = b""
    kit_fixtures = trusted.get("fixtures", {})
    expected_study = trusted.get("study", {})
    trusted_wheel = trusted.get("wheel")
    study_kit_sha256 = _sha256(study_kit) if study_kit.is_file() else None
    sessions, invalid_sessions, session_failed_count = _validate_session_set(
        session_dir, key, study_kit_sha256, kit_fixtures
    )
    (
        attempt_ledger_valid,
        invalid_attempt_ledger,
        attempt_count,
        ledger_failed_count,
    ) = _validate_attempt_ledger(attempt_ledger, key, sessions)
    failed_attempt_count = max(session_failed_count, ledger_failed_count)
    receipts: list[dict[str, Any]] = []
    receipt_hashes: dict[str, str] = {}
    invalid: list[dict[str, Any]] = []
    evidence_results: dict[str, tuple[bool, bool, bool, bool]] = {}
    used_hashes: set[str] = set()
    for ordinal, path in enumerate(paths, start=1):
        try:
            payload = _read_json(path)
            if receipt_validator is None:
                raise ValueError("receipt schema unavailable")
            errors = list(receipt_validator.iter_errors(payload))
            if errors:
                invalid.append(
                    {
                        "receipt": ordinal,
                        "reason": "schema_validation_failed",
                        "error_count": len(errors),
                    }
                )
                continue
            fixture_id = payload["fixture"]["id"]
            if (
                not kit_integrity_valid
                or fixture_id not in kit_fixtures
                or not key
                or trusted_wheel is None
                or attestation_dir is None
                or evidence_dir is None
                or evidence_validator is None
            ):
                raise ValueError("study trust inputs invalid")
            results = _receipt_evidence_matches(
                payload,
                kit_fixtures[fixture_id],
                expected_study,
                trusted_wheel,
                evidence_dir,
                attestation_dir,
                key,
                evidence_validator,
                used_hashes,
                trusted["runtime_tools"],
            )
            evidence_results[payload["anonymous_tester_id"]] = results
            receipt_hashes[payload["anonymous_tester_id"]] = _sha256(path)
            receipts.append(payload)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            invalid.append({"receipt": ordinal, "reason": type(exc).__name__})

    tester_ids = {item["anonymous_tester_id"] for item in receipts}
    fixtures = {item["fixture"]["id"] for item in receipts}
    artifact_hashes = {item["artifact"]["sha256"] for item in receipts}
    commits = {item["artifact"]["candidate_commit"] for item in receipts}
    command_successes = sum(result[0] for result in evidence_results.values())
    preservation_successes = sum(result[1] for result in evidence_results.values())
    runtime_successes = sum(result[2] for result in evidence_results.values())
    attestation_successes = sum(result[3] for result in evidence_results.values())
    activated = [
        item
        for item in receipts
        if item["completed"]
        and evidence_results.get(item["anonymous_tester_id"])
        == (True, True, True, True)
    ]
    times = [float(item["timing"]["first_use_seconds"]) for item in activated]
    median_seconds = statistics.median(times) if times else None
    undocumented_help_count = sum(len(item["undocumented_help"]) for item in receipts)
    documentation_successes = sum(
        bool(item["documentation"]["sufficient"]) for item in receipts
    )
    unresolved_failure_count = sum(
        failure["final_disposition"] == "unresolved"
        for item in receipts
        for failure in item["failures"]
    )
    expected_wheel = kit.get("wheel", {})
    expected_commit = kit.get("candidate_commit")
    kit_bindings_valid = kit_integrity_valid and all(
        item["artifact"]["filename"] == expected_wheel.get("filename")
        and item["artifact"]["sha256"] == expected_wheel.get("sha256")
        and item["artifact"]["candidate_commit"] == expected_commit
        and item["fixture"]["sha256"] == kit_fixtures[item["fixture"]["id"]]["sha256"]
        and item["study"] == expected_study
        for item in receipts
    )
    receipts_by_fixture = {item["fixture"]["id"]: item for item in receipts}
    session_bindings_valid = (
        not invalid_sessions
        and attempt_ledger_valid
        and len(sessions) == 5
        and failed_attempt_count == 0
        and all(
            state.get("status") == "finalized"
            and state.get("tester_id")
            == receipts_by_fixture.get(fixture_id, {}).get("anonymous_tester_id")
            and state.get("receipt_sha256")
            == receipt_hashes.get(str(state.get("tester_id")))
            for fixture_id, state in sessions.items()
        )
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
            kit_bindings_valid,
            session_bindings_valid,
            attestation_successes == 5,
        )
    )
    activation_rate = len(activated) / 5 if study_complete else 0.0
    passed = all(
        (
            study_complete,
            activation_rate >= 0.95,
            median_seconds is not None and median_seconds < 600,
            undocumented_help_count == 0,
            unresolved_failure_count == 0,
            command_successes == 5,
            preservation_successes == 5,
            runtime_successes == 5,
            documentation_successes == 5,
        )
    )
    lifecycle_applicable = [
        item for item in receipts if item["fixture"]["id"] != "fixture-01"
    ]
    lifecycle_successes = sum(
        evidence_results[item["anonymous_tester_id"]][0]
        and evidence_results[item["anonymous_tester_id"]][1]
        for item in lifecycle_applicable
    )
    invalid_reasons: dict[str, int] = {}
    for item in invalid:
        reason = str(item["reason"])
        invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
    result = {
        "schema_version": "pcodex.first-run-study-summary.v1",
        "status": "passed" if passed else "failed",
        "receipt_count": len(receipts),
        "invalid_receipt_count": len(invalid),
        "invalid_receipt_reasons": invalid_reasons,
        "attempt_count": attempt_count,
        "failed_attempt_count": failed_attempt_count,
        "attempt_ledger_valid": attempt_ledger_valid,
        "invalid_attempt_ledger_count": sum(invalid_attempt_ledger.values()),
        "invalid_attempt_ledger_reasons": invalid_attempt_ledger,
        "invalid_session_count": sum(invalid_sessions.values()),
        "invalid_session_reasons": invalid_sessions,
        "session_bindings_valid": session_bindings_valid,
        "unique_tester_count": len(tester_ids),
        "attestation_evidence_successes": attestation_successes,
        "attestation_evidence_valid": attestation_successes == len(receipts) == 5,
        "command_evidence_unique_count": len(used_hashes),
        "command_evidence_files_valid": command_successes == len(receipts) == 5,
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
        "unresolved_failure_count": unresolved_failure_count,
        "codex_lifecycle_applicable_count": len(lifecycle_applicable),
        "codex_lifecycle_successes": lifecycle_successes,
        "unrelated_state_preservation_successes": preservation_successes,
        "documentation_sufficient_count": documentation_successes,
        "transcript_evidence_successes": command_successes,
        "runtime_condition_successes": runtime_successes,
        "study_kit_sha256": study_kit_sha256,
        "study_kit_integrity_valid": kit_integrity_valid,
        "study_kit_bindings_valid": kit_bindings_valid,
        "private_receipt_content_included": False,
    }
    summary_schema = _read_json(SUMMARY_SCHEMA)
    Draft202012Validator.check_schema(summary_schema)
    Draft202012Validator(summary_schema).validate(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", nargs="+", type=Path)
    parser.add_argument("--study-kit", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--attestation-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--attestation-key", type=Path, required=True)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--attempt-ledger", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = validate_receipts(
        args.receipts,
        args.study_kit,
        args.qualification_root,
        args.wheel,
        args.attestation_dir,
        args.evidence_dir,
        args.attestation_key,
        args.session_dir,
        args.attempt_ledger,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"first-run study: {result['status']}")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
