#!/usr/bin/env python3
"""Build the frozen five-fixture first-run coordinator kit and blind payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import zipfile


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_release_artifacts import materialize_legacy_fixture  # noqa: E402
from first_run_study_authority import (  # noqa: E402
    executable_authority,
    expected_fixture_members,
    expected_fixture_surfaces,
    runbook_text,
    task_card_text,
)


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA = ROOT / "schemas/pcodex.first-run-study-receipt.v1.schema.json"
KIT_SCHEMA = ROOT / "schemas/pcodex.first-run-study-kit.v1.schema.json"
EVIDENCE_SCHEMA = ROOT / "schemas/pcodex.first-run-study-evidence.v1.schema.json"
PROTOCOL = ROOT / "docs/FIRST_RUN_STUDY_PROTOCOL.md"
VALIDATOR = ROOT / "scripts/validate_first_run_study.py"
RESTORER = ROOT / "scripts/restore_first_run_fixture.py"
RECORDER = ROOT / "scripts/record_first_run_study.py"

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
FIXTURE_OPERATIONS = {
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
FIXTURE_CONDITIONS = {
    "fixture-01": ["clean_repository", "missing_codex", "mcp_absent"],
    "fixture-02": ["dirty_repository", "unrelated_agents"],
    "fixture-03": ["unrelated_codex_config", "supported_codex_0.143.x"],
    "fixture-04": ["path_with_spaces", "unicode_path", "supported_legacy_plugin"],
    "fixture-05": ["optional_mcp", "install_twice", "uninstall_reinstall"],
}
FIXTURE_CHECKPOINTS = {
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _surface_sha256(path: Path) -> str:
    if path.is_file():
        return _sha256(path)
    entries = []
    for item in sorted(path.rglob("*")):
        if item.is_file() and not item.is_symlink():
            entries.append(
                {
                    "path": item.relative_to(path).as_posix(),
                    "sha256": _sha256(item),
                }
            )
    return _canonical_json_sha256(entries)


def _assert_source_commit(commit: str, source: Path = ROOT) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=source,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    if head != commit:
        raise RuntimeError(
            f"study-kit source HEAD {head} does not match candidate {commit}"
        )
    if dirty:
        raise RuntimeError("study-kit source worktree and index must be clean")


def _zip_tree(root: Path, destination: Path) -> str:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_STORED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            name = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def _qualify_restores(
    output: Path,
    fixtures: list[dict[str, Any]],
    python_executable: Path,
    git_executable: Path,
) -> None:
    with tempfile.TemporaryDirectory(
        prefix="pcodex-first-run-restore-", dir=output.parent
    ) as temporary:
        root = Path(temporary)
        for fixture in fixtures:
            fixture_id = str(fixture["id"])
            destination = root / (
                "repository with spaces β" if fixture_id == "fixture-04" else fixture_id
            )
            argv = list(fixture["restore_argv"])
            argv[1] = str(output / argv[1])
            argv[3] = str(output / argv[3])
            argv[7] = str(destination)
            completed = subprocess.run(
                argv,
                cwd=output,
                env={
                    "HOME": str(root / "home"),
                    "PATH": f"{python_executable.parent}:{git_executable.parent}:/usr/bin:/bin",
                    "TMPDIR": temporary,
                    "LC_ALL": "C",
                },
                capture_output=True,
                check=False,
                timeout=60,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"{fixture_id} restore qualification failed")
            status = subprocess.run(
                (str(git_executable), "status", "--porcelain=v1"),
                cwd=destination,
                env={
                    "HOME": str(root / "home"),
                    "PATH": f"{git_executable.parent}:/usr/bin:/bin",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull,
                    "LC_ALL": "C",
                },
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout
            expected = (
                b"?? dirty-untracked.txt\n" if fixture_id == "fixture-02" else b""
            )
            if status != expected:
                raise RuntimeError(f"{fixture_id} restore Git state mismatch")


def _validate_qualified_wheel(
    wheel: Path,
    qualification_root: Path,
    commit: str,
    *,
    verify_release_root: bool,
) -> tuple[bytes, str, Path]:
    if wheel.is_symlink():
        raise RuntimeError("--wheel must not be a symlink")
    wheel = wheel.resolve()
    if (
        wheel.is_symlink()
        or not wheel.is_file()
        or wheel.name != "premode_router-0.3.0b1-py3-none-any.whl"
    ):
        raise RuntimeError("--wheel must be the canonical 0.3.0b1 wheel")
    wheel_bytes = wheel.read_bytes()
    wheel_hash = hashlib.sha256(wheel_bytes).hexdigest()
    if not zipfile.is_zipfile(wheel):
        raise RuntimeError("qualified wheel is not a valid ZIP archive")
    if verify_release_root:
        from build_release_artifacts import (
            members,
            validate_archive_content,
            validate_archive_structure,
            validate_names,
        )
        from validate_release_metadata import validate

        release_result = validate(qualification_root.resolve())
        subjects = release_result["release_subjects"]
        wheel_relatives = [name for name in subjects if name.endswith(".whl")]
        if (
            len(wheel_relatives) != 1
            or (qualification_root.resolve() / wheel_relatives[0]).resolve() != wheel
        ):
            raise RuntimeError("wheel is not the release qualification subject")
        policy = json.loads(
            (ROOT / "release/artifact-allowlist.json").read_text(encoding="utf-8")
        )
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
            raise RuntimeError("qualified wheel failed default-deny archive policy")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        required_suffixes = (
            ".dist-info/METADATA",
            ".data/data/share/premode-router/premode.product.json",
            ".data/data/share/premode-router/plugins/pcodex/.codex-plugin/plugin.json",
            ".data/data/share/premode-router/plugins/pcodex/skills/pcodex/SKILL.md",
        )
        if not all(
            any(name.endswith(suffix) for name in names) for suffix in required_suffixes
        ):
            raise RuntimeError(
                "qualified wheel is missing canonical product/plugin resources"
            )
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise RuntimeError("qualified wheel must contain exactly one METADATA")
        metadata_name = metadata_names[0]
        metadata = archive.read(metadata_name).decode("utf-8", errors="strict")
        if "\nVersion: 0.3.0b1\n" not in f"\n{metadata}":
            raise RuntimeError("qualified wheel metadata version is not 0.3.0b1")
    qualification = (
        qualification_root.resolve() / "receipts/qualification-summary.json"
        if verify_release_root
        else qualification_root.resolve()
    )
    receipt = json.loads(qualification.read_text(encoding="utf-8"))
    artifact_hashes = {
        item.get("digest", {}).get("sha256")
        for item in receipt.get("artifacts", [])
        if str(item.get("name", "")).endswith(".whl")
    }
    if not all(
        (
            receipt.get("schema_version") == "pcodex.release-qualification.v1",
            receipt.get("status") == "passed",
            receipt.get("commit") == commit,
            receipt.get("product_version") == "0.3.0b1",
            receipt.get("package_content_allowlist") == "passed",
            receipt.get("wheel_sdist_parity") == "passed",
            wheel_hash in artifact_hashes,
        )
    ):
        raise RuntimeError("wheel is not bound to a passing qualification receipt")
    return wheel_bytes, wheel_hash, qualification


def build_kit(
    output: Path,
    wheel: Path,
    commit: str,
    qualification_root: Path,
    python_executable: Path,
    git_executable: Path,
    *,
    verify_release_root: bool = True,
) -> dict[str, object]:
    _assert_source_commit(commit)
    try:
        output.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise RuntimeError("study-kit output must be outside the source checkout")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("study-kit output must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    payload = output / "blind-tester-payload"
    coordinator = output / "coordinator"
    fixtures_root = coordinator / "fixture-work"
    snapshots = coordinator / "fixtures"
    task_cards = coordinator / "task-cards"
    for path in (
        payload / "artifacts",
        payload / "docs",
        fixtures_root,
        snapshots,
        task_cards,
    ):
        path.mkdir(parents=True, exist_ok=True)

    runtime_tools = {
        "python": executable_authority(python_executable, "python"),
        "git": executable_authority(git_executable, "git"),
    }
    trusted_python = Path(runtime_tools["python"]["path"])
    trusted_git = Path(runtime_tools["git"]["path"])

    wheel = wheel.resolve()
    wheel_bytes, wheel_hash, qualification = _validate_qualified_wheel(
        wheel,
        qualification_root.resolve(),
        commit,
        verify_release_root=verify_release_root,
    )
    (payload / "artifacts" / wheel.name).write_bytes(wheel_bytes)
    (payload / "artifacts" / "SHA256SUMS").write_text(
        f"{wheel_hash}  {wheel.name}\n", encoding="utf-8"
    )
    manifest = json.loads((ROOT / "premode.product.json").read_text(encoding="utf-8"))
    document_hashes: dict[str, str] = {}
    for relative in manifest["documentation_contract"]["canonical_docs"]:
        source = ROOT / relative
        destination = payload / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        document_hashes[relative] = hashlib.sha256(destination.read_bytes()).hexdigest()

    fixture_manifest: list[dict[str, Any]] = []
    for fixture_id, labels in FIXTURE_CONDITIONS.items():
        name = "repository"
        if fixture_id == "fixture-04":
            name = "repository with spaces β"
        repo = fixtures_root / fixture_id / name
        repo.mkdir(parents=True)
        (repo / "README.md").write_text(f"# {fixture_id}\n", encoding="utf-8")
        if fixture_id == "fixture-02":
            (repo / ".agents/unrelated").mkdir(parents=True)
            (repo / ".agents/unrelated/README.md").write_text(
                "unrelated user state\n", encoding="utf-8"
            )
            (repo / "dirty-untracked.txt").write_text(
                "must remain unrelated\n", encoding="utf-8"
            )
        if fixture_id == "fixture-03":
            (repo / "fixture-codex-home").mkdir()
            (repo / "fixture-codex-home/config.toml").write_text(
                'model = "preserve-me"\n[unknown]\nvalue = true\n', encoding="utf-8"
            )
        if fixture_id == "fixture-04":
            materialize_legacy_fixture(repo)
        if fixture_id == "fixture-05":
            (repo / "fixture-codex-home").mkdir()
            (repo / "fixture-codex-home/config.toml").write_text(
                '# preserve formatting and unrelated MCP\n[mcp_servers.unrelated]\ncommand = "/usr/bin/true"\n',
                encoding="utf-8",
            )
        preservation_surfaces = expected_fixture_surfaces(fixture_id, trusted_git)
        if fixture_id == "fixture-02":
            (repo / "dirty-untracked.txt").unlink()
        snapshot = snapshots / f"{fixture_id}.zip"
        digest = _zip_tree(repo, snapshot)
        with zipfile.ZipFile(snapshot) as archive:
            member_sha256 = {
                name: hashlib.sha256(archive.read(name)).hexdigest()
                for name in sorted(archive.namelist())
            }
        if member_sha256 != expected_fixture_members(fixture_id, trusted_git):
            raise RuntimeError(
                f"generated {fixture_id} does not match source authority"
            )
        task_card = task_cards / f"{fixture_id}.md"
        task_card.write_text(
            task_card_text(fixture_id, FIXTURE_OPERATIONS[fixture_id]),
            encoding="utf-8",
        )
        fixture_manifest.append(
            {
                "id": fixture_id,
                "conditions": labels,
                "snapshot": snapshot.relative_to(output).as_posix(),
                "sha256": digest,
                "member_sha256": member_sha256,
                "restore_argv": [
                    str(trusted_python),
                    "coordinator/restore_first_run_fixture.py",
                    "--snapshot",
                    snapshot.relative_to(output).as_posix(),
                    "--sha256",
                    digest,
                    "--destination",
                    "/new/empty/destination",
                    "--git",
                    str(trusted_git),
                    "--fixture-id",
                    fixture_id,
                ],
                "preservation_surfaces": preservation_surfaces,
                "required_operations": FIXTURE_OPERATIONS[fixture_id],
                "required_preservation_checkpoints": FIXTURE_CHECKPOINTS[fixture_id],
                "task_card": task_card.relative_to(output).as_posix(),
                "task_card_sha256": _sha256(task_card),
            }
        )

    shutil.copy2(PROTOCOL, coordinator / PROTOCOL.name)
    shutil.copy2(RECEIPT_SCHEMA, coordinator / RECEIPT_SCHEMA.name)
    shutil.copy2(KIT_SCHEMA, coordinator / KIT_SCHEMA.name)
    shutil.copy2(EVIDENCE_SCHEMA, coordinator / EVIDENCE_SCHEMA.name)
    shutil.copy2(RESTORER, coordinator / RESTORER.name)
    shutil.copy2(RECORDER, coordinator / RECORDER.name)
    shutil.copy2(VALIDATOR, coordinator / VALIDATOR.name)
    shutil.copy2(
        ROOT / "scripts/first_run_study_authority.py",
        coordinator / "first_run_study_authority.py",
    )
    runbook = coordinator / "RUNBOOK.md"
    runbook.write_text(runbook_text(), encoding="utf-8")
    document_manifest_hash = _canonical_json_sha256(document_hashes)
    result: dict[str, object] = {
        "schema_version": "pcodex.first-run-study-kit.v1",
        "candidate_commit": commit,
        "runtime_tools": runtime_tools,
        "wheel": {"filename": wheel.name, "sha256": wheel_hash},
        "qualification_receipt_sha256": hashlib.sha256(
            qualification.resolve().read_bytes()
        ).hexdigest(),
        "receipt_schema_sha256": _sha256(RECEIPT_SCHEMA),
        "kit_schema_sha256": _sha256(KIT_SCHEMA),
        "evidence_schema_sha256": _sha256(EVIDENCE_SCHEMA),
        "study_protocol_sha256": _sha256(PROTOCOL),
        "validator_sha256": _sha256(VALIDATOR),
        "restorer_sha256": _sha256(RESTORER),
        "recorder_sha256": _sha256(RECORDER),
        "study_authority_sha256": _sha256(
            ROOT / "scripts/first_run_study_authority.py"
        ),
        "runbook_sha256": _sha256(runbook),
        "canonical_document_sha256": document_hashes,
        "canonical_document_manifest_sha256": document_manifest_hash,
        "blind_payload_contents": [
            "one wheel",
            "SHA256SUMS",
            "canonical documentation",
        ],
        "fixtures": fixture_manifest,
        "receipt_validator": "scripts/validate_first_run_study.py",
    }
    study_kit = coordinator / "study-kit.json"
    study_kit.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.rmtree(fixtures_root)
    standalone = subprocess.run(
        (
            str(trusted_python),
            "-B",
            str(coordinator / RECORDER.name),
            "--help",
        ),
        cwd=output.parent,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LC_ALL": "C",
        },
        capture_output=True,
        check=False,
        timeout=30,
    )
    if standalone.returncode != 0 or b"run-next" not in standalone.stdout:
        raise RuntimeError("copied first-run recorder is not standalone-runnable")
    if any(path.name == "__pycache__" for path in output.rglob("__pycache__")):
        raise RuntimeError("copied first-run tools created unbound bytecode state")
    from validate_first_run_study import _kit_integrity

    qualified, _trusted = _kit_integrity(
        result,
        study_kit,
        qualification_root,
        wheel,
        verify_release_root=verify_release_root,
    )
    if not qualified:
        raise RuntimeError("generated first-run study kit failed self-qualification")
    _qualify_restores(output, fixture_manifest, trusted_python, trusted_git)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    if len(args.commit) != 40 or any(
        value not in "0123456789abcdef" for value in args.commit
    ):
        parser.error("--commit must be a lowercase 40-character SHA")
    result = build_kit(
        args.output.resolve(),
        args.wheel,
        args.commit,
        args.qualification_root,
        args.python,
        args.git,
    )
    print(
        json.dumps(
            {
                "kit": result,
                "study_kit_sha256": _sha256(
                    args.output.resolve() / "coordinator/study-kit.json"
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
