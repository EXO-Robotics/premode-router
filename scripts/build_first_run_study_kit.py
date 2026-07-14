#!/usr/bin/env python3
"""Build the frozen five-fixture first-run coordinator kit and blind payload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_release_artifacts import materialize_legacy_fixture


ROOT = Path(__file__).resolve().parents[1]


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
    with zipfile.ZipFile(
        destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            name = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def _receipt_template(
    fixture_id: str, fixture_hash: str, wheel: Path, wheel_hash: str, commit: str
) -> dict[str, object]:
    return {
        "schema_version": "pcodex.first-run-study-receipt.v1",
        "anonymous_tester_id": "REPLACE_WITH_TESTER_ID",
        "no_prior_knowledge_attested": True,
        "attestation_evidence_sha256": "REPLACE_WITH_SHA256_OF_STORED_SIGNED_ATTESTATION",
        "artifact": {
            "filename": wheel.name,
            "sha256": wheel_hash,
            "product_version": "0.3.0b1",
            "candidate_commit": commit,
        },
        "runtime": {
            "platform": "REPLACE",
            "architecture": "REPLACE",
            "python_version": "REPLACE",
            "codex_version": "REPLACE",
        },
        "fixture": {"id": fixture_id, "sha256": fixture_hash},
        "timing": {"first_use_seconds": -1, "completion_seconds": -1},
        "commands": ["REPLACE_WITH_EXACT_TRANSCRIPT"],
        "undocumented_help": [],
        "failures": [],
        "lifecycle": {
            "first_dry_run": False,
            "install_twice": False,
            "uninstall": False,
            "reinstall": False,
            "unrelated_state_preserved": False,
        },
        "documentation": {"sufficient": False, "missing_instruction": "REPLACE"},
        "completed": False,
    }


def _validate_qualified_wheel(
    wheel: Path, qualification: Path, commit: str
) -> tuple[bytes, str]:
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
        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8", errors="strict")
        if "\nVersion: 0.3.0b1\n" not in f"\n{metadata}":
            raise RuntimeError("qualified wheel metadata version is not 0.3.0b1")
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
    return wheel_bytes, wheel_hash


def build_kit(
    output: Path, wheel: Path, commit: str, qualification: Path
) -> dict[str, object]:
    _assert_source_commit(commit)
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("study-kit output must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    payload = output / "blind-tester-payload"
    coordinator = output / "coordinator"
    fixtures_root = coordinator / "fixture-work"
    snapshots = coordinator / "fixtures"
    receipts = coordinator / "receipt-templates"
    for path in (
        payload / "artifacts",
        payload / "docs",
        fixtures_root,
        snapshots,
        receipts,
    ):
        path.mkdir(parents=True, exist_ok=True)

    wheel = wheel.resolve()
    wheel_bytes, wheel_hash = _validate_qualified_wheel(
        wheel, qualification.resolve(), commit
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

    conditions = {
        "fixture-01": ["clean_repository", "missing_codex", "mcp_absent"],
        "fixture-02": ["dirty_repository", "unrelated_agents"],
        "fixture-03": ["unrelated_codex_config", "supported_codex_0.143.x"],
        "fixture-04": ["path_with_spaces", "unicode_path", "supported_legacy_plugin"],
        "fixture-05": ["optional_mcp", "install_twice", "uninstall_reinstall"],
    }
    fixture_manifest: list[dict[str, object]] = []
    for fixture_id, labels in conditions.items():
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
        if fixture_id == "fixture-03":
            (repo / "fixture-codex-home").mkdir()
            (repo / "fixture-codex-home/config.toml").write_text(
                'model = "preserve-me"\n[unknown]\nvalue = true\n', encoding="utf-8"
            )
        if fixture_id == "fixture-04":
            materialize_legacy_fixture(repo)
        snapshot = snapshots / f"{fixture_id}.zip"
        digest = _zip_tree(repo, snapshot)
        fixture_manifest.append(
            {
                "id": fixture_id,
                "conditions": labels,
                "snapshot": snapshot.relative_to(output).as_posix(),
                "sha256": digest,
                "restore": f"python scripts/restore_first_run_fixture.py --snapshot {snapshot.relative_to(output).as_posix()} --sha256 {digest} --destination /new/empty/destination --fixture-id {fixture_id}",
            }
        )
        template = _receipt_template(fixture_id, digest, wheel, wheel_hash, commit)
        (receipts / f"{fixture_id}.json").write_text(
            json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    shutil.copy2(
        ROOT / "docs/FIRST_RUN_STUDY_PROTOCOL.md",
        coordinator / "FIRST_RUN_STUDY_PROTOCOL.md",
    )
    shutil.copy2(
        ROOT / "schemas/pcodex.first-run-study-receipt.v1.schema.json",
        coordinator / "pcodex.first-run-study-receipt.v1.schema.json",
    )
    result = {
        "schema_version": "pcodex.first-run-study-kit.v1",
        "candidate_commit": commit,
        "wheel": {"filename": wheel.name, "sha256": wheel_hash},
        "qualification_receipt_sha256": hashlib.sha256(
            qualification.resolve().read_bytes()
        ).hexdigest(),
        "canonical_document_sha256": document_hashes,
        "blind_payload_contents": [
            "one wheel",
            "SHA256SUMS",
            "canonical documentation",
        ],
        "fixtures": fixture_manifest,
        "receipt_validator": "scripts/validate_first_run_study.py",
    }
    (coordinator / "study-kit.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    runbook = [
        "# First-Run Coordinator Runbook",
        "",
        "Restore each assigned archive with the exact command in study-kit.json before timing starts.",
        "The restore tool creates an isolated real Git repository; fixture-02 is then made dirty.",
        "Prepare the shell without coaching the tester:",
        "",
        "- fixture-01: make `codex` unavailable while retaining the invited-beta `pcodex` environment; verify `command -v codex` fails.",
        "- fixture-02: verify `git status --porcelain` reports the unrelated dirty file and `.agents` tree.",
        "- fixture-03: set `CODEX_HOME` to `<repository>/fixture-codex-home` and verify Codex 0.143.x.",
        "- fixture-04: restore into a destination whose path contains spaces and Unicode; assign the migration journey.",
        "- fixture-05: set an empty controlled `CODEX_HOME`; assign optional MCP, install-twice, uninstall, and reinstall journeys from canonical docs.",
        "",
        "Keep fixture mappings and receipt templates coordinator-only.",
    ]
    (coordinator / "RUNBOOK.md").write_text("\n".join(runbook) + "\n", encoding="utf-8")
    shutil.rmtree(fixtures_root)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    if len(args.commit) != 40 or any(
        value not in "0123456789abcdef" for value in args.commit
    ):
        parser.error("--commit must be a lowercase 40-character SHA")
    result = build_kit(
        args.output.resolve(), args.wheel, args.commit, args.qualification
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
