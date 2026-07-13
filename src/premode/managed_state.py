from __future__ import annotations

"""Receipt-driven ownership primitives for setup, repair, and uninstall."""

import hashlib
import ctypes
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import sys
from typing import Any, Mapping
from uuid import uuid4

from . import __version__
from .timeutil import timestamp_iso


INSTALL_STATE_SCHEMA_VERSION = "pcodex.install-state.v1"
REPAIR_PLAN_SCHEMA_VERSION = "pcodex.repair-plan.v1"
REPAIR_OPERATION_SCHEMA_VERSION = "pcodex.repair-operation.v1"
REINSTALL_VALIDATION_SCHEMA_VERSION = "pcodex.reinstall-validation.v1"
UNINSTALL_PLAN_SCHEMA_VERSION = "pcodex.uninstall-plan.v1"
UNINSTALL_OPERATION_SCHEMA_VERSION = "pcodex.uninstall-operation.v2"
LEGACY_UNINSTALL_OPERATION_SCHEMA_VERSION = "pcodex.uninstall-operation.v1"
OWNERSHIP_MARKER_SCHEMA_VERSION = "pcodex.managed-state-owner.v1"
OWNERSHIP_MARKER_RELATIVE_PATH = ".premode/managed-state-owner.json"
DEFAULT_INSTALL_STATE_RELATIVE_PATH = ".premode/install-state.json"
DEFAULT_REPAIR_OPERATION_RELATIVE_PATH = ".premode/repair-operation.json"
DEFAULT_REINSTALL_VALIDATION_RELATIVE_PATH = ".premode/reinstall-validation.json"
DEFAULT_UNINSTALL_OPERATION_RELATIVE_PATH = ".premode/uninstall-operation.json"
PRODUCT_INSTALL_MARKER_RELATIVE_PATH = ".premode/pcodex-install.json"
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


def product_install_marker_content() -> bytes:
    """Return the only generated lifecycle item repairable from product authority."""
    return (
        json.dumps(
            {
                "product_name": "pCodex",
                "product_version": __version__,
                "schema_version": "pcodex.managed-install.v1",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def product_expected_content() -> dict[str, bytes]:
    return {PRODUCT_INSTALL_MARKER_RELATIVE_PATH: product_install_marker_content()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_path_bytes(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


def _open_managed_parent_fd(root: Path, owned_path: str, *, create: bool = False) -> tuple[int, str]:
    relative = _relative_owned_path(owned_path)
    parts = PurePosixPath(relative).parts
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(root, directory_flags)
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=current_fd)
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
    except Exception:
        os.close(current_fd)
        raise
    return current_fd, parts[-1]


def _atomic_write_managed(
    root: Path,
    owned_path: str,
    content: bytes,
    *,
    mode: int = 0o600,
    require_absent: bool = False,
    expected_current_hash: str | None = None,
) -> Path:
    """Stage and commit through no-follow directory descriptors under root."""
    if require_absent and expected_current_hash is not None:
        raise ManagedStateError("managed write cannot require absence and existing content")
    relative = _relative_owned_path(owned_path)
    current_fd, target_name = _open_managed_parent_fd(root, relative, create=True)
    parts = PurePosixPath(relative).parts
    temporary_name = f".{parts[-1]}.{uuid4()}.tmp"
    temporary_created = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
            dir_fd=current_fd,
        )
        temporary_created = True
        try:
            with os.fdopen(os.dup(descriptor), "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)
        if require_absent:
            # linkat is the portable no-replace commit primitive available to
            # supported Python; an introduced leaf makes the operation fail.
            os.link(
                temporary_name,
                target_name,
                src_dir_fd=current_fd,
                dst_dir_fd=current_fd,
                follow_symlinks=False,
            )
            os.unlink(temporary_name, dir_fd=current_fd)
        else:
            if expected_current_hash is not None and sys.platform == "darwin":
                libc = ctypes.CDLL(None, use_errno=True)
                renameatx_np = libc.renameatx_np
                renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
                renameatx_np.restype = ctypes.c_int
                if renameatx_np(
                    current_fd,
                    os.fsencode(temporary_name),
                    current_fd,
                    os.fsencode(target_name),
                    0x00000002,  # RENAME_SWAP
                ) != 0:
                    error = ctypes.get_errno()
                    raise OSError(error, os.strerror(error), target_name)
                try:
                    displaced_descriptor = os.open(
                        temporary_name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=current_fd,
                    )
                    try:
                        displaced_stat = os.fstat(displaced_descriptor)
                        with os.fdopen(os.dup(displaced_descriptor), "rb") as handle:
                            displaced_content = handle.read()
                    finally:
                        os.close(displaced_descriptor)
                    if (
                        not stat.S_ISREG(displaced_stat.st_mode)
                        or displaced_stat.st_nlink != 1
                        or sha256_bytes(displaced_content) != expected_current_hash
                    ):
                        raise ManagedStateError("managed state changed before atomic commit")
                    committed_descriptor = os.open(
                        target_name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=current_fd,
                    )
                    try:
                        committed_stat = os.fstat(committed_descriptor)
                        with os.fdopen(os.dup(committed_descriptor), "rb") as handle:
                            committed_content = handle.read()
                    finally:
                        os.close(committed_descriptor)
                    if (
                        not stat.S_ISREG(committed_stat.st_mode)
                        or committed_stat.st_nlink != 1
                        or sha256_bytes(committed_content) != sha256_bytes(content)
                    ):
                        raise ManagedStateError("managed state changed after atomic commit")
                    os.unlink(temporary_name, dir_fd=current_fd)
                    temporary_created = False
                except Exception as original_error:
                    # The displaced entry may itself be an alternate object.
                    # Swap it back only while the destination is still our
                    # exact staged regular file; otherwise retain the displaced
                    # entry under the private temporary name for recovery.
                    target_is_staged = False
                    try:
                        target_descriptor = os.open(
                            target_name,
                            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=current_fd,
                        )
                        try:
                            target_stat = os.fstat(target_descriptor)
                            with os.fdopen(os.dup(target_descriptor), "rb") as handle:
                                target_content = handle.read()
                        finally:
                            os.close(target_descriptor)
                        target_is_staged = bool(
                            stat.S_ISREG(target_stat.st_mode)
                            and target_stat.st_nlink == 1
                            and sha256_bytes(target_content) == sha256_bytes(content)
                        )
                    except OSError:
                        target_is_staged = False
                    if target_is_staged:
                        if renameatx_np(
                            current_fd,
                            os.fsencode(temporary_name),
                            current_fd,
                            os.fsencode(target_name),
                            0x00000002,
                        ) != 0:
                            error = ctypes.get_errno()
                            temporary_created = False
                            raise ManagedStateError(
                                f"managed state changed and atomic swap-back failed; displaced entry retained: {os.strerror(error)}"
                            ) from original_error
                    else:
                        temporary_created = False
                    raise
            else:
                if expected_current_hash is not None:
                    current_descriptor = os.open(
                        target_name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=current_fd,
                    )
                    try:
                        before = os.fstat(current_descriptor)
                        with os.fdopen(os.dup(current_descriptor), "rb") as handle:
                            current_content = handle.read()
                        after = os.fstat(current_descriptor)
                        current_entry = os.stat(target_name, dir_fd=current_fd, follow_symlinks=False)
                    finally:
                        os.close(current_descriptor)
                    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or before.st_nlink != 1
                        or identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                        or identity != (current_entry.st_dev, current_entry.st_ino, current_entry.st_size, current_entry.st_mtime_ns)
                        or sha256_bytes(current_content) != expected_current_hash
                    ):
                        raise ManagedStateError("managed state changed before atomic commit")
                os.replace(temporary_name, target_name, src_dir_fd=current_fd, dst_dir_fd=current_fd)
                temporary_created = False
        if require_absent:
            temporary_created = False
        try:
            os.fsync(current_fd)
        except OSError:
            pass
    finally:
        if temporary_created:
            try:
                os.unlink(temporary_name, dir_fd=current_fd)
            except FileNotFoundError:
                pass
        os.close(current_fd)
    return resolve_managed_path(root, relative)


def _atomic_write_managed_json(
    root: Path,
    owned_path: str,
    payload: Mapping[str, Any],
    *,
    require_absent: bool = False,
    expected_current_hash: str | None = None,
) -> Path:
    return _atomic_write_managed(
        root,
        owned_path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        require_absent=require_absent,
        expected_current_hash=expected_current_hash,
    )


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
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root = validate_managed_root(root)
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
    prior_receipt_hash = _authority_receipt_hash(receipt_location) if prior["status"] == "loaded" else None
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
    if target.exists() or target.is_symlink():
        target_stat = target.lstat()
        if not stat.S_ISREG(target_stat.st_mode) or target_stat.st_nlink != 1:
            raise ManagedStateError(f"managed target is not an exclusively owned regular file: {relative}")
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
        if prior["status"] == "loaded":
            if _authority_receipt_hash(receipt_location) != prior_receipt_hash:
                raise ManagedStateError("install-state authority changed before managed update")
            current_marker = _read_owner_marker(root)
            if current_marker["ownership_id"] != ownership_id:
                raise ManagedStateError("ownership marker changed before managed update")
        target = _atomic_write_managed(
            root,
            relative,
            content,
            require_absent=created,
            expected_current_hash=original_hash if safe_update else None,
        )
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
            _atomic_write_managed_json(
                root,
                OWNERSHIP_MARKER_RELATIVE_PATH,
                marker_payload,
                require_absent=True,
            )
            marker_created = True
        _atomic_write_managed_json(
            root,
            receipt_location.relative_to(root).as_posix(),
            validated,
            require_absent=prior["status"] == "missing",
            expected_current_hash=prior_receipt_hash,
        )
    except Exception:
        if created and target.exists() and _hash_file(target) == installed_hash:
            parent_fd, target_name = _open_managed_parent_fd(root, relative, create=False)
            try:
                os.unlink(target_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        elif safe_update and previous_content is not None and previous_mode is not None:
            _atomic_write_managed(
                root,
                relative,
                previous_content,
                mode=previous_mode,
                expected_current_hash=installed_hash,
            )
        if marker_created and marker_location.exists():
            marker_parent_fd, marker_name = _open_managed_parent_fd(root, OWNERSHIP_MARKER_RELATIVE_PATH, create=False)
            try:
                os.unlink(marker_name, dir_fd=marker_parent_fd)
                os.fsync(marker_parent_fd)
            finally:
                os.close(marker_parent_fd)
        raise
    return {
        "status": "installed",
        "writes_performed": True,
        "target_write_performed": target_written,
        "receipt": validated,
    }


def _authority_receipt_hash(receipt_location: Path) -> str:
    return _hash_path_bytes(receipt_location)


def _read_matching_uninstall_tombstone(
    root: Path,
    receipt_location: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Read a v2 uninstall receipt only when it still binds the current authority."""
    output = resolve_managed_path(root, DEFAULT_UNINSTALL_OPERATION_RELATIVE_PATH)
    if not output.exists() or not output.is_file():
        return None
    try:
        operation = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return validate_uninstall_operation_receipt(
            operation,
            payload=payload,
            root=root,
            receipt_location=receipt_location,
            operation_relative_path=DEFAULT_UNINSTALL_OPERATION_RELATIVE_PATH,
        )
    except ManagedStateError:
        return None


def validate_uninstall_operation_receipt(
    operation: Any,
    *,
    payload: Mapping[str, Any],
    root: Path,
    receipt_location: Path,
    operation_relative_path: str,
) -> dict[str, Any]:
    required = {
        "schema_version", "product_version", "operation_id", "operation_type",
        "started_at", "completed_at", "managed_root_hash", "ownership_id",
        "install_state_receipt", "operation_receipt", "authority_receipt_hash",
        "planned_actions", "completed_actions", "preserved_items", "conflicts",
        "not_found", "unknown_owner", "unsupported_registration", "manual_actions",
        "result", "status", "failure_stage", "rollback_or_recovery_status",
    }
    if not isinstance(operation, dict) or set(operation) != required:
        raise ManagedStateError("uninstall operation receipt is malformed")
    if operation["schema_version"] != UNINSTALL_OPERATION_SCHEMA_VERSION or operation["operation_type"] != "uninstall_apply":
        raise ManagedStateError("uninstall operation receipt schema is unsupported")
    if operation["result"] not in {"applied", "applied_with_conflicts", "applied_with_manual_action"} or operation["status"] != operation["result"]:
        raise ManagedStateError("uninstall operation receipt is not successful")
    if operation["failure_stage"] is not None:
        raise ManagedStateError("failed uninstall receipt cannot be a tombstone")
    if operation["managed_root_hash"] != payload.get("managed_root_hash") or operation["managed_root_hash"] != sha256_bytes(str(root).encode("utf-8")):
        raise ManagedStateError("uninstall operation root mismatch")
    if operation["ownership_id"] != payload.get("ownership_id"):
        raise ManagedStateError("uninstall operation ownership mismatch")
    if operation["install_state_receipt"] != receipt_location.relative_to(root).as_posix():
        raise ManagedStateError("uninstall operation authority path mismatch")
    if operation["operation_receipt"] != operation_relative_path:
        raise ManagedStateError("uninstall operation path mismatch")
    if operation["authority_receipt_hash"] != _authority_receipt_hash(receipt_location):
        raise ManagedStateError("uninstall operation authority hash mismatch")
    planned = operation["planned_actions"]
    completed = operation["completed_actions"]
    if (
        not isinstance(planned, list)
        or not isinstance(completed, list)
        or not completed
        or any(not isinstance(value, str) for value in planned + completed)
        or len(planned) != len(set(planned))
        or len(completed) != len(set(completed))
        or not set(completed).issubset(set(planned))
    ):
        raise ManagedStateError("uninstall operation action set is invalid")
    receipt_items = {item["owned_path"]: item for item in payload.get("items", [])}
    for relative in completed:
        normalized = _relative_owned_path(relative)
        item = receipt_items.get(normalized)
        if (
            item is None
            or item.get("owner") not in KNOWN_PRODUCT_OWNERS
            or item.get("creation_or_modification") != "created"
            or item.get("cleanup_policy") != "remove_if_owned_and_unmodified"
        ):
            raise ManagedStateError("uninstall operation completed action lacks receipt authority")
    for key in ("preserved_items", "conflicts", "not_found", "unknown_owner", "unsupported_registration", "manual_actions"):
        if not isinstance(operation[key], list):
            raise ManagedStateError("uninstall operation list field is invalid")
    for key in ("product_version", "operation_id", "started_at", "completed_at", "rollback_or_recovery_status"):
        if not isinstance(operation[key], str) or not operation[key]:
            raise ManagedStateError("uninstall operation scalar field is invalid")
    return dict(operation)


def _matching_interrupted_uninstall(root: Path, receipt_location: Path, payload: Mapping[str, Any]) -> list[str]:
    premode = resolve_managed_path(root, ".premode")
    if not premode.exists() or not premode.is_dir():
        return []
    matches: list[str] = []
    def valid_action(action: Any) -> bool:
        if not isinstance(action, dict) or set(action) != {"target", "quarantine", "phase"}:
            return False
        try:
            target = _relative_owned_path(action.get("target"))
        except ManagedStateError:
            return False
        quarantine = action.get("quarantine")
        return bool(
            target == action.get("target")
            and isinstance(quarantine, str)
            and quarantine.endswith(".pending")
            and "/" not in quarantine
            and action.get("phase") in {"planned", "quarantined", "restored", "removed"}
        )
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        entries = list(os.scandir(premode))
    except OSError:
        return []
    for entry in entries:
        if not entry.name.startswith("uninstall-quarantine-") or not entry.is_dir(follow_symlinks=False):
            continue
        parent_fd: int | None = None
        quarantine_fd: int | None = None
        descriptor: int | None = None
        try:
            parent_fd = os.open(premode, directory_flags)
            quarantine_fd = os.open(entry.name, directory_flags, dir_fd=parent_fd)
        except OSError:
            if quarantine_fd is not None:
                os.close(quarantine_fd)
            if parent_fd is not None:
                os.close(parent_fd)
            continue
        try:
            try:
                descriptor = os.open("operation.json", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=quarantine_fd)
                with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as handle:
                    manifest = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            required = {"schema_version", "managed_root_hash", "ownership_id", "install_state_receipt", "authority_receipt_hash", "actions"}
            if (
                isinstance(manifest, dict)
                and set(manifest) == required
                and manifest.get("schema_version") == "pcodex.uninstall-staging.v1"
                and manifest.get("managed_root_hash") == payload.get("managed_root_hash")
                and manifest.get("ownership_id") == payload.get("ownership_id")
                and manifest.get("install_state_receipt") == receipt_location.relative_to(root).as_posix()
                and manifest.get("authority_receipt_hash") == _authority_receipt_hash(receipt_location)
                and isinstance(manifest.get("actions"), list)
                and all(valid_action(action) for action in manifest["actions"])
            ):
                matches.append(entry.name)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(quarantine_fd)
            if parent_fd is not None:
                os.close(parent_fd)
    return sorted(matches)


def _repair_empty_plan(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": REPAIR_PLAN_SCHEMA_VERSION,
        "product_version": __version__,
        "managed_root_hash": sha256_bytes(str(root).encode("utf-8")),
        "receipt_status": receipt["status"],
        "authority_receipt_hash": None,
        "ownership_id": None,
        "writes_performed": False,
        "will_create": [],
        "will_restore": [],
        "will_replace_owned": [],
        "will_preserve_modified": [],
        "will_preserve_unrelated": [],
        "conflict": [],
        "not_found": [],
        "unknown_owner": [],
        "unsupported_registration": [],
        "requires_manual_action": [],
        "already_healthy": [],
        "intentionally_uninstalled": [],
    }


def plan_repair(
    managed_root: Path | str,
    receipt_path: Path | str,
    *,
    expected_content: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Pure-read repair classification derived from bound receipts and hashes."""
    root = validate_managed_root(managed_root)
    receipt_location = _receipt_under_root(root, receipt_path)
    receipt = read_install_state_receipt(receipt_location)
    plan = _repair_empty_plan(root, receipt)
    if receipt["status"] != "loaded":
        plan["requires_manual_action"].append({
            "path": receipt_location.relative_to(root).as_posix(),
            "reason": f"install_state_{receipt['status']}",
            "error": receipt.get("error"),
        })
        return plan
    payload = receipt["payload"]
    plan["authority_receipt_hash"] = _authority_receipt_hash(receipt_location)
    plan["ownership_id"] = payload["ownership_id"]
    if payload["managed_root_hash"] != plan["managed_root_hash"]:
        plan["conflict"].append({"path": DEFAULT_INSTALL_STATE_RELATIVE_PATH, "reason": "managed_root_hash_mismatch"})
        plan["requires_manual_action"].append({"path": DEFAULT_INSTALL_STATE_RELATIVE_PATH, "reason": "managed_root_hash_mismatch"})
        return plan
    expected = {
        _relative_owned_path(path): bytes(content)
        for path, content in (expected_content or {}).items()
    }
    marker: dict[str, Any] | None = None
    marker_error: ManagedStateError | None = None
    try:
        marker = _read_owner_marker(root)
    except ManagedStateError as exc:
        marker_error = exc
    if marker is not None:
        if marker["ownership_id"] != payload["ownership_id"]:
            plan["conflict"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": "ownership_id_mismatch"})
            plan["requires_manual_action"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": "ownership_id_mismatch"})
            return plan
        if marker["install_state_receipt"] != receipt_location.relative_to(root).as_posix():
            plan["conflict"].append({"path": DEFAULT_INSTALL_STATE_RELATIVE_PATH, "reason": "receipt_path_mismatch"})
            plan["requires_manual_action"].append({"path": DEFAULT_INSTALL_STATE_RELATIVE_PATH, "reason": "receipt_path_mismatch"})
            return plan
    else:
        # A missing marker is repairable only at the canonical receipt path and
        # only when an extant, generated, known-content item proves the same
        # receipt authority. A damaged/corrupt marker always fails closed.
        canonical_receipt = receipt_location.relative_to(root).as_posix() == DEFAULT_INSTALL_STATE_RELATIVE_PATH
        proof_items = []
        if marker_error is not None and "is missing" in str(marker_error) and canonical_receipt:
            for item in payload["items"]:
                content = expected.get(item["owned_path"])
                try:
                    target = resolve_managed_path(root, item["owned_path"])
                    target_stat = target.lstat()
                except (ManagedStateError, FileNotFoundError, OSError):
                    continue
                if (
                    content is not None
                    and item["owner"] in KNOWN_PRODUCT_OWNERS
                    and item["creation_or_modification"] == "created"
                    and stat.S_ISREG(target_stat.st_mode)
                    and target_stat.st_nlink == 1
                    and sha256_bytes(content) == item["installed_hash"]
                    and _hash_file(target) == item["installed_hash"]
                    and _has_matching_reinstall_validation(root, receipt_location, payload, item["owned_path"])
                ):
                    proof_items.append(item["owned_path"])
        if proof_items:
            plan["will_create"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": "receipt_and_owned_item_prove_authority"})
        else:
            plan["conflict"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": str(marker_error)})
            plan["requires_manual_action"].append({"path": OWNERSHIP_MARKER_RELATIVE_PATH, "reason": "ownership_marker_invalid"})
            return plan

    tombstone = _read_matching_uninstall_tombstone(root, receipt_location, payload)
    intentionally_removed = set(tombstone.get("completed_actions") or []) if tombstone else set()
    for item in payload["items"]:
        relative = item["owned_path"]
        if item["owner"] not in KNOWN_PRODUCT_OWNERS:
            plan["unknown_owner"].append({"path": relative, "owner": item["owner"]})
            plan["conflict"].append({"path": relative, "reason": "unknown_owner"})
            plan["requires_manual_action"].append({"path": relative, "reason": "unknown_owner"})
            continue
        if item.get("external_registration") is not None:
            plan["unsupported_registration"].append({"path": relative, "reason": "registration_authority_unresolved"})
            plan["requires_manual_action"].append({"path": relative, "reason": "unsupported_registration"})
            continue
        if _forbidden_product_state_path(relative):
            plan["will_preserve_unrelated"].append({"path": relative, "reason": "experimental_state_excluded"})
            plan["conflict"].append({"path": relative, "reason": "forbidden_product_state_path"})
            plan["requires_manual_action"].append({"path": relative, "reason": "forbidden_product_state_path"})
            continue
        content = expected.get(relative)
        if content is None or sha256_bytes(content) != item["installed_hash"]:
            plan["will_preserve_unrelated"].append({"path": relative, "reason": "expected_content_not_authoritative"})
            plan["requires_manual_action"].append({"path": relative, "reason": "expected_content_not_authoritative"})
            continue
        try:
            target = resolve_managed_path(root, relative)
        except ManagedStateError as exc:
            plan["conflict"].append({"path": relative, "reason": str(exc)})
            plan["requires_manual_action"].append({"path": relative, "reason": "unsafe_path"})
            continue
        if not target.exists():
            if target.is_symlink():
                plan["will_preserve_unrelated"].append({"path": relative, "reason": "broken_symlink"})
                plan["conflict"].append({"path": relative, "reason": "alternate_filesystem_object"})
                plan["requires_manual_action"].append({"path": relative, "reason": "alternate_filesystem_object"})
            elif relative in intentionally_removed:
                plan["intentionally_uninstalled"].append({"path": relative, "reason": "matching_uninstall_tombstone"})
            else:
                plan["not_found"].append({"path": relative, "reason": "owned_file_missing"})
                plan["will_restore"].append({"path": relative, "reason": "proven_owned_known_content", "installed_hash": item["installed_hash"]})
            continue
        try:
            target_stat = target.lstat()
        except OSError as exc:
            plan["conflict"].append({"path": relative, "reason": type(exc).__name__})
            plan["requires_manual_action"].append({"path": relative, "reason": "unreadable_state"})
            continue
        if not stat.S_ISREG(target_stat.st_mode) or target_stat.st_nlink != 1:
            reason = "hard_link" if stat.S_ISREG(target_stat.st_mode) and target_stat.st_nlink != 1 else "alternate_filesystem_object"
            plan["will_preserve_unrelated"].append({"path": relative, "reason": reason})
            plan["conflict"].append({"path": relative, "reason": reason})
            plan["requires_manual_action"].append({"path": relative, "reason": reason})
            continue
        try:
            current_hash = _hash_file(target)
        except OSError as exc:
            plan["conflict"].append({"path": relative, "reason": type(exc).__name__})
            plan["requires_manual_action"].append({"path": relative, "reason": "unreadable_state"})
            continue
        if current_hash == item["installed_hash"]:
            plan["already_healthy"].append({"path": relative})
        else:
            plan["will_preserve_modified"].append({"path": relative, "reason": "user_modified", "current_hash": current_hash})
            plan["conflict"].append({"path": relative, "reason": "installed_hash_mismatch"})
            plan["requires_manual_action"].append({"path": relative, "reason": "user_modified"})
    return plan


def _operation_public_receipt(operation: Mapping[str, Any]) -> dict[str, Any]:
    """Return a bounded, path-label-only operation receipt safe for public evidence."""
    return {
        "schema_version": "pcodex.lifecycle-operation-public.v1",
        "product_version": operation.get("product_version"),
        "operation_id": operation.get("operation_id"),
        "operation_type": operation.get("operation_type"),
        "started_at": operation.get("started_at"),
        "completed_at": operation.get("completed_at"),
        "repository_or_installation_identity": operation.get("managed_root_hash"),
        "authority_receipt_hash": operation.get("authority_receipt_hash"),
        "planned_actions": [PurePosixPath(str(value)).name for value in operation.get("planned_actions", [])],
        "completed_actions": [PurePosixPath(str(value)).name for value in operation.get("completed_actions", [])],
        "preserved_items": len(operation.get("preserved_items", [])),
        "conflicts": len(operation.get("conflicts", [])),
        "manual_actions": len(operation.get("manual_actions", [])),
        "result": operation.get("result"),
        "failure_stage": operation.get("failure_stage"),
        "rollback_or_recovery_status": operation.get("rollback_or_recovery_status"),
    }


def record_reinstall_validation(
    managed_root: Path | str,
    receipt_path: Path | str,
    *,
    result: str = "validated",
) -> dict[str, Any]:
    """Commit proof that install/reinstall ended with exact healthy authority."""
    root = validate_managed_root(managed_root)
    receipt_location = _receipt_under_root(root, receipt_path)
    receipt = read_install_state_receipt(receipt_location)
    if receipt["status"] != "loaded":
        raise ManagedStateError("reinstall validation requires a valid install-state receipt")
    payload = receipt["payload"]
    marker = _read_owner_marker(root)
    if (
        marker["ownership_id"] != payload["ownership_id"]
        or marker["install_state_receipt"] != receipt_location.relative_to(root).as_posix()
        or marker["managed_root_hash"] != payload["managed_root_hash"]
    ):
        raise ManagedStateError("reinstall validation authority mismatch")
    completed: list[str] = []
    for item in payload["items"]:
        if item["owner"] not in KNOWN_PRODUCT_OWNERS or item.get("external_registration") is not None:
            raise ManagedStateError("reinstall validation encountered unsupported authority")
        target = resolve_managed_path(root, item["owned_path"])
        target_stat = target.lstat()
        if not stat.S_ISREG(target_stat.st_mode) or target_stat.st_nlink != 1 or _hash_file(target) != item["installed_hash"]:
            raise ManagedStateError("reinstall validation found non-healthy managed state")
        completed.append(item["owned_path"])
    relative_output = DEFAULT_REINSTALL_VALIDATION_RELATIVE_PATH
    output = resolve_managed_path(root, relative_output)
    output_expected_hash: str | None = None
    if output.exists():
        try:
            prior_bytes = output.read_bytes()
            prior = json.loads(prior_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ManagedStateError("reinstall validation receipt would overwrite unrelated state") from exc
        if (
            not isinstance(prior, dict)
            or prior.get("schema_version") != REINSTALL_VALIDATION_SCHEMA_VERSION
            or prior.get("managed_root_hash") != payload["managed_root_hash"]
            or prior.get("ownership_id") != payload["ownership_id"]
            or prior.get("operation_receipt") != relative_output
        ):
            raise ManagedStateError("reinstall validation receipt would overwrite unrelated state")
        if (
            prior.get("operation_type") == "reinstall_validation"
            and prior.get("result") == "validated"
            and prior.get("authority_receipt_hash") == _authority_receipt_hash(receipt_location)
            and prior.get("completed_actions") == completed
            and prior.get("failure_stage") is None
        ):
            return {
                "status": "already_validated",
                "writes_performed": False,
                "operation": prior,
                "public_receipt": _operation_public_receipt(prior),
                "operation_receipt": str(output),
            }
        output_expected_hash = sha256_bytes(prior_bytes)
    started_at = timestamp_iso()
    operation = {
        "schema_version": REINSTALL_VALIDATION_SCHEMA_VERSION,
        "product_version": __version__,
        "operation_id": str(uuid4()),
        "operation_type": "reinstall_validation",
        "started_at": started_at,
        "completed_at": timestamp_iso(),
        "managed_root_hash": payload["managed_root_hash"],
        "ownership_id": payload["ownership_id"],
        "install_state_receipt": receipt_location.relative_to(root).as_posix(),
        "operation_receipt": relative_output,
        "authority_receipt_hash": _authority_receipt_hash(receipt_location),
        "planned_actions": completed,
        "completed_actions": completed,
        "preserved_items": [],
        "conflicts": [],
        "manual_actions": [],
        "result": result,
        "failure_stage": None,
        "rollback_or_recovery_status": "not_required",
    }
    _atomic_write_managed_json(
        root,
        relative_output,
        operation,
        require_absent=output_expected_hash is None,
        expected_current_hash=output_expected_hash,
    )
    return {
        "status": "validated",
        "writes_performed": True,
        "operation": operation,
        "public_receipt": _operation_public_receipt(operation),
        "operation_receipt": str(output),
    }


def _has_matching_reinstall_validation(
    root: Path,
    receipt_location: Path,
    payload: Mapping[str, Any],
    required_path: str,
) -> bool:
    path = resolve_managed_path(root, DEFAULT_REINSTALL_VALIDATION_RELATIVE_PATH)
    if not path.exists() or not path.is_file():
        return False
    try:
        operation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    required = {
        "schema_version", "product_version", "operation_id", "operation_type", "started_at",
        "completed_at", "managed_root_hash", "ownership_id", "install_state_receipt",
        "operation_receipt", "authority_receipt_hash", "planned_actions", "completed_actions",
        "preserved_items", "conflicts", "manual_actions", "result", "failure_stage",
        "rollback_or_recovery_status",
    }
    return bool(
        isinstance(operation, dict)
        and set(operation) == required
        and operation.get("schema_version") == REINSTALL_VALIDATION_SCHEMA_VERSION
        and operation.get("operation_type") == "reinstall_validation"
        and operation.get("result") == "validated"
        and operation.get("failure_stage") is None
        and operation.get("managed_root_hash") == payload.get("managed_root_hash")
        and operation.get("ownership_id") == payload.get("ownership_id")
        and operation.get("install_state_receipt") == receipt_location.relative_to(root).as_posix()
        and operation.get("operation_receipt") == DEFAULT_REINSTALL_VALIDATION_RELATIVE_PATH
        and operation.get("authority_receipt_hash") == _authority_receipt_hash(receipt_location)
        and required_path in (operation.get("completed_actions") or [])
    )


def apply_repair(
    managed_root: Path | str,
    receipt_path: Path | str,
    *,
    expected_content: Mapping[str, bytes] | None = None,
    operation_receipt_path: Path | str | None = None,
    fault_injector: Any | None = None,
) -> dict[str, Any]:
    root = validate_managed_root(managed_root)
    receipt_location = _receipt_under_root(root, receipt_path)
    expected = {_relative_owned_path(path): bytes(content) for path, content in (expected_content or {}).items()}
    plan = plan_repair(root, receipt_location, expected_content=expected)
    authority_blockers = {
        "managed_root_hash_mismatch", "ownership_marker_invalid", "ownership_id_mismatch",
        "receipt_path_mismatch", "unknown_owner", "forbidden_product_state_path",
        "unsupported_registration", "unsafe_path", "alternate_filesystem_object", "hard_link",
        "unreadable_state", "expected_content_not_authoritative",
    }
    if plan["receipt_status"] != "loaded" or any(
        item.get("reason") in authority_blockers for item in plan["requires_manual_action"]
    ):
        return {**plan, "status": "blocked_unknown_state", "applied": False, "restored": [], "operation_receipt": None}
    prior_receipt_bytes = receipt_location.read_bytes()
    if sha256_bytes(prior_receipt_bytes) != plan.get("authority_receipt_hash"):
        return {**plan, "status": "blocked_concurrent_authority_change", "applied": False, "restored": [], "operation_receipt": None}
    marker_location = _ownership_marker_path(root)
    prior_marker_bytes = marker_location.read_bytes() if marker_location.exists() else None
    actions = list(plan["will_restore"])
    marker_actions = list(plan["will_create"])
    if not actions and not marker_actions:
        return {
            **plan,
            "status": "blocked_conflict" if plan["conflict"] else "complete_uninstall" if plan["intentionally_uninstalled"] else "already_healthy",
            "applied": False,
            "restored": [],
            "operation_receipt": None,
        }
    output_raw = Path(operation_receipt_path).expanduser() if operation_receipt_path is not None else root / DEFAULT_REPAIR_OPERATION_RELATIVE_PATH
    output_absolute = output_raw if output_raw.is_absolute() else root / output_raw
    try:
        relative_output = output_absolute.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ManagedStateError("operation receipt must remain under the managed root") from exc
    output = resolve_managed_path(root, relative_output)
    if relative_output != DEFAULT_REPAIR_OPERATION_RELATIVE_PATH:
        raise ManagedStateError("custom repair operation receipts are unsupported")
    protected = {receipt_location, _ownership_marker_path(root), *(resolve_managed_path(root, action["path"]) for action in actions)}
    if output in protected:
        raise ManagedStateError("operation receipt collides with managed lifecycle state")
    output_expected_hash: str | None = None
    if output.exists():
        try:
            existing_bytes = output.read_bytes()
            existing = json.loads(existing_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ManagedStateError("operation receipt would overwrite unrelated state") from exc
        payload = read_install_state_receipt(receipt_location)["payload"]
        if (
            not isinstance(existing, dict)
            or existing.get("schema_version") != REPAIR_OPERATION_SCHEMA_VERSION
            or existing.get("managed_root_hash") != plan["managed_root_hash"]
            or existing.get("ownership_id") != payload["ownership_id"]
            or existing.get("operation_receipt") != relative_output
        ):
            raise ManagedStateError("operation receipt would overwrite unrelated state")
        output_expected_hash = sha256_bytes(existing_bytes)
    restored: list[str] = []
    created_marker = False
    started_at = timestamp_iso()

    def inject(stage: str) -> None:
        if fault_injector is not None:
            fault_injector(stage)

    try:
        if marker_actions:
            if receipt_location.read_bytes() != prior_receipt_bytes:
                raise ManagedStateError("install-state authority changed before repair")
            inject("before_marker_write")
            receipt_payload = read_install_state_receipt(receipt_location)["payload"]
            marker_payload = {
                "schema_version": OWNERSHIP_MARKER_SCHEMA_VERSION,
                "product_name": "pCodex",
                "ownership_id": receipt_payload["ownership_id"],
                "managed_root_hash": plan["managed_root_hash"],
                "install_state_receipt": receipt_location.relative_to(root).as_posix(),
            }
            _atomic_write_managed(
                root,
                OWNERSHIP_MARKER_RELATIVE_PATH,
                (json.dumps(marker_payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                require_absent=True,
            )
            created_marker = True
            inject("after_marker_write")
        for action in actions:
            relative = action["path"]
            if receipt_location.read_bytes() != prior_receipt_bytes:
                raise ManagedStateError("install-state authority changed before repair")
            if not marker_actions and marker_location.read_bytes() != prior_marker_bytes:
                raise ManagedStateError("ownership marker changed before repair")
            target = resolve_managed_path(root, relative)
            if target.exists() or target.is_symlink():
                raise ManagedStateError(f"repair target changed after preview: {relative}")
            inject("before_staged_write")
            target = _atomic_write_managed(root, relative, expected[relative], require_absent=True)
            restored.append(relative)
            inject("after_atomic_replace")
            target_stat = target.lstat()
            if not stat.S_ISREG(target_stat.st_mode) or target_stat.st_nlink != 1 or _hash_file(target) != action["installed_hash"]:
                raise ManagedStateError(f"repair verification failed: {relative}")
        if receipt_location.read_bytes() != prior_receipt_bytes:
            raise ManagedStateError("install-state authority changed during repair")
        current = read_install_state_receipt(receipt_location)
        if (
            current["status"] != "loaded"
            or current["payload"]["managed_root_hash"] != plan["managed_root_hash"]
            or current["payload"]["ownership_id"] != plan["ownership_id"]
        ):
            raise ManagedStateError("install-state authority changed during repair")
        current_marker = _read_owner_marker(root)
        if (
            current_marker["ownership_id"] != plan["ownership_id"]
            or current_marker["install_state_receipt"] != receipt_location.relative_to(root).as_posix()
        ):
            raise ManagedStateError("ownership marker changed during repair")
        if not marker_actions and marker_location.read_bytes() != prior_marker_bytes:
            raise ManagedStateError("ownership marker bytes changed during repair")
        # Missing-file repair does not mutate install authority: the receipt
        # already records the expected installed bytes. Keeping it byte-stable
        # also preserves the independently bound reinstall-validation proof.
        updated = current["payload"]
        inject("before_receipt_update")
        inject("after_receipt_update")
        completed_at = timestamp_iso()
        operation = {
            "schema_version": REPAIR_OPERATION_SCHEMA_VERSION,
            "product_version": __version__,
            "operation_id": str(uuid4()),
            "operation_type": "repair_apply",
            "started_at": started_at,
            "completed_at": completed_at,
            "managed_root_hash": plan["managed_root_hash"],
            "ownership_id": updated["ownership_id"],
            "install_state_receipt": receipt_location.relative_to(root).as_posix(),
            "operation_receipt": relative_output,
            "authority_receipt_hash": _authority_receipt_hash(receipt_location),
            "planned_actions": [action["path"] for action in actions] + [action["path"] for action in marker_actions],
            "completed_actions": restored + [action["path"] for action in marker_actions],
            "preserved_items": plan["will_preserve_modified"] + plan["will_preserve_unrelated"],
            "conflicts": plan["conflict"],
            "manual_actions": plan["requires_manual_action"],
            "result": "applied_with_manual_action" if plan["requires_manual_action"] else "applied",
            "failure_stage": None,
            "rollback_or_recovery_status": "not_required",
        }
        inject("before_operation_receipt")
        _atomic_write_managed_json(
            root,
            relative_output,
            operation,
            require_absent=output_expected_hash is None,
            expected_current_hash=output_expected_hash,
        )
    except Exception as original_error:
        rollback_errors: list[Exception] = []
        for relative in reversed(restored):
            parent_fd: int | None = None
            try:
                parent_fd, target_name = _open_managed_parent_fd(root, relative, create=False)
                descriptor = os.open(target_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
                try:
                    before = os.fstat(descriptor)
                    with os.fdopen(os.dup(descriptor), "rb") as handle:
                        current_content = handle.read()
                    after = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
                current_entry = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
                if (
                    stat.S_ISREG(before.st_mode)
                    and before.st_nlink == 1
                    and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    == (current_entry.st_dev, current_entry.st_ino, current_entry.st_size, current_entry.st_mtime_ns)
                    and sha256_bytes(current_content) == sha256_bytes(expected[relative])
                ):
                    os.unlink(target_name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except FileNotFoundError:
                pass
            except Exception as exc:
                rollback_errors.append(exc)
            finally:
                if parent_fd is not None:
                    os.close(parent_fd)
        if created_marker:
            try:
                marker_path = _ownership_marker_path(root)
                if prior_marker_bytes is None:
                    marker_parent_fd, marker_name = _open_managed_parent_fd(root, OWNERSHIP_MARKER_RELATIVE_PATH)
                    try:
                        os.unlink(marker_name, dir_fd=marker_parent_fd)
                        os.fsync(marker_parent_fd)
                    finally:
                        os.close(marker_parent_fd)
                else:
                    _atomic_write_managed(root, OWNERSHIP_MARKER_RELATIVE_PATH, prior_marker_bytes)
            except FileNotFoundError:
                pass
            except Exception as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise ManagedStateError(f"repair failed and rollback requires recovery: {rollback_errors[0]}") from original_error
        raise
    return {
        **plan,
        "writes_performed": True,
        "applied": True,
        "restored": restored,
        "operation_receipt": str(output),
        "operation": operation,
        "public_receipt": _operation_public_receipt(operation),
        "status": operation["result"],
    }


def lifecycle_status(
    managed_root: Path | str,
    receipt_path: Path | str,
    *,
    expected_content: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Return deterministic read-only lifecycle integrity and one next action."""
    root = validate_managed_root(managed_root)
    receipt_location = _receipt_under_root(root, receipt_path)
    plan = plan_repair(root, receipt_location, expected_content=expected_content)
    if plan["receipt_status"] == "missing":
        residual_paths = [
            OWNERSHIP_MARKER_RELATIVE_PATH,
            DEFAULT_REPAIR_OPERATION_RELATIVE_PATH,
            DEFAULT_UNINSTALL_OPERATION_RELATIVE_PATH,
            *(expected_content or {}).keys(),
        ]
        residual = []
        for relative in residual_paths:
            try:
                candidate = resolve_managed_path(root, relative)
            except ManagedStateError:
                residual.append(str(relative))
                continue
            if candidate.exists() or candidate.is_symlink():
                residual.append(_relative_owned_path(relative))
        if residual:
            return {
                "schema_version": "pcodex.lifecycle-status.v1",
                "state": "partial_installation_missing_authority",
                "readiness": "BLOCKED",
                "recommended_action": "inspect residual lifecycle state; do not infer ownership without the receipt",
                "exit_code": 2,
                "residual_state": sorted(set(residual)),
                "repair_plan": plan,
            }
        return {
            "schema_version": "pcodex.lifecycle-status.v1",
            "state": "not_installed",
            "readiness": "NEEDS_ACTION",
            "recommended_action": "pcodex install --apply",
            "exit_code": 1,
            "repair_plan": plan,
        }
    loaded_receipt = read_install_state_receipt(receipt_location)
    if loaded_receipt["status"] == "loaded":
        interrupted_uninstall = _matching_interrupted_uninstall(root, receipt_location, loaded_receipt["payload"])
        if interrupted_uninstall:
            return {
                "schema_version": "pcodex.lifecycle-status.v1",
                "state": "interrupted_uninstall",
                "readiness": "BLOCKED",
                "recommended_action": "preserve the ownership-bound staging directory and inspect interrupted uninstall recovery manually",
                "exit_code": 2,
                "interrupted_operation_count": len(interrupted_uninstall),
                "repair_plan": plan,
            }
    authority_reasons = {
        "managed_root_hash_mismatch", "ownership_marker_invalid", "ownership_id_mismatch",
        "receipt_path_mismatch", "unknown_owner", "forbidden_product_state_path",
        "unsafe_path", "alternate_filesystem_object", "hard_link", "unreadable_state",
        "expected_content_not_authoritative", "unsupported_registration",
    }
    if plan["receipt_status"] != "loaded" or any(
        item.get("reason") in authority_reasons for item in plan["requires_manual_action"]
    ):
        return {
            "schema_version": "pcodex.lifecycle-status.v1",
            "state": "blocked_unknown_or_unsafe_state",
            "readiness": "BLOCKED",
            "recommended_action": "inspect lifecycle conflicts and restore trusted receipt authority",
            "exit_code": 2,
            "repair_plan": plan,
        }
    if plan["intentionally_uninstalled"] and not plan["will_restore"]:
        return {
            "schema_version": "pcodex.lifecycle-status.v1",
            "state": "complete_uninstall",
            "readiness": "NEEDS_ACTION",
            "recommended_action": "pcodex install --apply",
            "exit_code": 1,
            "repair_plan": plan,
        }
    if plan["will_preserve_modified"] or plan["conflict"]:
        return {
            "schema_version": "pcodex.lifecycle-status.v1",
            "state": "user_modified_or_conflicted",
            "readiness": "BLOCKED",
            "recommended_action": "review preserved managed-state conflicts manually",
            "exit_code": 2,
            "repair_plan": plan,
        }
    if plan["will_restore"] or plan["will_create"]:
        return {
            "schema_version": "pcodex.lifecycle-status.v1",
            "state": "repairable_incomplete_installation",
            "readiness": "NEEDS_ACTION",
            "recommended_action": "pcodex repair --dry-run, then pcodex repair --yes",
            "exit_code": 1,
            "repair_plan": plan,
        }
    return {
        "schema_version": "pcodex.lifecycle-status.v1",
        "state": "healthy_installation",
        "readiness": "READY",
        "recommended_action": "pcodex status --advisory",
        "exit_code": 0,
        "repair_plan": plan,
    }


def _empty_plan(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": UNINSTALL_PLAN_SCHEMA_VERSION,
        "product_version": __version__,
        "managed_root_hash": sha256_bytes(str(root).encode("utf-8")),
        "receipt_status": receipt["status"],
        "authority_receipt_hash": None,
        "ownership_id": None,
        "writes_performed": False,
        "will_remove": [],
        "will_restore": [],
        "will_preserve": [],
        "conflict": [],
        "not_found": [],
        "already_absent": [],
        "unknown_owner": [],
        "unsupported_registration": [],
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
    plan["authority_receipt_hash"] = _authority_receipt_hash(receipt_location)
    plan["ownership_id"] = payload["ownership_id"]
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
    tombstone = _read_matching_uninstall_tombstone(root, receipt_location, payload)
    intentionally_removed = set(tombstone.get("completed_actions") or []) if tombstone else set()
    for item in payload["items"]:
        relative = item["owned_path"]
        if item["owner"] not in KNOWN_PRODUCT_OWNERS:
            plan["unknown_owner"].append({"path": relative, "owner": item["owner"]})
            plan["conflict"].append({"path": relative, "reason": "unknown_owner"})
            plan["requires_manual_action"].append({"path": relative, "reason": "unknown_owner"})
            continue
        if item.get("external_registration") is not None:
            plan["unsupported_registration"].append({"path": relative, "reason": "external_registration_deferred"})
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
            if target.is_symlink():
                plan["will_preserve"].append({"path": relative, "reason": "broken_symlink"})
                plan["conflict"].append({"path": relative, "reason": "alternate_filesystem_object"})
                plan["requires_manual_action"].append({"path": relative, "reason": "alternate_filesystem_object"})
            elif relative in intentionally_removed:
                plan["already_absent"].append({"path": relative, "reason": "matching_uninstall_tombstone"})
                plan["not_found"].append({"path": relative, "reason": "already_missing"})
            else:
                plan["not_found"].append({"path": relative, "reason": "already_missing"})
            continue
        try:
            target_stat = target.lstat()
        except OSError as exc:
            plan["conflict"].append({"path": relative, "reason": type(exc).__name__})
            plan["requires_manual_action"].append({"path": relative, "reason": "unreadable_state"})
            continue
        if not stat.S_ISREG(target_stat.st_mode) or target_stat.st_nlink != 1:
            reason = "hard_link" if stat.S_ISREG(target_stat.st_mode) and target_stat.st_nlink != 1 else "not_regular_file"
            plan["conflict"].append({"path": relative, "reason": reason})
            plan["requires_manual_action"].append({"path": relative, "reason": reason})
            continue
        try:
            current_hash = _hash_file(target)
        except OSError as exc:
            plan["conflict"].append({"path": relative, "reason": type(exc).__name__})
            plan["requires_manual_action"].append({"path": relative, "reason": "unreadable_state"})
            continue
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
    fault_injector: Any | None = None,
) -> dict[str, Any]:
    root = validate_managed_root(managed_root)
    started_at = timestamp_iso()
    plan = plan_uninstall(root, receipt_path)
    authority_blockers = {
        "managed_root_hash_mismatch", "ownership_marker_invalid", "ownership_id_mismatch",
        "receipt_path_mismatch", "unknown_owner", "forbidden_product_state_path",
        "external_registration_deferred", "unsafe_path", "not_regular_file", "hard_link",
        "alternate_filesystem_object", "unreadable_state",
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
    receipt_location = _receipt_under_root(root, receipt_path)
    prior_receipt_bytes = receipt_location.read_bytes()
    if sha256_bytes(prior_receipt_bytes) != plan.get("authority_receipt_hash"):
        return {
            **plan,
            "writes_performed": False,
            "applied": False,
            "removed": [],
            "operation_receipt": None,
            "status": "blocked_concurrent_authority_change",
        }
    marker_location = _ownership_marker_path(root)
    prior_marker_bytes = marker_location.read_bytes()
    receipt_payload = validate_install_state_receipt(json.loads(prior_receipt_bytes))
    interrupted = _matching_interrupted_uninstall(root, receipt_location, receipt_payload)
    if interrupted:
        return {
            **plan,
            "writes_performed": False,
            "applied": False,
            "removed": [],
            "operation_receipt": None,
            "status": "blocked_interrupted_operation",
            "interrupted_operation_count": len(interrupted),
        }
    if not plan["will_remove"]:
        return {
            **plan,
            "writes_performed": False,
            "applied": False,
            "removed": [],
            "operation_receipt": None,
            "status": "blocked_conflict" if plan["conflict"] else "complete_uninstall" if plan["already_absent"] else "no_changes",
        }
    output_raw = Path(operation_receipt_path).expanduser() if operation_receipt_path is not None else root / ".premode" / "uninstall-operation.json"
    output_absolute = output_raw if output_raw.is_absolute() else root / output_raw
    try:
        relative_output = output_absolute.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ManagedStateError("operation receipt must remain under the managed root") from exc
    output = resolve_managed_path(root, relative_output)
    if relative_output != DEFAULT_UNINSTALL_OPERATION_RELATIVE_PATH:
        raise ManagedStateError("custom uninstall operation receipts are unsupported")
    protected = {
        _receipt_under_root(root, receipt_path),
        _ownership_marker_path(root),
        *(resolve_managed_path(root, action["path"]) for action in plan["will_remove"]),
    }
    if output in protected:
        raise ManagedStateError("operation receipt collides with managed lifecycle state")
    output_expected_hash: str | None = None
    if output.exists():
        marker = _read_owner_marker(root)
        try:
            existing_output_bytes = output.read_bytes()
            existing_operation = json.loads(existing_output_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ManagedStateError("operation receipt would overwrite unrelated state") from exc
        compatible_schema = existing_operation.get("schema_version") in {
            LEGACY_UNINSTALL_OPERATION_SCHEMA_VERSION, UNINSTALL_OPERATION_SCHEMA_VERSION,
        } if isinstance(existing_operation, dict) else False
        compatible_type = existing_operation.get("operation_type") in {"uninstall", "uninstall_apply"} if isinstance(existing_operation, dict) else False
        if (
            not isinstance(existing_operation, dict)
            or not compatible_schema
            or not compatible_type
            or existing_operation.get("managed_root_hash") != plan["managed_root_hash"]
            or existing_operation.get("ownership_id") != marker["ownership_id"]
            or existing_operation.get("install_state_receipt") != marker["install_state_receipt"]
            or existing_operation.get("operation_receipt") != relative_output
        ):
            raise ManagedStateError("operation receipt would overwrite unrelated state")
        output_expected_hash = sha256_bytes(existing_output_bytes)
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
    staging_manifest = {
        "schema_version": "pcodex.uninstall-staging.v1",
        "managed_root_hash": plan["managed_root_hash"],
        "ownership_id": plan["ownership_id"],
        "install_state_receipt": receipt_location.relative_to(root).as_posix(),
        "authority_receipt_hash": sha256_bytes(prior_receipt_bytes),
        "actions": [],
    }
    staging_descriptor = os.open(
        "operation.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=quarantine_fd,
    )
    try:
        with os.fdopen(os.dup(staging_descriptor), "wb") as handle:
            handle.write((json.dumps(staging_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(staging_descriptor)
    os.fsync(quarantine_fd)
    os.fsync(premode_fd)

    def write_staging_manifest() -> None:
        temporary_name = f".operation.{uuid4()}.tmp"
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=quarantine_fd,
        )
        try:
            with os.fdopen(os.dup(descriptor), "wb") as handle:
                handle.write((json.dumps(staging_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary_name, "operation.json", src_dir_fd=quarantine_fd, dst_dir_fd=quarantine_fd)
        os.fsync(quarantine_fd)

    def inject(stage: str) -> None:
        if fault_injector is not None:
            fault_injector(stage)

    def entry_exists(name: str, directory_fd: int) -> bool:
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def restore_records() -> list[Exception]:
        failures: list[Exception] = []
        for record in reversed(rollback):
            try:
                if entry_exists(record["target_name"], record["target_parent_fd"]):
                    raise ManagedStateError(f"rollback target is occupied: {record['relative']}")
                if record["quarantined"] and entry_exists(record["quarantine_name"], quarantine_fd):
                    os.rename(
                        record["quarantine_name"], record["target_name"],
                        src_dir_fd=quarantine_fd, dst_dir_fd=record["target_parent_fd"],
                    )
                    record["quarantined"] = False
                elif record.get("content") is not None:
                    temporary_name = f".{record['target_name']}.{uuid4()}.rollback"
                    descriptor = os.open(
                        temporary_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                        record["mode"],
                        dir_fd=record["target_parent_fd"],
                    )
                    try:
                        with os.fdopen(os.dup(descriptor), "wb") as handle:
                            handle.write(record["content"])
                            handle.flush()
                            os.fsync(handle.fileno())
                    finally:
                        os.close(descriptor)
                    try:
                        os.link(
                            temporary_name,
                            record["target_name"],
                            src_dir_fd=record["target_parent_fd"],
                            dst_dir_fd=record["target_parent_fd"],
                            follow_symlinks=False,
                        )
                    finally:
                        os.unlink(temporary_name, dir_fd=record["target_parent_fd"])
                    os.fsync(record["target_parent_fd"])
                    record["quarantined"] = False
            except Exception as exc:
                failures.append(exc)
        return failures

    def close_quarantine(*, preserve_manifest: bool = False) -> None:
        for record in rollback:
            parent_fd = record.get("target_parent_fd")
            if isinstance(parent_fd, int) and parent_fd >= 0:
                os.close(parent_fd)
                record["target_parent_fd"] = -1
        if not preserve_manifest:
            try:
                os.unlink("operation.json", dir_fd=quarantine_fd)
            except (FileNotFoundError, OSError):
                pass
        os.close(quarantine_fd)
        try:
            os.rmdir(quarantine_name, dir_fd=premode_fd)
        except OSError:
            pass
        try:
            os.fsync(premode_fd)
        except OSError:
            pass
        os.close(premode_fd)

    def rollback_and_close() -> Exception | None:
        failures = restore_records()
        try:
            close_quarantine(preserve_manifest=bool(failures or any(record["quarantined"] for record in rollback)))
        except Exception as exc:
            failures.append(exc)
        return failures[0] if failures else None

    try:
        for action in list(plan["will_remove"]):
            relative = action["path"]
            if receipt_location.read_bytes() != prior_receipt_bytes or marker_location.read_bytes() != prior_marker_bytes:
                raise ManagedStateError("lifecycle authority changed before uninstall mutation")
            target = resolve_managed_path(root, relative)
            if not target.exists():
                plan["not_found"].append({"path": relative, "reason": "missing_at_apply"})
                continue
            target_parent_fd, target_name = _open_managed_parent_fd(root, relative, create=False)
            quarantine_entry = f"{uuid4()}.pending"
            staging_action = {"target": relative, "quarantine": quarantine_entry, "phase": "planned"}
            staging_manifest["actions"].append(staging_action)
            write_staging_manifest()
            os.rename(
                target_name, quarantine_entry,
                src_dir_fd=target_parent_fd, dst_dir_fd=quarantine_fd,
            )
            record: dict[str, Any] = {
                "target": target,
                "relative": relative,
                "target_name": target_name,
                "target_parent_fd": target_parent_fd,
                "quarantine_name": quarantine_entry,
                "quarantined": True,
                "content": None,
                "mode": 0o600,
            }
            rollback.append(record)
            staging_action["phase"] = "quarantined"
            write_staging_manifest()
            os.fsync(target_parent_fd)
            os.fsync(quarantine_fd)
            inject("after_quarantine_rename")
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
            if not stable_identity or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or sha256_bytes(content) != action["installed_hash"]:
                if entry_exists(target_name, target_parent_fd):
                    raise ManagedStateError("target changed while restoring a quarantined mismatch")
                os.rename(
                    quarantine_entry, target_name,
                    src_dir_fd=quarantine_fd, dst_dir_fd=target_parent_fd,
                )
                os.fsync(target_parent_fd)
                os.fsync(quarantine_fd)
                record["quarantined"] = False
                rollback.pop()
                os.close(target_parent_fd)
                plan["will_preserve"].append({"path": relative, "reason": "user_modified_at_apply"})
                plan["conflict"].append({"path": relative, "reason": "installed_hash_mismatch_at_apply"})
                plan["requires_manual_action"].append({"path": relative, "reason": "user_modified_at_apply"})
                continue
            removed.append(relative)
            confirmed_actions.append(action)
    except Exception as exc:
        rollback_error = rollback_and_close()
        if rollback_error is not None:
            raise ManagedStateError(f"uninstall failed and rollback requires recovery: {rollback_error}") from exc
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
            "status": "blocked_conflict" if plan["conflict"] else "complete_uninstall" if plan["already_absent"] else "no_changes",
        }
    status = "applied_with_manual_action" if plan["requires_manual_action"] else "applied_with_conflicts" if plan["conflict"] else "applied"
    operation = {
        "schema_version": UNINSTALL_OPERATION_SCHEMA_VERSION,
        "product_version": __version__,
        "operation_id": str(uuid4()),
        "operation_type": "uninstall_apply",
        "started_at": started_at,
        "completed_at": None,
        "managed_root_hash": plan["managed_root_hash"],
        "ownership_id": marker["ownership_id"],
        "install_state_receipt": marker["install_state_receipt"],
        "operation_receipt": relative_output,
        "authority_receipt_hash": sha256_bytes(prior_receipt_bytes),
        "planned_actions": [action["path"] for action in confirmed_actions],
        "completed_actions": removed,
        "preserved_items": plan["will_preserve"],
        "conflicts": plan["conflict"],
        "not_found": plan["not_found"],
        "unknown_owner": plan["unknown_owner"],
        "unsupported_registration": plan["unsupported_registration"],
        "manual_actions": plan["requires_manual_action"],
        "result": status,
        "status": status,
        "failure_stage": None,
        "rollback_or_recovery_status": "not_required",
    }
    try:
        # Completion is recorded only after all quarantined bytes are gone. If
        # receipt writing fails, the in-memory copies restore the owned paths.
        for record in rollback:
            inject("during_quarantine_removal")
            os.unlink(record["quarantine_name"], dir_fd=quarantine_fd)
            inject("after_quarantine_removal")
            record["quarantined"] = False
        os.fsync(quarantine_fd)
        for record in rollback:
            os.fsync(record["target_parent_fd"])
        if receipt_location.read_bytes() != prior_receipt_bytes or marker_location.read_bytes() != prior_marker_bytes:
            raise ManagedStateError("lifecycle authority changed during uninstall")
        operation["completed_at"] = timestamp_iso()
        inject("before_operation_receipt")
        _atomic_write_managed_json(
            root,
            relative_output,
            operation,
            require_absent=output_expected_hash is None,
            expected_current_hash=output_expected_hash,
        )
    except Exception as exc:
        rollback_error = rollback_and_close()
        if rollback_error is not None:
            raise ManagedStateError(f"uninstall failed and rollback requires recovery: {rollback_error}") from exc
        raise
    close_quarantine()
    return {
        **plan,
        "writes_performed": True,
        "applied": True,
        "removed": removed,
        "operation_receipt": str(output),
        "operation": operation,
        "public_receipt": _operation_public_receipt(operation),
        "status": status,
    }
