from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from premode import managed_state, pcodex_bootstrap as pcodex
from premode.managed_state import (
    DEFAULT_INSTALL_STATE_RELATIVE_PATH,
    OWNERSHIP_MARKER_RELATIVE_PATH,
    PRODUCT_INSTALL_MARKER_RELATIVE_PATH,
    ManagedStateError,
    apply_repair,
    apply_uninstall,
    lifecycle_status,
    install_managed_file,
    plan_repair,
    plan_uninstall,
    product_expected_content,
    product_install_marker_content,
    sha256_bytes,
)
from premode.product_contract import validate_payload_against_schema


ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path, name: str = "lifecycle repo β") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / ".git").mkdir()
    return root


def _install(root: Path) -> dict[str, Any]:
    result = pcodex.install(root, dry_run=False)
    assert result["status"] == "installed"
    assert result["lifecycle_after"]["readiness"] == "READY"
    return result


def _receipt(root: Path) -> Path:
    return root / DEFAULT_INSTALL_STATE_RELATIVE_PATH


def _target(root: Path) -> Path:
    return root / PRODUCT_INSTALL_MARKER_RELATIVE_PATH


def test_full_install_repair_uninstall_reinstall_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    preview = pcodex.install(root, dry_run=True)
    assert preview["writes_performed"] is False
    assert not _receipt(root).exists()

    _install(root)
    assert lifecycle_status(root, _receipt(root), expected_content=product_expected_content())["state"] == "healthy_installation"
    _target(root).unlink()

    repair_preview = plan_repair(root, _receipt(root), expected_content=product_expected_content())
    assert [item["path"] for item in repair_preview["will_restore"]] == [PRODUCT_INSTALL_MARKER_RELATIVE_PATH]
    repaired = apply_repair(root, _receipt(root), expected_content=product_expected_content())
    assert repaired["status"] == "applied"
    assert repaired["restored"] == [PRODUCT_INSTALL_MARKER_RELATIVE_PATH]
    assert _target(root).read_bytes() == product_expected_content()[PRODUCT_INSTALL_MARKER_RELATIVE_PATH]
    assert lifecycle_status(root, _receipt(root), expected_content=product_expected_content())["readiness"] == "READY"

    uninstall_preview = plan_uninstall(root, _receipt(root))
    assert [item["path"] for item in uninstall_preview["will_remove"]] == [PRODUCT_INSTALL_MARKER_RELATIVE_PATH]
    removed = apply_uninstall(root, _receipt(root))
    assert removed["status"] == "applied"
    assert not _target(root).exists()
    uninstalled = lifecycle_status(root, _receipt(root), expected_content=product_expected_content())
    assert uninstalled["state"] == "complete_uninstall"
    assert uninstalled["recommended_action"] == "pcodex install --apply"
    repeated = apply_uninstall(root, _receipt(root))
    assert repeated["status"] == "complete_uninstall"
    assert repeated["writes_performed"] is False

    reinstalled = pcodex.install(root, dry_run=False)
    assert reinstalled["managed_install"]["receipt"]["operation_type"] == "reinstall"
    assert reinstalled["lifecycle_after"]["readiness"] == "READY"
    assert _target(root).exists()


def test_user_modified_managed_file_is_preserved_by_repair_and_uninstall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    modified = b"user-owned modification\n"
    _target(root).write_bytes(modified)

    repair = plan_repair(root, _receipt(root), expected_content=product_expected_content())
    assert repair["will_preserve_modified"][0]["reason"] == "user_modified"
    blocked_repair = apply_repair(root, _receipt(root), expected_content=product_expected_content())
    assert blocked_repair["status"] == "blocked_conflict"
    assert blocked_repair["writes_performed"] is False
    uninstall = plan_uninstall(root, _receipt(root))
    assert uninstall["will_preserve"][0]["reason"] == "user_modified"
    blocked_uninstall = apply_uninstall(root, _receipt(root))
    assert blocked_uninstall["status"] == "blocked_conflict"
    assert blocked_uninstall["writes_performed"] is False
    assert _target(root).read_bytes() == modified


def test_missing_marker_is_repaired_only_with_extant_exact_generated_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    marker = root / ".premode" / "managed-state-owner.json"
    marker.unlink()
    preview = plan_repair(root, _receipt(root), expected_content=product_expected_content())
    assert preview["will_create"] == [{"path": ".premode/managed-state-owner.json", "reason": "receipt_and_owned_item_prove_authority"}]
    repaired = apply_repair(root, _receipt(root), expected_content=product_expected_content())
    assert repaired["status"] == "applied"
    assert marker.exists()

    marker.unlink()
    _target(root).unlink()
    blocked = plan_repair(root, _receipt(root), expected_content=product_expected_content())
    assert blocked["requires_manual_action"][0]["reason"] == "ownership_marker_invalid"


@pytest.mark.parametrize("stage", ["before_staged_write", "after_atomic_replace", "before_receipt_update", "after_receipt_update", "before_operation_receipt"])
def test_repair_interruption_rolls_back_without_false_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    root = _repo(tmp_path, f"interrupt {stage}")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    _target(root).unlink()
    receipt_before = _receipt(root).read_bytes()

    def fail(current: str) -> None:
        if current == stage:
            raise RuntimeError(f"interrupted at {stage}")

    with pytest.raises(RuntimeError, match="interrupted"):
        apply_repair(root, _receipt(root), expected_content=product_expected_content(), fault_injector=fail)
    assert _receipt(root).read_bytes() == receipt_before
    assert not _target(root).exists()
    assert not (root / ".premode" / "repair-operation.json").exists()
    status = lifecycle_status(root, _receipt(root), expected_content=product_expected_content())
    assert status["state"] == "repairable_incomplete_installation"


def test_alternate_filesystem_objects_and_hard_links_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    target = _target(root)
    sibling = root / "unrelated.txt"
    sibling.write_bytes(target.read_bytes())
    target.unlink()
    os.link(sibling, target)
    repair = plan_repair(root, _receipt(root), expected_content=product_expected_content())
    uninstall = plan_uninstall(root, _receipt(root))
    assert repair["requires_manual_action"][0]["reason"] == "hard_link"
    assert uninstall["requires_manual_action"][0]["reason"] == "hard_link"
    assert sibling.exists() and target.exists()


@pytest.mark.parametrize("stage", ["after_quarantine_rename", "during_quarantine_removal", "after_quarantine_removal", "before_operation_receipt"])
def test_uninstall_interruption_restores_owned_file_without_false_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    root = _repo(tmp_path, f"uninstall interrupt {stage}")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    receipt_before = _receipt(root).read_bytes()

    def fail(current: str) -> None:
        if current == stage:
            raise RuntimeError(f"interrupted at {stage}")

    with pytest.raises(RuntimeError, match="interrupted"):
        apply_uninstall(root, _receipt(root), fault_injector=fail)
    assert _receipt(root).read_bytes() == receipt_before
    assert _target(root).read_bytes() == product_expected_content()[PRODUCT_INSTALL_MARKER_RELATIVE_PATH]
    assert not (root / ".premode" / "uninstall-operation.json").exists()
    assert lifecycle_status(root, _receipt(root), expected_content=product_expected_content())["readiness"] == "READY"


def test_repair_and_uninstall_plans_and_operation_receipts_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    installed = _install(root)
    validate_payload_against_schema(installed["reinstall_validation"]["operation"], json.loads((ROOT / "schemas" / "pcodex.reinstall-validation.schema.json").read_text()))
    validate_payload_against_schema(installed["reinstall_validation"]["public_receipt"], json.loads((ROOT / "schemas" / "pcodex.lifecycle-operation-public.schema.json").read_text()))
    repair_plan = plan_repair(root, _receipt(root), expected_content=product_expected_content())
    uninstall_plan = plan_uninstall(root, _receipt(root))
    validate_payload_against_schema(repair_plan, json.loads((ROOT / "schemas" / "pcodex.repair-plan.schema.json").read_text()))
    validate_payload_against_schema(uninstall_plan, json.loads((ROOT / "schemas" / "pcodex.uninstall-plan.schema.json").read_text()))
    _target(root).unlink()
    repaired = apply_repair(root, _receipt(root), expected_content=product_expected_content())
    validate_payload_against_schema(repaired["operation"], json.loads((ROOT / "schemas" / "pcodex.repair-operation.schema.json").read_text()))
    validate_payload_against_schema(repaired["public_receipt"], json.loads((ROOT / "schemas" / "pcodex.lifecycle-operation-public.schema.json").read_text()))
    removed = apply_uninstall(root, _receipt(root))
    validate_payload_against_schema(removed["operation"], json.loads((ROOT / "schemas" / "pcodex.uninstall-operation.schema.json").read_text()))
    validate_payload_against_schema(removed["public_receipt"], json.loads((ROOT / "schemas" / "pcodex.lifecycle-operation-public.schema.json").read_text()))


def test_repair_cli_preview_is_literal_no_write_and_apply_has_bounded_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    _target(root).unlink()
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert pcodex.main(["repair", "--dry-run", "--json", "--repo-root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert before == after
    assert payload["writes_performed"] is False
    assert payload["preview_receipt"]["operation_type"] == "repair_preview"
    assert payload["preview_receipt"]["authority_receipt_hash"] == sha256_bytes(_receipt(root).read_bytes())
    assert pcodex.main(["repair", "--yes", "--json", "--repo-root", str(root)]) == 0
    capsys.readouterr()
    assert pcodex.main(["repair", "--yes", "--json", "--repo-root", str(root)]) == 0


def test_lifecycle_status_ready_needs_action_and_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    missing = lifecycle_status(root, _receipt(root), expected_content=product_expected_content())
    assert (missing["readiness"], missing["exit_code"]) == ("NEEDS_ACTION", 1)
    _install(root)
    healthy = lifecycle_status(root, _receipt(root), expected_content=product_expected_content())
    assert (healthy["readiness"], healthy["exit_code"]) == ("READY", 0)
    _target(root).write_bytes(b"modified")
    blocked = lifecycle_status(root, _receipt(root), expected_content=product_expected_content())
    assert (blocked["readiness"], blocked["exit_code"]) == ("BLOCKED", 2)


def test_missing_receipt_with_residual_owned_state_is_partial_and_install_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    _receipt(root).unlink()
    partial = lifecycle_status(root, _receipt(root), expected_content=product_expected_content())
    assert (partial["state"], partial["readiness"], partial["exit_code"]) == (
        "partial_installation_missing_authority", "BLOCKED", 2,
    )
    install = pcodex.install(root, dry_run=False)
    assert install["status"] == "blocked_conflict"
    assert install["writes_performed"] is False


def test_install_preserves_broken_config_symlink_without_path_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config_dir = root / ".pcodex"
    config_dir.mkdir()
    outside = tmp_path / "outside" / "config.toml"
    (config_dir / "config.toml").symlink_to(outside)
    result = pcodex.install(root, dry_run=False)
    assert result["config_install"]["reason"] == "alternate_filesystem_object_preserved"
    assert result["lifecycle_after"]["readiness"] == "READY"
    assert not outside.exists()
    assert (config_dir / "config.toml").is_symlink()


def test_repair_no_replace_commit_preserves_leaf_introduced_at_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    target = _target(root)
    target.unlink()
    introduced = b"concurrent unrelated content\n"
    real_link = os.link

    def introduce_then_link(src: str, dst: str, **kwargs: Any) -> None:
        if dst == "pcodex-install.json":
            descriptor = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=kwargs["dst_dir_fd"])
            try:
                os.write(descriptor, introduced)
            finally:
                os.close(descriptor)
        real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", introduce_then_link)
    with pytest.raises(FileExistsError):
        apply_repair(root, _receipt(root), expected_content=product_expected_content())
    assert target.read_bytes() == introduced
    assert not (root / ".premode" / "repair-operation.json").exists()


def test_uninstall_rejects_hard_link_introduced_after_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    real_plan = __import__("premode.managed_state", fromlist=["plan_uninstall"]).plan_uninstall
    sibling = root / "linked-copy.json"

    def plan_then_link(*args: Any, **kwargs: Any) -> dict[str, Any]:
        plan = real_plan(*args, **kwargs)
        if not sibling.exists():
            os.link(_target(root), sibling)
        return plan

    monkeypatch.setattr("premode.managed_state.plan_uninstall", plan_then_link)
    result = apply_uninstall(root, _receipt(root))
    assert result["status"] == "blocked_conflict"
    assert _target(root).exists() and sibling.exists()
    assert not (root / ".premode" / "uninstall-operation.json").exists()


def test_status_identifies_authority_bound_interrupted_uninstall_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    receipt_payload = json.loads(_receipt(root).read_text(encoding="utf-8"))
    staging = root / ".premode" / "uninstall-quarantine-simulated"
    staging.mkdir()
    manifest = {
        "schema_version": "pcodex.uninstall-staging.v1",
        "managed_root_hash": receipt_payload["managed_root_hash"],
        "ownership_id": receipt_payload["ownership_id"],
        "install_state_receipt": DEFAULT_INSTALL_STATE_RELATIVE_PATH,
        "authority_receipt_hash": sha256_bytes(_receipt(root).read_bytes()),
        "actions": [],
    }
    (staging / "operation.json").write_text(json.dumps(manifest), encoding="utf-8")
    status = lifecycle_status(root, _receipt(root), expected_content=product_expected_content())
    assert (status["state"], status["readiness"], status["exit_code"]) == ("interrupted_uninstall", "BLOCKED", 2)
    rerun = apply_uninstall(root, _receipt(root))
    assert rerun["status"] == "blocked_interrupted_operation"
    assert rerun["writes_performed"] is False
    assert staging.exists()


def test_repair_keeps_reinstall_validation_bound_for_later_marker_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path, "repair authority remains stable")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    receipt_before = _receipt(root).read_bytes()
    _target(root).unlink()
    assert apply_repair(root, _receipt(root), expected_content=product_expected_content())["applied"] is True
    assert _receipt(root).read_bytes() == receipt_before
    (root / OWNERSHIP_MARKER_RELATIVE_PATH).unlink()
    plan = plan_repair(root, _receipt(root), expected_content=product_expected_content())
    assert [item["path"] for item in plan["will_create"]] == [OWNERSHIP_MARKER_RELATIVE_PATH]


def test_install_does_not_clobber_leaf_introduced_at_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path, "install no clobber")
    real_write = managed_state._atomic_write_managed
    introduced = False

    def introduce(managed_root: Path, owned_path: str, content: bytes, **kwargs: Any) -> Path:
        nonlocal introduced
        if owned_path == PRODUCT_INSTALL_MARKER_RELATIVE_PATH and not introduced:
            introduced = True
            target = managed_root / owned_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"unrelated")
        return real_write(managed_root, owned_path, content, **kwargs)

    monkeypatch.setattr(managed_state, "_atomic_write_managed", introduce)
    with pytest.raises(FileExistsError):
        install_managed_file(
            root,
            PRODUCT_INSTALL_MARKER_RELATIVE_PATH,
            product_install_marker_content(),
            receipt_path=_receipt(root),
            sensitivity="public_safe",
        )
    assert _target(root).read_bytes() == b"unrelated"
    assert not _receipt(root).exists()


def test_uninstall_rollback_preserves_journal_when_target_becomes_occupied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path, "rollback journal retained")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)

    def occupy(stage: str) -> None:
        if stage == "after_quarantine_rename":
            _target(root).write_bytes(b"unrelated concurrent state")
            raise RuntimeError("interrupt with occupied target")

    with pytest.raises(ManagedStateError, match="rollback requires recovery"):
        apply_uninstall(root, _receipt(root), fault_injector=occupy)
    assert _target(root).read_bytes() == b"unrelated concurrent state"
    staging = list((root / ".premode").glob("uninstall-quarantine-*"))
    assert len(staging) == 1
    manifest = json.loads((staging[0] / "operation.json").read_text(encoding="utf-8"))
    assert manifest["actions"][0]["target"] == PRODUCT_INSTALL_MARKER_RELATIVE_PATH
    assert lifecycle_status(root, _receipt(root), expected_content=product_expected_content())["state"] == "interrupted_uninstall"


def test_repair_operation_receipt_does_not_clobber_concurrent_unrelated_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path, "repair receipt no clobber")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install(root)
    _target(root).unlink()
    real_write = managed_state._atomic_write_managed_json
    introduced = False

    def introduce(managed_root: Path, owned_path: str, payload: dict[str, Any], **kwargs: Any) -> Path:
        nonlocal introduced
        if payload.get("operation_type") == "repair_apply" and not introduced:
            introduced = True
            concurrent = managed_root / owned_path
            concurrent.write_bytes(b"unrelated receipt leaf")
        return real_write(managed_root, owned_path, payload, **kwargs)

    monkeypatch.setattr(managed_state, "_atomic_write_managed_json", introduce)
    with pytest.raises(FileExistsError):
        apply_repair(root, _receipt(root), expected_content=product_expected_content())
    operation = root / ".premode" / "repair-operation.json"
    assert operation.read_bytes() == b"unrelated receipt leaf"
    assert not _target(root).exists()


@pytest.mark.skipif(os.sys.platform != "darwin", reason="macOS atomic-swap receipt qualification")
def test_existing_receipt_atomic_swap_restores_alternate_object_on_mismatch(tmp_path: Path) -> None:
    root = _repo(tmp_path, "existing receipt alternate swap")
    relative = ".premode/existing-operation.json"
    target = root / relative
    target.parent.mkdir()
    original = b"owned operation receipt"
    target.write_bytes(original)
    expected_hash = sha256_bytes(original)
    outside = tmp_path / "outside receipt"
    outside.write_bytes(b"unrelated")
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises((ManagedStateError, OSError)):
        managed_state._atomic_write_managed(
            root,
            relative,
            b"new owned operation receipt",
            expected_current_hash=expected_hash,
        )
    assert target.is_symlink()
    assert target.resolve() == outside.resolve()
    assert outside.read_bytes() == b"unrelated"


def test_human_lifecycle_output_has_one_coherent_next_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert pcodex.main(["install", "--repo-root", str(root)]) == 0
    install_text = capsys.readouterr().out
    assert "pCodex install: dry_run" in install_text
    assert "Next action: pcodex install --apply" in install_text
    assert pcodex.main(["status", "--advisory", "--repo-root", str(root)]) == 0
    status_text = capsys.readouterr().out
    assert "Lifecycle state: not_installed" in status_text
    assert "Next action: pcodex install --apply" in status_text
    assert "run without --advisory" not in status_text
    assert pcodex.main(["doctor", "--advisory", "--repo-root", str(root)]) == 0
    doctor_text = capsys.readouterr().out
    assert "Next action: pcodex install --apply" in doctor_text

    _install(root)
    _target(root).unlink()
    assert pcodex.main(["repair", "--dry-run", "--repo-root", str(root)]) == 0
    repair_text = capsys.readouterr().out
    assert "pCodex repair preview" in repair_text
    assert "will_restore: 1" in repair_text
    apply_repair(root, _receipt(root), expected_content=product_expected_content())
    assert pcodex.main(["uninstall", "--dry-run", "--repo-root", str(root)]) == 0
    uninstall_text = capsys.readouterr().out
    assert "pCodex uninstall preview" in uninstall_text
    assert "will_remove: 1" in uninstall_text
