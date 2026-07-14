from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import premode.openclaw_lifecycle as lifecycle
from premode.pcodex_bootstrap import main as pcodex_main
from premode.openclaw_json5 import (
    OpenClawJson5Ownership,
    apply_json5_edit_plan,
    plan_remove_pcodex,
)


REAL_HELPER_AUTHORITY = lifecycle._installed_helper_authority_available


def _write(root: Path, relative: str, content: str = "{}\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir(parents=True)
    _write(root, "AGENTS.md", "# authority\n")
    _write(root, "PROJECT/tasks.json")
    _write(root, "PROJECT/AI/worker_start/WORKER_START_HERE.md", "# worker\n")
    return root


def _environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".openclaw/openclaw.json"
    return {
        "HOME": str(home),
        "OPENCLAW_CONFIG_PATH": str(config),
    }, config


@pytest.fixture(autouse=True)
def _supported_openclaw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lifecycle,
        "openclaw_compatibility",
        lambda: {
            "installed": True,
            "version": "2026.4.14",
            "supported": True,
            "reason": "supported",
        },
    )
    monkeypatch.setattr(
        lifecycle, "_installed_helper_authority_available", lambda _path: True
    )


def _tree_snapshot(root: Path) -> list[tuple[str, bytes | None]]:
    snapshot: list[tuple[str, bytes | None]] = []
    for path in sorted(root.rglob("*")):
        snapshot.append(
            (
                path.relative_to(root).as_posix(),
                path.read_bytes() if path.is_file() else None,
            )
        )
    return snapshot


def test_preview_is_literal_no_write_and_no_process_claim(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    environ, _ = _environment(tmp_path)
    before = _tree_snapshot(tmp_path)

    result = lifecycle.integration_preview(workspace, environ=environ)

    assert result["status"] == "preview"
    assert result["writes_performed"] is False
    assert result["processes_launched"] is False
    assert _tree_snapshot(tmp_path) == before


def test_complete_install_disable_reenable_uninstall_lifecycle(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    original = b"{\n  // preserve me\n  unrelated: {value: 1},\n}\n"
    config.parent.mkdir(parents=True)
    config.write_bytes(original)

    installed = lifecycle.install_integration(workspace, environ=environ)

    assert installed["status"] == "installed"
    assert installed["writes_performed"] is True
    assert b"preserve me" in config.read_bytes()
    assert (
        lifecycle.integration_status(workspace, environ=environ)["readiness"] == "READY"
    )
    repeated = lifecycle.install_integration(workspace, environ=environ)
    assert repeated["idempotent"] is True
    assert repeated["writes_performed"] is False

    disabled = lifecycle.disable_integration(workspace, environ=environ)
    assert disabled["status"] == "disabled"
    status = lifecycle.integration_status(workspace, environ=environ)
    assert status["readiness"] == "NEEDS_ACTION"
    assert status["reason"] == "disabled"

    enabled = lifecycle.install_integration(workspace, environ=environ)
    assert enabled["status"] == "installed"
    assert (
        lifecycle.integration_status(workspace, environ=environ)["readiness"] == "READY"
    )

    preview = lifecycle.uninstall_integration(workspace, environ=environ, dry_run=True)
    assert preview["status"] == "uninstall_preview"
    assert preview["writes_performed"] is False
    removed = lifecycle.uninstall_integration(workspace, environ=environ)
    assert removed["status"] == "uninstalled"
    assert config.read_bytes() == original
    assert not (workspace / lifecycle.STATE_RELATIVE).exists()


def test_uninstall_removes_product_created_empty_config(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)

    lifecycle.install_integration(workspace, environ=environ)
    assert config.is_file()
    lifecycle.uninstall_integration(workspace, environ=environ)

    assert not config.exists()
    assert config.parent.is_dir()


def test_disabled_uninstall_removes_only_receipt(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    original = b"{unrelated: true}\n"
    config.parent.mkdir(parents=True)
    config.write_bytes(original)
    lifecycle.install_integration(workspace, environ=environ)
    lifecycle.disable_integration(workspace, environ=environ)
    assert config.read_bytes() == original

    result = lifecycle.uninstall_integration(workspace, environ=environ)

    assert result["status"] == "uninstalled"
    assert config.read_bytes() == original
    assert not (workspace / lifecycle.STATE_RELATIVE).exists()


def test_repair_restores_only_missing_receipt_owned_registration(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    config.parent.mkdir(parents=True)
    config.write_bytes(b"{other: 1}\n")
    lifecycle.install_integration(workspace, environ=environ)
    state = json.loads(
        (workspace / lifecycle.STATE_RELATIVE).read_text(encoding="utf-8")
    )
    owned = state["editor_ownership"]
    ownership = OpenClawJson5Ownership(
        schema_version=owned["schema_version"],
        target_path=tuple(owned["target_path"]),
        target_value_sha256=owned["target_value_sha256"],
        created_containers=tuple(owned["created_containers"]),
    )
    raw = config.read_bytes()
    config.write_bytes(apply_json5_edit_plan(raw, plan_remove_pcodex(raw, ownership)))
    assert (
        lifecycle.integration_status(workspace, environ=environ)["reason"]
        == "registration_missing"
    )

    preview = lifecycle.repair_integration(workspace, environ=environ, dry_run=True)
    assert preview["status"] == "repair_preview"
    assert preview["writes_performed"] is False
    repaired = lifecycle.repair_integration(workspace, environ=environ)

    assert repaired["status"] == "installed"
    assert (
        lifecycle.integration_status(workspace, environ=environ)["readiness"] == "READY"
    )


def test_modified_registration_is_preserved_by_repair_and_uninstall(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    lifecycle.install_integration(workspace, environ=environ)
    changed = config.read_bytes().replace(
        b'"premode.pcodex_bootstrap"', b'"user.modified.module"'
    )
    assert changed != config.read_bytes()
    config.write_bytes(changed)

    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.repair_integration(workspace, environ=environ)
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.uninstall_integration(workspace, environ=environ)

    assert config.read_bytes() == changed


def test_unknown_existing_registration_fails_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    config.parent.mkdir(parents=True)
    config.write_text(
        '{mcp:{servers:{pcodex:{command:"user-command"}}}}\n', encoding="utf-8"
    )

    status = lifecycle.integration_status(workspace, environ=environ)
    assert status["readiness"] == "BLOCKED"
    assert status["reason"] == "registration_has_unknown_owner"
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.install_integration(workspace, environ=environ)
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.uninstall_integration(workspace, environ=environ)


def test_authority_switch_blocks_status_and_mutation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    environ, _ = _environment(tmp_path)
    lifecycle.install_integration(workspace, environ=environ)
    switched = {**environ, "OPENCLAW_CONFIG_PATH": str(tmp_path / "other.json")}

    status = lifecycle.integration_status(workspace, environ=switched)

    assert status["readiness"] == "BLOCKED"
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.disable_integration(workspace, environ=switched)


def test_copied_receipt_cannot_authorize_another_workspace(tmp_path: Path) -> None:
    source = _workspace(tmp_path / "source")
    target = _workspace(tmp_path / "target")
    environ, config = _environment(tmp_path)
    lifecycle.install_integration(source, environ=environ)
    copied_state = target / lifecycle.STATE_RELATIVE
    copied_state.parent.mkdir(parents=True)
    copied_state.write_bytes((source / lifecycle.STATE_RELATIVE).read_bytes())
    config_before = config.read_bytes()

    status = lifecycle.integration_status(target, environ=environ)
    assert status["readiness"] == "BLOCKED"
    assert "workspace binding authority changed" in status["reason"]
    for operation in (
        lifecycle.integration_preview,
        lifecycle.install_integration,
        lifecycle.disable_integration,
        lifecycle.repair_integration,
        lifecycle.uninstall_integration,
    ):
        with pytest.raises(
            lifecycle.OpenClawLifecycleError,
            match="workspace binding authority changed",
        ):
            operation(target, environ=environ)
        assert config.read_bytes() == config_before


def test_malformed_state_reports_blocked_and_cannot_mutate(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    lifecycle.install_integration(workspace, environ=environ)
    state_path = workspace / lifecycle.STATE_RELATIVE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["workspace_inode"] = "not-an-inode"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    config_before = config.read_bytes()

    status = lifecycle.integration_status(workspace, environ=environ)
    assert status["readiness"] == "BLOCKED"
    assert status["reason"] == "corrupt_or_unsafe_authority"
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.uninstall_integration(workspace, environ=environ)
    assert config.read_bytes() == config_before


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "pcodex.openclaw-json5-ownership.v999"),
        ("created_containers", ["mcp"]),
        ("created_containers", ["mcp.servers", "mcp"]),
    ),
)
def test_invalid_nested_ownership_never_reports_ready(
    tmp_path: Path, field: str, value: object
) -> None:
    workspace = _workspace(tmp_path)
    environ, _ = _environment(tmp_path)
    lifecycle.install_integration(workspace, environ=environ)
    state_path = workspace / lifecycle.STATE_RELATIVE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["editor_ownership"][field] = value
    state_path.write_text(json.dumps(state), encoding="utf-8")

    status = lifecycle.integration_status(workspace, environ=environ)

    assert status["readiness"] == "BLOCKED"
    assert status["reason"] == "corrupt_or_unsafe_authority"


def test_interruption_after_config_commit_is_recovered_from_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    original_atomic_json = lifecycle._atomic_json
    state_path = workspace / lifecycle.STATE_RELATIVE

    def fail_state_write(path: Path, value: dict[str, object]) -> None:
        if path == state_path:
            raise OSError("injected state receipt interruption")
        original_atomic_json(path, value)

    monkeypatch.setattr(lifecycle, "_atomic_json", fail_state_write)
    with pytest.raises(OSError):
        lifecycle.install_integration(workspace, environ=environ)
    assert config.is_file()
    assert (workspace / lifecycle.JOURNAL_RELATIVE).is_file()
    assert (
        lifecycle.integration_status(workspace, environ=environ)["reason"]
        == "interrupted_operation"
    )

    monkeypatch.setattr(lifecycle, "_atomic_json", original_atomic_json)
    result = lifecycle.repair_integration(workspace, environ=environ)

    assert result["status"] == "repaired"
    assert (
        lifecycle.integration_status(workspace, environ=environ)["readiness"] == "READY"
    )
    assert not (workspace / lifecycle.JOURNAL_RELATIVE).exists()


def test_interruption_before_config_commit_preserves_prior_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    original_atomic_write = lifecycle._atomic_write

    def fail_config_write(path: Path, content: bytes, *, mode: int) -> None:
        if path == config:
            raise OSError("injected pre-commit interruption")
        original_atomic_write(path, content, mode=mode)

    monkeypatch.setattr(lifecycle, "_atomic_write", fail_config_write)
    with pytest.raises(OSError):
        lifecycle.install_integration(workspace, environ=environ)
    assert not config.exists()
    assert (workspace / lifecycle.JOURNAL_RELATIVE).is_file()

    monkeypatch.setattr(lifecycle, "_atomic_write", original_atomic_write)
    result = lifecycle.repair_integration(workspace, environ=environ)

    assert result["status"] == "repaired"
    assert result["recovery"] == "prior_state_preserved"
    assert result["readiness"] == "NEEDS_ACTION"
    assert not (workspace / lifecycle.JOURNAL_RELATIVE).exists()
    assert not config.exists()


def test_corrupt_interruption_journal_fails_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    environ, config = _environment(tmp_path)
    original_atomic_json = lifecycle._atomic_json
    state_path = workspace / lifecycle.STATE_RELATIVE

    def fail_state_write(path: Path, value: dict[str, object]) -> None:
        if path == state_path:
            raise OSError("injected interruption")
        original_atomic_json(path, value)

    lifecycle._atomic_json = fail_state_write
    try:
        with pytest.raises(OSError):
            lifecycle.install_integration(workspace, environ=environ)
    finally:
        lifecycle._atomic_json = original_atomic_json
    journal_path = workspace / lifecycle.JOURNAL_RELATIVE
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["state_after"]["workspace"] = str(tmp_path / "replayed")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    config_before = config.read_bytes()
    journal_before = journal_path.read_bytes()

    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.repair_integration(workspace, environ=environ)

    assert config.read_bytes() == config_before
    assert journal_path.read_bytes() == journal_before
    assert not state_path.exists()


def test_corrupt_journal_status_requires_manual_recovery(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    environ, _ = _environment(tmp_path)
    lifecycle.install_integration(workspace, environ=environ)
    journal = workspace / lifecycle.JOURNAL_RELATIVE
    journal.write_text("{}\n", encoding="utf-8")

    status = lifecycle.integration_status(workspace, environ=environ)

    assert status["readiness"] == "BLOCKED"
    assert status["reason"] == "corrupt_or_unsafe_authority"
    assert status["next_recommended_action"] == "manual recovery is required"
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.repair_integration(workspace, environ=environ)


def test_atomic_write_preserves_concurrent_target_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write(tmp_path, "authority.json", "before\n")
    original_rename = os.rename

    def concurrent_rename(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if source == target.name:
            target.write_bytes(b"concurrent-user-edit\n")
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(lifecycle.os, "rename", concurrent_rename)

    with pytest.raises(lifecycle.OpenClawLifecycleError, match="changed during"):
        lifecycle._atomic_write(target, b"pcodex-edit\n", mode=0o600)

    assert target.read_bytes() == b"concurrent-user-edit\n"
    assert not (tmp_path / f".{target.name}.pcodex-cas-backup").exists()


def test_atomic_write_rechecks_displaced_file_after_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write(tmp_path, "authority.json", "before\n")
    backup = tmp_path / f".{target.name}.pcodex-cas-backup"
    original_link = os.link

    def concurrent_link(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        if destination == target.name and source.startswith(
            f".{target.name}.pcodex-stage-"
        ):
            backup.write_bytes(b"concurrent-user-edit\n")
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(lifecycle.os, "link", concurrent_link)

    with pytest.raises(lifecycle.OpenClawLifecycleError, match="publication"):
        lifecycle._atomic_write(target, b"pcodex-edit\n", mode=0o600)

    assert target.read_bytes() == b"pcodex-edit\n"
    assert backup.read_bytes() == b"concurrent-user-edit\n"


def test_atomic_write_preserves_edit_injected_during_backup_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write(tmp_path, "authority.json", "before\n")
    backup_name = f".{target.name}.pcodex-cas-backup"
    original_unlink = os.unlink

    def late_unlink(path: object, *, dir_fd: int | None = None) -> None:
        if path == backup_name:
            (tmp_path / backup_name).write_bytes(b"late-concurrent-user-edit\n")
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(lifecycle.os, "unlink", late_unlink)

    with pytest.raises(lifecycle.OpenClawLifecycleError, match="final cleanup"):
        lifecycle._atomic_write(target, b"pcodex-edit\n", mode=0o600)

    recovery = list(tmp_path.glob(f".{target.name}.pcodex-cas-recovery-*"))
    assert target.read_bytes() == b"pcodex-edit\n"
    assert len(recovery) == 1
    assert recovery[0].read_bytes() == b"late-concurrent-user-edit\n"


def test_safe_unlink_preserves_concurrent_replacement_in_recovery_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write(tmp_path, "authority.json", "owned\n")
    original_rename = os.rename

    def concurrent_rename(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if source == target.name:
            target.write_bytes(b"concurrent-user-file\n")
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(lifecycle.os, "rename", concurrent_rename)

    with pytest.raises(lifecycle.OpenClawLifecycleError, match="recovery staging"):
        lifecycle._safe_unlink(target, expected_hash=lifecycle._sha256(b"owned\n"))

    staged = list(tmp_path.glob(f".{target.name}.pcodex-remove-*"))
    assert len(staged) == 1
    assert staged[0].read_bytes() == b"concurrent-user-file\n"


def test_safe_unlink_preserves_edit_injected_during_quarantine_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write(tmp_path, "authority.json", "owned\n")
    original_unlink = os.unlink

    def late_unlink(path: object, *, dir_fd: int | None = None) -> None:
        if isinstance(path, str) and ".pcodex-remove-" in path:
            (tmp_path / path).write_bytes(b"late-concurrent-user-edit\n")
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(lifecycle.os, "unlink", late_unlink)

    with pytest.raises(lifecycle.OpenClawLifecycleError, match="final cleanup"):
        lifecycle._safe_unlink(target, expected_hash=lifecycle._sha256(b"owned\n"))

    recovery = list(tmp_path.glob(f".{target.name}.pcodex-remove-recovery-*"))
    assert len(recovery) == 1
    assert recovery[0].read_bytes() == b"late-concurrent-user-edit\n"


def test_safe_unlink_rejects_parent_swap_without_touching_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "authority"
    target = _write(parent, "owned.json", "owned\n")
    outside = tmp_path / "outside"
    outside_target = _write(outside, "owned.json", "owned\n")
    saved = tmp_path / "authority-saved"
    original_open = os.open
    swapped = False

    def swapping_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if not swapped and Path(path) == parent:
            swapped = True
            parent.rename(saved)
            parent.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(lifecycle.os, "open", swapping_open)

    with pytest.raises(lifecycle.OpenClawLifecycleError, match="bind"):
        lifecycle._safe_unlink(target, expected_hash=lifecycle._sha256(b"owned\n"))

    assert outside_target.read_bytes() == b"owned\n"
    assert (saved / "owned.json").read_bytes() == b"owned\n"


def test_journal_creation_rejects_parent_swap_without_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    pcodex = workspace / ".pcodex"
    pcodex.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    saved = workspace / ".pcodex-saved"
    original_open = os.open
    swapped = False

    def swapping_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if not swapped and Path(path) == pcodex:
            swapped = True
            pcodex.rename(saved)
            pcodex.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(lifecycle.os, "open", swapping_open)

    with pytest.raises(lifecycle.OpenClawLifecycleError, match="bind"):
        lifecycle._write_journal_exclusive(workspace, {"phase": "test"})

    assert not (outside / lifecycle.JOURNAL_RELATIVE.name).exists()
    assert not (saved / lifecycle.JOURNAL_RELATIVE.name).exists()


def test_helper_authority_change_requires_and_accepts_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    environ, _ = _environment(tmp_path)
    lifecycle.install_integration(workspace, environ=environ)
    original_registration = lifecycle.canonical_registration

    def updated_registration(root: Path) -> dict[str, object]:
        registration = original_registration(root)
        return {**registration, "args": [*registration["args"], "--transport-v2"]}

    monkeypatch.setattr(lifecycle, "canonical_registration", updated_registration)

    status = lifecycle.integration_status(workspace, environ=environ)
    assert status["readiness"] == "NEEDS_ACTION"
    assert status["reason"] == "helper_authority_changed"
    install_preview = lifecycle.integration_preview(workspace, environ=environ)
    assert install_preview["status"] == "preview"
    assert install_preview["plan"] == {"operation": "replace_owned_helper_authority"}
    preview = lifecycle.repair_integration(workspace, environ=environ, dry_run=True)
    assert preview["status"] == "repair_preview"
    repaired = lifecycle.repair_integration(workspace, environ=environ)
    assert repaired["status"] == "installed"
    assert (
        lifecycle.integration_status(workspace, environ=environ)["readiness"] == "READY"
    )


def test_checkout_dependent_helper_authority_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.setattr(
        lifecycle, "_installed_helper_authority_available", lambda _path: False
    )

    with pytest.raises(
        lifecycle.OpenClawLifecycleError,
        match="installed OpenClaw helper authority is unavailable",
    ):
        lifecycle.canonical_registration(workspace)


def test_helper_authority_binds_loaded_module_to_distribution_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = tmp_path / "venv"
    executable = _write(prefix, "bin/python", "")
    site = prefix / "lib/site-packages"
    installed_helper = _write(site, "premode/pcodex_bootstrap.py", "")
    shadow_helper = _write(tmp_path, "shadow/premode/pcodex_bootstrap.py", "")
    monkeypatch.setattr(
        lifecycle, "_installed_helper_authority_available", REAL_HELPER_AUTHORITY
    )

    class FakeDistribution:
        files = (Path("premode/pcodex_bootstrap.py"),)
        version = lifecycle.__version__

        @staticmethod
        def locate_file(item: Path) -> Path:
            return site / item

    monkeypatch.setattr(lifecycle.sys, "prefix", str(prefix))
    monkeypatch.setattr(
        lifecycle.importlib.metadata,
        "distribution",
        lambda _name: FakeDistribution(),
    )
    monkeypatch.setattr(
        lifecycle.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(origin=str(shadow_helper)),
    )

    assert not lifecycle._installed_helper_authority_available(executable)

    monkeypatch.setattr(
        lifecycle.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(origin=str(installed_helper)),
    )
    assert lifecycle._installed_helper_authority_available(executable)


def test_safe_unlink_rejects_multiply_linked_authority(tmp_path: Path) -> None:
    authority = _write(tmp_path, "authority.json", "owned\n")
    sibling = tmp_path / "authority-hardlink.json"
    sibling.hardlink_to(authority)

    with pytest.raises(lifecycle.OpenClawLifecycleError, match="multiply linked"):
        lifecycle._safe_unlink(
            authority, expected_hash=lifecycle._sha256(authority.read_bytes())
        )

    assert authority.read_text(encoding="utf-8") == "owned\n"
    assert sibling.read_text(encoding="utf-8") == "owned\n"


def test_unsupported_runtime_blocks_install_but_not_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    environ, _ = _environment(tmp_path)
    monkeypatch.setattr(
        lifecycle,
        "openclaw_compatibility",
        lambda: {
            "installed": True,
            "version": "2026.4.15",
            "supported": False,
            "reason": "unsupported_openclaw_version",
        },
    )

    status = lifecycle.integration_status(workspace, environ=environ)
    assert status["readiness"] == "BLOCKED"
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.integration_preview(workspace, environ=environ)
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.install_integration(workspace, environ=environ)


def test_installed_adapter_status_blocks_after_runtime_version_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    environ, _ = _environment(tmp_path)
    lifecycle.install_integration(workspace, environ=environ)
    monkeypatch.setattr(
        lifecycle,
        "openclaw_compatibility",
        lambda: {
            "installed": True,
            "version": "2026.4.15",
            "supported": False,
            "reason": "unsupported_openclaw_version",
        },
    )

    status = lifecycle.integration_status(workspace, environ=environ)

    assert status["readiness"] == "BLOCKED"
    assert status["reason"] == "unsupported_openclaw_version"


def test_false_positive_workspace_cannot_be_installed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write(workspace, "AGENTS.md", "# generic\n")
    _write(workspace, "_claw_output/proof.json")
    _write(workspace, "tools/symphony/readme.md")
    environ, _ = _environment(tmp_path)

    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.integration_preview(workspace, environ=environ)
    with pytest.raises(lifecycle.OpenClawLifecycleError):
        lifecycle.install_integration(workspace, environ=environ)


def test_authoritative_cli_maps_complete_openclaw_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    environ, _ = _environment(tmp_path)
    monkeypatch.setenv("HOME", environ["HOME"])
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", environ["OPENCLAW_CONFIG_PATH"])

    commands = (
        ("--dry-run", 0, "preview"),
        ("--write", 0, "installed"),
        ("--status", 0, "READY"),
        ("--repair", 0, "healthy"),
        ("--disable", 0, "disabled"),
        ("--write", 0, "installed"),
        ("--uninstall", 0, "uninstalled"),
        ("--write", 0, "installed"),
    )
    for flag, expected_code, expected_status in commands:
        code = pcodex_main(
            [
                "integrate",
                "openclaw",
                flag,
                "--repo-root",
                str(workspace),
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == expected_code
        assert expected_status in {payload.get("status"), payload.get("readiness")}


def test_explicit_openclaw_repo_root_is_never_broadened_to_parent_git_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outer = tmp_path / "outer"
    (outer / ".git").mkdir(parents=True)
    workspace = _workspace(outer / "nested")
    environ, _ = _environment(tmp_path)
    monkeypatch.setenv("HOME", environ["HOME"])
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", environ["OPENCLAW_CONFIG_PATH"])

    code = pcodex_main(
        [
            "integrate",
            "openclaw",
            "--dry-run",
            "--repo-root",
            str(workspace),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["registration"]["env"] == {"PCODEX_WORKSPACE": str(workspace)}


def test_openclaw_mcp_entrypoint_requires_immutable_environment_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PCODEX_WORKSPACE", raising=False)

    assert pcodex_main(["openclaw-mcp-server"]) == 2
