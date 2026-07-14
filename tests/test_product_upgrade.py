from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from premode import __version__
from premode import codex_plugin
from premode.codex_plugin import repair_integration
from premode.managed_state import (
    DEFAULT_INSTALL_STATE_RELATIVE_PATH,
    OWNERSHIP_MARKER_RELATIVE_PATH,
    install_managed_file,
    product_install_marker_content,
    read_install_state_receipt,
)
from premode.pcodex_bootstrap import main as pcodex_main
from premode.product_contract import validate_payload_against_schema
from premode.product_upgrade import (
    ProductUpgradeError,
    UPGRADE_OPERATION_RELATIVE_PATH,
    _previous_install_marker_content,
    apply_product_upgrade,
    load_previous_authority,
    plan_product_upgrade,
)


ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = "0.2.6.24"


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def _install_previous(root: Path) -> None:
    """Create a receipt-compatibility fixture, not historical package output."""

    install_managed_file(
        root,
        ".premode/pcodex-install.json",
        product_install_marker_content(),
        receipt_path=root / DEFAULT_INSTALL_STATE_RELATIVE_PATH,
    )
    marker = root / ".premode/pcodex-install.json"
    marker.write_bytes(_previous_install_marker_content())
    marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
    receipt_path = root / DEFAULT_INSTALL_STATE_RELATIVE_PATH
    receipt = json.loads(receipt_path.read_text())
    receipt["product_version"] = PREVIOUS
    item = next(
        item
        for item in receipt["items"]
        if item["owned_path"] == ".premode/pcodex-install.json"
    )
    item["installed_hash"] = marker_hash
    item["current_hash"] = marker_hash
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _validate_plan(plan: dict[str, object]) -> None:
    schema = json.loads(
        (ROOT / "schemas/pcodex.upgrade-plan.v1.schema.json").read_text()
    )
    validate_payload_against_schema(plan, schema)


def test_previous_authority_is_exact_and_current() -> None:
    authority = load_previous_authority()
    assert authority["current_version"] == __version__
    assert authority["previous_version"] == PREVIOUS
    assert authority["previous_commit"] == "b9aede455c8d49217ef0a67e8dec0c8cf2c565a6"
    assert authority["publication_authorized"] is False
    schema = json.loads(
        (ROOT / "schemas/pcodex.previous-supported.v1.schema.json").read_text()
    )
    validate_payload_against_schema(authority, schema)


def test_modified_previous_authority_is_rejected(tmp_path: Path) -> None:
    authority = load_previous_authority()
    authority["previous_version"] = "9.9.9"
    share = tmp_path / "share/premode-router/release"
    share.mkdir(parents=True)
    (share / "previous-supported.json").write_text(
        json.dumps(authority, indent=2, sort_keys=True) + "\n"
    )

    with pytest.raises(ProductUpgradeError, match="authority was modified"):
        load_previous_authority(tmp_path)


def test_upgrade_check_is_literal_no_write_when_state_absent(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    before = _snapshot(root)

    plan = plan_product_upgrade(root)

    assert plan["readiness"] == "READY"
    assert plan["planned_actions"] == []
    assert plan["writes_performed"] is False
    assert _snapshot(root) == before


def test_actual_predecessor_user_config_is_preserved_as_noop(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    config = root / ".pcodex/config.toml"
    config.parent.mkdir()
    config.write_text('[pcodex]\nmode = "assist"\nuser_key = "preserve"\n')
    before = _snapshot(root)

    plan = plan_product_upgrade(root)
    result = apply_product_upgrade(root)

    assert plan["readiness"] == "READY"
    assert plan["planned_actions"] == []
    assert result["status"] == "already_current"
    assert result["writes_performed"] is False
    assert _snapshot(root) == before


def test_supported_predecessor_upgrades_and_is_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)

    plan = plan_product_upgrade(root)
    assert plan["readiness"] == "NEEDS_ACTION"
    assert plan["planned_actions"] == ["upgrade_managed_install_state"]
    assert plan["components"]["managed_state"]["from_version"] == PREVIOUS

    result = apply_product_upgrade(root)
    assert result["status"] == "upgraded"
    assert result["operation"]["status"] == "succeeded"
    assert result["operation"]["completed_actions"] == ["upgrade_managed_install_state"]
    receipt = read_install_state_receipt(root / DEFAULT_INSTALL_STATE_RELATIVE_PATH)
    assert receipt["payload"]["product_version"] == __version__
    upgraded_item = next(
        item
        for item in receipt["payload"]["items"]
        if item["owned_path"] == ".premode/pcodex-install.json"
    )
    assert upgraded_item["creation_or_modification"] == "created"
    assert upgraded_item["cleanup_policy"] == "remove_if_owned_and_unmodified"
    marker = json.loads((root / ".premode/pcodex-install.json").read_text())
    assert marker["product_version"] == __version__

    second = apply_product_upgrade(root)
    assert second["status"] == "already_current"
    assert second["writes_performed"] is False
    assert pcodex_main(["uninstall", "--yes", "--json", "--repo-root", str(root)]) == 0
    uninstall = json.loads(capsys.readouterr().out)
    assert uninstall["status"] == "applied"
    assert uninstall["removed"] == [".premode/pcodex-install.json"]


def test_upgrade_plan_and_operation_validate_against_schemas(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    plan = plan_product_upgrade(root)
    result = apply_product_upgrade(root)
    plan_schema = json.loads(
        (ROOT / "schemas/pcodex.upgrade-plan.v1.schema.json").read_text()
    )
    operation_schema = json.loads(
        (ROOT / "schemas/pcodex.upgrade-operation.v1.schema.json").read_text()
    )

    validate_payload_against_schema(plan, plan_schema)
    validate_payload_against_schema(result["operation"], operation_schema)


def test_modified_predecessor_state_is_preserved_and_blocked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    marker = root / ".premode/pcodex-install.json"
    marker.write_text("user modified\n", encoding="utf-8")
    before = _snapshot(root)

    plan = plan_product_upgrade(root)
    result = apply_product_upgrade(root)

    assert plan["readiness"] == "BLOCKED"
    assert result["status"] == "blocked"
    assert result["applied"] is False
    assert _snapshot(root) == before


def test_unknown_or_future_receipt_version_fails_closed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    receipt_path = root / DEFAULT_INSTALL_STATE_RELATIVE_PATH
    payload = json.loads(receipt_path.read_text())
    payload["product_version"] = "99.0.0"
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    before = _snapshot(root)

    plan = plan_product_upgrade(root)
    result = apply_product_upgrade(root)

    assert plan["readiness"] == "BLOCKED"
    assert plan["conflicts"][0]["reason"] == "unsupported_or_future_product_version"
    assert result["status"] == "blocked"
    assert _snapshot(root) == before


def test_interrupted_upgrade_retains_failed_receipt_without_false_success(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)

    def inject(stage: str) -> None:
        if stage == "operation_started":
            raise RuntimeError("injected interruption")

    with pytest.raises(ProductUpgradeError, match="injected interruption"):
        apply_product_upgrade(root, fault_injector=inject)

    operation = json.loads((root / UPGRADE_OPERATION_RELATIVE_PATH).read_text())
    assert operation["status"] == "failed"
    assert operation["completed_actions"] == []
    assert operation["failure_stage"] == "upgrade_managed_install_state"
    assert operation["rollback_or_recovery_status"] == "no_product_state_committed"
    receipt = read_install_state_receipt(root / DEFAULT_INSTALL_STATE_RELATIVE_PATH)
    assert receipt["payload"]["product_version"] == PREVIOUS


def test_cli_requires_explicit_mode_and_check_is_no_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path)
    before = _snapshot(root)

    assert pcodex_main(["upgrade", "--repo-root", str(root)]) == 2
    assert "requires --check or --apply" in capsys.readouterr().err
    assert pcodex_main(["upgrade", "--check", "--json", "--repo-root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["codex_launch"] == "not_executed"
    assert _snapshot(root) == before


def test_cli_blocked_check_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    operation = root / UPGRADE_OPERATION_RELATIVE_PATH
    operation.parent.mkdir(parents=True, exist_ok=True)
    operation.write_text('{"schema_version":"future.v9"}\n')
    before = _snapshot(root)

    assert pcodex_main(["upgrade", "--check", "--json", "--repo-root", str(root)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["readiness"] == "BLOCKED"
    assert _snapshot(root) == before


def test_unrelated_operation_receipt_fails_closed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    operation = root / UPGRADE_OPERATION_RELATIVE_PATH
    operation.parent.mkdir(parents=True, exist_ok=True)
    operation.write_text('{"schema_version":"other.v1"}\n', encoding="utf-8")

    before = _snapshot(root)
    result = apply_product_upgrade(root)
    assert result["status"] == "blocked"
    assert result["conflicts"][-1]["reason"] == "operation_receipt_invalid"
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.update({"to_version": "99.0.0"}),
        lambda payload: payload.update(
            {"completed_actions": [], "status": "succeeded"}
        ),
    ],
    ids=["extended", "wrong-version", "inconsistent-terminal"],
)
def test_malformed_terminal_operation_receipts_are_preserved_and_blocked(
    tmp_path: Path, mutate: object
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    assert apply_product_upgrade(root)["status"] == "upgraded"
    operation = root / UPGRADE_OPERATION_RELATIVE_PATH
    payload = json.loads(operation.read_text())
    mutate(payload)  # type: ignore[operator]
    operation.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    before = _snapshot(root)

    plan = plan_product_upgrade(root)
    result = apply_product_upgrade(root)

    assert plan["readiness"] == "BLOCKED"
    assert plan["conflicts"][-1]["reason"] == "operation_receipt_invalid"
    assert result["status"] == "blocked"
    assert _snapshot(root) == before


def test_hardlinked_operation_receipt_blocks_preview(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    assert apply_product_upgrade(root)["status"] == "upgraded"
    operation = root / UPGRADE_OPERATION_RELATIVE_PATH
    outside = tmp_path / "shared-operation.json"
    operation.replace(outside)
    os.link(outside, operation)
    before = _snapshot(root)

    plan = plan_product_upgrade(root)

    assert plan["readiness"] == "BLOCKED"
    assert plan["conflicts"][-1]["reason"] == "operation_receipt_unsafe"
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    "relative",
    [DEFAULT_INSTALL_STATE_RELATIVE_PATH, OWNERSHIP_MARKER_RELATIVE_PATH],
)
def test_hardlinked_managed_authority_blocks_upgrade_preview(
    tmp_path: Path, relative: str
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    authority_path = root / relative
    outside = tmp_path / (authority_path.name + ".shared")
    authority_path.replace(outside)
    os.link(outside, authority_path)
    before = _snapshot(root)

    plan = plan_product_upgrade(root)

    assert plan["readiness"] == "BLOCKED"
    assert _snapshot(root) == before


def test_non_object_owner_marker_blocks_without_traceback(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    marker = root / OWNERSHIP_MARKER_RELATIVE_PATH
    marker.write_text(
        json.dumps(
            [
                "schema_version",
                "product_name",
                "ownership_id",
                "managed_root_hash",
                "install_state_receipt",
            ]
        )
        + "\n"
    )
    before = _snapshot(root)

    plan = plan_product_upgrade(root)

    assert plan["readiness"] == "BLOCKED"
    assert plan["conflicts"][0]["reason"] in {
        "authority_invalid",
        "state_not_exactly_healthy",
    }
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    ("operation_id", "recovery"),
    [
        ("00000000-0000-0000-0000-000000000000", "not_required"),
        (None, "managed_state_rolled_back"),
        (None, "managed_state_rolled_back_codex_recovery_required"),
    ],
    ids=["nil-uuid", "impossible-recovery", "codex-recovery-without-codex"],
)
def test_semantically_invalid_operation_authority_blocks(
    tmp_path: Path, operation_id: str | None, recovery: str
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    assert apply_product_upgrade(root)["status"] == "upgraded"
    operation = root / UPGRADE_OPERATION_RELATIVE_PATH
    payload = json.loads(operation.read_text())
    if operation_id is not None:
        payload["operation_id"] = operation_id
    else:
        payload.update(
            {
                "status": "failed",
                "completed_actions": [],
                "failure_stage": "upgrade_managed_install_state",
                "rollback_or_recovery_status": recovery,
                "completed_at": payload["completed_at"],
            }
        )
    operation.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    before = _snapshot(root)

    plan = plan_product_upgrade(root)

    assert plan["readiness"] == "BLOCKED"
    assert plan["conflicts"][-1]["reason"] == "operation_receipt_invalid"
    assert _snapshot(root) == before


def test_post_commit_failure_restores_exact_predecessor_and_retry_succeeds(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    before_marker = (root / ".premode/pcodex-install.json").read_bytes()
    before_receipt = (root / DEFAULT_INSTALL_STATE_RELATIVE_PATH).read_bytes()

    def inject(stage: str) -> None:
        if stage == "managed_state_committed":
            raise RuntimeError("injected after managed commit")

    with pytest.raises(ProductUpgradeError, match="injected after managed commit"):
        apply_product_upgrade(root, fault_injector=inject)

    assert (root / ".premode/pcodex-install.json").read_bytes() == before_marker
    assert (root / DEFAULT_INSTALL_STATE_RELATIVE_PATH).read_bytes() == before_receipt
    failed = json.loads((root / UPGRADE_OPERATION_RELATIVE_PATH).read_text())
    assert failed["status"] == "failed"
    assert failed["rollback_or_recovery_status"] == "managed_state_rolled_back"
    assert apply_product_upgrade(root)["status"] == "upgraded"


def test_native_preview_conflict_blocks_before_managed_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    before = _snapshot(root)

    def preview(*_args: object, **kwargs: object) -> dict[str, object]:
        if kwargs.get("native") is True:
            return {
                "legacy_sources_found": [{"classification": "legacy_migratable"}],
                "conflicts": [{"reason": "native_registration_conflict"}],
            }
        return {
            "legacy_sources_found": [{"classification": "legacy_migratable"}],
            "conflicts": [],
        }

    monkeypatch.setattr("premode.product_upgrade.codex_integration_preview", preview)
    result = apply_product_upgrade(root)

    assert result["status"] == "blocked"
    assert _snapshot(root) == before


def test_unknown_legacy_state_requires_manual_action(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    legacy = root / ".agents/plugins/plugins/premode-router/user-owned.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("preserve\n")
    before = _snapshot(root)

    plan = plan_product_upgrade(root)

    assert plan["readiness"] == "BLOCKED"
    assert plan["next_recommended_action"] == (
        "review preserved legacy plugin state manually"
    )
    assert _snapshot(root) == before


def test_partial_codex_migration_reports_recovery_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path)
    legacy = root / ".agents/plugins/plugins/premode-router"
    content = b"historical plugin\n"
    path = legacy / ".codex-plugin/plugin.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    monkeypatch.setattr(
        codex_plugin,
        "LEGACY_PLUGIN_FINGERPRINT",
        {".codex-plugin/plugin.json": hashlib.sha256(content).hexdigest()},
    )
    monkeypatch.setattr(codex_plugin, "LEGACY_SKILL_FINGERPRINT", {})

    def apply_without_native(
        repository: Path,
        *,
        migration: bool,
        native: bool,
        inject: object,
    ) -> dict[str, object]:
        assert native is True
        return codex_plugin.apply_integration(
            repository,
            migration=migration,
            native=False,
            inject=inject,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        "premode.product_upgrade.apply_codex_integration", apply_without_native
    )

    _validate_plan(plan_product_upgrade(root))

    def inject(stage: str) -> None:
        if stage == "receipt_update":
            raise RuntimeError("injected Codex migration interruption")

    with pytest.raises(ProductUpgradeError, match="Codex migration interruption"):
        apply_product_upgrade(root, fault_injector=inject)

    operation = json.loads((root / UPGRADE_OPERATION_RELATIVE_PATH).read_text())
    assert operation["status"] == "failed"
    assert operation["failure_stage"] == "migrate_supported_legacy_codex_plugin"
    assert operation["rollback_or_recovery_status"] == (
        "codex_migration_recovery_required"
    )
    blocked = plan_product_upgrade(root)
    assert blocked["readiness"] == "BLOCKED"
    assert blocked["next_recommended_action"] == "pcodex integrate codex --repair"

    monkeypatch.setattr(
        codex_plugin,
        "repair_integration",
        lambda repository, native=True: repair_integration(repository, native=False),
    )
    assert (
        pcodex_main(
            [
                "integrate",
                "codex",
                "--repair",
                "--json",
                "--repo-root",
                str(root),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "recovered"
    assert pcodex_main(["upgrade", "--check", "--json", "--repo-root", str(root)]) == 0
    reconciled = json.loads(capsys.readouterr().out)
    assert reconciled["readiness"] == "READY"
    assert reconciled["components"]["upgrade_operation"]["state"] == "recovered"
    _validate_plan(plan_product_upgrade(root))
    assert pcodex_main(["upgrade", "--apply", "--json", "--repo-root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_current"


def test_finalize_failure_after_codex_migration_has_valid_recoverable_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    _install_previous(root)
    legacy = root / ".agents/plugins/plugins/premode-router"
    content = b"historical plugin\n"
    path = legacy / ".codex-plugin/plugin.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    monkeypatch.setattr(
        codex_plugin,
        "LEGACY_PLUGIN_FINGERPRINT",
        {".codex-plugin/plugin.json": hashlib.sha256(content).hexdigest()},
    )
    monkeypatch.setattr(codex_plugin, "LEGACY_SKILL_FINGERPRINT", {})

    def apply_without_native(
        repository: Path,
        *,
        migration: bool,
        native: bool,
        inject: object,
    ) -> dict[str, object]:
        assert native is True
        return codex_plugin.apply_integration(
            repository,
            migration=migration,
            native=False,
            inject=inject,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        "premode.product_upgrade.apply_codex_integration", apply_without_native
    )

    def inject(stage: str) -> None:
        if stage == "before_upgrade_finalize":
            raise RuntimeError("injected upgrade finalization failure")

    with pytest.raises(ProductUpgradeError, match="finalization failure"):
        apply_product_upgrade(root, fault_injector=inject)

    operation = json.loads((root / UPGRADE_OPERATION_RELATIVE_PATH).read_text())
    assert operation["completed_actions"] == [
        "upgrade_managed_install_state",
        "migrate_supported_legacy_codex_plugin",
    ]
    assert operation["failure_stage"] == "finalize"
    assert operation["rollback_or_recovery_status"] == (
        "managed_state_rolled_back_codex_recovery_required"
    )
    recovered = plan_product_upgrade(root)
    assert recovered["components"]["upgrade_operation"]["state"] == "recovered"
    _validate_plan(recovered)
    assert apply_product_upgrade(root)["status"] == "upgraded"


def test_missing_codex_state_does_not_clear_recovery_required_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    legacy = root / ".agents/plugins/plugins/premode-router"
    content = b"historical plugin\n"
    path = legacy / ".codex-plugin/plugin.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    monkeypatch.setattr(
        codex_plugin,
        "LEGACY_PLUGIN_FINGERPRINT",
        {".codex-plugin/plugin.json": hashlib.sha256(content).hexdigest()},
    )
    monkeypatch.setattr(codex_plugin, "LEGACY_SKILL_FINGERPRINT", {})

    def inject(stage: str) -> None:
        if stage == "receipt_update":
            raise RuntimeError("injected partial migration")

    with pytest.raises(ProductUpgradeError):
        apply_product_upgrade(root, fault_injector=inject)
    for relative in (
        codex_plugin.STATE_RELATIVE,
        codex_plugin.JOURNAL_RELATIVE,
    ):
        target = root / relative
        if target.exists():
            target.unlink()
    plugin = root / codex_plugin.PLUGIN_INSTALL_RELATIVE
    if plugin.exists():
        import shutil

        shutil.rmtree(plugin)
    if path.exists():
        path.unlink()

    blocked = plan_product_upgrade(root)
    assert blocked["readiness"] == "BLOCKED"
    assert blocked["components"]["upgrade_operation"]["state"] == "interrupted"
