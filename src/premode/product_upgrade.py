"""Receipt-bound product-state upgrade after explicit package replacement.

The Python environment remains owned by the user's package manager.  This
module only reconciles repository-local state whose predecessor ownership can
be proven from the frozen previous-release authority.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from . import __version__
from .codex_plugin import (
    CodexPluginError,
    STATE_RELATIVE as CODEX_STATE_RELATIVE,
    apply_integration as apply_codex_integration,
    integration_preview as codex_integration_preview,
    plugin_status as codex_plugin_status,
)
from .managed_state import (
    DEFAULT_INSTALL_STATE_RELATIVE_PATH,
    ManagedStateError,
    _atomic_write_managed,
    _atomic_write_managed_json,
    install_managed_file,
    plan_repair,
    product_install_marker_content,
    read_install_state_receipt,
    resolve_managed_path,
    sha256_bytes,
    validate_managed_root,
)
from .openclaw_lifecycle import (
    STATE_RELATIVE as OPENCLAW_STATE_RELATIVE,
    OpenClawLifecycleError,
    integration_status as openclaw_status,
)
from .timeutil import timestamp_iso


UPGRADE_PLAN_SCHEMA_VERSION = "pcodex.upgrade-plan.v1"
UPGRADE_OPERATION_SCHEMA_VERSION = "pcodex.upgrade-operation.v1"
UPGRADE_OPERATION_RELATIVE_PATH = ".premode/upgrade-operation.json"
PREVIOUS_AUTHORITY_SCHEMA_VERSION = "pcodex.previous-supported.v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SUPPORTED_PREVIOUS_VERSION = "0.2.6.24"
SUPPORTED_PREVIOUS_COMMIT = (
    "b9aede455c8d49217ef0a67e8dec0c8cf2c565a6"  # pragma: allowlist secret
)
_UPGRADE_ACTIONS = (
    "upgrade_managed_install_state",
    "migrate_supported_legacy_codex_plugin",
)
_RECOVERY_STATUSES = {
    "not_required",
    "no_product_state_committed",
    "managed_state_rolled_back",
    "managed_state_rolled_back_codex_recovery_required",
    "managed_state_rollback_failed_recovery_required",
    "managed_state_rollback_failed_codex_recovery_required",
    "codex_migration_recovery_required",
}


class ProductUpgradeError(RuntimeError):
    """Fail-closed product-state upgrade error."""


def _read_bound_operation(root: Path, relative: str) -> bytes | None:
    path = resolve_managed_path(root, relative)
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
        raise ProductUpgradeError(
            "upgrade operation receipt must be an exclusively linked regular file"
        )
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            content = handle.read()
        after = os.fstat(descriptor)
        current = path.lstat()
    finally:
        os.close(descriptor)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or identity
        != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    ):
        raise ProductUpgradeError("upgrade operation receipt changed during inspection")
    return content


def _validate_operation_receipt(
    payload: Any, root: Path, authority: Mapping[str, Any]
) -> dict[str, Any]:
    required = {
        "schema_version",
        "operation_id",
        "operation_type",
        "from_version",
        "to_version",
        "managed_root_hash",
        "planned_actions",
        "completed_actions",
        "status",
        "failure_stage",
        "rollback_or_recovery_status",
        "started_at",
        "completed_at",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ProductUpgradeError("upgrade operation receipt is malformed")
    if (
        payload["schema_version"] != UPGRADE_OPERATION_SCHEMA_VERSION
        or payload["operation_type"] != "product_state_upgrade"
        or payload["from_version"] != authority["previous_version"]
        or payload["to_version"] != __version__
        or payload["managed_root_hash"] != sha256_bytes(str(root).encode("utf-8"))
    ):
        raise ProductUpgradeError("upgrade operation receipt is unrelated")
    if not isinstance(payload["operation_id"], str) or not _CANONICAL_UUID.fullmatch(
        payload["operation_id"]
    ):
        raise ProductUpgradeError("upgrade operation id is invalid")
    try:
        parsed_id = __import__("uuid").UUID(payload["operation_id"])
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProductUpgradeError("upgrade operation id is invalid") from exc
    if str(parsed_id) != payload["operation_id"]:
        raise ProductUpgradeError("upgrade operation id is not canonical")
    planned = payload["planned_actions"]
    completed = payload["completed_actions"]
    if (
        not isinstance(planned, list)
        or not planned
        or any(not isinstance(item, str) for item in planned)
        or len(planned) != len(set(planned))
        or tuple(planned) != tuple(item for item in _UPGRADE_ACTIONS if item in planned)
    ):
        raise ProductUpgradeError("upgrade planned actions are invalid")
    if (
        not isinstance(completed, list)
        or any(not isinstance(item, str) for item in completed)
        or completed != planned[: len(completed)]
    ):
        raise ProductUpgradeError("upgrade completed actions are invalid")
    status = payload["status"]
    recovery = payload["rollback_or_recovery_status"]
    if (
        status not in {"started", "succeeded", "failed"}
        or recovery not in _RECOVERY_STATUSES
    ):
        raise ProductUpgradeError("upgrade operation state is invalid")
    if not isinstance(payload["started_at"], str) or not payload["started_at"]:
        raise ProductUpgradeError("upgrade operation start timestamp is invalid")
    if status == "started":
        valid_correlation = (
            payload["failure_stage"] is None
            and payload["completed_at"] is None
            and recovery == "not_required"
        )
    elif status == "succeeded":
        valid_correlation = (
            completed == planned
            and payload["failure_stage"] is None
            and isinstance(payload["completed_at"], str)
            and bool(payload["completed_at"])
            and recovery == "not_required"
        )
    else:
        expected_failure = (
            planned[len(completed)] if len(completed) < len(planned) else "finalize"
        )
        valid_correlation = (
            payload["failure_stage"] == expected_failure
            and isinstance(payload["completed_at"], str)
            and bool(payload["completed_at"])
            and recovery != "not_required"
        )
        recovery_correlation = {
            "no_product_state_committed": completed == [],
            "managed_state_rolled_back": (
                "upgrade_managed_install_state" in completed
                and "migrate_supported_legacy_codex_plugin" not in completed
            ),
            "managed_state_rolled_back_codex_recovery_required": (
                "upgrade_managed_install_state" in completed
                and "migrate_supported_legacy_codex_plugin" in planned
                and expected_failure
                in {"migrate_supported_legacy_codex_plugin", "finalize"}
            ),
            "managed_state_rollback_failed_recovery_required": (
                "upgrade_managed_install_state" in completed
                and "migrate_supported_legacy_codex_plugin" not in completed
                and expected_failure
                in {"migrate_supported_legacy_codex_plugin", "finalize"}
            ),
            "managed_state_rollback_failed_codex_recovery_required": (
                "upgrade_managed_install_state" in completed
                and "migrate_supported_legacy_codex_plugin" in planned
                and expected_failure
                in {"migrate_supported_legacy_codex_plugin", "finalize"}
            ),
            "codex_migration_recovery_required": (
                "migrate_supported_legacy_codex_plugin" in planned
                and (
                    completed == []
                    and expected_failure == "migrate_supported_legacy_codex_plugin"
                )
                or (
                    completed == ["migrate_supported_legacy_codex_plugin"]
                    and expected_failure == "finalize"
                )
            ),
        }.get(recovery, False)
        valid_correlation = valid_correlation and recovery_correlation
    if not valid_correlation:
        raise ProductUpgradeError("upgrade operation fields are inconsistent")
    return dict(payload)


def _source_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").is_file() and (
        candidate / "release" / "previous-supported.json"
    ).is_file():
        return candidate
    return None


def previous_authority_path(prefix: Path | str | None = None) -> Path:
    """Resolve the one frozen predecessor authority for this installation."""

    source = _source_root()
    if source is not None and prefix is None:
        return source / "release" / "previous-supported.json"
    base = Path(sys.prefix if prefix is None else prefix)
    return base / "share" / "premode-router" / "release" / "previous-supported.json"


def load_previous_authority(prefix: Path | str | None = None) -> dict[str, Any]:
    path = previous_authority_path(prefix)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductUpgradeError(
            "previous supported release authority is unavailable"
        ) from exc
    required = {
        "schema_version",
        "product",
        "current_version",
        "previous_version",
        "previous_commit",
        "upgrade_policy",
        "downgrade_policy",
        "publication_authorized",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ProductUpgradeError("previous supported release authority is malformed")
    if (
        payload.get("schema_version") != PREVIOUS_AUTHORITY_SCHEMA_VERSION
        or payload.get("product") != "premode-router"
        or payload.get("current_version") != __version__
        or payload.get("upgrade_policy")
        != "explicit_package_upgrade_then_current_receipt_bound_lifecycle"
        or payload.get("downgrade_policy")
        != "unsupported_fail_closed_for_future_or_unknown_receipts"
        or payload.get("publication_authorized") is not False
    ):
        raise ProductUpgradeError(
            "previous supported release authority is incompatible"
        )
    for key in ("previous_version", "previous_commit"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise ProductUpgradeError(
                "previous supported release authority is incomplete"
            )
    if not _HEX40.fullmatch(payload["previous_commit"]):
        raise ProductUpgradeError("previous supported commit is not a SHA-1 authority")
    if (
        payload["current_version"] != __version__
        or payload["previous_version"] != SUPPORTED_PREVIOUS_VERSION
        or payload["previous_commit"] != SUPPORTED_PREVIOUS_COMMIT
    ):
        raise ProductUpgradeError("previous supported release authority was modified")
    return payload


def _previous_install_marker_content(
    authority: Mapping[str, Any] | None = None,
) -> bytes:
    frozen = load_previous_authority() if authority is None else authority
    return (
        json.dumps(
            {
                "product_name": "pCodex",
                "product_version": frozen["previous_version"],
                "schema_version": "pcodex.managed-install.v1",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _managed_component(
    root: Path, authority: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    receipt_path = root / DEFAULT_INSTALL_STATE_RELATIVE_PATH
    receipt = read_install_state_receipt(receipt_path)
    conflicts: list[dict[str, Any]] = []
    actions: list[str] = []
    if receipt["status"] == "missing":
        return (
            {
                "state": "absent",
                "receipt": DEFAULT_INSTALL_STATE_RELATIVE_PATH,
                "from_version": None,
                "to_version": __version__,
            },
            conflicts,
            actions,
        )
    if receipt["status"] != "loaded":
        conflicts.append(
            {
                "component": "managed_state",
                "reason": f"install_state_{receipt['status']}",
            }
        )
        return (
            {
                "state": "blocked",
                "receipt": DEFAULT_INSTALL_STATE_RELATIVE_PATH,
                "from_version": None,
                "to_version": __version__,
            },
            conflicts,
            actions,
        )
    payload = receipt["payload"]
    version = payload.get("product_version")
    if not isinstance(version, str) or version not in {
        authority["previous_version"],
        __version__,
    }:
        conflicts.append(
            {
                "component": "managed_state",
                "reason": "unsupported_or_future_product_version",
                "observed_version": version,
            }
        )
        state = "blocked"
    else:
        expected = (
            _previous_install_marker_content(authority)
            if version == authority["previous_version"]
            else product_install_marker_content()
        )
        try:
            repair = plan_repair(
                root,
                receipt_path,
                expected_content={".premode/pcodex-install.json": expected},
            )
        except (ManagedStateError, OSError) as exc:
            conflicts.append(
                {
                    "component": "managed_state",
                    "reason": "authority_invalid",
                    "detail": str(exc),
                }
            )
            state = "blocked"
        else:
            unsafe = sum(
                len(repair.get(key) or [])
                for key in (
                    "will_create",
                    "will_restore",
                    "will_replace_owned",
                    "will_preserve_modified",
                    "conflict",
                    "unknown_owner",
                    "unsupported_registration",
                    "requires_manual_action",
                )
            )
            if unsafe:
                conflicts.append(
                    {
                        "component": "managed_state",
                        "reason": "state_not_exactly_healthy",
                    }
                )
                state = "blocked"
            elif version == __version__:
                state = "current"
            else:
                state = "supported_predecessor"
                actions.append("upgrade_managed_install_state")
    return (
        {
            "state": state,
            "receipt": DEFAULT_INSTALL_STATE_RELATIVE_PATH,
            "from_version": version,
            "to_version": __version__,
        },
        conflicts,
        actions,
    )


def _codex_component(
    root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    conflicts: list[dict[str, Any]] = []
    actions: list[str] = []
    state_path = root / CODEX_STATE_RELATIVE
    if state_path.exists() or state_path.is_symlink():
        try:
            status = codex_plugin_status(root, native=True)
        except (CodexPluginError, OSError) as exc:
            conflicts.append(
                {
                    "component": "codex_plugin",
                    "reason": "authority_invalid",
                    "detail": str(exc),
                }
            )
            return {"state": "blocked", "legacy": []}, conflicts, actions
        if status.get("readiness") not in {"READY", "NEEDS_ACTION"} or status.get(
            "conflicts"
        ):
            conflicts.append(
                {
                    "component": "codex_plugin",
                    "reason": "canonical_plugin_requires_repair",
                }
            )
            return {"state": "blocked", "legacy": []}, conflicts, actions
        return {"state": "current", "legacy": []}, conflicts, actions
    try:
        preview = codex_integration_preview(root, migration=True, native=False)
    except (CodexPluginError, OSError) as exc:
        conflicts.append(
            {
                "component": "codex_plugin",
                "reason": "inventory_invalid",
                "detail": str(exc),
            }
        )
        return {"state": "blocked", "legacy": []}, conflicts, actions
    legacy = list(preview.get("legacy_sources_found") or [])
    unknown = [item for item in legacy if item.get("requires_manual_action")]
    migratable = [
        item for item in legacy if item.get("classification") == "legacy_migratable"
    ]
    if preview.get("conflicts"):
        conflicts.extend(
            {
                "component": "codex_plugin",
                "reason": str(item.get("reason") or "conflict"),
            }
            for item in preview["conflicts"]
        )
        state = "blocked"
    elif unknown:
        conflicts.append(
            {"component": "codex_plugin", "reason": "unknown_legacy_state_preserved"}
        )
        state = "blocked"
    elif migratable:
        try:
            native_preview = codex_integration_preview(
                root, migration=True, native=True
            )
        except (CodexPluginError, OSError) as exc:
            conflicts.append(
                {
                    "component": "codex_plugin",
                    "reason": "native_inventory_invalid",
                    "detail": str(exc),
                }
            )
            state = "blocked"
        else:
            conflicts.extend(
                {
                    "component": "codex_plugin",
                    "reason": str(item.get("reason") or "native_conflict"),
                }
                for item in native_preview.get("conflicts") or []
            )
            if conflicts:
                state = "blocked"
            else:
                actions.append("migrate_supported_legacy_codex_plugin")
                state = "supported_legacy"
    else:
        state = "absent"
    return {"state": state, "legacy": legacy}, conflicts, actions


def _openclaw_component(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = root / OPENCLAW_STATE_RELATIVE
    if not path.exists() and not path.is_symlink():
        return {"state": "absent"}, []
    try:
        status = openclaw_status(root)
    except (OpenClawLifecycleError, OSError) as exc:
        return {"state": "blocked"}, [
            {"component": "openclaw", "reason": "authority_invalid", "detail": str(exc)}
        ]
    if status.get("readiness") not in {"READY", "NEEDS_ACTION"} or status.get(
        "conflicts"
    ):
        return {"state": "blocked"}, [
            {"component": "openclaw", "reason": "integration_requires_repair"}
        ]
    return {"state": "current_preserved"}, []


def _operation_component(
    root: Path, authority: Mapping[str, Any], codex: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        content = _read_bound_operation(root, UPGRADE_OPERATION_RELATIVE_PATH)
    except ProductUpgradeError as exc:
        return {"state": "blocked"}, [
            {
                "component": "upgrade_operation",
                "reason": "operation_receipt_unsafe",
                "detail": str(exc),
            }
        ]
    if content is None:
        return {"state": "absent"}, []
    try:
        payload = _validate_operation_receipt(json.loads(content), root, authority)
    except (json.JSONDecodeError, ProductUpgradeError) as exc:
        return {"state": "blocked"}, [
            {
                "component": "upgrade_operation",
                "reason": "operation_receipt_invalid",
                "detail": str(exc),
            }
        ]
    rollback_status = str(payload["rollback_or_recovery_status"])
    codex_recovery_statuses = {
        "codex_migration_recovery_required",
        "managed_state_rolled_back_codex_recovery_required",
    }
    if (
        payload["status"] == "failed"
        and rollback_status in codex_recovery_statuses
        and codex.get("state") in {"current", "supported_legacy"}
    ):
        return {
            "state": "recovered",
            "status": payload["status"],
            "recovery": "codex_state_reconciled",
        }, []
    if payload["status"] == "started" or (
        payload["status"] == "failed"
        and (
            rollback_status.endswith("recovery_required")
            or (
                payload["completed_actions"]
                and rollback_status != "managed_state_rolled_back"
            )
        )
    ):
        return {"state": "interrupted", "status": payload["status"]}, [
            {
                "component": "upgrade_operation",
                "reason": "interrupted_upgrade_requires_recovery",
            }
        ]
    return {"state": "terminal", "status": payload["status"]}, []


def plan_product_upgrade(managed_root: Path | str) -> dict[str, Any]:
    """Return an exact no-write product-state upgrade plan."""

    root = validate_managed_root(managed_root)
    authority = load_previous_authority()
    managed, managed_conflicts, managed_actions = _managed_component(root, authority)
    codex, codex_conflicts, codex_actions = _codex_component(root)
    openclaw, openclaw_conflicts = _openclaw_component(root)
    operation, operation_conflicts = _operation_component(root, authority, codex)
    conflicts = (
        managed_conflicts + codex_conflicts + openclaw_conflicts + operation_conflicts
    )
    actions = managed_actions + codex_actions
    readiness = "BLOCKED" if conflicts else "READY"
    if not conflicts and actions:
        readiness = "NEEDS_ACTION"
    manual_legacy_action = any(
        item.get("reason") == "unknown_legacy_state_preserved" for item in conflicts
    )
    codex_repair_required = any(
        item.get("component") == "codex_plugin"
        or item.get("reason") == "interrupted_upgrade_requires_recovery"
        for item in conflicts
    )
    next_action = (
        "review preserved legacy plugin state manually"
        if conflicts and manual_legacy_action
        else "pcodex integrate codex --repair"
        if conflicts and codex_repair_required
        else "resolve reported upgrade conflicts"
        if conflicts
        else "pcodex upgrade --apply"
        if actions
        else "none"
    )
    return {
        "schema_version": UPGRADE_PLAN_SCHEMA_VERSION,
        "current_version": __version__,
        "previous_version": authority["previous_version"],
        "previous_commit": authority["previous_commit"],
        "package_replacement_policy": authority["upgrade_policy"],
        "managed_root_hash": sha256_bytes(str(root).encode("utf-8")),
        "readiness": readiness,
        "components": {
            "managed_state": managed,
            "codex_plugin": codex,
            "openclaw": openclaw,
            "upgrade_operation": operation,
        },
        "planned_actions": actions,
        "preserved_components": [
            name
            for name, component in (("codex_plugin", codex), ("openclaw", openclaw))
            if component["state"] in {"current", "current_preserved"}
        ],
        "conflicts": conflicts,
        "writes_performed": False,
        "next_recommended_action": next_action,
    }


def _operation_content(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_operation(
    root: Path,
    relative: str,
    payload: Mapping[str, Any],
    *,
    require_absent: bool = False,
    expected_current_hash: str | None = None,
) -> str:
    _atomic_write_managed_json(
        root,
        relative,
        payload,
        require_absent=require_absent,
        expected_current_hash=expected_current_hash,
    )
    return sha256_bytes(_operation_content(payload))


def _restore_previous_managed_state(root: Path, snapshots: Mapping[str, bytes]) -> None:
    """Restore the exact receipt-proven predecessor bytes after a caught failure."""

    for relative in (
        ".premode/pcodex-install.json",
        DEFAULT_INSTALL_STATE_RELATIVE_PATH,
    ):
        before = snapshots[relative]
        path = resolve_managed_path(root, relative)
        current = path.read_bytes()
        _atomic_write_managed(
            root,
            relative,
            before,
            expected_current_hash=sha256_bytes(current),
        )


def apply_product_upgrade(
    managed_root: Path | str,
    *,
    fault_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Apply only the exact actions authorized by ``plan_product_upgrade``."""

    root = validate_managed_root(managed_root)
    plan = plan_product_upgrade(root)
    if plan["readiness"] == "BLOCKED":
        return {**plan, "status": "blocked", "applied": False}
    if not plan["planned_actions"]:
        return {**plan, "status": "already_current", "applied": False}
    relative_operation = UPGRADE_OPERATION_RELATIVE_PATH
    authority = load_previous_authority()
    existing_operation_hash: str | None = None
    existing_bytes = _read_bound_operation(root, relative_operation)
    if existing_bytes is not None:
        try:
            existing = _validate_operation_receipt(
                json.loads(existing_bytes), root, authority
            )
        except (json.JSONDecodeError, ProductUpgradeError) as exc:
            raise ProductUpgradeError(
                "existing upgrade operation receipt is invalid"
            ) from exc
        recovered_operation = (
            plan["components"]["upgrade_operation"].get("state") == "recovered"
        )
        if existing.get("status") == "started" or (
            existing.get("status") == "failed"
            and not recovered_operation
            and (
                str(existing.get("rollback_or_recovery_status")).endswith(
                    "recovery_required"
                )
                or (
                    existing.get("completed_actions")
                    and existing.get("rollback_or_recovery_status")
                    != "managed_state_rolled_back"
                )
            )
        ):
            raise ProductUpgradeError("interrupted upgrade requires recovery")
        existing_operation_hash = sha256_bytes(existing_bytes)
    operation_id = str(uuid4())
    operation: dict[str, Any] = {
        "schema_version": UPGRADE_OPERATION_SCHEMA_VERSION,
        "operation_id": operation_id,
        "operation_type": "product_state_upgrade",
        "from_version": plan["previous_version"],
        "to_version": __version__,
        "managed_root_hash": plan["managed_root_hash"],
        "planned_actions": list(plan["planned_actions"]),
        "completed_actions": [],
        "status": "started",
        "failure_stage": None,
        "rollback_or_recovery_status": "not_required",
        "started_at": timestamp_iso(),
        "completed_at": None,
    }
    operation_hash = _write_operation(
        root,
        relative_operation,
        operation,
        require_absent=existing_operation_hash is None,
        expected_current_hash=existing_operation_hash,
    )
    managed_upgraded = False
    codex_migration_started = False
    managed_snapshots: dict[str, bytes] = {}
    try:
        if fault_injector is not None:
            fault_injector("operation_started")
        if "upgrade_managed_install_state" in plan["planned_actions"]:
            managed_snapshots = {
                relative: resolve_managed_path(root, relative).read_bytes()
                for relative in (
                    ".premode/pcodex-install.json",
                    DEFAULT_INSTALL_STATE_RELATIVE_PATH,
                )
            }
            result = install_managed_file(
                root,
                ".premode/pcodex-install.json",
                product_install_marker_content(),
                receipt_path=root / DEFAULT_INSTALL_STATE_RELATIVE_PATH,
                operation_type="migration",
                operation_id=operation_id,
            )
            if result.get("status") not in {"installed", "already_installed"}:
                raise ProductUpgradeError(
                    "managed install state upgrade was not applied"
                )
            managed_upgraded = True
            operation["completed_actions"].append("upgrade_managed_install_state")
            operation_hash = _write_operation(
                root,
                relative_operation,
                operation,
                expected_current_hash=operation_hash,
            )
            if fault_injector is not None:
                fault_injector("managed_state_committed")
        if "migrate_supported_legacy_codex_plugin" in plan["planned_actions"]:
            codex_migration_started = True
            result = apply_codex_integration(
                root, migration=True, native=True, inject=fault_injector
            )
            if result.get("status") in {"blocked", "error"}:
                raise ProductUpgradeError(
                    "supported legacy Codex migration was blocked"
                )
            operation["completed_actions"].append(
                "migrate_supported_legacy_codex_plugin"
            )
            operation_hash = _write_operation(
                root,
                relative_operation,
                operation,
                expected_current_hash=operation_hash,
            )
        if fault_injector is not None:
            fault_injector("before_upgrade_finalize")
        operation["status"] = "succeeded"
        operation["completed_at"] = timestamp_iso()
        operation_hash = _write_operation(
            root,
            relative_operation,
            operation,
            expected_current_hash=operation_hash,
        )
    except Exception as exc:
        operation["status"] = "failed"
        operation["failure_stage"] = (
            plan["planned_actions"][len(operation["completed_actions"])]
            if len(operation["completed_actions"]) < len(plan["planned_actions"])
            else "finalize"
        )
        operation["completed_at"] = timestamp_iso()
        if managed_upgraded:
            try:
                _restore_previous_managed_state(root, managed_snapshots)
            except Exception:
                operation["rollback_or_recovery_status"] = (
                    "managed_state_rollback_failed_codex_recovery_required"
                    if codex_migration_started
                    else "managed_state_rollback_failed_recovery_required"
                )
            else:
                operation["rollback_or_recovery_status"] = (
                    "managed_state_rolled_back_codex_recovery_required"
                    if codex_migration_started
                    else "managed_state_rolled_back"
                )
        elif codex_migration_started:
            operation["rollback_or_recovery_status"] = (
                "codex_migration_recovery_required"
            )
        else:
            operation["rollback_or_recovery_status"] = "no_product_state_committed"
        _write_operation(
            root,
            relative_operation,
            operation,
            expected_current_hash=operation_hash,
        )
        raise ProductUpgradeError(str(exc)) from exc
    return {
        **plan,
        "status": "upgraded",
        "applied": True,
        "writes_performed": True,
        "operation_receipt": relative_operation,
        "operation": operation,
        "next_recommended_action": "pcodex status --advisory --json",
    }
