from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import zipfile

import pytest

import scripts.build_first_run_study_kit as kit_builder
import scripts.record_first_run_study as recorder
import scripts.validate_first_run_study as validator
from scripts.build_first_run_study_kit import build_kit
from scripts.restore_first_run_fixture import restore
from scripts.validate_first_run_study import validate_receipts
from premode.codex_plugin import (
    apply_integration,
    disable_integration,
    plugin_status,
    repair_integration,
)


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "904d5762f37a3dcff057a919c5d34ee6ce007b74"
KEY = b"coordinator witness key for tests only" * 2
PYTHON = Path(sys.executable).resolve()
GIT = Path(shutil.which("git") or "/usr/bin/git").resolve()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _json_sha(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _qualified_wheel(tmp_path: Path) -> tuple[Path, Path]:
    wheel = tmp_path / "premode_router-0.3.0b1-py3-none-any.whl"
    prefix = "premode_router-0.3.0b1"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(
            f"{prefix}.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: premode-router\nVersion: 0.3.0b1\n",
        )
        archive.writestr(
            f"{prefix}.data/data/share/premode-router/premode.product.json", "{}"
        )
        archive.writestr(
            f"{prefix}.data/data/share/premode-router/plugins/pcodex/.codex-plugin/plugin.json",
            "{}",
        )
        archive.writestr(
            f"{prefix}.data/data/share/premode-router/plugins/pcodex/skills/pcodex/SKILL.md",
            "fixture",
        )
    qualification = tmp_path / "qualification-summary.json"
    qualification.write_text(
        json.dumps(
            {
                "schema_version": "pcodex.release-qualification.v1",
                "status": "passed",
                "commit": COMMIT,
                "product_version": "0.3.0b1",
                "package_content_allowlist": "passed",
                "wheel_sdist_parity": "passed",
                "artifacts": [
                    {
                        "name": f"artifacts/{wheel.name}",
                        "digest": {"sha256": _sha(wheel)},
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return wheel, qualification


def _build_kit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    wheel, qualification = _qualified_wheel(tmp_path)
    monkeypatch.setattr(kit_builder, "_assert_source_commit", lambda _commit: None)
    root = tmp_path / "kit"
    build_kit(
        root,
        wheel,
        COMMIT,
        qualification,
        PYTHON,
        GIT,
        verify_release_root=False,
    )
    return root / "coordinator/study-kit.json", wheel, qualification


def _argv(
    operation: str, wheel: Path, venv: Path, base_python: Path
) -> tuple[list[str], str]:
    python = venv / "bin/python"
    pcodex = venv / "bin/pcodex"
    fixed = {
        "artifact_verify": (
            [str(base_python), "-c", validator.ARTIFACT_HASH_CODE, str(wheel)],
            str(base_python),
        ),
        "venv_create": (
            [str(base_python), "-m", "venv", str(venv)],
            str(base_python),
        ),
        "package_install": (
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel),
            ],
            str(python),
        ),
        "help": (["pcodex", "--help"], str(pcodex)),
        "doctor_advisory": (
            ["pcodex", "doctor", "--advisory", "--json"],
            str(pcodex),
        ),
        "status_advisory": (
            ["pcodex", "status", "--advisory", "--json"],
            str(pcodex),
        ),
        "run_dry_run": (
            ["pcodex", "run", "--dry-run", "Fix the failing test", "--json"],
            str(pcodex),
        ),
        "managed_install_preview": (["pcodex", "install", "--json"], str(pcodex)),
        "managed_install_apply": (
            ["pcodex", "install", "--apply", "--json"],
            str(pcodex),
        ),
        "managed_uninstall_preview": (
            ["pcodex", "uninstall", "--dry-run", "--json"],
            str(pcodex),
        ),
        "managed_uninstall_apply": (
            ["pcodex", "uninstall", "--yes", "--json"],
            str(pcodex),
        ),
    }
    if operation in fixed:
        return fixed[operation]
    flags = validator.INTEGRATE_FLAGS[operation]
    order = [
        flag
        for flag in (
            "--dry-run",
            "--write",
            "--status",
            "--repair",
            "--disable",
            "--uninstall",
            "--migrate",
            "--with-mcp",
        )
        if flag in flags
    ]
    return ["pcodex", "integrate", "codex", *order, "--json"], str(pcodex)


def _stdout(operation: str, wheel_hash: str) -> tuple[bytes, int]:
    if operation == "artifact_verify":
        return f"{wheel_hash}\n".encode(), 0
    if operation in {"venv_create", "package_install", "help"}:
        return f"{operation} completed\n".encode(), 0
    outcomes, writes, _structured, statuses = validator.EXPECTED_RESULTS[operation]
    operation_status = sorted(outcomes)[0]
    status = sorted(statuses)[0]
    exit_code = 0
    if operation == "missing_codex_status":
        exit_code = 1
    if operation == "mcp_repair_preview":
        exit_code = 1
    payload: dict[str, object] = {
        "status": operation_status,
        "writes_performed": writes,
    }
    if operation in {"doctor_advisory", "status_advisory"}:
        payload.update(
            {
                "schema_version": "pcodex.advisory_receipt.v1",
                "command": operation.removesuffix("_advisory"),
                "codex_launch": "not_executed",
                "global_codex_config_mutation": False,
                "lifecycle": {},
                "next_action": "continue",
                "readiness": status,
            }
        )
    elif operation == "run_dry_run":
        payload.update(
            {
                "status": "dry_run",
                "codex_launch": "not_executed",
                "raw_task_preview": "Fix the failing test",
                "final_prompt_preview": "Fix the failing test",
                "packet_path": None,
                "transform_applied": False,
            }
        )
    elif operation in {"managed_install_preview", "managed_install_apply"}:
        payload["written"] = operation.endswith("apply")
        payload[
            "lifecycle_after" if operation.endswith("apply") else "lifecycle_before"
        ] = {}
    elif operation in {"managed_uninstall_preview", "managed_uninstall_apply"}:
        if operation.endswith("preview"):
            payload.update({"dry_run": True, "preview_receipt": {}})
        else:
            payload.update({"applied": True, "public_receipt": {}})
    elif operation in {
        "missing_codex_status",
        "codex_status",
        "codex_status_final",
        "mcp_status",
    }:
        payload.update(
            {
                "schema_version": "pcodex.codex-plugin-status.v1",
                "readiness": status,
                "optional_mcp": (
                    "healthy" if operation == "mcp_status" else "disabled"
                ),
                "reason": (
                    "plugin_absent"
                    if operation == "missing_codex_status"
                    else "healthy"
                ),
            }
        )
        if operation == "missing_codex_status":
            payload["codex_compatibility"] = {
                "installed": False,
                "version": None,
                "supported": False,
                "reason": "codex_missing",
            }
        if operation != "missing_codex_status":
            payload.update(
                {
                    "enabled": True,
                    "conflicts": [],
                    "native_registration": {"readiness": "READY"},
                }
            )
    elif operation in {"codex_preview", "migration_preview", "mcp_preview"}:
        payload.update(
            {
                "schema_version": "pcodex.codex-plugin-plan.v1",
                "dry_run": True,
                "conflicts": [],
                "readiness": status,
                "migration": {"requested": operation == "migration_preview"},
                "optional_mcp": {"authorized": operation == "mcp_preview"},
            }
        )
    elif operation in {"codex_repair_preview", "mcp_repair_preview"}:
        payload.update(
            {
                "schema_version": "pcodex.codex-plugin-repair-preview.v1",
                "dry_run": True,
                "readiness": status,
            }
        )
    elif operation in {"codex_uninstall_preview", "mcp_uninstall_preview"}:
        payload.update(
            {
                "schema_version": "pcodex.codex-plugin-uninstall-preview.v1",
                "dry_run": True,
                "readiness": status,
            }
        )
    else:
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
            payload["optional_mcp_enabled"] = operation in mcp_operations
        if operation in {
            "codex_install",
            "migration_apply",
            "mcp_apply",
            "codex_reinstall",
            "mcp_reinstall",
        }:
            native_receipts = ["codex_marketplace", "codex_plugin_enable"]
            if operation in {"mcp_apply", "mcp_reinstall"}:
                native_receipts.append("codex_mcp")
            payload.update(
                {
                    "schema_version": "pcodex.codex-plugin-result.v1",
                    "ownership_id": "synthetic-ownership",
                    "receipt": ".premode/codex-plugin-state.json",
                    "registration_receipts": ["marketplace"],
                    "native_registration": {
                        "status": "registered",
                        "registration_receipts": native_receipts,
                    },
                    "migration_applied": operation == "migration_apply",
                }
            )
        if operation in {"codex_install_idempotent", "mcp_install_idempotent"}:
            payload.update(
                {
                    "schema_version": "pcodex.codex-plugin-result.v1",
                    "ownership_id": "synthetic-ownership",
                    "registration_receipts": ["marketplace"],
                }
            )
        if operation in {"codex_disable", "mcp_disable"}:
            payload["native_registration"] = {"status": "disabled"}
        if operation in {"codex_reenable", "mcp_repair"}:
            payload["repaired_files"] = []
        if operation in {
            "codex_uninstall_apply",
            "codex_final_uninstall",
            "mcp_uninstall_apply",
            "mcp_final_uninstall",
        }:
            payload.update(
                {
                    "removed_files": ["owned-file"],
                    "legacy_preserved": [],
                    "native_registration": {"status": "uninstalled"},
                }
            )
    return json.dumps(payload, sort_keys=True).encode(), exit_code


def _store(directory: Path, suffix: str, payload: dict[str, object]) -> str:
    data = _json_bytes(payload)
    digest = hashlib.sha256(data).hexdigest()
    (directory / f"{digest}{suffix}").write_bytes(data)
    return digest


def _surface_bytes(
    kit_root: Path, fixture: dict[str, object], surface: dict[str, str]
) -> bytes:
    if surface["measurement_kind"] == "post_restore_file_bytes":
        return b"must remain unrelated\n"
    snapshot = kit_root / str(fixture["snapshot"])
    with zipfile.ZipFile(snapshot) as archive:
        if surface["measurement_kind"] == "file_bytes":
            return archive.read(surface["relative_path"])
        prefix = surface["relative_path"].rstrip("/") + "/"
        entries = [
            {
                "path": name[len(prefix) :],
                "sha256": hashlib.sha256(archive.read(name)).hexdigest(),
            }
            for name in sorted(archive.namelist())
            if name.startswith(prefix)
        ]
    return _json_bytes(entries)


def _receipt(
    index: int,
    kit_path: Path,
    wheel: Path,
    attestation_dir: Path,
    evidence_dir: Path,
) -> dict[str, object]:
    kit = json.loads(kit_path.read_text(encoding="utf-8"))
    fixture = kit["fixtures"][index - 1]
    runtime_python_version = subprocess.run(
        [
            kit["runtime_tools"]["python"]["path"],
            "-c",
            "import platform; print(platform.python_version())",
        ],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    tester = f"tester-{index:08d}"
    repo = kit_path.parents[1] / f"tester-{index}"
    if index == 4:
        repo = kit_path.parents[1] / "repository with spaces β"
    venv = kit_path.parents[2] / f"synthetic-venv-{index}"
    (venv / "bin").mkdir(parents=True)
    for name in ("python", "pcodex", "premode"):
        executable = venv / "bin" / name
        executable.write_text(f"#!/bin/sh\n# synthetic {name}\n", encoding="utf-8")
        executable.chmod(0o700)
    site_packages = venv / "lib/python3.11/site-packages"
    (site_packages / "premode").mkdir(parents=True)
    (site_packages / "premode/__init__.py").write_text(
        '__version__ = "0.3.0b1"\n', encoding="utf-8"
    )
    dist_info = site_packages / "premode_router-0.3.0b1.dist-info"
    dist_info.mkdir()
    (dist_info / "RECORD").write_text(
        "premode/__init__.py,,\n"
        "premode_router-0.3.0b1.dist-info/RECORD,,\n"
        "../../../bin/pcodex,,\n"
        "../../../bin/premode,,\n"
        "../../../bin/python,,\n",
        encoding="utf-8",
    )
    runtime_authority = validator._installed_runtime_authority(venv)
    sandbox = kit_path.parents[1] / f"sandbox-{index}"
    controlled_environment = {
        "sandbox_root": str(sandbox),
        "HOME": str(sandbox / "home"),
        "XDG_CONFIG_HOME": str(sandbox / "xdg-config"),
        "XDG_CACHE_HOME": str(sandbox / "xdg-cache"),
        "XDG_DATA_HOME": str(sandbox / "xdg-data"),
        "TMPDIR": str(sandbox / "tmp"),
        "CODEX_HOME": str(sandbox / "codex-home"),
        "PATH": (
            f"{venv / 'bin'}:/usr/bin:/bin"
            if index == 1
            else f"{venv / 'bin'}:{sandbox / 'bin'}:/usr/bin:/bin"
        ),
    }
    commands: list[dict[str, object]] = []
    command_hashes: list[str] = []
    elapsed = 0.0
    for sequence, operation in enumerate(fixture["required_operations"], start=1):
        argv, executable = _argv(
            operation, wheel, venv, Path(kit["runtime_tools"]["python"]["path"])
        )
        stdout, exit_code = _stdout(operation, kit["wheel"]["sha256"])
        if index == 5 and operation == "codex_status_final":
            payload = json.loads(stdout)
            payload["optional_mcp"] = "healthy"
            stdout = json.dumps(payload, sort_keys=True).encode()
        stderr = b""
        if sequence <= 2:
            started = completed = None
        else:
            started = elapsed
            elapsed += 1.0
            completed = elapsed
        result = validator._derived_result(operation, stdout)
        command = {
            "sequence": sequence,
            "operation": operation,
            "argv": argv,
            "resolved_executable": executable,
            "started_seconds": started,
            "completed_seconds": completed,
            "exit_code": exit_code,
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "evidence_sha256": "",
            "sensitivity_reviewed": True,
            "result": result,
        }
        evidence = {
            "schema_version": "pcodex.first-run-study-evidence.v1",
            "kind": "command",
            "tester_id": tester,
            "fixture_id": fixture["id"],
            "study_kit_sha256": _sha(kit_path),
            "sequence": sequence,
            "operation": operation,
            "argv": argv,
            "resolved_executable": executable,
            "cwd": str(repo),
            "controlled_environment": controlled_environment,
            "venv_root": str(venv),
            "runtime_authority_sha256": (None if sequence <= 2 else runtime_authority),
            "no_write_observation_sha256": (
                None
                if validator.EXPECTED_RESULTS[operation][1]
                else hashlib.sha256(f"no-write-{index}-{sequence}".encode()).hexdigest()
            ),
            "started_seconds": started,
            "completed_seconds": completed,
            "exit_code": exit_code,
            "stdout_base64": base64.b64encode(stdout).decode(),
            "stderr_base64": base64.b64encode(stderr).decode(),
            "normalized_result": result,
            "sensitivity_reviewed": True,
        }
        digest = _store(evidence_dir, ".evidence", evidence)
        command["evidence_sha256"] = digest
        command_hashes.append(digest)
        commands.append(command)

    condition_items: list[dict[str, str]] = []
    condition_hashes: list[str] = []
    for condition in fixture["conditions"]:
        observation = f"condition={condition};observed=true\n".encode()
        if condition == "missing_codex":
            observation = b"codex_version=absent\n"
        if condition == "supported_codex_0.143.x":
            observation = b"codex_version=0.143.0\n"
        if condition == "clean_repository":
            observation = b"git_status=clean\n"
        if condition == "dirty_repository":
            observation = b"git_status=dirty_untracked_fixture_only\n"
        if condition == "mcp_absent":
            observation = b"mcp_state=absent\n"
        if condition == "unrelated_agents":
            digest = next(
                item["initial_sha256"]
                for item in fixture["preservation_surfaces"]
                if item["name"] == "unrelated_agents"
            )
            observation = f"unrelated_agents_sha256={digest}\n".encode()
        if condition == "unrelated_codex_config":
            digest = next(
                item["initial_sha256"]
                for item in fixture["preservation_surfaces"]
                if item["name"] == "unrelated_codex_config"
            )
            observation = f"codex_config_sha256={digest}\n".encode()
        if condition == "path_with_spaces":
            observation = b"path_contains_space=true\n"
        if condition == "unicode_path":
            observation = b"path_contains_unicode=true\n"
        if condition == "supported_legacy_plugin":
            legacy = [
                name for name in fixture["member_sha256"] if name.startswith(".agents/")
            ]
            observation = (
                f"legacy_member_manifest_sha256={_json_sha(legacy)}\n".encode()
            )
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
            observation = (
                f"condition={condition};operations="
                + ",".join(postconditions[condition])
                + "\n"
            ).encode()
        evidence = {
            "schema_version": "pcodex.first-run-study-evidence.v1",
            "kind": "condition",
            "tester_id": tester,
            "fixture_id": fixture["id"],
            "study_kit_sha256": _sha(kit_path),
            "condition": condition,
            "observation_base64": base64.b64encode(observation).decode(),
            "observation_sha256": hashlib.sha256(observation).hexdigest(),
            "observed": True,
            "sensitivity_reviewed": True,
        }
        digest = _store(evidence_dir, ".evidence", evidence)
        condition_hashes.append(digest)
        condition_items.append({"condition": condition, "evidence_sha256": digest})

    preservation: list[dict[str, object]] = []
    preservation_hashes: list[str] = []
    for surface in fixture["preservation_surfaces"]:
        measurement = _surface_bytes(kit_path.parents[1], fixture, surface)
        measured = hashlib.sha256(measurement).hexdigest()
        assert measured == surface["initial_sha256"]
        for checkpoint in fixture["required_preservation_checkpoints"]:
            evidence = {
                "schema_version": "pcodex.first-run-study-evidence.v1",
                "kind": "preservation",
                "tester_id": tester,
                "fixture_id": fixture["id"],
                "study_kit_sha256": _sha(kit_path),
                "surface": surface["name"],
                "checkpoint": checkpoint,
                "measurement_base64": base64.b64encode(measurement).decode(),
                "measurement_sha256": measured,
                "sensitivity_reviewed": True,
            }
            digest = _store(evidence_dir, ".evidence", evidence)
            preservation_hashes.append(digest)
            preservation.append(
                {
                    "surface": surface["name"],
                    "checkpoint": checkpoint,
                    "sha256": measured,
                    "evidence_sha256": digest,
                    "sensitivity_reviewed": True,
                }
            )

    dry_run = next(item for item in commands if item["operation"] == "run_dry_run")
    study = {
        key: kit[key]
        for key in (
            "qualification_receipt_sha256",
            "receipt_schema_sha256",
            "kit_schema_sha256",
            "evidence_schema_sha256",
            "study_protocol_sha256",
            "validator_sha256",
            "restorer_sha256",
            "recorder_sha256",
            "study_authority_sha256",
            "canonical_document_manifest_sha256",
        )
    }
    study["study_kit_sha256"] = _sha(kit_path)
    receipt: dict[str, object] = {
        "schema_version": "pcodex.first-run-study-receipt.v1",
        "anonymous_tester_id": tester,
        "no_prior_knowledge_attested": True,
        "attestation_evidence_sha256": "0" * 64,
        "study": study,
        "artifact": {
            "filename": wheel.name,
            "sha256": _sha(wheel),
            "product_version": "0.3.0b1",
            "candidate_commit": COMMIT,
        },
        "runtime": {
            "platform": "macos" if index % 2 else "linux",
            "architecture": "arm64",
            "python_version": runtime_python_version,
            "codex_version": "absent" if index == 1 else "0.143.0",
            "repository_root": str(repo),
        },
        "fixture": {
            "id": fixture["id"],
            "sha256": fixture["sha256"],
            "conditions": fixture["conditions"],
        },
        "timing": {
            "timer_start_operation": "package_install",
            "first_use_seconds": dry_run["completed_seconds"],
            "completion_seconds": commands[-1]["completed_seconds"],
        },
        "commands": commands,
        "condition_evidence": condition_items,
        "preservation_evidence": preservation,
        "undocumented_help": [],
        "failures": [],
        "documentation": {"sufficient": True, "missing_instruction": None},
        "completed": True,
    }
    attestation = {
        "schema_version": "pcodex.first-run-study-evidence.v1",
        "kind": "attestation",
        "tester_id": tester,
        "fixture_id": fixture["id"],
        "study_kit_sha256": _sha(kit_path),
        "statement": "I had no prior internal knowledge of pCodex and followed only the supplied canonical documentation and frozen task card.",
        "signed_at_utc": "2026-07-14T12:00:00Z",
        "signer_id": f"coordinator-{index:08d}",
        "signer_role": "study_coordinator_witness",
        "command_evidence_manifest_sha256": _json_sha(command_hashes),
        "condition_evidence_manifest_sha256": _json_sha(condition_hashes),
        "preservation_evidence_manifest_sha256": _json_sha(preservation_hashes),
        "receipt_claims_sha256": validator._receipt_claims_sha256(receipt),
    }
    signature = hmac.new(KEY, _json_bytes(attestation), hashlib.sha256).hexdigest()
    attestation["signature"] = {"algorithm": "hmac-sha256", "value": signature}
    receipt["attestation_evidence_sha256"] = _store(
        attestation_dir, ".attestation", attestation
    )
    return receipt


def _append_test_state_history(
    ledger: Path, state: dict[str, object], final_sha256: str, seed: str
) -> None:
    fixture = state["fixture"]
    tester_id = state["tester_id"]
    initial = {
        "fixture": fixture,
        "tester_id": tester_id,
        "status": "recording",
        "cursor": 0,
        "events": [],
        "failed_attempts": [],
    }
    predecessor = hashlib.sha256(f"{seed}-initial".encode()).hexdigest()
    recorder._append_attempt_ledger(ledger, initial, predecessor, KEY)
    cursor = int(state["cursor"])
    for current in range(1, cursor + 1):
        transition = {
            "fixture": fixture,
            "tester_id": tester_id,
            "status": "recording",
            "cursor": current,
            "events": [{"operation": "accepted"}] * current,
            "failed_attempts": [],
        }
        digest = hashlib.sha256(f"{seed}-recording-{current}".encode()).hexdigest()
        recorder._append_attempt_ledger(ledger, transition, digest, KEY, predecessor)
        predecessor = digest
    if state["status"] == "failed_closed":
        recorder._append_attempt_ledger(ledger, state, final_sha256, KEY, predecessor)
        return
    for status in ("reviewed", "finalizing"):
        transition = {
            "fixture": fixture,
            "tester_id": tester_id,
            "status": status,
            "cursor": cursor,
            "events": state["events"],
            "failed_attempts": [],
        }
        digest = hashlib.sha256(f"{seed}-{status}".encode()).hexdigest()
        recorder._append_attempt_ledger(ledger, transition, digest, KEY, predecessor)
        predecessor = digest
    recorder._append_attempt_ledger(ledger, state, final_sha256, KEY, predecessor)


def _inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, ...]:
    kit, wheel, qualification = _build_kit(tmp_path, monkeypatch)
    payload_wheel = kit.parents[1] / "blind-tester-payload/artifacts" / wheel.name
    attestations = tmp_path / "attestations"
    evidence = tmp_path / "evidence"
    attestations.mkdir()
    evidence.mkdir()
    key = tmp_path / "attestation.key"
    key.write_bytes(KEY)
    key.chmod(0o600)
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(mode=0o700)
    attempt_ledger = tmp_path / "attempt-ledger.jsonl"
    paths = []
    for index in range(1, 6):
        path = tmp_path / f"receipt-{index}.json"
        receipt = _receipt(index, kit, payload_wheel, attestations, evidence)
        path.write_text(json.dumps(receipt), encoding="utf-8")
        paths.append(path)
        fixture = json.loads(kit.read_text(encoding="utf-8"))["fixtures"][index - 1]
        session = {
            "schema_version": "pcodex.first-run-recorder-state.v1",
            "status": "finalized",
            "study_kit_sha256": _sha(kit),
            "fixture": fixture,
            "tester_id": receipt["anonymous_tester_id"],
            "cursor": len(fixture["required_operations"]),
            "events": [
                {"operation": operation} for operation in fixture["required_operations"]
            ],
            "failed_attempts": [],
            "receipt_sha256": _sha(path),
        }
        session["signature"] = hmac.new(
            KEY, _json_bytes(session), hashlib.sha256
        ).hexdigest()
        session_path = session_dir / f"{fixture['id']}.session.json"
        lock_path = session_dir / f"{fixture['id']}.session.lock"
        lock_path.touch(mode=0o600)
        session_path.write_text(json.dumps(session), encoding="utf-8")
        session_path.chmod(0o600)
        _append_test_state_history(
            attempt_ledger, session, _sha(session_path), f"fixture-{index}"
        )
    return (
        paths,
        kit,
        qualification,
        wheel,
        attestations,
        evidence,
        key,
        session_dir,
        attempt_ledger,
    )


def _validate(inputs: tuple[object, ...]) -> dict[str, object]:
    (
        paths,
        kit,
        qualification,
        wheel,
        attestations,
        evidence,
        key,
        session_dir,
        attempt_ledger,
    ) = inputs
    return validate_receipts(
        paths,  # type: ignore[arg-type]
        kit,  # type: ignore[arg-type]
        qualification,  # type: ignore[arg-type]
        wheel,  # type: ignore[arg-type]
        attestations,  # type: ignore[arg-type]
        evidence,  # type: ignore[arg-type]
        key,  # type: ignore[arg-type]
        session_dir,  # type: ignore[arg-type]
        attempt_ledger,  # type: ignore[arg-type]
        verify_release_root=False,
        verify_git=False,
    )


def _materialize_test_runtime(venv: Path) -> None:
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("python", "pcodex", "premode"):
        executable = venv / "bin" / name
        executable.write_text(f"#!/bin/sh\n# synthetic {name}\n", encoding="utf-8")
        executable.chmod(0o700)
    site_packages = venv / "lib/python3.11/site-packages"
    (site_packages / "premode").mkdir(parents=True, exist_ok=True)
    (site_packages / "premode/__init__.py").write_text(
        '__version__ = "0.3.0b1"\n', encoding="utf-8"
    )
    dist_info = site_packages / "premode_router-0.3.0b1.dist-info"
    dist_info.mkdir(exist_ok=True)
    (dist_info / "RECORD").write_text(
        "premode/__init__.py,,\n"
        "premode_router-0.3.0b1.dist-info/RECORD,,\n"
        "../../../bin/pcodex,,\n"
        "../../../bin/premode,,\n"
        "../../../bin/python,,\n",
        encoding="utf-8",
    )


def _replace_fixture_two_with_real_recorder_journey(
    inputs: tuple[object, ...], tmp_path: Path
) -> None:
    (
        paths,
        kit_path,
        _qualification,
        _wheel,
        attestations,
        evidence,
        _key,
        sessions,
        ledger,
    ) = inputs
    kit = json.loads(kit_path.read_text(encoding="utf-8"))
    fixture = kit["fixtures"][1]
    copied_path = kit_path.parent / "record_first_run_study.py"
    spec = importlib.util.spec_from_file_location(
        "copied_first_run_recorder", copied_path
    )
    assert spec is not None and spec.loader is not None
    copied = importlib.util.module_from_spec(spec)
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(copied)
    finally:
        sys.dont_write_bytecode = previous_bytecode

    authority = tmp_path / "actual-authority"
    authority.mkdir(mode=0o700)
    key_path = authority / "coordinator.key"
    key_path.write_bytes(KEY)
    key_path.chmod(0o600)
    actual_ledger = authority / "attempt-ledger.jsonl"
    session_dir = authority / "sessions"
    session = session_dir / "fixture-02.session.json"
    sandbox = tmp_path / "actual-sandbox"
    sandbox.mkdir(mode=0o700)
    repository = sandbox / "fixture-02-repository"
    restore(
        kit_path.parents[1] / fixture["snapshot"],
        fixture["sha256"],
        repository,
        "fixture-02",
        Path(kit["runtime_tools"]["git"]["path"]),
    )
    codex = authority / "codex"
    codex.write_text("#!/bin/sh\necho 'codex-cli 0.143.0'\n", encoding="utf-8")
    codex.chmod(0o700)
    venv = sandbox / "venv"
    copied.init_session(
        SimpleNamespace(
            session=session,
            study_kit=kit_path,
            study_kit_sha256=_sha(kit_path),
            fixture="fixture-02",
            tester_id="tester-e2e00002",
            repository=repository,
            venv=venv,
            sandbox=sandbox,
            codex=codex,
            attestation_key=key_path,
            attempt_ledger=actual_ledger,
        )
    )

    original_operation_argv = copied._operation_argv
    real_subprocess_run = subprocess.run

    def fake_operation_argv(
        operation: str, state: dict[str, object]
    ) -> tuple[list[str], str, list[str]]:
        argv, resolved, _execution = original_operation_argv(operation, state)
        return argv, resolved, ["__pcodex_fixture_command__", operation]

    def fake_run(argv: list[str] | tuple[str, ...], **kwargs: object) -> object:
        if argv[0] != "__pcodex_fixture_command__":
            return real_subprocess_run(argv, **kwargs)
        operation = argv[1]
        if operation == "venv_create":
            (venv / "bin").mkdir(parents=True)
        if operation == "package_install":
            _materialize_test_runtime(venv)
        stdout, returncode = _stdout(operation, kit["wheel"]["sha256"])
        return subprocess.CompletedProcess(argv, returncode, stdout, b"")

    copied._operation_argv = fake_operation_argv
    copied.subprocess = SimpleNamespace(
        run=fake_run, SubprocessError=subprocess.SubprocessError
    )
    for operation in fixture["required_operations"]:
        assert (
            copied.run_next(
                SimpleNamespace(
                    session=session,
                    operation=operation,
                    attestation_key=key_path,
                )
            )
            == 0
        )

    review_dir = authority / "reviews"
    review_dir.mkdir(mode=0o700)
    review_path = review_dir / "fixture-02.review.json"
    copied.build_review_manifest(
        SimpleNamespace(
            session=session,
            output=review_path,
            signer_id="coordinator-e2e00002",
            attestation_key=key_path,
        )
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["no_prior_knowledge_attested"] = True
    review["completed"] = True
    for group in (
        review["command_reviews"],
        review["condition_reviews"],
        review["preservation_reviews"],
    ):
        for item in group:
            item["approved"] = True
    review["documentation"] = {"sufficient": True, "missing_instruction": None}
    review_path.write_text(json.dumps(review), encoding="utf-8")
    copied.review_session(
        SimpleNamespace(
            session=session,
            review_manifest=review_path,
            attestation_key=key_path,
        )
    )
    final_parent = authority / "final"
    final_parent.mkdir(mode=0o700)
    final_output = final_parent / "fixture-02"
    copied.finalize_session(
        SimpleNamespace(session=session, output=final_output, attestation_key=key_path)
    )

    actual_receipt = final_output / "receipts/tester-e2e00002.json"
    paths[1].write_bytes(actual_receipt.read_bytes())
    (sessions / "fixture-02.session.json").write_bytes(session.read_bytes())
    for source, destination in (
        (final_output / "evidence", evidence),
        (final_output / "attestations", attestations),
    ):
        for item in source.iterdir():
            shutil.copy2(item, destination / item.name)

    ledger.unlink()
    for fixture_index in range(5):
        state_path = sessions / f"fixture-{fixture_index + 1:02d}.session.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        _append_test_state_history(
            ledger,
            state,
            _sha(state_path),
            f"actual-fixture-{fixture_index}",
        )


def _write_subprocess_controller_harness(tmp_path: Path) -> tuple[Path, Path]:
    executor = tmp_path / "fixture-command-executor.py"
    executor.write_text(
        """import base64
import json
from pathlib import Path
import sys

operation, venv_text, mapping_text, fixture_id = sys.argv[1:]
venv = Path(venv_text)
if operation == "venv_create":
    (venv / "bin").mkdir(parents=True)
if operation == "package_install":
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("python", "pcodex", "premode"):
        target = venv / "bin" / name
        target.write_text(f"#!/bin/sh\\n# controlled {name}\\n", encoding="utf-8")
        target.chmod(0o700)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site = venv / "lib" / version / "site-packages"
    (site / "premode").mkdir(parents=True)
    (site / "premode/__init__.py").write_text('__version__ = "0.3.0b1"\\n', encoding="utf-8")
    info = site / "premode_router-0.3.0b1.dist-info"
    info.mkdir()
    (info / "RECORD").write_text(
        "premode/__init__.py,,\\n"
        "premode_router-0.3.0b1.dist-info/RECORD,,\\n"
        "../../../bin/pcodex,,\\n../../../bin/premode,,\\n../../../bin/python,,\\n",
        encoding="utf-8",
    )
mapping = json.loads(Path(mapping_text).read_text(encoding="utf-8"))
item = mapping[f"{fixture_id}:{operation}"]
sys.stdout.buffer.write(base64.b64decode(item["stdout_base64"]))
sys.stderr.buffer.write(base64.b64decode(item["stderr_base64"]))
raise SystemExit(item["exit_code"])
""",
        encoding="utf-8",
    )
    harness = tmp_path / "copied-recorder-controller.py"
    harness.write_text(
        """from pathlib import Path
import sys

coordinator, executor, mapping, fixture_id, *arguments = sys.argv[1:]
sys.path.insert(0, coordinator)
import record_first_run_study as recorder

original = recorder._operation_argv
def controlled(operation, state):
    argv, resolved, _execution = original(operation, state)
    execution = [sys.executable, "-B", executor, operation, state["venv_root"], mapping, fixture_id]
    return argv, resolved, execution
recorder._operation_argv = controlled
raise SystemExit(recorder.main(arguments))
""",
        encoding="utf-8",
    )
    return harness, executor


def test_strict_five_tester_evidence_produces_content_free_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _validate(_inputs(tmp_path, monkeypatch))
    assert result["status"] == "passed", result
    assert result["activation_rate"] == 1.0
    assert result["study_kit_integrity_valid"] is True
    assert result["attestation_evidence_successes"] == 5
    assert result["transcript_evidence_successes"] == 5
    assert result["private_receipt_content_included"] is False
    assert result["invalid_receipt_count"] == 0
    assert "invalid_receipts" not in result


def test_copied_recorder_fixture_two_passes_final_aggregate_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    _replace_fixture_two_with_real_recorder_journey(inputs, tmp_path)
    result = _validate(inputs)
    assert result["status"] == "passed", result
    assert result["runtime_condition_successes"] == 5
    assert result["attempt_ledger_valid"] is True


def test_copied_cli_runs_all_fixtures_and_passes_aggregate_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel, qualification = _qualified_wheel(tmp_path)
    runtime_python = tmp_path / "controlled-python"
    runtime_python.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n',
        encoding="utf-8",
    )
    runtime_python.chmod(0o700)
    monkeypatch.setattr(kit_builder, "_assert_source_commit", lambda _commit: None)
    kit_root = tmp_path / "cli-kit"
    build_kit(
        kit_root,
        wheel,
        COMMIT,
        qualification,
        runtime_python,
        GIT,
        verify_release_root=False,
    )
    kit_path = kit_root / "coordinator/study-kit.json"
    kit = json.loads(kit_path.read_text(encoding="utf-8"))
    coordinator = kit_path.parent
    harness, executor = _write_subprocess_controller_harness(tmp_path)
    mapping: dict[str, dict[str, object]] = {}
    for fixture in kit["fixtures"]:
        for operation in fixture["required_operations"]:
            stdout, exit_code = _stdout(operation, kit["wheel"]["sha256"])
            if fixture["id"] == "fixture-05" and operation in {
                "mcp_status",
                "codex_status_final",
            }:
                payload = json.loads(stdout)
                payload["optional_mcp"] = "healthy"
                stdout = json.dumps(payload, sort_keys=True).encode()
            mapping[f"{fixture['id']}:{operation}"] = {
                "stdout_base64": base64.b64encode(stdout).decode(),
                "stderr_base64": "",
                "exit_code": exit_code,
            }
    mapping_path = tmp_path / "controlled-command-results.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

    private = tmp_path / "private-controller"
    private.mkdir(mode=0o700)
    key = private / "coordinator.key"
    key.write_bytes(KEY)
    key.chmod(0o600)
    sessions = private / "sessions"
    ledger = private / "attempt-ledger.jsonl"
    reviews = private / "reviews"
    reviews.mkdir(mode=0o700)
    final_parent = private / "final"
    final_parent.mkdir(mode=0o700)
    evidence = private / "aggregate-evidence"
    attestations = private / "aggregate-attestations"
    evidence.mkdir(mode=0o700)
    attestations.mkdir(mode=0o700)
    codex = private / "codex"
    codex.write_text("#!/bin/sh\necho 'codex-cli 0.143.0'\n", encoding="utf-8")
    codex.chmod(0o700)

    controller_environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C",
    }

    def controller(
        fixture_id: str, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [
                str(runtime_python),
                "-B",
                str(harness),
                str(coordinator),
                str(executor),
                str(mapping_path),
                fixture_id,
                *arguments,
            ],
            cwd=tmp_path,
            env=controller_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr
        return completed

    receipt_paths: list[Path] = []
    for fixture in kit["fixtures"]:
        fixture_id = fixture["id"]
        sandbox = tmp_path / f"sandbox-{fixture_id}"
        sandbox.mkdir(mode=0o700)
        repository = (
            sandbox / "repository with spaces β"
            if fixture_id == "fixture-04"
            else sandbox / "repository"
        )
        restored = subprocess.run(
            [
                str(runtime_python),
                "-B",
                str(coordinator / "restore_first_run_fixture.py"),
                "--snapshot",
                str(kit_path.parents[1] / fixture["snapshot"]),
                "--sha256",
                fixture["sha256"],
                "--destination",
                str(repository),
                "--git",
                kit["runtime_tools"]["git"]["path"],
                "--fixture-id",
                fixture_id,
            ],
            cwd=tmp_path,
            env=controller_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert restored.returncode == 0, restored.stderr
        session = sessions / f"{fixture_id}.session.json"
        init_arguments = [
            "init",
            "--session",
            str(session),
            "--study-kit",
            str(kit_path),
            "--study-kit-sha256",
            _sha(kit_path),
            "--fixture",
            fixture_id,
            "--tester-id",
            f"tester-cli{fixture_id[-2:] * 4}",
            "--repository",
            str(repository),
            "--venv",
            str(sandbox / "venv"),
            "--sandbox",
            str(sandbox),
            "--attestation-key",
            str(key),
            "--attempt-ledger",
            str(ledger),
        ]
        if fixture_id != "fixture-01":
            init_arguments.extend(("--codex", str(codex)))
        controller(fixture_id, *init_arguments)
        for operation in fixture["required_operations"]:
            controller(
                fixture_id,
                "run-next",
                "--session",
                str(session),
                "--operation",
                operation,
                "--attestation-key",
                str(key),
            )
        review_path = reviews / f"{fixture_id}.json"
        controller(
            fixture_id,
            "build-review-manifest",
            "--session",
            str(session),
            "--output",
            str(review_path),
            "--signer-id",
            f"coordinator-cli{fixture_id[-2:] * 4}",
            "--attestation-key",
            str(key),
        )
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["no_prior_knowledge_attested"] = True
        review["completed"] = True
        for group in (
            review["command_reviews"],
            review["condition_reviews"],
            review["preservation_reviews"],
        ):
            for item in group:
                item["approved"] = True
        review["documentation"] = {
            "sufficient": True,
            "missing_instruction": None,
        }
        review_path.write_text(json.dumps(review), encoding="utf-8")
        controller(
            fixture_id,
            "review",
            "--session",
            str(session),
            "--review-manifest",
            str(review_path),
            "--attestation-key",
            str(key),
        )
        output = final_parent / fixture_id
        controller(
            fixture_id,
            "finalize",
            "--session",
            str(session),
            "--output",
            str(output),
            "--attestation-key",
            str(key),
        )
        fixture_receipts = list((output / "receipts").glob("*.json"))
        assert len(fixture_receipts) == 1
        receipt_paths.append(fixture_receipts[0])
        for source, destination in (
            (output / "evidence", evidence),
            (output / "attestations", attestations),
        ):
            for item in source.iterdir():
                shutil.copy2(item, destination / item.name)

    result = validate_receipts(
        receipt_paths,
        kit_path,
        qualification,
        wheel,
        attestations,
        evidence,
        key,
        sessions,
        ledger,
        verify_release_root=False,
        verify_git=False,
    )
    assert result["status"] == "passed", result
    assert result["attempt_ledger_valid"] is True
    assert not list(kit_path.parents[1].rglob("__pycache__"))


@pytest.mark.parametrize("payload", [b"{}", b'{"status":"error"}'])
def test_run_dry_run_semantics_fail_closed(payload: bytes) -> None:
    with pytest.raises(ValueError):
        validator._derived_result("run_dry_run", payload)


def test_signed_human_claim_mutation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    receipt_path = inputs[0][0]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["documentation"] = {
        "sufficient": False,
        "missing_instruction": "mutated after witnessing",
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert _validate(inputs)["status"] == "failed"


def test_missing_codex_exit_one_is_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    assert _validate(inputs)["status"] == "passed"
    receipt = json.loads(inputs[0][0].read_text(encoding="utf-8"))  # type: ignore[index,union-attr]
    command = next(
        c for c in receipt["commands"] if c["operation"] == "missing_codex_status"
    )
    command["exit_code"] = 0
    inputs[0][0].write_text(json.dumps(receipt), encoding="utf-8")  # type: ignore[index,union-attr]
    assert _validate(inputs)["status"] == "failed"


def test_signed_failed_session_cannot_be_replaced_or_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    session_path = inputs[7] / "fixture-01.session.json"  # type: ignore[operator]
    successful_session = session_path.read_bytes()
    state = json.loads(session_path.read_text(encoding="utf-8"))
    state.pop("signature")
    state["status"] = "failed_closed"
    state["events"] = state["events"][:3]
    state["cursor"] = 3
    state["failed_attempts"] = [{"category": "command_failed"}]
    state["signature"] = hmac.new(KEY, _json_bytes(state), hashlib.sha256).hexdigest()
    session_path.write_text(json.dumps(state), encoding="utf-8")
    inputs[8].unlink()  # type: ignore[union-attr]
    for index in range(1, 6):
        candidate = inputs[7] / f"fixture-{index:02d}.session.json"  # type: ignore[operator]
        candidate_state = json.loads(candidate.read_text(encoding="utf-8"))
        _append_test_state_history(
            inputs[8],  # type: ignore[arg-type]
            candidate_state,
            _sha(candidate),
            f"failed-fixture-{index}",
        )
    result = _validate(inputs)
    assert result["status"] == "failed"
    assert result["attempt_count"] == 5
    assert result["failed_attempt_count"] == 1
    assert result["invalid_session_count"] == 0
    assert result["session_bindings_valid"] is False
    session_path.write_bytes(successful_session)
    replacement_result = _validate(inputs)
    assert replacement_result["status"] == "failed"
    assert replacement_result["failed_attempt_count"] == 1
    assert replacement_result["attempt_ledger_valid"] is False


def test_missing_preassigned_session_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    (inputs[7] / "fixture-05.session.json").unlink()  # type: ignore[operator]
    result = _validate(inputs)
    assert result["status"] == "failed"
    assert result["invalid_session_count"] == 1


def test_forged_or_reused_private_evidence_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    receipt = json.loads(inputs[0][1].read_text(encoding="utf-8"))  # type: ignore[index,union-attr]
    receipt["commands"][1]["evidence_sha256"] = receipt["commands"][0][
        "evidence_sha256"
    ]
    inputs[0][1].write_text(json.dumps(receipt), encoding="utf-8")  # type: ignore[index,union-attr]
    result = _validate(inputs)
    assert result["status"] == "failed"
    assert result["transcript_evidence_successes"] == 4


@pytest.mark.parametrize("target", ["snapshot", "wheel", "document"])
def test_missing_or_tampered_kit_member_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    kit = json.loads(inputs[1].read_text(encoding="utf-8"))  # type: ignore[union-attr]
    root = inputs[1].parents[1]  # type: ignore[union-attr]
    if target == "snapshot":
        (root / kit["fixtures"][0]["snapshot"]).unlink()
    elif target == "wheel":
        (
            root / "blind-tester-payload/artifacts" / kit["wheel"]["filename"]
        ).write_bytes(b"tampered")
    else:
        (root / "blind-tester-payload/README.md").write_text(
            "tampered\n", encoding="utf-8"
        )
    result = _validate(inputs)
    assert result["status"] == "failed"
    assert result["study_kit_integrity_valid"] is False


def test_fixture_member_authority_rejects_rehashed_extra_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    kit_path = inputs[1]  # type: ignore[assignment]
    kit = json.loads(kit_path.read_text(encoding="utf-8"))
    fixture = kit["fixtures"][0]
    snapshot = kit_path.parents[1] / fixture["snapshot"]
    rewritten = snapshot.with_suffix(".new.zip")
    with (
        zipfile.ZipFile(snapshot) as source,
        zipfile.ZipFile(rewritten, "w", zipfile.ZIP_STORED) as target,
    ):
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        info = zipfile.ZipInfo("AGENTS.md", date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        target.writestr(info, b"hostile undeclared authority\n")
    rewritten.replace(snapshot)
    fixture["sha256"] = _sha(snapshot)
    fixture["member_sha256"]["AGENTS.md"] = hashlib.sha256(
        b"hostile undeclared authority\n"
    ).hexdigest()
    fixture["restore_argv"][5] = fixture["sha256"]
    kit_path.write_text(json.dumps(kit), encoding="utf-8")
    result = _validate(inputs)
    assert result["status"] == "failed"
    assert result["study_kit_integrity_valid"] is False


@pytest.mark.parametrize(
    "relative", ["coordinator/RUNBOOK.md", "coordinator/task-cards/fixture-01.md"]
)
def test_study_instruction_authority_is_byte_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    target = inputs[1].parents[1] / relative  # type: ignore[union-attr]
    target.write_text("tampered coordinator instruction\n", encoding="utf-8")
    result = _validate(inputs)
    assert result["study_kit_integrity_valid"] is False


def test_kit_has_no_unbound_receipt_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit, _wheel, _qualification = _build_kit(tmp_path, monkeypatch)
    assert not (kit.parent / "receipt-templates").exists()
    assert (kit.parent / "record_first_run_study.py").is_file()


def test_copied_recorder_runs_without_source_checkout_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit, _wheel, _qualification = _build_kit(tmp_path, monkeypatch)
    completed = subprocess.run(
        [
            str(PYTHON),
            "-B",
            str(kit.parent / "record_first_run_study.py"),
            "--help",
        ],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "run-next" in completed.stdout


def test_recorder_state_is_signed_and_rejects_tampering(tmp_path: Path) -> None:
    session = tmp_path / "session.json"
    state = {"schema_version": "pcodex.first-run-recorder-state.v1", "cursor": 0}
    recorder._write_state(session, state, KEY)
    assert recorder._read_state(session, KEY)["cursor"] == 0
    tampered = json.loads(session.read_text(encoding="utf-8"))
    tampered["cursor"] = 1
    session.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="signature mismatch"):
        recorder._read_state(session, KEY)


def test_attempt_ledger_blocks_deleted_session_reinitialization(tmp_path: Path) -> None:
    session = tmp_path / "fixture-01.session.json"
    ledger = tmp_path / "attempt-ledger.jsonl"
    state = {
        "schema_version": "pcodex.first-run-recorder-state.v1",
        "status": "recording",
        "attempt_ledger": str(ledger),
        "fixture": {"id": "fixture-01"},
        "tester_id": "tester-ledger001",
        "cursor": 0,
        "events": [],
        "failed_attempts": [],
    }
    recorder._write_state(session, state, KEY)
    session.unlink()
    with pytest.raises(ValueError, match="already been consumed"):
        recorder._write_state(session, state, KEY)


def test_attempt_ledger_is_preflighted_before_session_use(tmp_path: Path) -> None:
    session = tmp_path / "fixture-01.session.json"
    ledger = tmp_path / "attempt-ledger.jsonl"
    state = {
        "schema_version": "pcodex.first-run-recorder-state.v1",
        "status": "recording",
        "attempt_ledger": str(ledger),
        "fixture": {"id": "fixture-01"},
        "tester_id": "tester-ledger002",
        "cursor": 0,
        "events": [],
        "failed_attempts": [],
    }
    recorder._write_state(session, state, KEY)
    ledger.write_bytes(ledger.read_bytes() + b"tampered\n")
    with pytest.raises(ValueError, match="attempt ledger"):
        recorder._read_state(session, KEY)


def test_attempt_ledger_rejects_duplicate_cursor_transition(tmp_path: Path) -> None:
    ledger = tmp_path / "attempt-ledger.jsonl"
    initial = {
        "fixture": {"id": "fixture-01"},
        "tester_id": "tester-ledger003",
        "status": "recording",
        "cursor": 0,
        "events": [],
        "failed_attempts": [],
    }
    first = {**initial, "cursor": 1, "events": [{"operation": "one"}]}
    recorder._append_attempt_ledger(ledger, initial, "0" * 64, KEY)
    recorder._append_attempt_ledger(ledger, first, "1" * 64, KEY, "0" * 64)
    with pytest.raises(ValueError, match="descend from current state"):
        recorder._append_attempt_ledger(ledger, first, "2" * 64, KEY, "0" * 64)


def test_run_next_serializes_the_full_session_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = tmp_path / "fixture-01.session.json"
    session.write_text("{}", encoding="utf-8")
    recorder._create_session_lock(session)
    active = 0
    maximum = 0
    guard = threading.Lock()

    def fake_locked(_args: object) -> int:
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return 0

    monkeypatch.setattr(recorder, "_run_next_locked", fake_locked)
    args = SimpleNamespace(session=session)
    threads = [
        threading.Thread(target=recorder.run_next, args=(args,)) for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert not any(thread.is_alive() for thread in threads)
    assert maximum == 1


def test_failed_package_install_is_signed_and_cannot_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit_path, _wheel, _qualification = _build_kit(tmp_path, monkeypatch)
    kit = json.loads(kit_path.read_text(encoding="utf-8"))
    fixture = kit["fixtures"][0]
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(mode=0o700)
    repository = sandbox / "repository"
    restore(
        kit_path.parents[1] / fixture["snapshot"],
        fixture["sha256"],
        repository,
        fixture["id"],
        Path(kit["runtime_tools"]["git"]["path"]),
    )
    key_path = tmp_path / "coordinator.key"
    key_path.write_bytes(KEY)
    key_path.chmod(0o600)
    session = tmp_path / "sessions/fixture-01.session.json"
    ledger = tmp_path / "attempt-ledger.jsonl"
    venv = sandbox / "venv"
    recorder.init_session(
        SimpleNamespace(
            session=session,
            study_kit=kit_path,
            study_kit_sha256=_sha(kit_path),
            fixture="fixture-01",
            tester_id="tester-installfail1",
            repository=repository,
            venv=venv,
            sandbox=sandbox,
            codex=None,
            attestation_key=key_path,
            attempt_ledger=ledger,
        )
    )
    original_operation_argv = recorder._operation_argv
    real_subprocess_run = subprocess.run

    def fake_operation_argv(
        operation: str, state: dict[str, object]
    ) -> tuple[list[str], str, list[str]]:
        argv, resolved, _execution = original_operation_argv(operation, state)
        return argv, resolved, ["__pcodex_failed_install__", operation]

    def fake_run(argv: list[str] | tuple[str, ...], **kwargs: object) -> object:
        if argv[0] != "__pcodex_failed_install__":
            return real_subprocess_run(argv, **kwargs)
        operation = argv[1]
        if operation == "artifact_verify":
            stdout = f"{kit['wheel']['sha256']}\n".encode()
            return subprocess.CompletedProcess(argv, 0, stdout, b"")
        if operation == "venv_create":
            (venv / "bin").mkdir(parents=True)
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        assert operation == "package_install"
        return subprocess.CompletedProcess(argv, 1, b"", b"controlled failure")

    monkeypatch.setattr(recorder, "_operation_argv", fake_operation_argv)
    monkeypatch.setattr(recorder.subprocess, "run", fake_run)
    for operation in ("artifact_verify", "venv_create"):
        assert (
            recorder.run_next(
                SimpleNamespace(
                    session=session,
                    operation=operation,
                    attestation_key=key_path,
                )
            )
            == 0
        )
    args = SimpleNamespace(
        session=session,
        operation="package_install",
        attestation_key=key_path,
    )
    assert recorder.run_next(args) == 1
    state = recorder._read_state(session, KEY)
    assert state["status"] == "failed_closed"
    assert state["cursor"] == 2
    assert len(state["failed_attempts"]) == 1
    assert state["failed_attempts"][0]["operation"] == "package_install"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 4
    with pytest.raises(ValueError, match="not in the recording state"):
        recorder.run_next(args)


def test_finalization_rejects_existing_output_and_symlink_children(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    repository = tmp_path / "repo"
    repository.mkdir()
    kit_root = tmp_path / "kit"
    (kit_root / "coordinator").mkdir(parents=True)
    study_kit = kit_root / "coordinator/study-kit.json"
    study_kit.write_text("{}", encoding="utf-8")
    session = tmp_path / "session.json"
    output = tmp_path / "private-output"
    output.mkdir(mode=0o700)
    reviewed = {
        "status": "reviewed",
        "repository_root": str(repository),
        "study_kit": str(study_kit),
    }
    with pytest.raises(ValueError, match="must be absent"):
        recorder._prepare_finalization_output(
            SimpleNamespace(output=output, session=session), reviewed, KEY
        )

    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "evidence").symlink_to(outside, target_is_directory=True)
    finalizing = {
        "status": "finalizing",
        "repository_root": str(repository),
        "study_kit": str(study_kit),
        "finalization_output": str(output),
    }
    with pytest.raises(ValueError, match="must not be a symlink"):
        recorder._prepare_finalization_output(
            SimpleNamespace(output=output, session=session), finalizing, KEY
        )


def test_atomic_private_output_is_idempotent_and_mismatch_fails(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    recorder._atomic_private_file(target, b"same\n")
    recorder._atomic_private_file(target, b"same\n")
    with pytest.raises(ValueError, match="does not match"):
        recorder._atomic_private_file(target, b"different\n")


def test_content_addressed_evidence_recovers_partial_atomic_write(
    tmp_path: Path,
) -> None:
    payload = {"kind": "command", "value": "bounded"}
    digest = hashlib.sha256(_json_bytes(payload)).hexdigest()
    target = tmp_path / f"{digest}.evidence"
    target.write_bytes(b"partial")
    assert recorder._store_content(tmp_path, ".evidence", payload) == digest
    assert target.read_bytes() == _json_bytes(payload)


def test_missing_codex_semantics_match_real_plugin_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "")
    payload = plugin_status(tmp_path)
    assert payload["reason"] == "plugin_absent"
    result = validator._derived_result(
        "missing_codex_status", json.dumps(payload).encode("utf-8")
    )
    assert result["status"] == "NEEDS_ACTION"


def test_recorder_operation_authority_rejects_unknown_operation(tmp_path: Path) -> None:
    state = {
        "payload_wheel": str(tmp_path / "payload.whl"),
        "venv_root": str(tmp_path / "venv"),
        "runtime_python": str(PYTHON),
    }
    with pytest.raises(KeyError):
        recorder._operation_argv("arbitrary_shell_command", state)


def test_custom_schema_bypass_is_not_a_cli_option() -> None:
    with pytest.raises(SystemExit):
        validator.main(["--schema", "/tmp/permissive.json"])


def test_fixture_idempotency_matches_actual_mcp_mode_state_machine(
    tmp_path: Path,
) -> None:
    standard = tmp_path / "standard"
    standard.mkdir()
    assert apply_integration(standard)["status"] == "installed"
    assert apply_integration(standard)["status"] == "unchanged"
    assert apply_integration(standard, with_mcp=True)["status"] == "blocked"
    assert "codex_install_idempotent" in validator.EXPECTED_OPERATIONS["fixture-04"]

    mcp = tmp_path / "mcp"
    mcp.mkdir()
    assert apply_integration(mcp, with_mcp=True)["status"] == "installed"
    assert apply_integration(mcp, with_mcp=True)["status"] == "unchanged"
    assert apply_integration(mcp)["status"] == "blocked"
    assert "mcp_install_idempotent" in validator.EXPECTED_OPERATIONS["fixture-05"]


def test_reenable_uses_actual_repair_lifecycle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert apply_integration(repo)["status"] == "installed"
    assert disable_integration(repo)["status"] == "disabled"
    assert repair_integration(repo)["status"] == "repaired"
    assert validator.INTEGRATE_FLAGS["codex_reenable"] == {"--repair"}


def test_fixture_restore_rejects_traversal_and_duplicates(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape", "bad")
    with pytest.raises(RuntimeError, match="unsafe"):
        restore(
            archive, _sha(archive), tmp_path / "out", "fixture-01", Path("/usr/bin/git")
        )

    alias = tmp_path / "alias.zip"
    with zipfile.ZipFile(alias, "w") as handle:
        for name, content in (("README.md", "first"), ("./README.md", "second")):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            handle.writestr(info, content)
    with pytest.raises(RuntimeError, match="unsafe"):
        restore(
            alias,
            _sha(alias),
            tmp_path / "alias-out",
            "fixture-01",
            Path("/usr/bin/git"),
        )


@pytest.mark.parametrize(
    ("git_config", "attributes"),
    [(".git/config", ".gitattributes"), (".GIT/config", ".GITATTRIBUTES")],
)
def test_fixture_restore_rejects_git_filter_execution_surface(
    tmp_path: Path, git_config: str, attributes: str
) -> None:
    marker = tmp_path / "must-not-exist"
    archive = tmp_path / "git-filter.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(
            git_config,
            f'[filter "evil"]\n\tclean = /usr/bin/touch {marker}\n\trequired = true\n',
        )
        handle.writestr(attributes, "payload filter=evil\n")
        handle.writestr("payload", "content\n")
    with pytest.raises(RuntimeError, match="unsafe"):
        restore(
            archive, _sha(archive), tmp_path / "out", "fixture-01", Path("/usr/bin/git")
        )
    assert not marker.exists()


def test_fixture_restore_ignores_hostile_inherited_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as handle:
        info = zipfile.ZipInfo("README.md", date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        handle.writestr(info, "safe\n")
    outside = tmp_path / "outside.git"
    monkeypatch.setenv("GIT_DIR", str(outside))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "outside-worktree"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "outside.index"))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.hooksPath=/tmp/hostile'")
    destination = tmp_path / "restored"
    restore(archive, _sha(archive), destination, "fixture-01", Path("/usr/bin/git"))
    assert (destination / ".git").is_dir()
    assert not outside.exists()
    assert not (tmp_path / "outside.index").exists()


def test_builder_is_deterministic_and_source_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_assert = kit_builder._assert_source_commit
    wheel, qualification = _qualified_wheel(tmp_path)
    monkeypatch.setattr(kit_builder, "_assert_source_commit", lambda _commit: None)
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_kit(
        first, wheel, COMMIT, qualification, PYTHON, GIT, verify_release_root=False
    )
    build_kit(
        second, wheel, COMMIT, qualification, PYTHON, GIT, verify_release_root=False
    )
    first_map = {
        path.relative_to(first).as_posix(): _sha(path)
        for path in first.rglob("*")
        if path.is_file()
    }
    second_map = {
        path.relative_to(second).as_posix(): _sha(path)
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_map == second_map

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture.invalid"], cwd=source, check=True
    )
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=source, check=True)
    (source / "README.md").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=source, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    source_assert(head, source)
    (source / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="must be clean"):
        source_assert(head, source)
