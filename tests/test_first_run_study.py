from __future__ import annotations

import json
from pathlib import Path
import subprocess
import zipfile

import pytest

import scripts.build_first_run_study_kit as study_kit_builder
from scripts.build_first_run_study_kit import build_kit
from scripts.validate_first_run_study import validate_receipts


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "904d5762f37a3dcff057a919c5d34ee6ce007b74"


def _receipt(index: int) -> dict[str, object]:
    commands = [
        'pcodex run --dry-run "Fix the failing test"',
        "pcodex integrate codex --dry-run",
        "pcodex integrate codex --write",
        "pcodex integrate codex --write",
        "pcodex integrate codex --uninstall --dry-run",
        "pcodex integrate codex --uninstall",
    ]
    if index == 4:
        commands.append("pcodex integrate codex --write --migrate")
    elif index == 5:
        commands.append("pcodex integrate codex --write --with-mcp")
    else:
        commands.append("pcodex integrate codex --write")
    commands.extend(["pcodex uninstall --dry-run", "pcodex uninstall --yes"])
    return {
        "schema_version": "pcodex.first-run-study-receipt.v1",
        "anonymous_tester_id": f"tester-{index:08d}",
        "no_prior_knowledge_attested": True,
        "attestation_evidence_sha256": format(index + 5, "x") * 64,
        "artifact": {
            "filename": "fixture.whl",
            "sha256": "a" * 64,
            "product_version": "0.3.0b1",
            "candidate_commit": COMMIT,
        },
        "runtime": {
            "platform": "macos" if index % 2 else "linux",
            "architecture": "arm64",
            "python_version": "3.11.15",
            "codex_version": "0.143.0" if index != 1 else "absent",
        },
        "fixture": {"id": f"fixture-{index:02d}", "sha256": f"{index}" * 64},
        "timing": {"first_use_seconds": 120 + index, "completion_seconds": 240 + index},
        "commands": commands,
        "undocumented_help": [],
        "failures": [],
        "lifecycle": {
            "first_dry_run": True,
            "install_twice": True,
            "uninstall": True,
            "reinstall": True,
            "unrelated_state_preserved": True,
        },
        "documentation": {"sufficient": True, "missing_instruction": None},
        "completed": True,
    }


def _study_kit(tmp_path: Path) -> Path:
    path = tmp_path / "study-kit.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "pcodex.first-run-study-kit.v1",
                "candidate_commit": COMMIT,
                "wheel": {"filename": "fixture.whl", "sha256": "a" * 64},
                "fixtures": [
                    {"id": f"fixture-{index:02d}", "sha256": f"{index}" * 64}
                    for index in range(1, 6)
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_five_valid_first_run_receipts_produce_content_free_pass(
    tmp_path: Path,
) -> None:
    paths = []
    for index in range(1, 6):
        path = tmp_path / f"fixture-{index:02d}.json"
        path.write_text(json.dumps(_receipt(index)), encoding="utf-8")
        paths.append(path)

    result = validate_receipts(paths, _study_kit(tmp_path))

    assert result["status"] == "passed"
    assert result["receipt_count"] == 5
    assert result["activation_rate"] == 1.0
    assert result["median_first_use_seconds"] == 123
    assert result["first_use_seconds_range"] == [121.0, 125.0]
    assert result["study_kit_bindings_valid"] is True
    assert result["transcript_evidence_successes"] == 5
    assert result["monotonic_timing_successes"] == 5
    assert result["private_receipt_content_included"] is False


def test_failed_or_duplicate_study_receipts_are_retained_and_fail(
    tmp_path: Path,
) -> None:
    paths = []
    for index in range(1, 6):
        payload = _receipt(index)
        if index == 5:
            payload["anonymous_tester_id"] = "tester-00000001"
            payload["lifecycle"]["uninstall"] = False  # type: ignore[index]
        path = tmp_path / f"fixture-{index:02d}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)

    result = validate_receipts(paths, _study_kit(tmp_path))

    assert result["status"] == "failed"
    assert result["unique_tester_count"] == 4
    assert all(path.is_file() for path in paths)


def test_study_rejects_unbound_fixture_and_incomplete_lifecycle(tmp_path: Path) -> None:
    paths = []
    for index in range(1, 6):
        payload = _receipt(index)
        if index == 5:
            payload["fixture"]["sha256"] = "f" * 64  # type: ignore[index]
            payload["lifecycle"]["install_twice"] = False  # type: ignore[index]
            payload["documentation"]["sufficient"] = False  # type: ignore[index]
        path = tmp_path / f"receipt-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)

    result = validate_receipts(paths, _study_kit(tmp_path))

    assert result["status"] == "failed"
    assert result["study_kit_bindings_valid"] is False
    assert result["install_twice_successes"] == 4
    assert result["documentation_sufficient_count"] == 4


def test_study_rejects_contradictory_transcript_and_timing(tmp_path: Path) -> None:
    paths = []
    for index in range(1, 6):
        payload = _receipt(index)
        if index == 5:
            payload["commands"] = ['pcodex run --dry-run "Fix the failing test"']
            payload["timing"]["completion_seconds"] = 1  # type: ignore[index]
        path = tmp_path / f"contradictory-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)

    result = validate_receipts(paths, _study_kit(tmp_path))

    assert result["status"] == "failed"
    assert result["transcript_evidence_successes"] == 4
    assert result["monotonic_timing_successes"] == 4


def _qualified_wheel(tmp_path: Path) -> tuple[Path, Path]:
    wheel = tmp_path / "premode_router-0.3.0b1-py3-none-any.whl"
    prefix = "premode_router-0.3.0b1"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"{prefix}.dist-info/METADATA", "Metadata-Version: 2.4\nVersion: 0.3.0b1\n"
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
    wheel_hash = __import__("hashlib").sha256(wheel.read_bytes()).hexdigest()
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
                        "digest": {"sha256": wheel_hash},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return wheel, qualification


def test_study_kit_separates_blind_payload_and_coordinator_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        study_kit_builder, "_assert_source_commit", lambda _commit: None
    )
    wheel, qualification = _qualified_wheel(tmp_path)
    output = tmp_path / "kit"

    result = build_kit(output, wheel, COMMIT, qualification)

    payload_files = {
        path.relative_to(output / "blind-tester-payload").as_posix()
        for path in (output / "blind-tester-payload").rglob("*")
        if path.is_file()
    }
    manifest = json.loads((ROOT / "premode.product.json").read_text(encoding="utf-8"))
    assert payload_files == {
        f"artifacts/{wheel.name}",
        "artifacts/SHA256SUMS",
        *manifest["documentation_contract"]["canonical_docs"],
    }
    assert len(result["fixtures"]) == 5  # type: ignore[arg-type]
    for fixture in result["fixtures"]:  # type: ignore[union-attr]
        snapshot = output / fixture["snapshot"]
        assert snapshot.is_file()
        assert zipfile.is_zipfile(snapshot)
    assert not (output / "coordinator/fixture-work").exists()
    assert (output / "coordinator/RUNBOOK.md").is_file()


def test_study_kit_is_deterministic_and_rejects_unqualified_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        study_kit_builder, "_assert_source_commit", lambda _commit: None
    )
    wheel, qualification = _qualified_wheel(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_result = build_kit(first, wheel, COMMIT, qualification)
    second_result = build_kit(second, wheel, COMMIT, qualification)

    assert first_result == second_result
    assert (first / "coordinator/study-kit.json").read_bytes() == (
        second / "coordinator/study-kit.json"
    ).read_bytes()
    for index in range(1, 6):
        assert (
            first / f"coordinator/fixtures/fixture-{index:02d}.zip"
        ).read_bytes() == (
            second / f"coordinator/fixtures/fixture-{index:02d}.zip"
        ).read_bytes()

    bad = tmp_path / "premode_router-0.3.0b1-py3-none-any.whl.bad"
    bad.write_bytes(b"not a wheel")
    try:
        build_kit(tmp_path / "bad-kit", bad, COMMIT, qualification)
    except RuntimeError:
        pass
    else:
        raise AssertionError("unqualified wheel was accepted")


def test_study_kit_source_must_be_clean_and_commit_bound(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture.invalid"], cwd=source, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "pCodex Fixture"], cwd=source, check=True
    )
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

    study_kit_builder._assert_source_commit(head, source)
    with pytest.raises(RuntimeError, match="does not match"):
        study_kit_builder._assert_source_commit("0" * 40, source)
    (source / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="must be clean"):
        study_kit_builder._assert_source_commit(head, source)
