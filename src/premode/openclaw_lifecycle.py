"""Receipt-bound lifecycle for the production OpenClaw adapter registration."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import re
from typing import Any, Mapping
from uuid import uuid4

from . import __version__
from .openclaw_adapter import qualify_openclaw_workspace
from .openclaw_integration import (
    OpenClawConfigAuthority,
    SUPPORTED_OPENCLAW_VERSION,
    openclaw_compatibility,
    resolve_openclaw_config_authority,
)
from .openclaw_json5 import (
    OWNERSHIP_SCHEMA_VERSION,
    Json5EditPlan,
    OpenClawJson5ConflictError,
    OpenClawJson5Error,
    OpenClawJson5Ownership,
    apply_json5_edit_plan,
    inspect_pcodex_document,
    plan_install_pcodex,
    plan_remove_pcodex,
)


STATE_SCHEMA_VERSION = "pcodex.openclaw-integration-state.v1"
OPERATION_SCHEMA_VERSION = "pcodex.openclaw-integration-operation.v1"
ADAPTER_VERSION = "pcodex.openclaw-agent-adapter.v1"
STATE_RELATIVE = Path(".pcodex/openclaw-integration-state.json")
JOURNAL_RELATIVE = Path(".pcodex/openclaw-integration-operation.json")
DEFAULT_CONFIG = b"{}\n"
TARGET_PATH = ("mcp", "servers", "pcodex")
_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_WORKSPACE_BINDING = re.compile(r"^ocwb_[0-9a-f]{32}$")


class OpenClawLifecycleError(RuntimeError):
    """The adapter lifecycle cannot safely mutate the current authority."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _preserve_recovery_bytes(directory: int, name: str, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, 0o600, dir_fd=directory)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory)


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return _sha256(encoded.encode("utf-8"))


def _workspace_identity(workspace: Path) -> tuple[Path, int, int]:
    lexical = Path(os.path.abspath(os.fspath(workspace)))
    try:
        info = lexical.stat(follow_symlinks=False)
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise OpenClawLifecycleError("configured workspace is unavailable") from exc
    if resolved != lexical or not stat.S_ISDIR(info.st_mode):
        raise OpenClawLifecycleError(
            "configured workspace must be an absolute non-symlink directory"
        )
    return lexical, info.st_dev, info.st_ino


def _assert_workspace_identity(workspace: Path, *, device: int, inode: int) -> None:
    current, current_device, current_inode = _workspace_identity(workspace)
    if current != workspace or (current_device, current_inode) != (device, inode):
        raise OpenClawLifecycleError("configured workspace identity changed")


def canonical_registration(workspace: Path) -> dict[str, Any]:
    root, _, _ = _workspace_identity(workspace)
    executable = Path(sys.executable)
    if (
        not executable.is_absolute()
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
        or not _installed_helper_authority_available(executable)
    ):
        raise OpenClawLifecycleError(
            "installed OpenClaw helper authority is unavailable"
        )
    return {
        "command": str(executable),
        "args": ["-m", "premode.pcodex_bootstrap", "openclaw-mcp-server"],
        "env": {"PCODEX_WORKSPACE": str(root)},
    }


def _installed_helper_authority_available(executable: Path) -> bool:
    """Require helper code owned by this interpreter, not PYTHONPATH/a checkout."""

    try:
        prefix = Path(sys.prefix).resolve(strict=True)
        distribution = importlib.metadata.distribution("premode-router")
        files = distribution.files or ()
        helpers = [
            Path(str(distribution.locate_file(item))).resolve(strict=True)
            for item in files
            if str(item).replace("\\", "/").endswith("premode/pcodex_bootstrap.py")
        ]
        helper_spec = importlib.util.find_spec("premode.pcodex_bootstrap")
        loaded_helper = (
            Path(str(helper_spec.origin)).resolve(strict=True)
            if helper_spec is not None and helper_spec.origin is not None
            else None
        )
    except (OSError, importlib.metadata.PackageNotFoundError):
        return False
    return bool(
        executable.is_absolute()
        and executable.is_relative_to(prefix)
        and executable.is_file()
        and len(helpers) == 1
        and helpers[0].is_file()
        and helpers[0].is_relative_to(prefix)
        and loaded_helper == helpers[0]
        and distribution.version == __version__
    )


def _ownership_payload(ownership: OpenClawJson5Ownership) -> dict[str, Any]:
    return {
        "schema_version": ownership.schema_version,
        "target_path": list(ownership.target_path),
        "target_value_sha256": ownership.target_value_sha256,
        "created_containers": list(ownership.created_containers),
    }


def _ownership_from_payload(value: Any) -> OpenClawJson5Ownership:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "target_path",
        "target_value_sha256",
        "created_containers",
    }:
        raise OpenClawLifecycleError("OpenClaw editor ownership is malformed")
    target_path = value.get("target_path")
    created = value.get("created_containers")
    created_tuple = (
        tuple(str(item) for item in created) if isinstance(created, list) else ()
    )
    if (
        value.get("schema_version") != OWNERSHIP_SCHEMA_VERSION
        or not isinstance(target_path, list)
        or tuple(target_path) != TARGET_PATH
        or not isinstance(created, list)
        or created_tuple not in {(), ("mcp.servers",), ("mcp", "mcp.servers")}
    ):
        raise OpenClawLifecycleError("OpenClaw editor ownership is invalid")
    digest = value.get("target_value_sha256")
    if not isinstance(digest, str) or _HEX_64.fullmatch(digest) is None:
        raise OpenClawLifecycleError("OpenClaw editor target authority is invalid")
    try:
        return OpenClawJson5Ownership(
            schema_version=str(value["schema_version"]),
            target_path=tuple(str(item) for item in target_path),
            target_value_sha256=digest,
            created_containers=tuple(str(item) for item in created),
        )
    except (TypeError, ValueError) as exc:
        raise OpenClawLifecycleError("OpenClaw editor ownership is invalid") from exc


def _safe_parent_chain(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:-1]:
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise OpenClawLifecycleError(
                "cannot inspect OpenClaw lifecycle parent"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise OpenClawLifecycleError("OpenClaw lifecycle path has an unsafe parent")


def _read_regular(path: Path, *, allow_missing: bool) -> bytes | None:
    _safe_parent_chain(path)
    try:
        before = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise OpenClawLifecycleError(
            "required OpenClaw lifecycle file is missing"
        ) from None
    except OSError as exc:
        raise OpenClawLifecycleError("cannot inspect OpenClaw lifecycle file") from exc
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise OpenClawLifecycleError(
            "OpenClaw lifecycle file is unsafe or multiply linked"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise OpenClawLifecycleError(
            "cannot open OpenClaw lifecycle file safely"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OpenClawLifecycleError(
                "OpenClaw lifecycle file changed during inspection"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _atomic_write(path: Path, content: bytes, *, mode: int) -> None:
    _safe_parent_chain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_parent_chain(path)
    expected = _read_regular(path, allow_missing=True)
    try:
        parent_before = path.parent.stat(follow_symlinks=False)
        directory = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise OpenClawLifecycleError(
            "cannot bind OpenClaw lifecycle parent for atomic write"
        ) from exc
    opened_parent = os.fstat(directory)
    if not stat.S_ISDIR(parent_before.st_mode) or (
        opened_parent.st_dev,
        opened_parent.st_ino,
    ) != (parent_before.st_dev, parent_before.st_ino):
        os.close(directory)
        raise OpenClawLifecycleError(
            "OpenClaw lifecycle parent changed before atomic write"
        )
    stage_name = f".{path.name}.pcodex-stage-{uuid4().hex}"
    backup_name = f".{path.name}.pcodex-cas-backup"
    stage_created = False
    backup_created = False
    target_installed = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            stage = os.open(stage_name, flags, mode, dir_fd=directory)
        except OSError as exc:
            raise OpenClawLifecycleError(
                "cannot stage OpenClaw lifecycle atomic write"
            ) from exc
        stage_created = True
        try:
            view = memoryview(content)
            while view:
                written = os.write(stage, view)
                view = view[written:]
            os.fchmod(stage, mode)
            os.fsync(stage)
            staged_identity = os.fstat(stage)
        finally:
            os.close(stage)

        try:
            current_info = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            if expected is not None:
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle target disappeared before atomic write"
                ) from None
        else:
            if expected is None:
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle target appeared before atomic write"
                )
            if not stat.S_ISREG(current_info.st_mode) or current_info.st_nlink != 1:
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle target is unsafe or multiply linked"
                )
            current_fd = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
            try:
                opened = os.fstat(current_fd)
                digest = hashlib.sha256()
                while True:
                    chunk = os.read(current_fd, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            finally:
                os.close(current_fd)
            if (opened.st_dev, opened.st_ino) != (
                current_info.st_dev,
                current_info.st_ino,
            ) or digest.digest() != hashlib.sha256(expected).digest():
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle target changed before atomic write"
                )
            try:
                os.stat(backup_name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle CAS backup already exists"
                )
            os.rename(
                path.name,
                backup_name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
            backup_created = True
            backup = os.open(
                backup_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
            try:
                displaced = os.fstat(backup)
                displaced_digest = hashlib.sha256()
                while True:
                    chunk = os.read(backup, 1024 * 1024)
                    if not chunk:
                        break
                    displaced_digest.update(chunk)
            finally:
                os.close(backup)
            if (displaced.st_dev, displaced.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ) or displaced_digest.digest() != hashlib.sha256(expected).digest():
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle target changed during atomic exchange"
                )

        try:
            os.link(
                stage_name,
                path.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise OpenClawLifecycleError(
                "OpenClaw lifecycle target changed during atomic exchange"
            ) from exc
        target_installed = True
        if backup_created:
            assert expected is not None
            backup = os.open(
                backup_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
            try:
                after_publication = os.fstat(backup)
                after_digest = hashlib.sha256()
                while True:
                    chunk = os.read(backup, 1024 * 1024)
                    if not chunk:
                        break
                    after_digest.update(chunk)
            finally:
                os.close(backup)
            if (after_publication.st_dev, after_publication.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ) or after_digest.digest() != hashlib.sha256(expected).digest():
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle target changed during publication; "
                    f"preserved at {backup_name}"
                )
        published = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        if (published.st_dev, published.st_ino) != (
            staged_identity.st_dev,
            staged_identity.st_ino,
        ):
            raise OpenClawLifecycleError(
                "OpenClaw lifecycle published target was concurrently replaced"
            )
        os.unlink(stage_name, dir_fd=directory)
        stage_created = False
        if backup_created:
            backup_guard = os.open(
                backup_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
            try:
                os.unlink(backup_name, dir_fd=directory)
                backup_created = False
                final_displaced = _read_descriptor(backup_guard)
            finally:
                os.close(backup_guard)
            if final_displaced != expected:
                recovery_name = f".{path.name}.pcodex-cas-recovery-{uuid4().hex}"
                _preserve_recovery_bytes(directory, recovery_name, final_displaced)
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle target changed during final cleanup; "
                    f"preserved at {recovery_name}"
                )
        os.fsync(directory)
    except Exception:
        if backup_created and not target_installed:
            try:
                os.link(
                    backup_name,
                    path.name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            except FileExistsError:
                # Preserve the displaced bytes under the deterministic backup
                # name when a concurrent writer claimed the target.
                pass
            else:
                os.unlink(backup_name, dir_fd=directory)
                backup_created = False
        raise
    finally:
        if stage_created:
            try:
                os.unlink(stage_name, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(
        path,
        _serialized_json(value),
        mode=0o600,
    )


def _serialized_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _open_bound_parent(path: Path) -> int:
    _safe_parent_chain(path)
    try:
        parent_before = path.parent.stat(follow_symlinks=False)
        directory = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise OpenClawLifecycleError("cannot bind OpenClaw lifecycle parent") from exc
    opened = os.fstat(directory)
    if not stat.S_ISDIR(parent_before.st_mode) or (
        opened.st_dev,
        opened.st_ino,
    ) != (parent_before.st_dev, parent_before.st_ino):
        os.close(directory)
        raise OpenClawLifecycleError("OpenClaw lifecycle parent changed")
    return directory


def _safe_unlink(path: Path, *, expected_hash: str) -> None:
    directory = _open_bound_parent(path)
    quarantine = f".{path.name}.pcodex-remove-{uuid4().hex}"
    try:
        try:
            before = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except OSError as exc:
            raise OpenClawLifecycleError(
                "cannot inspect OpenClaw lifecycle file for removal"
            ) from exc
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OpenClawLifecycleError(
                "OpenClaw lifecycle removal target is unsafe or multiply linked"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path.name, flags, dir_fd=directory)
        except OSError as exc:
            raise OpenClawLifecycleError(
                "cannot open OpenClaw lifecycle file for removal"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle file changed during removal inspection"
                )
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            if digest.hexdigest() != expected_hash:
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle file changed before removal"
                )
            current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise OpenClawLifecycleError(
                    "OpenClaw lifecycle file was replaced before removal"
                )
            os.rename(
                path.name,
                quarantine,
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
        finally:
            os.close(descriptor)
        moved = os.open(
            quarantine,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory,
        )
        moved_info = os.fstat(moved)
        moved_content = _read_descriptor(moved)
        if (moved_info.st_dev, moved_info.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ) or _sha256(moved_content) != expected_hash:
            os.close(moved)
            raise OpenClawLifecycleError(
                "OpenClaw lifecycle removal target changed; preserved in recovery staging"
            )
        try:
            os.unlink(quarantine, dir_fd=directory)
            final_content = _read_descriptor(moved)
        finally:
            os.close(moved)
        if _sha256(final_content) != expected_hash:
            recovery_name = f".{path.name}.pcodex-remove-recovery-{uuid4().hex}"
            _preserve_recovery_bytes(directory, recovery_name, final_content)
            raise OpenClawLifecycleError(
                "OpenClaw lifecycle removal target changed during final cleanup; "
                f"preserved at {recovery_name}"
            )
        os.fsync(directory)
    except OSError as exc:
        raise OpenClawLifecycleError("cannot remove OpenClaw lifecycle file") from exc
    finally:
        os.close(directory)


def _load_json(
    path: Path, *, label: str, allow_missing: bool = True
) -> dict[str, Any] | None:
    raw = _read_regular(path, allow_missing=allow_missing)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OpenClawLifecycleError(f"malformed {label}") from exc
    if not isinstance(value, dict):
        raise OpenClawLifecycleError(f"{label} must contain an object")
    return value


def _validate_state_payload(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "adapter_version",
        "product_version",
        "ownership_id",
        "workspace_binding_id",
        "workspace",
        "workspace_device",
        "workspace_inode",
        "config_path",
        "config_authority_source",
        "openclaw_version",
        "enabled",
        "registration_value_sha256",
        "editor_ownership",
        "config_was_absent",
    }
    if set(value) != required or value.get("schema_version") != STATE_SCHEMA_VERSION:
        raise OpenClawLifecycleError(
            "OpenClaw integration state is malformed or future-versioned"
        )
    if (
        value.get("adapter_version") != ADAPTER_VERSION
        or value.get("product_version") != __version__
        or not isinstance(value.get("ownership_id"), str)
        or _HEX_32.fullmatch(str(value["ownership_id"])) is None
        or not isinstance(value.get("workspace_binding_id"), str)
        or _WORKSPACE_BINDING.fullmatch(str(value["workspace_binding_id"])) is None
        or not isinstance(value.get("workspace"), str)
        or not Path(str(value["workspace"])).is_absolute()
        or not isinstance(value.get("workspace_device"), int)
        or isinstance(value.get("workspace_device"), bool)
        or int(value["workspace_device"]) < 0
        or not isinstance(value.get("workspace_inode"), int)
        or isinstance(value.get("workspace_inode"), bool)
        or int(value["workspace_inode"]) < 0
        or not isinstance(value.get("config_path"), str)
        or not Path(str(value["config_path"])).is_absolute()
        or not isinstance(value.get("config_authority_source"), str)
        or not value.get("config_authority_source")
        or value.get("openclaw_version") != SUPPORTED_OPENCLAW_VERSION
        or not isinstance(value.get("enabled"), bool)
        or not isinstance(value.get("registration_value_sha256"), str)
        or _HEX_64.fullmatch(str(value["registration_value_sha256"])) is None
        or not isinstance(value.get("config_was_absent"), bool)
    ):
        raise OpenClawLifecycleError("OpenClaw integration state authority is invalid")
    ownership = _ownership_from_payload(value["editor_ownership"])
    if value["registration_value_sha256"] != ownership.target_value_sha256:
        raise OpenClawLifecycleError(
            "OpenClaw registration and editor ownership authority differ"
        )
    return value


def _load_state(workspace: Path) -> dict[str, Any] | None:
    value = _load_json(workspace / STATE_RELATIVE, label="OpenClaw integration state")
    return None if value is None else _validate_state_payload(value)


def _assert_state_binding(state: Mapping[str, Any], workspace: Path) -> None:
    root, device, inode = _workspace_identity(workspace)
    if state.get("workspace") != str(root) or (
        state.get("workspace_device"),
        state.get("workspace_inode"),
    ) != (device, inode):
        raise OpenClawLifecycleError("workspace binding authority changed")


def _authority(environ: Mapping[str, str] | None) -> OpenClawConfigAuthority:
    return resolve_openclaw_config_authority(environ=environ or os.environ)


def _assert_authority_matches(
    state: Mapping[str, Any], authority: OpenClawConfigAuthority
) -> None:
    if str(authority.config_path) != state.get("config_path"):
        raise OpenClawLifecycleError("active OpenClaw configuration authority changed")


def _compatibility_or_error() -> dict[str, Any]:
    compatibility = openclaw_compatibility()
    if not compatibility["supported"]:
        raise OpenClawLifecycleError(str(compatibility["reason"]))
    return compatibility


def _qualification_or_error(workspace: Path) -> None:
    qualification = qualify_openclaw_workspace(workspace)
    if not qualification.qualified:
        raise OpenClawLifecycleError(
            f"workspace is not a qualified OpenClaw control plane: {qualification.reason}"
        )


def _plan_payload(plan: Json5EditPlan) -> dict[str, Any]:
    return {
        "operation": plan.operation,
        "source_sha256": plan.source_sha256,
        "edit_count": len(plan.edits),
        "target_path": list(plan.ownership.target_path),
        "target_value_sha256": plan.ownership.target_value_sha256,
        "created_containers": list(plan.ownership.created_containers),
    }


def _journal_path(workspace: Path) -> Path:
    return workspace / JOURNAL_RELATIVE


def _write_journal_exclusive(workspace: Path, value: Mapping[str, Any]) -> None:
    path = _journal_path(workspace)
    _safe_parent_chain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_parent_chain(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    directory = _open_bound_parent(path)
    try:
        descriptor = os.open(path.name, flags, 0o600, dir_fd=directory)
    except FileExistsError as exc:
        os.close(directory)
        raise OpenClawLifecycleError(
            "another or interrupted OpenClaw operation is active"
        ) from exc
    except OSError as exc:
        os.close(directory)
        raise OpenClawLifecycleError(
            "cannot create OpenClaw operation journal"
        ) from exc
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(directory)
    except Exception:
        # Preserve incomplete evidence rather than performing a path-based
        # cleanup that could race with replacement. Status will fail closed.
        raise
    finally:
        os.close(directory)


def _base_journal(
    *,
    operation: str,
    ownership_id: str,
    config_path: Path,
    config_before: bytes,
    config_after: bytes,
    state_before_sha256: str | None,
    state_after: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": OPERATION_SCHEMA_VERSION,
        "operation": operation,
        "phase": "started",
        "ownership_id": ownership_id,
        "config_path": str(config_path),
        "config_before_sha256": _sha256(config_before),
        "config_after_sha256": _sha256(config_after),
        "state_before_sha256": state_before_sha256,
        "state_after": dict(state_after) if state_after is not None else None,
    }


def _state_content_hash(workspace: Path) -> str | None:
    raw = _read_regular(workspace / STATE_RELATIVE, allow_missing=True)
    return None if raw is None else _sha256(raw)


def _validate_journal(
    value: dict[str, Any],
    *,
    workspace: Path,
    authority: OpenClawConfigAuthority,
) -> dict[str, Any]:
    required = {
        "schema_version",
        "operation",
        "phase",
        "ownership_id",
        "config_path",
        "config_before_sha256",
        "config_after_sha256",
        "state_before_sha256",
        "state_after",
    }
    if (
        set(value) != required
        or value.get("schema_version") != OPERATION_SCHEMA_VERSION
        or value.get("operation")
        not in {"install", "disable", "uninstall", "uninstall_disabled"}
        or value.get("phase") not in {"started", "config_committed"}
        or not isinstance(value.get("ownership_id"), str)
        or _HEX_32.fullmatch(str(value["ownership_id"])) is None
        or value.get("config_path") != str(authority.config_path)
        or not isinstance(value.get("config_before_sha256"), str)
        or _HEX_64.fullmatch(str(value["config_before_sha256"])) is None
        or not isinstance(value.get("config_after_sha256"), str)
        or _HEX_64.fullmatch(str(value["config_after_sha256"])) is None
        or (
            value.get("state_before_sha256") is not None
            and (
                not isinstance(value.get("state_before_sha256"), str)
                or _HEX_64.fullmatch(str(value["state_before_sha256"])) is None
            )
        )
    ):
        raise OpenClawLifecycleError(
            "OpenClaw operation journal is malformed or future-versioned"
        )
    state_after = value.get("state_after")
    if state_after is not None:
        if not isinstance(state_after, dict):
            raise OpenClawLifecycleError(
                "interrupted OpenClaw state authority is invalid"
            )
        validated = _validate_state_payload(state_after)
        _assert_state_binding(validated, workspace)
        _assert_authority_matches(validated, authority)
        if validated["ownership_id"] != value["ownership_id"]:
            raise OpenClawLifecycleError(
                "interrupted OpenClaw ownership authority differs"
            )
    current_state = _load_state(workspace)
    if current_state is not None:
        _assert_state_binding(current_state, workspace)
        _assert_authority_matches(current_state, authority)
        if current_state["ownership_id"] != value["ownership_id"]:
            raise OpenClawLifecycleError(
                "interrupted operation does not own current OpenClaw state"
            )
    return value


def _commit_config_and_state(
    workspace: Path,
    *,
    journal: dict[str, Any],
    config_path: Path,
    config_before: bytes,
    config_after: bytes,
    state_after: Mapping[str, Any] | None,
    remove_created_config: bool = False,
) -> None:
    root, device, inode = _workspace_identity(workspace)
    _write_journal_exclusive(root, journal)
    try:
        if _state_content_hash(root) != journal.get("state_before_sha256"):
            raise OpenClawLifecycleError(
                "OpenClaw integration state changed before commit"
            )
        current = _read_regular(config_path, allow_missing=True)
        effective = DEFAULT_CONFIG if current is None else current
        if effective != config_before:
            raise OpenClawLifecycleError("OpenClaw configuration changed before commit")
        mode = 0o600
        if current is not None:
            mode = stat.S_IMODE(config_path.stat(follow_symlinks=False).st_mode)
        if remove_created_config:
            if current is None:
                raise OpenClawLifecycleError(
                    "owned OpenClaw configuration is already absent"
                )
            _safe_unlink(config_path, expected_hash=_sha256(config_before))
        else:
            _atomic_write(config_path, config_after, mode=mode)
        _assert_workspace_identity(root, device=device, inode=inode)
        journal["phase"] = "config_committed"
        _atomic_json(_journal_path(root), journal)
        state_path = root / STATE_RELATIVE
        if _state_content_hash(root) != journal.get("state_before_sha256"):
            raise OpenClawLifecycleError(
                "OpenClaw integration state changed before commit"
            )
        if state_after is None:
            raw_state = _read_regular(state_path, allow_missing=True)
            if raw_state is not None:
                _safe_unlink(state_path, expected_hash=_sha256(raw_state))
        else:
            _atomic_json(state_path, state_after)
        journal_raw = _read_regular(_journal_path(root), allow_missing=False)
        assert journal_raw is not None
        _safe_unlink(_journal_path(root), expected_hash=_sha256(journal_raw))
    except Exception:
        # Preserve the journal and exact phase for deterministic repair.
        raise


def _new_state(
    *,
    workspace: Path,
    authority: OpenClawConfigAuthority,
    compatibility: Mapping[str, Any],
    ownership: OpenClawJson5Ownership,
    ownership_id: str,
    workspace_binding_id: str,
    enabled: bool,
    config_was_absent: bool,
) -> dict[str, Any]:
    root, device, inode = _workspace_identity(workspace)
    registration = canonical_registration(root)
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "product_version": __version__,
        "ownership_id": ownership_id,
        "workspace_binding_id": workspace_binding_id,
        "workspace": str(root),
        "workspace_device": device,
        "workspace_inode": inode,
        "config_path": str(authority.config_path),
        "config_authority_source": authority.source,
        "openclaw_version": str(compatibility["version"]),
        "enabled": enabled,
        "registration_value_sha256": _json_hash(registration),
        "editor_ownership": _ownership_payload(ownership),
        "config_was_absent": config_was_absent,
    }


def integration_status(
    workspace: Path, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    root, device, inode = _workspace_identity(workspace)
    compatibility = openclaw_compatibility()
    authority = _authority(environ)
    try:
        state = _load_state(root)
        journal = _load_json(_journal_path(root), label="OpenClaw operation journal")
        if journal is not None:
            journal = _validate_journal(journal, workspace=root, authority=authority)
        raw = _read_regular(authority.config_path, allow_missing=True)
        inspection = inspect_pcodex_document(DEFAULT_CONFIG if raw is None else raw)
    except (OpenClawLifecycleError, OpenClawJson5Error) as exc:
        return {
            "schema_version": "pcodex.openclaw-integration-status.v1",
            "readiness": "BLOCKED",
            "reason": "corrupt_or_unsafe_authority",
            "error": str(exc),
            "writes_performed": False,
            "next_recommended_action": "manual recovery is required",
        }
    if journal is not None:
        return {
            "schema_version": "pcodex.openclaw-integration-status.v1",
            "readiness": "BLOCKED",
            "reason": "interrupted_operation",
            "writes_performed": False,
            "next_recommended_action": "pcodex integrate openclaw --repair",
        }
    if state is None:
        reason = "registration_absent"
        readiness = "NEEDS_ACTION"
        if inspection.target_present:
            readiness, reason = "BLOCKED", "registration_has_unknown_owner"
        elif compatibility["installed"] and not compatibility["supported"]:
            readiness, reason = "BLOCKED", str(compatibility["reason"])
        elif not compatibility["installed"]:
            reason = "openclaw_missing"
        return {
            "schema_version": "pcodex.openclaw-integration-status.v1",
            "readiness": readiness,
            "reason": reason,
            "enabled": False,
            "openclaw_compatibility": compatibility,
            "writes_performed": False,
            "next_recommended_action": "pcodex integrate openclaw --dry-run",
        }
    if not compatibility.get("supported"):
        return {
            "schema_version": "pcodex.openclaw-integration-status.v1",
            "readiness": "BLOCKED",
            "reason": str(compatibility.get("reason") or "unsupported_openclaw"),
            "enabled": bool(state["enabled"]),
            "workspace_binding_id": state["workspace_binding_id"],
            "openclaw_compatibility": compatibility,
            "writes_performed": False,
            "next_recommended_action": "install the supported OpenClaw version",
        }
    try:
        _assert_authority_matches(state, authority)
        _assert_state_binding(state, root)
        ownership = _ownership_from_payload(state["editor_ownership"])
        target_exact = inspection.target_value_sha256 == ownership.target_value_sha256
        canonical_hash = _json_hash(canonical_registration(root))
        canonical_current = (
            state["registration_value_sha256"] == canonical_hash
            and ownership.target_value_sha256 == canonical_hash
        )
        if state["enabled"]:
            readiness = (
                "READY" if target_exact and canonical_current else "NEEDS_ACTION"
            )
            reason = (
                "healthy"
                if target_exact and canonical_current
                else "helper_authority_changed"
                if target_exact
                else (
                    "registration_missing"
                    if not inspection.target_present
                    else "registration_user_modified"
                )
            )
            if inspection.target_present and not target_exact:
                readiness = "BLOCKED"
        else:
            readiness = "NEEDS_ACTION" if not inspection.target_present else "BLOCKED"
            reason = (
                "disabled"
                if not inspection.target_present
                else "disabled_registration_conflict"
            )
    except OpenClawLifecycleError as exc:
        readiness, reason = "BLOCKED", str(exc)
    next_action = (
        "none"
        if readiness == "READY"
        else (
            "pcodex integrate openclaw --repair"
            if reason
            in {
                "registration_missing",
                "interrupted_operation",
                "helper_authority_changed",
            }
            else "pcodex integrate openclaw --write"
            if reason == "disabled"
            else "manual recovery is required"
        )
    )
    return {
        "schema_version": "pcodex.openclaw-integration-status.v1",
        "readiness": readiness,
        "reason": reason,
        "enabled": bool(state["enabled"]),
        "workspace_binding_id": state["workspace_binding_id"],
        "openclaw_compatibility": compatibility,
        "writes_performed": False,
        "next_recommended_action": next_action,
    }


def ready_workspace_binding(
    workspace: Path, *, environ: Mapping[str, str] | None = None
) -> str:
    """Return only a healthy receipt-bound workspace identity."""

    status = integration_status(workspace, environ=environ)
    if status.get("readiness") != "READY":
        raise OpenClawLifecycleError("OpenClaw adapter is not READY")
    binding_id = status.get("workspace_binding_id")
    if not isinstance(binding_id, str):
        raise OpenClawLifecycleError("OpenClaw workspace binding authority is missing")
    return binding_id


def integration_preview(
    workspace: Path, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    root, _, _ = _workspace_identity(workspace)
    compatibility = _compatibility_or_error()
    _qualification_or_error(root)
    authority = _authority(environ)
    if _load_json(_journal_path(root), label="OpenClaw operation journal") is not None:
        raise OpenClawLifecycleError("interrupted OpenClaw operation requires repair")
    state = _load_state(root)
    raw_file = _read_regular(authority.config_path, allow_missing=True)
    raw = DEFAULT_CONFIG if raw_file is None else raw_file
    inspection = inspect_pcodex_document(raw)
    if state is None and inspection.target_present:
        raise OpenClawLifecycleError(
            "existing pcodex registration has unknown ownership"
        )
    if state is not None:
        _assert_authority_matches(state, authority)
        _assert_state_binding(state, root)
        ownership = _ownership_from_payload(state["editor_ownership"])
        if (
            state["enabled"]
            and inspection.target_value_sha256 == ownership.target_value_sha256
        ):
            canonical_hash = _json_hash(canonical_registration(root))
            if (
                state["registration_value_sha256"] != canonical_hash
                or ownership.target_value_sha256 != canonical_hash
            ):
                return {
                    "schema_version": "pcodex.openclaw-integration-preview.v1",
                    "status": "preview",
                    "dry_run": True,
                    "writes_performed": False,
                    "processes_launched": False,
                    "plan": {"operation": "replace_owned_helper_authority"},
                    "openclaw_compatibility": compatibility,
                    "next_recommended_action": "pcodex integrate openclaw --write",
                }
            return {
                "schema_version": "pcodex.openclaw-integration-preview.v1",
                "status": "already_installed",
                "dry_run": True,
                "writes_performed": False,
                "processes_launched": False,
                "openclaw_compatibility": compatibility,
                "next_recommended_action": "none",
            }
        if inspection.target_present:
            raise OpenClawLifecycleError(
                "pcodex registration differs from receipt authority"
            )
    plan = plan_install_pcodex(raw, canonical_registration(root))
    return {
        "schema_version": "pcodex.openclaw-integration-preview.v1",
        "status": "preview",
        "dry_run": True,
        "writes_performed": False,
        "processes_launched": False,
        "config_path": str(authority.config_path),
        "registration": canonical_registration(root),
        "plan": _plan_payload(plan),
        "openclaw_compatibility": compatibility,
        "next_recommended_action": "pcodex integrate openclaw --write",
    }


def install_integration(
    workspace: Path, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    root, _, _ = _workspace_identity(workspace)
    compatibility = _compatibility_or_error()
    _qualification_or_error(root)
    authority = _authority(environ)
    if _load_json(_journal_path(root), label="OpenClaw operation journal") is not None:
        raise OpenClawLifecycleError("interrupted OpenClaw operation requires repair")
    state = _load_state(root)
    raw_file = _read_regular(authority.config_path, allow_missing=True)
    raw = DEFAULT_CONFIG if raw_file is None else raw_file
    inspection = inspect_pcodex_document(raw)
    replace_owned = False
    prior_ownership: OpenClawJson5Ownership | None = None
    if state is None:
        if inspection.target_present:
            raise OpenClawLifecycleError(
                "existing pcodex registration has unknown ownership"
            )
        ownership_id = uuid4().hex
        workspace_binding_id = (
            "ocwb_"
            + hashlib.sha256(
                f"pcodex-openclaw-binding-v1\0{ownership_id}\0{root}".encode("utf-8")
            ).hexdigest()[:32]
        )
        config_was_absent = raw_file is None
    else:
        _assert_authority_matches(state, authority)
        _assert_state_binding(state, root)
        ownership = _ownership_from_payload(state["editor_ownership"])
        prior_ownership = ownership
        if (
            state["enabled"]
            and inspection.target_value_sha256 == ownership.target_value_sha256
        ):
            canonical_hash = _json_hash(canonical_registration(root))
            if (
                state["registration_value_sha256"] == canonical_hash
                and ownership.target_value_sha256 == canonical_hash
            ):
                return {
                    "schema_version": "pcodex.openclaw-integration-result.v1",
                    "status": "installed",
                    "idempotent": True,
                    "writes_performed": False,
                    "workspace_binding_id": state["workspace_binding_id"],
                    "next_recommended_action": "none",
                }
            replace_owned = True
        if inspection.target_present and not replace_owned:
            raise OpenClawLifecycleError(
                "pcodex registration differs from receipt authority"
            )
        ownership_id = str(state["ownership_id"])
        workspace_binding_id = str(state["workspace_binding_id"])
        config_was_absent = bool(state["config_was_absent"])
    try:
        planning_source = raw
        if replace_owned:
            assert prior_ownership is not None
            remove_plan = plan_remove_pcodex(raw, prior_ownership)
            planning_source = apply_json5_edit_plan(raw, remove_plan)
        plan = plan_install_pcodex(planning_source, canonical_registration(root))
        updated = apply_json5_edit_plan(planning_source, plan)
    except (OpenClawJson5Error, OpenClawJson5ConflictError) as exc:
        raise OpenClawLifecycleError(str(exc)) from exc
    state_after = _new_state(
        workspace=root,
        authority=authority,
        compatibility=compatibility,
        ownership=plan.ownership,
        ownership_id=ownership_id,
        workspace_binding_id=workspace_binding_id,
        enabled=True,
        config_was_absent=config_was_absent,
    )
    journal = _base_journal(
        operation="install",
        ownership_id=ownership_id,
        config_path=authority.config_path,
        config_before=raw,
        config_after=updated,
        state_before_sha256=_state_content_hash(root),
        state_after=state_after,
    )
    _commit_config_and_state(
        root,
        journal=journal,
        config_path=authority.config_path,
        config_before=raw,
        config_after=updated,
        state_after=state_after,
    )
    return {
        "schema_version": "pcodex.openclaw-integration-result.v1",
        "status": "installed",
        "idempotent": False,
        "writes_performed": True,
        "workspace_binding_id": workspace_binding_id,
        "next_recommended_action": "pcodex integrate openclaw --status",
    }


def _remove_registration(
    workspace: Path,
    *,
    state: dict[str, Any],
    authority: OpenClawConfigAuthority,
    operation: str,
    keep_state: bool,
) -> dict[str, Any]:
    raw = _read_regular(authority.config_path, allow_missing=False)
    assert raw is not None
    ownership = _ownership_from_payload(state["editor_ownership"])
    try:
        plan = plan_remove_pcodex(raw, ownership)
        updated = apply_json5_edit_plan(raw, plan)
    except (OpenClawJson5Error, OpenClawJson5ConflictError) as exc:
        raise OpenClawLifecycleError(str(exc)) from exc
    state_after = dict(state) if keep_state else None
    if state_after is not None:
        state_after["enabled"] = False
    remove_created_config = bool(
        state["config_was_absent"] and updated == DEFAULT_CONFIG and not keep_state
    )
    journal = _base_journal(
        operation=operation,
        ownership_id=str(state["ownership_id"]),
        config_path=authority.config_path,
        config_before=raw,
        config_after=updated,
        state_before_sha256=_state_content_hash(workspace),
        state_after=state_after,
    )
    _commit_config_and_state(
        workspace,
        journal=journal,
        config_path=authority.config_path,
        config_before=raw,
        config_after=updated,
        state_after=state_after,
        remove_created_config=remove_created_config,
    )
    return {
        "schema_version": "pcodex.openclaw-integration-result.v1",
        "status": "disabled" if keep_state else "uninstalled",
        "writes_performed": True,
        "next_recommended_action": (
            "pcodex integrate openclaw --write" if keep_state else "none"
        ),
    }


def disable_integration(
    workspace: Path, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    root, _, _ = _workspace_identity(workspace)
    authority = _authority(environ)
    state = _load_state(root)
    if state is None:
        raise OpenClawLifecycleError("OpenClaw integration is not installed")
    _assert_authority_matches(state, authority)
    _assert_state_binding(state, root)
    if not state["enabled"]:
        raw = _read_regular(authority.config_path, allow_missing=True)
        inspection = inspect_pcodex_document(DEFAULT_CONFIG if raw is None else raw)
        if inspection.target_present:
            raise OpenClawLifecycleError(
                "disabled registration has conflicting active state"
            )
        return {
            "schema_version": "pcodex.openclaw-integration-result.v1",
            "status": "disabled",
            "idempotent": True,
            "writes_performed": False,
            "next_recommended_action": "pcodex integrate openclaw --write",
        }
    return _remove_registration(
        root, state=state, authority=authority, operation="disable", keep_state=True
    )


def uninstall_integration(
    workspace: Path,
    *,
    environ: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root, _, _ = _workspace_identity(workspace)
    authority = _authority(environ)
    state = _load_state(root)
    raw = _read_regular(authority.config_path, allow_missing=True)
    inspection = inspect_pcodex_document(DEFAULT_CONFIG if raw is None else raw)
    if state is None:
        if inspection.target_present:
            raise OpenClawLifecycleError(
                "existing pcodex registration has unknown ownership"
            )
        return {
            "schema_version": "pcodex.openclaw-integration-result.v1",
            "status": "already_absent",
            "dry_run": dry_run,
            "writes_performed": False,
            "next_recommended_action": "none",
        }
    _assert_authority_matches(state, authority)
    _assert_state_binding(state, root)
    if dry_run:
        if state["enabled"]:
            if raw is None:
                raise OpenClawLifecycleError("owned pcodex registration is missing")
            plan = plan_remove_pcodex(
                raw, _ownership_from_payload(state["editor_ownership"])
            )
            plan_payload: dict[str, Any] | None = _plan_payload(plan)
        else:
            if inspection.target_present:
                raise OpenClawLifecycleError(
                    "disabled registration has conflicting active state"
                )
            plan_payload = None
        return {
            "schema_version": "pcodex.openclaw-integration-preview.v1",
            "status": "uninstall_preview",
            "dry_run": True,
            "writes_performed": False,
            "processes_launched": False,
            "plan": plan_payload,
            "next_recommended_action": "pcodex integrate openclaw --uninstall",
        }
    if state["enabled"]:
        return _remove_registration(
            root,
            state=state,
            authority=authority,
            operation="uninstall",
            keep_state=False,
        )
    if inspection.target_present:
        raise OpenClawLifecycleError(
            "disabled registration has conflicting active state"
        )
    if state["config_was_absent"] and raw == DEFAULT_CONFIG:
        journal = _base_journal(
            operation="uninstall_disabled",
            ownership_id=str(state["ownership_id"]),
            config_path=authority.config_path,
            config_before=raw,
            config_after=raw,
            state_before_sha256=_state_content_hash(root),
            state_after=None,
        )
        _commit_config_and_state(
            root,
            journal=journal,
            config_path=authority.config_path,
            config_before=raw,
            config_after=raw,
            state_after=None,
            remove_created_config=True,
        )
        return {
            "schema_version": "pcodex.openclaw-integration-result.v1",
            "status": "uninstalled",
            "writes_performed": True,
            "next_recommended_action": "none",
        }
    state_path = root / STATE_RELATIVE
    state_raw = _read_regular(state_path, allow_missing=False)
    assert state_raw is not None
    journal = _base_journal(
        operation="uninstall_disabled",
        ownership_id=str(state["ownership_id"]),
        config_path=authority.config_path,
        config_before=DEFAULT_CONFIG if raw is None else raw,
        config_after=DEFAULT_CONFIG if raw is None else raw,
        state_before_sha256=_sha256(state_raw),
        state_after=None,
    )
    _write_journal_exclusive(root, journal)
    _safe_unlink(state_path, expected_hash=_sha256(state_raw))
    journal_raw = _read_regular(_journal_path(root), allow_missing=False)
    assert journal_raw is not None
    _safe_unlink(_journal_path(root), expected_hash=_sha256(journal_raw))
    return {
        "schema_version": "pcodex.openclaw-integration-result.v1",
        "status": "uninstalled",
        "writes_performed": True,
        "next_recommended_action": "none",
    }


def repair_integration(
    workspace: Path,
    *,
    environ: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root, _, _ = _workspace_identity(workspace)
    authority = _authority(environ)
    journal = _load_json(_journal_path(root), label="OpenClaw operation journal")
    if journal is not None:
        journal = _validate_journal(journal, workspace=root, authority=authority)
        raw = _read_regular(authority.config_path, allow_missing=True)
        current = DEFAULT_CONFIG if raw is None else raw
        current_hash = _sha256(current)
        state_before_hash = journal["state_before_sha256"]
        state_after = journal["state_after"]
        state_after_hash = (
            None if state_after is None else _sha256(_serialized_json(state_after))
        )
        current_state_hash = _state_content_hash(root)
        state_recoverable = current_state_hash in {
            state_before_hash,
            state_after_hash,
        }
        if dry_run:
            recoverable = (
                current_hash
                in {
                    journal["config_before_sha256"],
                    journal["config_after_sha256"],
                }
                and state_recoverable
            )
            return {
                "schema_version": "pcodex.openclaw-integration-preview.v1",
                "status": "repair_preview",
                "dry_run": True,
                "recoverable": recoverable,
                "writes_performed": False,
                "processes_launched": False,
                "next_recommended_action": (
                    "pcodex integrate openclaw --repair"
                    if recoverable
                    else "manual recovery is required"
                ),
            }
        if current_hash == journal["config_before_sha256"]:
            if current_state_hash != state_before_hash:
                raise OpenClawLifecycleError(
                    "interrupted OpenClaw state changed before recovery"
                )
            journal_raw = _read_regular(_journal_path(root), allow_missing=False)
            assert journal_raw is not None
            _safe_unlink(_journal_path(root), expected_hash=_sha256(journal_raw))
            prior_status = integration_status(root, environ=environ)
            return {
                "schema_version": "pcodex.openclaw-integration-result.v1",
                "status": "repaired",
                "recovery": "prior_state_preserved",
                "writes_performed": True,
                "readiness": prior_status.get("readiness"),
                "next_recommended_action": prior_status.get(
                    "next_recommended_action", "pcodex integrate openclaw --status"
                ),
            }
        if current_hash != journal["config_after_sha256"]:
            raise OpenClawLifecycleError(
                "interrupted OpenClaw operation is not safely recoverable"
            )
        if not state_recoverable:
            raise OpenClawLifecycleError(
                "interrupted OpenClaw state changed before recovery"
            )
        state_path = root / STATE_RELATIVE
        if current_state_hash == state_after_hash:
            pass
        elif state_after is None:
            state_raw = _read_regular(state_path, allow_missing=True)
            if state_raw is not None:
                if _sha256(state_raw) != state_before_hash:
                    raise OpenClawLifecycleError(
                        "interrupted OpenClaw state differs from journal authority"
                    )
                _safe_unlink(state_path, expected_hash=str(state_before_hash))
        else:
            assert isinstance(state_after, dict)
            _atomic_json(state_path, state_after)
        journal_raw = _read_regular(_journal_path(root), allow_missing=False)
        assert journal_raw is not None
        _safe_unlink(_journal_path(root), expected_hash=_sha256(journal_raw))
        return {
            "schema_version": "pcodex.openclaw-integration-result.v1",
            "status": "repaired",
            "writes_performed": True,
            "next_recommended_action": "pcodex integrate openclaw --status",
        }
    state = _load_state(root)
    if state is None:
        raise OpenClawLifecycleError(
            "OpenClaw integration has no repairable ownership receipt"
        )
    _assert_authority_matches(state, authority)
    _assert_state_binding(state, root)
    raw = _read_regular(authority.config_path, allow_missing=True)
    inspection = inspect_pcodex_document(DEFAULT_CONFIG if raw is None else raw)
    ownership = _ownership_from_payload(state["editor_ownership"])
    if not state["enabled"]:
        if inspection.target_present:
            raise OpenClawLifecycleError(
                "disabled registration has conflicting active state"
            )
        return {
            "schema_version": "pcodex.openclaw-integration-result.v1",
            "status": "disabled",
            "dry_run": dry_run,
            "writes_performed": False,
            "next_recommended_action": "pcodex integrate openclaw --write",
        }
    if inspection.target_value_sha256 == ownership.target_value_sha256:
        canonical_hash = _json_hash(canonical_registration(root))
        if (
            state["registration_value_sha256"] != canonical_hash
            or ownership.target_value_sha256 != canonical_hash
        ):
            if dry_run:
                return {
                    "schema_version": "pcodex.openclaw-integration-preview.v1",
                    "status": "repair_preview",
                    "dry_run": True,
                    "writes_performed": False,
                    "processes_launched": False,
                    "plan": {"operation": "replace_owned_helper_authority"},
                    "next_recommended_action": "pcodex integrate openclaw --repair",
                }
            return install_integration(root, environ=environ)
        return {
            "schema_version": "pcodex.openclaw-integration-result.v1",
            "status": "healthy",
            "dry_run": dry_run,
            "writes_performed": False,
            "next_recommended_action": "none",
        }
    if inspection.target_present:
        raise OpenClawLifecycleError("user-modified pcodex registration is preserved")
    if dry_run:
        plan = plan_install_pcodex(
            DEFAULT_CONFIG if raw is None else raw, canonical_registration(root)
        )
        return {
            "schema_version": "pcodex.openclaw-integration-preview.v1",
            "status": "repair_preview",
            "dry_run": True,
            "writes_performed": False,
            "processes_launched": False,
            "plan": _plan_payload(plan),
            "next_recommended_action": "pcodex integrate openclaw --repair",
        }
    return install_integration(root, environ=environ)
