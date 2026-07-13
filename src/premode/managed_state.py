from __future__ import annotations

"""Receipt-driven ownership primitives for setup, repair, and uninstall."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from typing import Any, Mapping
from uuid import uuid4

from . import __version__
from .timeutil import timestamp_iso


INSTALL_STATE_SCHEMA_VERSION = "pcodex.install-state.v1"
UNINSTALL_PLAN_SCHEMA_VERSION = "pcodex.uninstall-plan.v1"
UNINSTALL_OPERATION_SCHEMA_VERSION = "pcodex.uninstall-operation.v1"
OWNERSHIP_MARKER_SCHEMA_VERSION = "pcodex.managed-state-owner.v1"
OWNERSHIP_MARKER_RELATIVE_PATH = ".premode/managed-state-owner.json"
KNOWN_PRODUCT_OWNERS = frozenset({"pcodex", "premode", "pcodex_codex_plugin"})
FORBIDDEN_PRODUCT_OWNER_TERMS = ("observer", "qwen", "experiment")
FORBIDDEN_PRODUCT_STATE_PATH_TERMS = ("observer", "qwen", "openclaw", "experiment")
DESIGNATED_MANAGED_ROOT_NAMES = frozenset({
    ".codex", ".pcodex", ".premode", "pcodex", "pcodex beta", "pcodex state",
    "pcodex-state", "pcodex β", "premode", "premode-state",
})


class ManagedStateError(ValueError):
    pass


def validate_managed_root(root: Path | str) -> Path:
    raw = Path(root).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    if raw.is_symlink():
        raise ManagedStateError("managed root cannot be a symlink")
    current = Path(raw.anchor)
    for part in raw.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ManagedStateError("managed root cannot traverse a symlink")
    resolved = raw.resolve(strict=False)
    home = Path.home().resolve()
    broad_roots = {Path(resolved.anchor), home, Path("/tmp"), Path("/private/tmp")}
    if resolved in broad_roots or len(resolved.parts) < 4:
        raise ManagedStateError(f"unsafe broad managed root: {resolved}")
    has_repository_identity = (
        (resolved / ".git").exists()
        or (resolved / "premode.product.json").is_file()
        or ((resolved / "pyproject.toml").is_file() and (resolved / "src").is_dir())
    )
    if not has_repository_identity and resolved.name.casefold() not in DESIGNATED_MANAGED_ROOT_NAMES:
        raise ManagedStateError(f"managed root is not a repository or designated pCodex state root: {resolved}")
    return resolved


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_owner(owner: str) -> str:
    normalized = str(owner or "").strip()
    if normalized not in KNOWN_PRODUCT_OWNERS:
        raise ManagedStateError(f"unknown product owner: {normalized or '<empty>'}")
    if any(term in normalized.casefold() for term in FORBIDDEN_PRODUCT_OWNER_TERMS):
        raise ManagedStateError("observer, experiment, and Qwen state cannot be product-owned")
    return normalized


def _relative_owned_path(value: str | Path) -> str:
    text = str(value).replace("\\", "/")
    pure = PurePosixPath(text)
    if not text or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ManagedStateError(f"unsafe managed path: {value}")
    return pure.as_posix()


def _forbidden_product_state_path(relative: str) -> bool:
    lowered = relative.casefold()
    return any(term in lowered for term in FORBIDDEN_PRODUCT_STATE_PATH_TERMS)


def resolve_managed_path(root: Path | str, owned_path: str | Path, *, allow_missing: bool = True) -> Path:
    base = validate_managed_root(root)
    relative = _relative_owned_path(owned_path)
    candidate = base.joinpath(*PurePosixPath(relative).parts)
    current = base
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ManagedStateError(f"managed path traverses symlink: {relative}")
    resolved = candidate.resolve(strict=False)
    if resolved != base and base not in resolved.parents:
        raise ManagedStateError(f"managed path escapes root: {relative}")
    if not allow_missing and not candidate.exists():
        raise ManagedStateError(f"managed path not found: {relative}")
    return candidate


def _receipt_under_root(root: Path, receipt_path: Path | str) -> Path:
    raw = Path(receipt_path).expanduser()
    if not raw.is_absolute():
        raw = root / raw
    try:
        relative = raw.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ManagedStateError("install-state receipt must remain under the managed root") from exc
    return resolve_managed_path(root, relative)


def _ownership_marker_path(root: Path) -> Path:
    return resolve_managed_path(root, OWNERSHIP_MARKER_RELATIVE_PATH)


def _read_owner_marker(root: Path) -> dict[str, Any]:
    path = _ownership_marker_path(root)
    if not path.exists():
        raise ManagedStateError("managed-state ownership marker is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManagedStateError("managed-state ownership marker is corrupt") from exc
    required = {
        "schema_version", "product_name", "ownership_id", "managed_root_hash",
        "install_state_receipt",
    }
    if set(payload) != required or payload.get("schema_version") != OWNERSHIP_MARKER_SCHEMA_VERSION or payload.get("product_name") != "pCodex":
        raise ManagedStateError("managed-state ownership marker is invalid")
    if payload.get("managed_root_hash") != sha256_bytes(str(root).encode("utf-8")):
        raise ManagedStateError("managed-state ownership marker root mismatch")
    if not isinstance(payload.get("ownership_id"), str) or not payload["ownership_id"]:
        raise ManagedStateError("managed-state ownership marker id is invalid")
    payload["install_state_receipt"] = _relative_owned_path(payload.get("install_state_receipt"))
    return payload


def _atomic_write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    # os.replace is the logical commit point. Raising after it
                    # would make callers roll back targets while the committed
                    # receipt remains installed. Some filesystems also reject
                    # directory fsync even though replacement succeeded.
                    pass
            finally:
                os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _validate_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ManagedStateError("install-state item must be an object")
    required = {
        "owned_path", "owner", "preexisting_state", "original_hash", "installed_hash",
        "current_hash", "creation_or_modification", "sensitivity", "cleanup_policy",
        "repair_policy", "conflict_state", "user_modified", "external_registration",
    }
    missing = sorted(required - set(item))
    if missing:
        raise ManagedStateError("install-state item missing: " + ", ".join(missing))
    if set(item) != required:
        raise ManagedStateError("install-state item contains unsupported fields")
    validated = dict(item)
    validated["owned_path"] = _relative_owned_path(validated["owned_path"])
    validated["owner"] = str(validated["owner"] or "").strip()
    if not validated["owner"]:
        raise ManagedStateError("install-state owner must be a non-empty string")
    if validated["preexisting_state"] not in {"absent", "identical", "different", "unknown"}:
        raise ManagedStateError("unsupported preexisting_state")
    if validated["creation_or_modification"] not in {"created", "preexisting_identical", "modified", "registration"}:
        raise ManagedStateError("unsupported creation_or_modification")
    if validated["sensitivity"] not in {"public_safe", "private_metadata", "sensitive"}:
        raise ManagedStateError("unsupported install-state sensitivity")
    for field in ("original_hash", "installed_hash", "current_hash"):
        value = validated[field]
        if value is not None and (not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value)):
            raise ManagedStateError(f"{field} must be a lowercase SHA-256 digest or null")
    if validated["installed_hash"] is None:
        raise ManagedStateError("installed_hash cannot be null")
    for field in ("cleanup_policy", "repair_policy"):
        if not isinstance(validated[field], str) or not validated[field]:
            raise ManagedStateError(f"{field} must be a non-empty string")
    if validated["conflict_state"] is not None and not isinstance(validated["conflict_state"], str):
        raise ManagedStateError("conflict_state must be a string or null")
    if not isinstance(validated["user_modified"], bool):
        raise ManagedStateError("user_modified must be boolean")
    if validated["external_registration"] is not None and not isinstance(validated["external_registration"], dict):
        raise ManagedStateError("external_registration must be an object or null")
    return validated


def validate_install_state_receipt(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ManagedStateError("install-state receipt must be an object")
    schema_version = payload.get("schema_version")
    if schema_version != INSTALL_STATE_SCHEMA_VERSION:
        if isinstance(schema_version, str) and schema_version.startswith("pcodex.install-state."):
            raise ManagedStateError(f"unknown future install-state schema: {schema_version}")
        raise ManagedStateError(f"unsupported install-state schema: {schema_version}")
    required = {
        "schema_version", "product_version", "operation_id", "operation_type", "timestamp",
        "managed_root_hash", "ownership_id", "items",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ManagedStateError("install-state receipt missing: " + ", ".join(missing))
    if set(payload) != required:
        raise ManagedStateError("install-state receipt contains unsupported fields")
    if payload.get("operation_type") not in {"setup", "repair", "migration", "reinstall"}:
        raise ManagedStateError("unsupported install-state operation_type")
    if not isinstance(payload.get("items"), list):
        raise ManagedStateError("install-state items must be an array")
    if not isinstance(payload.get("ownership_id"), str) or not payload["ownership_id"]:
        raise ManagedStateError("install-state ownership_id is required")
    root_hash = payload.get("managed_root_hash")
    if not isinstance(root_hash, str) or len(root_hash) != 64 or any(character not in "0123456789abcdef" for character in root_hash):
        raise ManagedStateError("install-state managed_root_hash must be SHA-256")
    validated = dict(payload)
    validated["items"] = [_validate_item(item) for item in payload["items"]]
    return validated


def read_install_state_receipt(path: Path | str) -> dict[str, Any]:
    receipt_path = Path(path)
    if not receipt_path.exists():
        return {"status": "missing", "path": str(receipt_path), "payload": None, "error": None}
    try:
        raw = json.loads(receipt_path.read_text(encoding="utf-8"))
        payload = validate_install_state_receipt(raw)
    except json.JSONDecodeError as exc:
        return {"status": "corrupt", "path": str(receipt_path), "payload": None, "error": str(exc)}
    except (OSError, ManagedStateError) as exc:
        status = "unknown_schema" if "future install-state schema" in str(exc) else "invalid"
        return {"status": status, "path": str(receipt_path), "payload": None, "error": str(exc)}
    return {"status": "loaded", "path": str(receipt_path), "payload": payload, "error": None}


def install_managed_file(
    managed_root: Path | str,
    owned_path: str | Path,
    content: bytes,
    *,
    receipt_path: Path | str,
    owner: str = "pcodex",
    operation_type: str = "setup",
    operation_id: str | None = None,
    sensitivity: str = "private_metadata",
) -> dict[str, Any]:
    root = validate_managed_root(managed_root)
    relative = _relative_owned_path(owned_path)
    if _forbidden_product_state_path(relative):
        raise ManagedStateError("research, experiment, Qwen, and OpenClaw paths cannot be product-owned")
    owner = _validate_owner(owner)
    if operation_type not in {"setup", "repair", "migration", "reinstall"}:
        raise ManagedStateError("unsupported operation_type")
    if sensitivity not in {"public_safe", "private_metadata", "sensitive"}:
        raise ManagedStateError("unsupported install-state sensitivity")
    receipt_location = _receipt_under_root(root, receipt_path)
    marker_location = _ownership_marker_path(root)
    if receipt_location == marker_location:
        raise ManagedStateError("install-state receipt cannot replace the ownership marker")
    if resolve_managed_path(root, relative) in {receipt_location, marker_location}:
        raise ManagedStateError("managed target collides with lifecycle authority")
    prior = read_install_state_receipt(receipt_location)
    prior_items: list[dict[str, Any]] = []
    marker_created = False
    if prior["status"] != "missing":
        if prior["status"] != "loaded":
            raise ManagedStateError(f"cannot update {prior['status']} install-state receipt")
        expected_root_hash = sha256_bytes(str(root).encode("utf-8"))
        if prior["payload"]["managed_root_hash"] != expected_root_hash:
            raise ManagedStateError("install-state managed_root_hash mismatch")
        marker = _read_owner_marker(root)
        if marker["ownership_id"] != prior["payload"]["ownership_id"]:
            raise ManagedStateError("install-state ownership marker mismatch")
        if marker["install_state_receipt"] != receipt_location.relative_to(root).as_posix():
            raise ManagedStateError("install-state receipt is not the authoritative receipt")
        ownership_id = marker["ownership_id"]
        prior_items = list(prior["payload"]["items"])
    else:
        if marker_location.exists():
            raise ManagedStateError("partial managed installation has marker without receipt")
        ownership_id = str(uuid4())
    target = resolve_managed_path(root, relative)
    if target.exists() and not target.is_file():
        raise ManagedStateError(f"managed target is not a regular file: {relative}")
    installed_hash = sha256_bytes(content)
    existed = target.exists()
    original_hash = _hash_file(target) if existed else None
    prior_item = next((item for item in prior_items if item["owned_path"].casefold() == relative.casefold()), None)
    if prior_item is not None and existed and original_hash == prior_item["installed_hash"] == installed_hash:
        return {"status": "already_installed", "writes_performed": False, "receipt": prior["payload"]}
    safe_update = bool(
        prior_item is not None
        and existed
        and original_hash == prior_item["installed_hash"]
        and prior_item["creation_or_modification"] == "created"
        and original_hash != installed_hash
    )
    if existed and original_hash != installed_hash and not safe_update:
        return {
            "status": "conflict",
            "writes_performed": False,
            "conflict": "preexisting_different_file",
            "owned_path": relative,
            "original_hash": original_hash,
            "installed_hash": installed_hash,
        }

    created = not existed
    target_written = created or safe_update
    previous_content = target.read_bytes() if safe_update else None
    previous_mode = target.stat().st_mode & 0o777 if safe_update else None
    if target_written:
        # Re-check after creating parents so a concurrently introduced symlink
        # cannot redirect the atomic replacement outside the managed root.
        target.parent.mkdir(parents=True, exist_ok=True)
        target = resolve_managed_path(root, relative)
        _atomic_write(target, content)
    current_hash = _hash_file(target)
    item = {
        "owned_path": relative,
        "owner": owner,
        "preexisting_state": prior_item["preexisting_state"] if safe_update else "absent" if created else "identical",
        "original_hash": prior_item["original_hash"] if safe_update else original_hash,
        "installed_hash": installed_hash,
        "current_hash": current_hash,
        "creation_or_modification": "created" if created or safe_update else "preexisting_identical",
        "sensitivity": sensitivity,
        "cleanup_policy": "remove_if_owned_and_unmodified" if created else "preserve_preexisting",
        "repair_policy": "replace_only_if_owned_and_unmodified",
        "conflict_state": None,
        "user_modified": False,
        "external_registration": None,
    }
    merged_items = [item for item in prior_items if item["owned_path"].casefold() != relative.casefold()]
    merged_items.append(item)
    merged_items.sort(key=lambda value: value["owned_path"].casefold())
    payload = {
        "schema_version": INSTALL_STATE_SCHEMA_VERSION,
        "product_version": __version__,
        "operation_id": operation_id or str(uuid4()),
        "operation_type": operation_type,
        "timestamp": timestamp_iso(),
        "managed_root_hash": sha256_bytes(str(root).encode("utf-8")),
        "ownership_id": ownership_id,
        "items": merged_items,
    }
    validated = validate_install_state_receipt(payload)
    try:
        if prior["status"] == "missing":
            marker_payload = {
                "schema_version": OWNERSHIP_MARKER_SCHEMA_VERSION,
                "product_name": "pCodex",
                "ownership_id": ownership_id,
                "managed_root_hash": sha256_bytes(str(root).encode("utf-8")),
                "install_state_receipt": receipt_location.relative_to(root).as_posix(),
            }
            _atomic_write_json(marker_location, marker_payload)
            marker_created = True
        _atomic_write_json(receipt_location, validated)
    except Exception:
        if created and target.exists() and _hash_file(target) == installed_hash:
            target.unlink()
        elif safe_update and previous_content is not None and previous_mode is not None:
            _atomic_write(target, previous_content, mode=previous_mode)
        if marker_created and marker_location.exists():
            marker_location.unlink()
        raise
    return {
        "status": "installed",
        "writes_performed": True,
        "target_write_performed": target_written,
        "receipt": validated,
    }


def _empty_plan(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": UNINSTALL_PLAN_SCHEMA_VERSION,
        "product_version": __version__,
        "managed_root_hash": sha256_bytes(str(root).encode("utf-8")),
        "receipt_status": receipt["status"],
        "writes_performed": False,
        "will_remove": [],
        "will_restore": [],
        "will_preserve": [],
        "conflict": [],
        "not_found": [],
        "unknown_owner": [],
        "requires_manual_action": [],
    }


def plan_uninstall(managed_root: Path | str, receipt_path: Path | str) -> dict[str, Any]:
    root = validate_managed_root(managed_root)
    receipt_location = _receipt_under_root(root, receipt_path)
    receipt = read_install_state_receipt(receipt_location)
    plan = _empty_plan(root, receipt)
    if receipt["status"] != "loaded":
        plan["requires_manual_action"].append({
            "path": str(receipt_location),
            "reason": f"install_state_{receipt['status']}",
            "error": receipt.get("error"),
        })
        return plan
    payload = receipt["payload"]
    if payload["managed_root_hash"] != plan["managed_root_hash"]:
        plan["conflict"].append({"path": str(receipt_location), "reason": "managed_root_hash_mismatch"})
        plan["requires_manual_action"].append({"path": str(receipt_location), "reason": "managed_root_hash_mismatch"})
        return plan
    try:
        marker = _read_owner_marker(root)
    except ManagedStateError as exc:
        plan["conflict"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": str(exc)})
        plan["requires_manual_action"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": "ownership_marker_invalid"})
        return plan
    if marker["ownership_id"] != payload["ownership_id"]:
        plan["conflict"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": "ownership_id_mismatch"})
        plan["requires_manual_action"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": "ownership_id_mismatch"})
        return plan
    if marker["install_state_receipt"] != receipt_location.relative_to(root).as_posix():
        plan["conflict"].append({"path": str(receipt_location), "reason": "receipt_path_mismatch"})
        plan["requires_manual_action"].append({"path": str(receipt_location), "reason": "receipt_path_mismatch"})
        return plan
    for item in payload["items"]:
        relative = item["owned_path"]
        if item["owner"] not in KNOWN_PRODUCT_OWNERS:
            plan["unknown_owner"].append({"path": relative, "owner": item["owner"]})
            plan["conflict"].append({"path": relative, "reason": "unknown_owner"})
            plan["requires_manual_action"].append({"path": relative, "reason": "unknown_owner"})
            continue
        if item.get("external_registration") is not None:
            plan["will_preserve"].append({"path": relative, "reason": "external_registration_deferred"})
            plan["conflict"].append({"path": relative, "reason": "external_registration_deferred"})
            plan["requires_manual_action"].append({"path": relative, "reason": "external_registration_deferred"})
            continue
        if _forbidden_product_state_path(relative):
            plan["will_preserve"].append({"path": relative, "reason": "non_product_research_or_experimental_state"})
            plan["conflict"].append({"path": relative, "reason": "forbidden_product_state_path"})
            plan["requires_manual_action"].append({"path": relative, "reason": "forbidden_product_state_path"})
            continue
        try:
            target = resolve_managed_path(root, relative)
        except ManagedStateError as exc:
            plan["conflict"].append({"path": relative, "reason": str(exc)})
            plan["requires_manual_action"].append({"path": relative, "reason": "unsafe_path"})
            continue
        if not target.exists():
            plan["not_found"].append({"path": relative, "reason": "already_missing"})
            continue
        if not target.is_file():
            plan["conflict"].append({"path": relative, "reason": "not_regular_file"})
            plan["requires_manual_action"].append({"path": relative, "reason": "not_regular_file"})
            continue
        current_hash = _hash_file(target)
        if current_hash != item["installed_hash"]:
            plan["will_preserve"].append({"path": relative, "reason": "user_modified"})
            plan["conflict"].append({"path": relative, "reason": "installed_hash_mismatch"})
            plan["requires_manual_action"].append({"path": relative, "reason": "user_modified"})
            continue
        if item["creation_or_modification"] == "created" and item["cleanup_policy"] == "remove_if_owned_and_unmodified":
            plan["will_remove"].append({"path": relative, "reason": "proven_owned_unmodified", "installed_hash": item["installed_hash"]})
        else:
            plan["will_preserve"].append({"path": relative, "reason": "preexisting_state"})
    return plan


def apply_uninstall(
    managed_root: Path | str,
    receipt_path: Path | str,
    *,
    operation_receipt_path: Path | str | None = None,
) -> dict[str, Any]:
    root = validate_managed_root(managed_root)
    plan = plan_uninstall(root, receipt_path)
    authority_blockers = {
        "managed_root_hash_mismatch", "ownership_marker_invalid", "ownership_id_mismatch",
        "receipt_path_mismatch", "unknown_owner", "forbidden_product_state_path",
        "external_registration_deferred", "unsafe_path", "not_regular_file",
    }
    if plan["receipt_status"] != "loaded" or any(item.get("reason") in authority_blockers for item in plan["requires_manual_action"]):
        return {
            **plan,
            "writes_performed": False,
            "applied": False,
            "removed": [],
            "operation_receipt": None,
            "status": "blocked_unknown_state",
        }
    if not plan["will_remove"]:
        return {
            **plan,
            "writes_performed": False,
            "applied": False,
            "removed": [],
            "operation_receipt": None,
            "status": "blocked_conflict" if plan["conflict"] else "no_changes",
        }
    output_raw = Path(operation_receipt_path).expanduser() if operation_receipt_path is not None else root / ".premode" / "uninstall-operation.json"
    output_absolute = output_raw if output_raw.is_absolute() else root / output_raw
    try:
        relative_output = output_absolute.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ManagedStateError("operation receipt must remain under the managed root") from exc
    output = resolve_managed_path(root, relative_output)
    protected = {
        _receipt_under_root(root, receipt_path),
        _ownership_marker_path(root),
        *(resolve_managed_path(root, action["path"]) for action in plan["will_remove"]),
    }
    if output in protected:
        raise ManagedStateError("operation receipt collides with managed lifecycle state")
    if output.exists():
        marker = _read_owner_marker(root)
        try:
            existing_operation = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManagedStateError("operation receipt would overwrite unrelated state") from exc
        expected_operation_fields = {
            "schema_version", "product_version", "operation_id", "operation_type", "timestamp",
            "managed_root_hash", "ownership_id", "install_state_receipt", "operation_receipt",
            "removed", "preserved", "conflicts", "not_found", "unknown_owner",
            "requires_manual_action", "status",
        }
        if (
            not isinstance(existing_operation, dict)
            or set(existing_operation) != expected_operation_fields
            or existing_operation.get("schema_version") != UNINSTALL_OPERATION_SCHEMA_VERSION
            or existing_operation.get("operation_type") != "uninstall"
            or existing_operation.get("managed_root_hash") != plan["managed_root_hash"]
            or existing_operation.get("ownership_id") != marker["ownership_id"]
            or existing_operation.get("install_state_receipt") != marker["install_state_receipt"]
            or existing_operation.get("operation_receipt") != relative_output
        ):
            raise ManagedStateError("operation receipt would overwrite unrelated state")
    marker = _read_owner_marker(root)
    removed: list[str] = []
    rollback: list[dict[str, Any]] = []
    confirmed_actions: list[dict[str, Any]] = []
    premode_directory = resolve_managed_path(root, ".premode")
    premode_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    premode_directory = resolve_managed_path(root, ".premode")
    if not premode_directory.is_dir():
        raise ManagedStateError("managed lifecycle directory is not a regular directory")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    premode_fd = os.open(premode_directory, directory_flags)
    quarantine_name = f"uninstall-quarantine-{uuid4()}"
    os.mkdir(quarantine_name, 0o700, dir_fd=premode_fd)
    quarantine_fd = os.open(quarantine_name, directory_flags, dir_fd=premode_fd)

    def entry_exists(name: str, directory_fd: int) -> bool:
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def restore_records() -> None:
        for record in reversed(rollback):
            if entry_exists(record["target_name"], record["target_parent_fd"]):
                continue
            if record["quarantined"] and entry_exists(record["quarantine_name"], quarantine_fd):
                os.rename(
                    record["quarantine_name"], record["target_name"],
                    src_dir_fd=quarantine_fd, dst_dir_fd=record["target_parent_fd"],
                )
                record["quarantined"] = False
            elif record.get("content") is not None:
                _atomic_write(record["target"], record["content"], mode=record["mode"])

    def close_quarantine() -> None:
        for record in rollback:
            parent_fd = record.get("target_parent_fd")
            if isinstance(parent_fd, int) and parent_fd >= 0:
                os.close(parent_fd)
                record["target_parent_fd"] = -1
        os.close(quarantine_fd)
        try:
            os.rmdir(quarantine_name, dir_fd=premode_fd)
        except OSError:
            pass
        os.close(premode_fd)

    try:
        for action in list(plan["will_remove"]):
            relative = action["path"]
            target = resolve_managed_path(root, relative)
            if not target.exists():
                plan["not_found"].append({"path": relative, "reason": "missing_at_apply"})
                continue
            target_parent_fd = os.open(target.parent, directory_flags)
            quarantine_entry = f"{uuid4()}.pending"
            os.rename(
                target.name, quarantine_entry,
                src_dir_fd=target_parent_fd, dst_dir_fd=quarantine_fd,
            )
            record: dict[str, Any] = {
                "target": target,
                "target_name": target.name,
                "target_parent_fd": target_parent_fd,
                "quarantine_name": quarantine_entry,
                "quarantined": True,
                "content": None,
                "mode": 0o600,
            }
            rollback.append(record)
            quarantined_file_fd = os.open(
                quarantine_entry,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=quarantine_fd,
            )
            try:
                before = os.fstat(quarantined_file_fd)
                with os.fdopen(os.dup(quarantined_file_fd), "rb") as handle:
                    content = handle.read()
                after = os.fstat(quarantined_file_fd)
            finally:
                os.close(quarantined_file_fd)
            stable_identity = (
                before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
            ) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            record["content"] = content
            record["mode"] = before.st_mode & 0o777
            if not stable_identity or not stat.S_ISREG(before.st_mode) or sha256_bytes(content) != action["installed_hash"]:
                if entry_exists(target.name, target_parent_fd):
                    raise ManagedStateError("target changed while restoring a quarantined mismatch")
                os.rename(
                    quarantine_entry, target.name,
                    src_dir_fd=quarantine_fd, dst_dir_fd=target_parent_fd,
                )
                record["quarantined"] = False
                rollback.pop()
                os.close(target_parent_fd)
                plan["will_preserve"].append({"path": relative, "reason": "user_modified_at_apply"})
                plan["conflict"].append({"path": relative, "reason": "installed_hash_mismatch_at_apply"})
                plan["requires_manual_action"].append({"path": relative, "reason": "user_modified_at_apply"})
                continue
            removed.append(relative)
            confirmed_actions.append(action)
    except Exception:
        restore_records()
        close_quarantine()
        raise
    plan["will_remove"] = confirmed_actions
    if not removed:
        close_quarantine()
        return {
            **plan,
            "writes_performed": False,
            "applied": False,
            "removed": [],
            "operation_receipt": None,
            "status": "blocked_conflict" if plan["conflict"] else "no_changes",
        }
    status = "applied_with_manual_action" if plan["requires_manual_action"] else "applied_with_conflicts" if plan["conflict"] else "applied"
    operation = {
        "schema_version": UNINSTALL_OPERATION_SCHEMA_VERSION,
        "product_version": __version__,
        "operation_id": str(uuid4()),
        "operation_type": "uninstall",
        "timestamp": timestamp_iso(),
        "managed_root_hash": plan["managed_root_hash"],
        "ownership_id": marker["ownership_id"],
        "install_state_receipt": marker["install_state_receipt"],
        "operation_receipt": relative_output,
        "removed": removed,
        "preserved": plan["will_preserve"],
        "conflicts": plan["conflict"],
        "not_found": plan["not_found"],
        "unknown_owner": plan["unknown_owner"],
        "requires_manual_action": plan["requires_manual_action"],
        "status": status,
    }
    try:
        # Completion is recorded only after all quarantined bytes are gone. If
        # receipt writing fails, the in-memory copies restore the owned paths.
        for record in rollback:
            os.unlink(record["quarantine_name"], dir_fd=quarantine_fd)
            record["quarantined"] = False
        _atomic_write_json(output, operation)
    except Exception:
        restore_records()
        close_quarantine()
        raise
    close_quarantine()
    return {
        **plan,
        "writes_performed": True,
        "applied": True,
        "removed": removed,
        "operation_receipt": str(output),
        "operation": operation,
        "status": status,
    }
