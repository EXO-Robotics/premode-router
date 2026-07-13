from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import select
import shlex
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Sequence


SCHEMA_VERSION = "pcodex.no-write-evidence.v1"
PRIVATE_SCHEMA_VERSION = "pcodex.no-write-evidence.private.v1"
DEFAULT_FULL_HASH_LIMIT = 4 * 1024 * 1024
DEFAULT_SAMPLE_SIZE = 64 * 1024

REQUIRED_GOVERNED_ROOTS = {
    "repository": "repository",
    "repository_premode": "managed_state",
    "repository_pcodex": "user_state",
    "repository_codex_home": "integration_state",
    "repository_codex_plugins": "integration_state",
    "repository_marketplace": "integration_state",
    "user_pcodex": "user_state",
    "source_install": "package_state",
    "codex_config": "external_config",
    "codex_plugins": "integration_state",
    "codex_marketplace_external": "integration_state",
    "codex_marketplace": "integration_state",
    "codex_mcp": "external_config",
    "xdg_config": "user_state",
    "xdg_cache": "cache",
    "designated_temp": "temporary_state",
}

PUBLIC_SAFE_ARGUMENT_FLAGS = {
    "--advisory", "--apply", "--dry-run", "--json", "--local-marketplace",
    "--local-state", "--no-mcp", "--no-record", "--no-save", "--repo",
    "--repo-root", "--skip-tune", "--yes",
}


@dataclass(frozen=True)
class GovernedRoot:
    root_id: str
    path: Path
    category: str = "managed_state"


@dataclass(frozen=True)
class SnapshotPolicy:
    full_hash_limit: int = DEFAULT_FULL_HASH_LIMIT
    sample_size: int = DEFAULT_SAMPLE_SIZE


_ROOT_AUTHORITY_TOKEN = object()


def _root_manifest_sha256(roots: Sequence[GovernedRoot]) -> str:
    rows = [
        {
            "root_id": root.root_id,
            "category": root.category,
            "resolved_path": str(root.path.expanduser().absolute().resolve(strict=False)),
        }
        for root in roots
    ]
    return _sha256_bytes(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class GovernedRootSet(Sequence[GovernedRoot]):
    """Immutable, factory-bound root and resolved-path authority manifest."""

    __slots__ = ("_roots", "_manifest_sha256")
    authority = "premode.product.v2"

    def __init__(self, roots: Sequence[GovernedRoot], *, _token: object | None = None) -> None:
        if _token is not _ROOT_AUTHORITY_TOKEN:
            raise TypeError("GovernedRootSet must be created by governed_roots_from_product")
        self._roots = tuple(roots)
        self._manifest_sha256 = _root_manifest_sha256(self._roots)

    def __getitem__(self, index: int | slice) -> GovernedRoot | tuple[GovernedRoot, ...]:
        return self._roots[index]

    def __len__(self) -> int:
        return len(self._roots)

    @property
    def manifest_sha256(self) -> str:
        return self._manifest_sha256


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_regular_file(path: Path, size: int, policy: SnapshotPolicy) -> dict[str, Any]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    no_atime = getattr(os, "O_NOATIME", 0)
    if no_atime:
        flags |= no_atime
    try:
        descriptor = os.open(path, flags)
        atime_protection = "o_noatime"
    except PermissionError:
        descriptor = os.open(path, flags & ~no_atime)
        atime_protection = "platform_default"
    try:
        if size <= policy.full_hash_limit:
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return {
                "hash_strategy": "sha256_full",
                "content_sha256": digest.hexdigest(),
                "bytes_hashed": size,
                "atime_protection": atime_protection,
            }
        offsets = sorted({0, max(0, size // 2 - policy.sample_size // 2), max(0, size - policy.sample_size)})
        digest = hashlib.sha256()
        hashed = 0
        for offset in offsets:
            os.lseek(descriptor, offset, os.SEEK_SET)
            chunk = os.read(descriptor, min(policy.sample_size, size - offset))
            digest.update(f"{offset}:{len(chunk)}:".encode("ascii"))
            digest.update(chunk)
            hashed += len(chunk)
        return {
            "hash_strategy": "sha256_size_and_three_samples",
            "content_sha256": digest.hexdigest(),
            "bytes_hashed": hashed,
            "sample_offsets": offsets,
            "atime_protection": atime_protection,
        }
    finally:
        os.close(descriptor)


def _xattrs(path: Path) -> dict[str, Any]:
    if not hasattr(os, "listxattr"):
        return {"supported": False, "entries": []}
    try:
        names = sorted(os.listxattr(path, follow_symlinks=False))
    except (OSError, TypeError) as exc:
        return {"supported": True, "error": type(exc).__name__, "entries": []}
    entries = []
    for name in names:
        try:
            value = os.getxattr(path, name, follow_symlinks=False)
            entries.append({"name": name, "size": len(value), "sha256": _sha256_bytes(value)})
        except (OSError, TypeError) as exc:
            entries.append({"name": name, "error": type(exc).__name__})
    return {"supported": True, "entries": entries}


def _entry_type(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "character_device"
    if stat.S_ISBLK(mode):
        return "block_device"
    return "other"


def _snapshot_entry(path: Path, relative_path: str, policy: SnapshotPolicy) -> dict[str, Any]:
    try:
        info = path.lstat()
    except OSError as exc:
        return {"path": relative_path, "entry_type": "unreadable", "error": type(exc).__name__}
    entry: dict[str, Any] = {
        "path": relative_path,
        "resolved_path": str(path.resolve(strict=False)),
        "entry_type": _entry_type(info.st_mode),
        "device": getattr(info, "st_dev", None),
        "inode": getattr(info, "st_ino", None),
        "size": info.st_size,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": getattr(info, "st_uid", None),
        "gid": getattr(info, "st_gid", None),
        "mtime_ns": getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
        "ctime_ns": getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000)),
        "birthtime_ns": int(info.st_birthtime * 1_000_000_000) if hasattr(info, "st_birthtime") else None,
        "hard_link_count": getattr(info, "st_nlink", None),
        "extended_attributes": _xattrs(path),
    }
    if stat.S_ISLNK(info.st_mode):
        try:
            entry["symlink_target"] = os.readlink(path)
        except OSError as exc:
            entry["symlink_target_error"] = type(exc).__name__
    elif stat.S_ISREG(info.st_mode):
        try:
            entry.update(_hash_regular_file(path, info.st_size, policy))
        except OSError as exc:
            entry["content_error"] = type(exc).__name__
    return entry


def _walk_no_follow(root: Path, traversal_errors: list[dict[str, str]]) -> Iterable[tuple[Path, str]]:
    yield root, "."
    try:
        root_info = root.lstat()
    except OSError as exc:
        traversal_errors.append({"path": ".", "operation": "lstat", "error": type(exc).__name__})
        return
    stack: list[tuple[Path, str]] = [(root, ".")] if stat.S_ISDIR(root_info.st_mode) and not stat.S_ISLNK(root_info.st_mode) else []
    while stack:
        directory, relative = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: os.fsencode(item.name))
        except OSError as exc:
            traversal_errors.append({"path": relative, "operation": "scandir", "error": type(exc).__name__})
            continue
        directories: list[tuple[Path, str]] = []
        for child in children:
            child_path = directory / child.name
            child_relative = child.name if relative == "." else f"{relative}/{child.name}"
            yield child_path, child_relative
            try:
                if child.is_dir(follow_symlinks=False):
                    directories.append((child_path, child_relative))
            except OSError as exc:
                traversal_errors.append({"path": child_relative, "operation": "classify", "error": type(exc).__name__})
                continue
        stack.extend(reversed(directories))


def snapshot_roots(
    roots: Sequence[GovernedRoot],
    *,
    policy: SnapshotPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or SnapshotPolicy()
    root_records: list[dict[str, Any]] = []
    for governed in roots:
        path = governed.path.expanduser().absolute()
        record: dict[str, Any] = {
            "root_id": governed.root_id,
            "category": governed.category,
            "resolved_path": str(path.resolve(strict=False)),
            "exists": path.exists() or path.is_symlink(),
            "entries": [],
        }
        if record["exists"]:
            traversal_errors: list[dict[str, str]] = []
            record["entries"] = [_snapshot_entry(item, relative, policy) for item, relative in _walk_no_follow(path, traversal_errors)]
            record["traversal_errors"] = traversal_errors
            membership = [entry["path"] for entry in record["entries"]]
            record["directory_membership_sha256"] = _sha256_bytes(json.dumps(membership, ensure_ascii=False).encode("utf-8"))
        else:
            record["traversal_errors"] = []
        root_records.append(record)
    completeness_errors = []
    for root in root_records:
        completeness_errors.extend({"root_id": root["root_id"], **error} for error in root["traversal_errors"])
        for entry in root["entries"]:
            if entry.get("entry_type") == "unreadable" or entry.get("content_error") or entry.get("symlink_target_error"):
                completeness_errors.append({"root_id": root["root_id"], "path": entry["path"], "operation": "entry", "error": str(entry.get("error") or entry.get("content_error") or entry.get("symlink_target_error"))})
            xattrs = entry.get("extended_attributes") if isinstance(entry.get("extended_attributes"), dict) else {}
            if xattrs.get("error") or any(item.get("error") for item in xattrs.get("entries", [])):
                completeness_errors.append({"root_id": root["root_id"], "path": entry["path"], "operation": "xattr", "error": "unreadable_xattr"})
    payload = {
        "snapshot_format": "pcodex.no-write-snapshot.v1",
        "policy": asdict(policy),
        "roots": root_records,
        "complete": not completeness_errors,
        "completeness_errors": completeness_errors,
    }
    payload["snapshot_sha256"] = snapshot_hash(payload)
    return payload


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    normalized = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    return _sha256_bytes(json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    unchanged = snapshot_hash(before) == snapshot_hash(after)
    changes: list[dict[str, str]] = []
    if not unchanged:
        before_roots = {root["root_id"]: root for root in before.get("roots", [])}
        after_roots = {root["root_id"]: root for root in after.get("roots", [])}
        for root_id in sorted(set(before_roots) | set(after_roots)):
            left = before_roots.get(root_id)
            right = after_roots.get(root_id)
            if left == right:
                continue
            left_entries = {item["path"]: item for item in (left or {}).get("entries", [])}
            right_entries = {item["path"]: item for item in (right or {}).get("entries", [])}
            for relative in sorted(set(left_entries) | set(right_entries)):
                if left_entries.get(relative) != right_entries.get(relative):
                    kind = "created" if relative not in left_entries else "deleted" if relative not in right_entries else "modified"
                    changes.append({"root_id": root_id, "path": relative, "change": kind})
    return {"unchanged": unchanged, "changes": changes}


def governed_roots_from_product(
    repo_root: Path,
    *,
    home: Path | None = None,
    temp_root: Path | None = None,
    environ: dict[str, str] | None = None,
) -> GovernedRootSet:
    """Return bounded roots from premode.product.v2 state authority; never the full home."""
    env = os.environ if environ is None else environ
    home = (home or Path(env.get("HOME", "~"))).expanduser()
    roots = [
        GovernedRoot("repository", repo_root, "repository"),
        GovernedRoot("repository_premode", repo_root / ".premode", "managed_state"),
        GovernedRoot("repository_pcodex", repo_root / ".pcodex", "user_state"),
        GovernedRoot("repository_codex_home", repo_root / ".premode" / "pcodex_codex_home", "integration_state"),
        GovernedRoot("repository_codex_plugins", repo_root / "plugins" / "pcodex", "integration_state"),
        GovernedRoot("repository_marketplace", repo_root / ".agents" / "plugins" / "marketplace.json", "integration_state"),
    ]
    codex_home = Path(env.get("CODEX_HOME", home / ".codex"))
    candidates = [
        GovernedRoot("user_pcodex", home / ".pcodex", "user_state"),
        GovernedRoot("source_install", home / ".pcodex-alpha", "package_state"),
        GovernedRoot("codex_config", codex_home / "config.toml", "external_config"),
        GovernedRoot("codex_plugins", codex_home / "plugins" / "pcodex", "integration_state"),
        GovernedRoot("codex_marketplace_external", codex_home / "plugins" / "marketplace.json", "integration_state"),
        GovernedRoot("codex_marketplace", home / ".agents" / "plugins" / "marketplace.json", "integration_state"),
        GovernedRoot("codex_mcp", codex_home / "mcp.json", "external_config"),
        GovernedRoot("xdg_config", Path(env.get("XDG_CONFIG_HOME", home / ".config")) / "pcodex", "user_state"),
        GovernedRoot("xdg_cache", Path(env.get("XDG_CACHE_HOME", home / ".cache")) / "pcodex", "cache"),
    ]
    roots.extend(candidates)
    for index, variable in enumerate(("PCODEX_CONFIG", "PCODEX_CONFIG_PATH"), start=1):
        if env.get(variable):
            roots.append(GovernedRoot(f"explicit_pcodex_config_{index}", Path(env[variable]), "external_config"))
    if env.get("OPENCLAW_HOME"):
        roots.append(GovernedRoot("openclaw_config", Path(env["OPENCLAW_HOME"]) / "config.json", "external_config"))
    roots.append(GovernedRoot("designated_temp", temp_root or Path(env.get("TMPDIR", tempfile.gettempdir())), "temporary_state"))
    return GovernedRootSet(roots, _token=_ROOT_AUTHORITY_TOKEN)


class FilesystemActivityMonitor:
    """Best-effort transient-write detector using macOS kqueue vnode events."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.available = hasattr(select, "kqueue") and hasattr(select, "KQ_FILTER_VNODE")
        self.events: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._kqueue: Any = None
        self._fds: list[int] = []
        self._fd_records: dict[int, tuple[str, str]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "FilesystemActivityMonitor":
        if not self.available:
            return self
        try:
            self._kqueue = select.kqueue()
            for root in self.snapshot.get("roots", []):
                candidates = []
                if root.get("exists"):
                    candidates.extend(
                        (Path(entry["resolved_path"]), entry["path"])
                        for entry in root.get("entries", [])
                        if entry.get("entry_type") in {"regular", "directory"}
                    )
                else:
                    parent = Path(root["resolved_path"]).parent
                    while not (parent.exists() or parent == parent.parent):
                        parent = parent.parent
                    if parent.exists():
                        candidates.append((parent, "<missing-root-parent>"))
                for path, relative in candidates:
                    try:
                        descriptor = os.open(path, getattr(os, "O_EVTONLY", os.O_RDONLY) | getattr(os, "O_CLOEXEC", 0))
                        event = select.kevent(
                            descriptor,
                            filter=select.KQ_FILTER_VNODE,
                            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                            fflags=(
                                select.KQ_NOTE_WRITE
                                | select.KQ_NOTE_EXTEND
                                | select.KQ_NOTE_LINK
                                | select.KQ_NOTE_RENAME
                                | select.KQ_NOTE_DELETE
                                | select.KQ_NOTE_REVOKE
                            ),
                        )
                        self._kqueue.control([event], 0, 0)
                        self._fds.append(descriptor)
                        self._fd_records[descriptor] = (root["root_id"], relative)
                    except OSError as exc:
                        self.errors.append(f"{root['root_id']}:{relative}:{type(exc).__name__}")
            if self.errors:
                self.available = False
                self._close()
                return self
            self._thread = threading.Thread(target=self._poll, name="pcodex-no-write-filesystem-monitor", daemon=True)
            self._thread.start()
        except (OSError, ValueError) as exc:
            self.available = False
            self.errors.append(type(exc).__name__)
            self._close()
        return self

    def _poll(self) -> None:
        assert self._kqueue is not None
        while not self._stop.is_set():
            try:
                events = self._kqueue.control(None, 256, 0.01)
            except OSError as exc:
                self.errors.append(type(exc).__name__)
                self.available = False
                return
            for event in events:
                root_id, relative = self._fd_records.get(int(event.ident), ("unknown", "unknown"))
                self.events.append({"root_id": root_id, "path": relative, "flags": int(event.fflags)})

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._close()

    def _close(self) -> None:
        for descriptor in self._fds:
            try:
                os.close(descriptor)
            except OSError:
                pass
        self._fds.clear()
        if self._kqueue is not None:
            try:
                self._kqueue.close()
            except OSError:
                pass
            self._kqueue = None


def _read_process_table() -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    proc = Path("/proc")
    if proc.is_dir():
        for item in proc.iterdir():
            if not item.name.isdigit():
                continue
            try:
                raw = (item / "stat").read_text(encoding="utf-8", errors="replace")
                command = (item / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
                suffix = raw[raw.rfind(")") + 2 :].split()
                try:
                    executable_path = os.readlink(item / "exe")
                except OSError:
                    executable_path = command.split()[0] if command else None
                records[int(item.name)] = {"pid": int(item.name), "ppid": int(suffix[1]), "start_time": suffix[19], "executable_path": executable_path, "command": command}
            except (OSError, ValueError, IndexError):
                continue
        return records
    try:
        completed = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,lstart=,command="], text=True, capture_output=True, check=False, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return records
    for line in completed.stdout.splitlines():
        parts = line.strip().split(None, 7)
        if len(parts) < 8 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        records[int(parts[0])] = {"pid": int(parts[0]), "ppid": int(parts[1]), "start_time": " ".join(parts[2:7]), "executable_path": parts[7].split()[0] if parts[7] else None, "command": parts[7]}
    return records


def classify_process(command: str, executable_path: str | None = None) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    candidates = [Path(executable_path).name.lower()] if executable_path else []
    first = Path(tokens[0]).name.lower() if tokens else ""
    candidates.append(first)
    python_wrappers = {"python", "python3", "python3.11", "python3.12", "python3.13"}
    script_wrappers = {"sh", "bash", "zsh", "fish", "node", "npx", "bun", "ruby"}
    if first in python_wrappers:
        if "-m" in tokens:
            module_index = tokens.index("-m") + 1
            if module_index < len(tokens):
                candidates.append(tokens[module_index].lower())
        elif "-c" not in tokens:
            target = next((token for token in tokens[1:] if token and not token.startswith("-")), None)
            if target:
                candidates.append(Path(target).name.lower())
    elif first in script_wrappers:
        target = next((token for token in tokens[1:] if token and not token.startswith("-")), None)
        if target:
            candidates.append(Path(target).name.lower())
    elif first == "env":
        target = next((token for token in tokens[1:] if token and not token.startswith("-") and "=" not in token), None)
        if target:
            candidates.append(Path(target).name.lower())
    normalized: list[str] = []
    for executable in candidates:
        name = re.sub(r"\.(?:c?js|mjs|py)$", "", executable)
        normalized.extend((executable, name, name.rsplit(".", 1)[-1]))
    for executable in normalized:
        if executable == "codex":
            return "codex"
        if executable.startswith("openclaw"):
            return "openclaw"
        if (
            executable in {"mcp", "mcp-server", "mcp_server"}
            or executable.endswith(("-mcp-server", "_mcp_server"))
            or (executable.startswith("mcp-") and "server" in executable)
        ):
            return "mcp"
        if executable in {"ollama", "llama-server", "llama_cpp", "qwen"}:
            return "local_model"
        if executable in {"celery", "rq", "dramatiq"}:
            return "background_worker"
    return None


class ProcessMonitor:
    def __init__(self, *, interval_seconds: float = 0.02) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.before: dict[int, dict[str, Any]] = {}
        self.after: dict[int, dict[str, Any]] = {}
        self.observed: dict[tuple[int, str], dict[str, Any]] = {}
        self.root_pid = os.getpid()

    def __enter__(self) -> "ProcessMonitor":
        self.before = _read_process_table()
        self._thread = threading.Thread(target=self._poll, name="pcodex-no-write-process-monitor", daemon=True)
        self._thread.start()
        return self

    def _poll(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            for record in _read_process_table().values():
                if record["pid"] not in self.before:
                    self.observed[(record["pid"], str(record["start_time"]))] = record

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self.after = _read_process_table()
        for record in self.after.values():
            if record["pid"] not in self.before:
                self.observed[(record["pid"], str(record["start_time"]))] = record

    @property
    def observation_available(self) -> bool:
        return bool(self.before) and bool(self.after)

    @property
    def forbidden(self) -> list[dict[str, Any]]:
        findings = []
        process_index = {**self.before, **{record["pid"]: record for record in self.observed.values()}, **self.after}

        def is_descendant(record: dict[str, Any]) -> bool:
            seen: set[int] = set()
            parent = int(record.get("ppid") or 0)
            while parent > 0 and parent not in seen:
                if parent == self.root_pid:
                    return True
                seen.add(parent)
                ancestor = process_index.get(parent)
                if ancestor is None:
                    return False
                parent = int(ancestor.get("ppid") or 0)
            return False

        for record in self.observed.values():
            classification = classify_process(str(record.get("command") or ""), str(record.get("executable_path") or "") or None)
            if classification and is_descendant(record):
                findings.append({**record, "classification": classification, "survived": record["pid"] in self.after})
        return sorted(findings, key=lambda item: (item["pid"], item["classification"]))


def verify_no_write(
    operation: Callable[[], Any],
    *,
    roots: Sequence[GovernedRoot],
    monitor_processes: bool = True,
    monitor_filesystem: bool = False,
    policy: SnapshotPolicy | None = None,
) -> dict[str, Any]:
    before = snapshot_roots(roots, policy=policy)
    started = time.perf_counter()
    value: Any = None
    exceptions: list[str] = []
    process_observation = "disabled"
    filesystem_observation = "disabled"
    transient_filesystem_events: list[dict[str, Any]] = []
    filesystem_monitor = FilesystemActivityMonitor(before)
    try:
        if monitor_filesystem:
            filesystem_monitor.__enter__()
            filesystem_observation = "complete" if filesystem_monitor.available else "unavailable"
        try:
            if monitor_processes:
                with ProcessMonitor() as process_monitor:
                    value = operation()
                forbidden = process_monitor.forbidden
                process_observation = "complete" if process_monitor.observation_available else "unavailable"
            else:
                value = operation()
                forbidden = []
        finally:
            if monitor_filesystem:
                filesystem_monitor.__exit__(None, None, None)
                transient_filesystem_events = filesystem_monitor.events
                filesystem_observation = "complete" if filesystem_monitor.available and not filesystem_monitor.errors else "unavailable"
    except BaseException as exc:
        exceptions.append(type(exc).__name__)
        if monitor_processes:
            forbidden = process_monitor.forbidden
            process_observation = "complete" if process_monitor.observation_available else "unavailable"
        else:
            forbidden = []
    elapsed = time.perf_counter() - started
    after = snapshot_roots(roots, policy=policy)
    comparison = compare_snapshots(before, after)
    return {
        "before": before,
        "after": after,
        "comparison": comparison,
        "forbidden_processes_launched": forbidden,
        "process_observation": process_observation,
        "filesystem_observation": filesystem_observation,
        "transient_filesystem_events": transient_filesystem_events,
        "exceptions": exceptions,
        "root_authority": (
            roots.authority
            if isinstance(roots, GovernedRootSet)
            and roots.manifest_sha256 == _root_manifest_sha256(roots)
            else None
        ),
        "root_authority_manifest_sha256": (
            roots.manifest_sha256
            if isinstance(roots, GovernedRootSet)
            and roots.manifest_sha256 == _root_manifest_sha256(roots)
            else None
        ),
        "passed": bool(roots) and len({root.root_id for root in roots}) == len(roots) and comparison["unchanged"] and before.get("complete", False) and after.get("complete", False) and not forbidden and not transient_filesystem_events and not exceptions and (not monitor_processes or process_observation == "complete") and (not monitor_filesystem or filesystem_observation == "complete"),
        "elapsed_seconds": elapsed,
        "value": value,
    }


def _sanitize_arguments(arguments: Sequence[str]) -> list[str]:
    sanitized: list[str] = []
    for argument in arguments:
        if argument.startswith("-") and "=" in argument:
            flag, value = argument.split("=", 1)
            if flag in PUBLIC_SAFE_ARGUMENT_FLAGS:
                sanitized.append(f"{flag}=opaque:{_sha256_bytes(value.encode('utf-8'))[:12]}")
            else:
                sanitized.append(f"opaque:{_sha256_bytes(argument.encode('utf-8'))[:12]}")
        elif argument in PUBLIC_SAFE_ARGUMENT_FLAGS:
            sanitized.append(argument)
        else:
            sanitized.append(f"opaque:{_sha256_bytes(argument.encode('utf-8'))[:12]}")
    return sanitized


def evidence_receipt(
    verification: dict[str, Any],
    *,
    product_version: str,
    commit_sha: str,
    command: str,
    arguments: Sequence[str],
    scenario_id: str,
    timestamp: str,
    sanitized: bool = True,
) -> dict[str, Any]:
    before = verification["before"]
    after = verification["after"]
    comparison = verification["comparison"]
    root_rows = before.get("roots", [])
    governed = [
        {"root_id": item["root_id"], "category": item["category"], "exists": item["exists"]}
        for item in root_rows
    ]
    forbidden_processes = verification["forbidden_processes_launched"]
    if sanitized:
        forbidden_processes = [
            {
                "classification": item.get("classification"),
                "survived": bool(item.get("survived")),
                "process_id": f"opaque:{_sha256_bytes(str(item.get('pid')).encode())[:12]}",
            }
            for item in forbidden_processes
        ]
    root_categories = {item["root_id"]: item["category"] for item in root_rows}
    external_categories = {"external_config", "integration_state", "package_state"}
    external_governed = any(category in external_categories for category in root_categories.values())
    temporary_governed = "temporary_state" in root_categories.values()
    coverage_complete = (
        verification.get("root_authority") == "premode.product.v2"
        and all(root_categories.get(root_id) == category for root_id, category in REQUIRED_GOVERNED_ROOTS.items())
    )
    external_changes = [change for change in comparison["changes"] if root_categories.get(change["root_id"]) in external_categories]
    temporary_changes = [change for change in comparison["changes"] if root_categories.get(change["root_id"]) == "temporary_state"]
    safe_command = command
    if sanitized and re.fullmatch(r"[a-z0-9_.-]+", command) is None:
        safe_command = f"opaque:{_sha256_bytes(command.encode('utf-8'))[:12]}"
    observations_complete = (
        verification.get("process_observation") == "complete"
        and verification.get("filesystem_observation") == "complete"
    )
    evidence_exceptions = [
        *list(verification.get("exceptions") or []),
        *([] if coverage_complete else ["incomplete_governed_root_coverage"]),
        *([] if verification.get("process_observation") == "complete" else ["incomplete_process_observation"]),
        *([] if verification.get("filesystem_observation") == "complete" else ["incomplete_filesystem_observation"]),
    ]
    receipt = {
        "schema_version": SCHEMA_VERSION if sanitized else PRIVATE_SCHEMA_VERSION,
        "product_version": product_version,
        "commit_sha": commit_sha,
        "command": safe_command,
        "arguments": _sanitize_arguments(arguments),
        "scenario_id": scenario_id,
        "governed_roots": governed,
        "before_snapshot_hash": snapshot_hash(before),
        "after_snapshot_hash": snapshot_hash(after),
        "filesystem_unchanged": comparison["unchanged"] and not verification.get("transient_filesystem_events"),
        "external_config_unchanged": external_governed and not external_changes,
        "temporary_state_unchanged": temporary_governed and not temporary_changes,
        "forbidden_processes_launched": forbidden_processes,
        "network_attempted_if_measurable": "not_measured",
        "result": "pass" if verification["passed"] and coverage_complete and observations_complete else "fail",
        "exceptions": evidence_exceptions,
        "snapshot_complete": bool(before.get("complete") and after.get("complete")),
        "process_observation": verification.get("process_observation", "unknown"),
        "filesystem_observation": verification.get("filesystem_observation", "unknown"),
        "coverage_complete": coverage_complete,
        "transient_filesystem_events": [
            {"root_id": item.get("root_id"), "path": item.get("path"), "flags": item.get("flags")}
            for item in verification.get("transient_filesystem_events", [])
        ] if not sanitized else [
            {"root_id": item.get("root_id"), "path_id": f"opaque:{_sha256_bytes(str(item.get('path')).encode())[:12]}", "flags": item.get("flags")}
            for item in verification.get("transient_filesystem_events", [])
        ],
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "timestamp": timestamp,
    }
    if not sanitized:
        receipt["detailed_changes"] = comparison["changes"]
        receipt["governed_root_paths"] = {item["root_id"]: item["resolved_path"] for item in root_rows}
    return receipt


def write_evidence_receipts(
    output_dir: Path,
    verification: dict[str, Any],
    **receipt_fields: Any,
) -> tuple[Path, Path]:
    """Write only after verification, to a caller-owned directory outside governed roots."""
    resolved_output = output_dir.expanduser().resolve(strict=False)
    for root in verification.get("before", {}).get("roots", []):
        resolved_root = Path(root["resolved_path"]).resolve(strict=False)
        if resolved_output == resolved_root or resolved_root in resolved_output.parents or resolved_output in resolved_root.parents:
            raise ValueError(f"evidence output overlaps governed root: {root['root_id']}")
    output_dir.mkdir(parents=True, exist_ok=True)
    private_path = output_dir / "no-write-evidence.private.json"
    public_path = output_dir / "no-write-evidence.sanitized.json"
    private_path.write_text(json.dumps(evidence_receipt(verification, sanitized=False, **receipt_fields), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    public_path.write_text(json.dumps(evidence_receipt(verification, sanitized=True, **receipt_fields), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return private_path, public_path
