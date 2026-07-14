#!/usr/bin/env python3
"""Capture and finalize one private, coordinator-witnessed first-run journey."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from typing import Any, Iterator


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from first_run_study_authority import ARTIFACT_HASH_CODE  # noqa: E402
import validate_first_run_study as validator  # noqa: E402


MAX_STATE_BYTES = 16 * 1024 * 1024
CHECKPOINT_AFTER = {
    "fixture-01": {
        "missing_codex_status": "after_expected_missing_codex",
        "managed_uninstall_apply": "after_managed_uninstall",
    },
    "fixture-02": {
        "codex_uninstall_apply": "after_integration_uninstall",
        "codex_reinstall": "after_reinstall",
        "codex_final_uninstall": "after_final_integration_uninstall",
        "managed_uninstall_apply": "after_managed_uninstall",
    },
    "fixture-03": {
        "codex_uninstall_apply": "after_integration_uninstall",
        "codex_final_uninstall": "after_final_integration_uninstall",
        "managed_uninstall_apply": "after_managed_uninstall",
    },
    "fixture-04": {
        "codex_uninstall_apply": "after_integration_uninstall",
        "codex_reinstall": "after_reinstall",
        "codex_final_uninstall": "after_final_integration_uninstall",
        "managed_uninstall_apply": "after_managed_uninstall",
    },
    "fixture-05": {
        "mcp_uninstall_apply": "after_mcp_uninstall",
        "mcp_final_uninstall": "after_final_integration_uninstall",
        "managed_uninstall_apply": "after_managed_uninstall",
    },
}


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_key(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("attestation key must be a regular file")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("attestation key permissions must be 0600 or stricter")
    key = path.read_bytes()
    if not 32 <= len(key) <= 4096:
        raise ValueError("attestation key length is invalid")
    return key


def _session_lock_path(session: Path) -> Path:
    return session.with_name(session.name.removesuffix(".json") + ".lock")


def _create_session_lock(session: Path) -> None:
    lock = _session_lock_path(session)
    descriptor = os.open(
        lock,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    os.close(descriptor)
    directory = os.open(lock.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def _session_transition_lock(session: Path) -> Iterator[None]:
    lock = _session_lock_path(session)
    if lock.is_symlink() or not lock.is_file() or lock.stat().st_size != 0:
        raise ValueError("session transition lock authority is invalid")
    descriptor = os.open(lock, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            raise ValueError("session transition lock must be private")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _state_signature(state: dict[str, Any], key: bytes) -> str:
    unsigned = {name: value for name, value in state.items() if name != "signature"}
    return hmac.new(key, _json_bytes(unsigned), hashlib.sha256).hexdigest()


def _parse_attempt_ledger(data: bytes, key: bytes) -> list[dict[str, Any]]:
    if len(data) > MAX_STATE_BYTES:
        raise ValueError("attempt ledger exceeds its size bound")
    entries: list[dict[str, Any]] = []
    previous = "0" * 64
    for sequence, line in enumerate(data.splitlines(), start=1):
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("attempt ledger chain is invalid") from exc
        signature = entry.get("signature")
        unsigned = {name: value for name, value in entry.items() if name != "signature"}
        if not all(
            (
                entry.get("schema_version") == "pcodex.first-run-attempt-ledger.v1",
                entry.get("sequence") == sequence,
                entry.get("previous_entry_sha256") == previous,
                isinstance(signature, str),
                hmac.compare_digest(
                    signature,
                    hmac.new(key, _json_bytes(unsigned), hashlib.sha256).hexdigest(),
                ),
            )
        ):
            raise ValueError("attempt ledger chain is invalid")
        entries.append(entry)
        previous = _sha(_json_bytes(entry))
    return entries


def _read_attempt_ledger(path: Path, key: bytes) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("attempt ledger authority is invalid")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        file_stat = os.fstat(descriptor)
        if (
            file_stat.st_size > MAX_STATE_BYTES
            or stat.S_IMODE(file_stat.st_mode) & 0o077
        ):
            raise ValueError("attempt ledger authority is invalid")
        data = os.read(descriptor, MAX_STATE_BYTES + 1)
        return _parse_attempt_ledger(data, key)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _append_attempt_ledger(
    path: Path,
    state: dict[str, Any],
    state_sha256: str,
    key: bytes,
    predecessor_state_sha256: str | None = None,
) -> None:
    if path.is_symlink():
        raise ValueError("attempt ledger must not be a symlink")
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            raise ValueError("attempt ledger must be private")
        os.lseek(descriptor, 0, os.SEEK_SET)
        entries = _parse_attempt_ledger(os.read(descriptor, MAX_STATE_BYTES + 1), key)
        fixture_id = state["fixture"]["id"]
        fixture_entries = [item for item in entries if item["fixture_id"] == fixture_id]
        initial = (
            state.get("status") == "recording"
            and state.get("cursor") == 0
            and state.get("events") == []
            and state.get("failed_attempts") == []
        )
        if initial and fixture_entries:
            raise ValueError("preassigned fixture attempt has already been consumed")
        if not initial and not fixture_entries:
            raise ValueError("attempt ledger is missing the fixture initialization")
        if fixture_entries and (
            predecessor_state_sha256 is None
            or fixture_entries[-1]["state_sha256"] != predecessor_state_sha256
        ):
            raise ValueError("attempt transition does not descend from current state")
        if fixture_entries:
            previous_status = fixture_entries[-1]["state_status"]
            previous_cursor = fixture_entries[-1]["cursor"]
            legal_transition = (
                (
                    state["status"] == "recording"
                    and previous_status == "recording"
                    and int(state["cursor"]) == previous_cursor + 1
                )
                or (
                    state["status"] == "failed_closed"
                    and previous_status == "recording"
                    and int(state["cursor"]) == previous_cursor
                )
                or (
                    state["status"] == "reviewed"
                    and previous_status == "recording"
                    and int(state["cursor"]) == previous_cursor
                )
                or (
                    state["status"] == "finalizing"
                    and previous_status == "reviewed"
                    and int(state["cursor"]) == previous_cursor
                )
                or (
                    state["status"] == "finalized"
                    and previous_status == "finalizing"
                    and int(state["cursor"]) == previous_cursor
                )
            )
            if not legal_transition:
                raise ValueError("attempt state transition is not monotonic")
        entry: dict[str, Any] = {
            "schema_version": "pcodex.first-run-attempt-ledger.v1",
            "sequence": len(entries) + 1,
            "previous_entry_sha256": (
                _sha(_json_bytes(entries[-1])) if entries else "0" * 64
            ),
            "fixture_id": fixture_id,
            "tester_id": state["tester_id"],
            "state_status": state["status"],
            "cursor": int(state["cursor"]),
            "failed_attempt_count": len(state.get("failed_attempts", [])),
            "state_sha256": state_sha256,
        }
        entry["signature"] = hmac.new(
            key, _json_bytes(entry), hashlib.sha256
        ).hexdigest()
        os.write(descriptor, _json_bytes(entry) + b"\n")
        os.fsync(descriptor)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_state(path: Path, state: dict[str, Any], key: bytes) -> None:
    predecessor = state.pop("_ledger_predecessor_sha256", None)
    state["signature"] = _state_signature(state, key)
    data = json.dumps(state, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    ledger = state.get("attempt_ledger")
    if isinstance(ledger, str):
        _append_attempt_ledger(Path(ledger), state, _sha(data), key, predecessor)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()
    state["_ledger_predecessor_sha256"] = _sha(data)


def _read_state(path: Path, key: bytes) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
        raise ValueError("invalid recorder session")
    data = path.read_bytes()
    state = json.loads(data)
    signature = state.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, _state_signature(state, key)
    ):
        raise ValueError("recorder session signature mismatch")
    ledger = state.get("attempt_ledger")
    if isinstance(ledger, str):
        entries = _read_attempt_ledger(Path(ledger), key)
        fixture_id = state.get("fixture", {}).get("id")
        fixture_entries = [
            item for item in entries if item.get("fixture_id") == fixture_id
        ]
        if (
            not fixture_entries
            or fixture_entries[-1].get("tester_id") != state.get("tester_id")
            or fixture_entries[-1].get("state_sha256") != _sha(data)
        ):
            raise ValueError("attempt ledger does not match the current session")
        state["_ledger_predecessor_sha256"] = _sha(data)
    return state


def _measurement(repository: Path, surface: dict[str, str]) -> bytes:
    path = repository / surface["relative_path"]
    if surface["measurement_kind"] in {"file_bytes", "post_restore_file_bytes"}:
        if path.is_symlink() or not path.is_file():
            raise ValueError("preservation file is missing")
        return path.read_bytes()
    if path.is_symlink() or not path.is_dir():
        raise ValueError("preservation directory is missing")
    entries = [
        {
            "path": item.relative_to(path).as_posix(),
            "sha256": _sha(item.read_bytes()),
        }
        for item in sorted(path.rglob("*"))
        if item.is_file() and not item.is_symlink()
    ]
    return _json_bytes(entries)


def _repository_member_hashes(repository: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(repository.rglob("*")):
        relative = path.relative_to(repository)
        if relative.parts and relative.parts[0].casefold() == ".git":
            continue
        if relative.as_posix() == "dirty-untracked.txt":
            continue
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("restored fixture contains an unsupported object")
        if path.is_file():
            result[relative.as_posix()] = validator._sha256(path)
    return result


def _assert_restored_fixture(
    repository: Path, fixture: dict[str, Any], git_executable: Path
) -> None:
    if _repository_member_hashes(repository) != fixture["member_sha256"]:
        raise ValueError("repository does not match the restored fixture authority")
    status = subprocess.run(
        (str(git_executable), "status", "--porcelain=v1", "-z"),
        cwd=repository,
        env={
            "HOME": os.devnull,
            "PATH": f"{git_executable.parent}:/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "LC_ALL": "C",
        },
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout
    expected = b"?? dirty-untracked.txt\x00" if fixture["id"] == "fixture-02" else b""
    if status != expected:
        raise ValueError("restored fixture Git state mismatch")


def _initial_condition_observations(
    repository: Path,
    fixture: dict[str, Any],
    environment: dict[str, str],
    codex_version: str,
) -> dict[str, str]:
    observations: dict[str, str] = {}
    for condition in fixture["conditions"]:
        if condition in {"optional_mcp", "install_twice", "uninstall_reinstall"}:
            continue
        if condition == "clean_repository":
            value = b"git_status=clean\n"
        elif condition == "dirty_repository":
            value = b"git_status=dirty_untracked_fixture_only\n"
        elif condition == "missing_codex":
            if codex_version != "absent" or shutil.which(
                "codex", path=environment["PATH"]
            ):
                raise ValueError("missing-Codex fixture unexpectedly resolves Codex")
            value = b"codex_version=absent\n"
        elif condition == "supported_codex_0.143.x":
            if not codex_version.startswith("0.143."):
                raise ValueError("supported Codex condition is false")
            value = f"codex_version={codex_version}\n".encode()
        elif condition == "mcp_absent":
            codex_home = Path(environment["CODEX_HOME"])
            if any(codex_home.rglob("*")):
                raise ValueError("MCP-absent fixture has Codex state")
            value = b"mcp_state=absent\n"
        elif condition == "unrelated_agents":
            path = repository / ".agents/unrelated/README.md"
            if not path.is_file():
                raise ValueError("unrelated .agents fixture is missing")
            authority = next(
                surface["initial_sha256"]
                for surface in fixture["preservation_surfaces"]
                if surface["name"] == "unrelated_agents"
            )
            value = f"unrelated_agents_sha256={authority}\n".encode()
        elif condition in {"unrelated_codex_config"}:
            path = repository / "fixture-codex-home/config.toml"
            if not path.is_file():
                raise ValueError("unrelated Codex config fixture is missing")
            value = f"codex_config_sha256={validator._sha256(path)}\n".encode()
        elif condition == "path_with_spaces":
            if " " not in str(repository):
                raise ValueError("fixture path does not contain a space")
            value = b"path_contains_space=true\n"
        elif condition == "unicode_path":
            if str(repository).isascii():
                raise ValueError("fixture path does not contain Unicode")
            value = b"path_contains_unicode=true\n"
        elif condition == "supported_legacy_plugin":
            legacy = [
                name for name in fixture["member_sha256"] if name.startswith(".agents/")
            ]
            if not legacy:
                raise ValueError("supported legacy fixture is missing")
            value = f"legacy_member_manifest_sha256={validator._canonical_json_sha256(legacy)}\n".encode()
        else:
            raise ValueError(f"unsupported fixture condition: {condition}")
        observations[condition] = base64.b64encode(value).decode("ascii")
    return observations


def _derive_post_conditions(state: dict[str, Any]) -> None:
    accepted = [event["operation"] for event in state["events"]]
    required: dict[str, tuple[str, ...]] = {
        "optional_mcp": ("mcp_apply", "mcp_status", "mcp_final_uninstall"),
        "install_twice": ("mcp_apply", "mcp_install_idempotent"),
        "uninstall_reinstall": (
            "mcp_uninstall_apply",
            "mcp_reinstall",
            "codex_status_final",
        ),
    }
    for condition in state["fixture"]["conditions"]:
        if condition not in required:
            continue
        if not all(operation in accepted for operation in required[condition]):
            raise ValueError(f"postcondition was not proven: {condition}")
        observation = (
            f"condition={condition};operations=" + ",".join(required[condition]) + "\n"
        ).encode()
        state["condition_observations"][condition] = base64.b64encode(
            observation
        ).decode("ascii")


def _capture_checkpoint(state: dict[str, Any], checkpoint: str) -> None:
    repository = Path(state["repository_root"])
    fixture = state["fixture"]
    values: dict[str, str] = {}
    for surface in fixture["preservation_surfaces"]:
        measurement = _measurement(repository, surface)
        if _sha(measurement) != surface["initial_sha256"]:
            raise ValueError("unrelated state no longer matches frozen authority")
        values[surface["name"]] = base64.b64encode(measurement).decode("ascii")
    state["preservation"][checkpoint] = values


def _operation_argv(
    operation: str, state: dict[str, Any]
) -> tuple[list[str], str, list[str]]:
    wheel = state["payload_wheel"]
    venv = Path(state["venv_root"])
    python = Path(state["runtime_python"])
    pcodex = venv / "bin/pcodex"
    if operation == "artifact_verify":
        argv = [str(python), "-c", ARTIFACT_HASH_CODE, wheel]
        return argv, str(python), argv
    if operation == "venv_create":
        argv = [str(python), "-m", "venv", str(venv)]
        return argv, str(python), argv
    if operation == "package_install":
        executable = venv / "bin/python"
        argv = [
            str(executable),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            wheel,
        ]
        return argv, str(executable), argv
    fixed: dict[str, list[str]] = {
        "help": ["pcodex", "--help"],
        "doctor_advisory": ["pcodex", "doctor", "--advisory", "--json"],
        "status_advisory": ["pcodex", "status", "--advisory", "--json"],
        "run_dry_run": [
            "pcodex",
            "run",
            "--dry-run",
            "Fix the failing test",
            "--json",
        ],
        "managed_install_preview": ["pcodex", "install", "--json"],
        "managed_install_apply": ["pcodex", "install", "--apply", "--json"],
        "managed_uninstall_preview": [
            "pcodex",
            "uninstall",
            "--dry-run",
            "--json",
        ],
        "managed_uninstall_apply": ["pcodex", "uninstall", "--yes", "--json"],
    }
    command_argv = fixed.get(operation)
    if command_argv is None:
        order = [
            flag
            for flag in (
                "--dry-run",
                "--write",
                "--status",
                "--repair",
                "--disable",
                "--uninstall",
                "--migrate",
                "--with-mcp",
            )
            if flag in validator.INTEGRATE_FLAGS[operation]
        ]
        command_argv = ["pcodex", "integrate", "codex", *order, "--json"]
    return command_argv, str(pcodex), [str(pcodex), *command_argv[1:]]


def _controlled_environment(state: dict[str, Any]) -> dict[str, str]:
    return dict(state["controlled_environment"])


def _filesystem_snapshot(*roots: Path) -> str:
    entries: list[dict[str, Any]] = []
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("no-write root authority is invalid")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("no-write root contains a symlink")
            stat_result = path.stat()
            item: dict[str, Any] = {
                "root": str(root),
                "path": path.relative_to(root).as_posix(),
                "kind": "file" if path.is_file() else "directory",
                "mode": stat.S_IMODE(stat_result.st_mode),
                "mtime_ns": stat_result.st_mtime_ns,
            }
            if path.is_file():
                item["size"] = stat_result.st_size
                item["sha256"] = validator._sha256(path)
            entries.append(item)
    return validator._canonical_json_sha256(entries)


def _codex_wrapper_command(codex: Path) -> tuple[list[str], dict[str, Any]]:
    if not codex.is_absolute() or not codex.is_file():
        raise ValueError("--codex must be an absolute file")
    target = codex.resolve(strict=True)
    first_line = target.read_bytes().splitlines()[:1]
    command = [str(target)]
    interpreter: Path | None = None
    if first_line and first_line[0].startswith(b"#!"):
        shebang = first_line[0][2:].decode("utf-8", errors="strict").strip()
        if shebang == "/usr/bin/env node":
            found = shutil.which("node")
            if found is None:
                raise ValueError("Codex node interpreter is unavailable")
            interpreter = Path(found).resolve(strict=True)
        else:
            interpreter = Path(shlex.split(shebang)[0]).resolve(strict=True)
        if interpreter.is_symlink() or not interpreter.is_file():
            raise ValueError("Codex interpreter authority is invalid")
        command = [str(interpreter), str(target)]
    authority = {
        "requested_path": str(codex),
        "requested_symlink_target": os.readlink(codex) if codex.is_symlink() else None,
        "target_path": str(target),
        "target_sha256": validator._sha256(target),
        "interpreter_path": str(interpreter) if interpreter else None,
        "interpreter_sha256": validator._sha256(interpreter) if interpreter else None,
    }
    return command, authority


def _verify_codex_authority(state: dict[str, Any]) -> None:
    authority = state.get("codex_authority")
    if authority is None:
        return
    target = Path(authority["target_path"])
    requested = Path(authority["requested_path"])
    if (
        not requested.is_file()
        or requested.resolve() != target
        or (os.readlink(requested) if requested.is_symlink() else None)
        != authority["requested_symlink_target"]
    ):
        raise ValueError("Codex executable resolution changed during the study")
    if target.is_symlink() or validator._sha256(target) != authority["target_sha256"]:
        raise ValueError("Codex target authority changed during the study")
    if authority["interpreter_path"] is not None:
        interpreter = Path(authority["interpreter_path"])
        if (
            interpreter.is_symlink()
            or validator._sha256(interpreter) != authority["interpreter_sha256"]
        ):
            raise ValueError("Codex interpreter authority changed during the study")
    wrapper = Path(authority["wrapper_path"])
    if (
        wrapper.is_symlink()
        or validator._sha256(wrapper) != authority["wrapper_sha256"]
    ):
        raise ValueError("Codex wrapper authority changed during the study")


def _command_evidence(event: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "pcodex.first-run-study-evidence.v1",
        "kind": "command",
        "tester_id": state["tester_id"],
        "fixture_id": state["fixture"]["id"],
        "study_kit_sha256": state["study_kit_sha256"],
        "sequence": event["sequence"],
        "operation": event["operation"],
        "argv": event["argv"],
        "resolved_executable": event["resolved_executable"],
        "cwd": state["repository_root"],
        "controlled_environment": state["controlled_environment"],
        "venv_root": state["venv_root"],
        "runtime_authority_sha256": event["runtime_authority_sha256"],
        "no_write_observation_sha256": event["no_write_observation_sha256"],
        "started_seconds": event["started_seconds"],
        "completed_seconds": event["completed_seconds"],
        "exit_code": event["exit_code"],
        "stdout_base64": event["stdout_base64"],
        "stderr_base64": event["stderr_base64"],
        "normalized_result": event["result"],
        "sensitivity_reviewed": True,
    }


def _store_content(directory: Path, suffix: str, payload: dict[str, Any]) -> str:
    data = _json_bytes(payload)
    digest = _sha(data)
    path = directory / f"{digest}{suffix}"
    _atomic_private_file(path, data, replace_incomplete=True)
    return digest


def _atomic_private_file(
    path: Path, data: bytes, *, replace_incomplete: bool = False
) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                "existing private output does not match recovery authority"
            )
        if path.read_bytes() == data:
            return
        if not replace_incomplete:
            raise ValueError(
                "existing private output does not match recovery authority"
            )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _create_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("private output directory must not be a symlink")
    if path.exists():
        if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("private output directory has unsafe authority")
        return
    os.mkdir(path, 0o700)
    parent = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def _prepare_finalization_output(
    args: argparse.Namespace, state: dict[str, Any], key: bytes
) -> Path:
    requested = args.output.expanduser()
    if not requested.is_absolute():
        raise ValueError("private evidence output must be an absolute path")
    if requested.is_symlink():
        raise ValueError("private evidence output must not be a symlink")
    parent = requested.parent.resolve(strict=True)
    if not parent.is_dir() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise ValueError(
            "private evidence parent must be an existing private directory"
        )
    private_root = parent / requested.name
    for forbidden in (
        Path(state["repository_root"]),
        Path(state["study_kit"]).parents[1],
    ):
        if private_root.is_relative_to(forbidden.resolve()):
            raise ValueError("private evidence output escapes its authority boundary")
    if state["status"] == "reviewed":
        if private_root.exists() or private_root.is_symlink():
            raise ValueError("private evidence output must be absent at finalization")
        state["status"] = "finalizing"
        state["finalization_output"] = str(private_root)
        state["finalization_signed_at_utc"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        _write_state(args.session, state, key)
    elif state["status"] in {"finalizing", "finalized"}:
        if state.get("finalization_output") != str(private_root):
            raise ValueError("finalization recovery output does not match authority")
    else:
        raise ValueError("review is required before finalization")
    _create_private_directory(private_root)
    for name in ("evidence", "attestations", "receipts"):
        _create_private_directory(private_root / name)
    return private_root


def _load_anchored_kit(
    study_kit: Path, expected_sha256: str, fixture_id: str
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    from jsonschema import Draft202012Validator

    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("--study-kit-sha256 must be a lowercase SHA-256 digest")
    if study_kit.is_symlink() or not study_kit.is_file():
        raise ValueError("invalid study kit")
    if validator._sha256(study_kit) != expected_sha256:
        raise ValueError("study kit anchor mismatch")
    coordinator = study_kit.resolve().parent
    kit_root = coordinator.parent
    if study_kit.resolve() != coordinator / "study-kit.json":
        raise ValueError("study kit must use the canonical coordinator layout")
    kit = json.loads(study_kit.read_text(encoding="utf-8"))
    schema_path = coordinator / "pcodex.first-run-study-kit.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(kit)
    copied_hashes = {
        "kit_schema_sha256": schema_path,
        "receipt_schema_sha256": coordinator
        / "pcodex.first-run-study-receipt.v1.schema.json",
        "evidence_schema_sha256": coordinator
        / "pcodex.first-run-study-evidence.v1.schema.json",
        "study_protocol_sha256": coordinator / "FIRST_RUN_STUDY_PROTOCOL.md",
        "validator_sha256": coordinator / "validate_first_run_study.py",
        "restorer_sha256": coordinator / "restore_first_run_fixture.py",
        "recorder_sha256": coordinator / "record_first_run_study.py",
        "study_authority_sha256": coordinator / "first_run_study_authority.py",
        "runbook_sha256": coordinator / "RUNBOOK.md",
    }
    for field, path in copied_hashes.items():
        if (
            path.is_symlink()
            or not path.is_file()
            or validator._sha256(path) != kit[field]
        ):
            raise ValueError("coordinator authority hash mismatch")
    fixtures = {item["id"]: item for item in kit["fixtures"]}
    fixture = fixtures.get(fixture_id)
    if fixture is None or len(fixtures) != 5:
        raise ValueError("fixture authority is incomplete")
    snapshot = kit_root / fixture["snapshot"]
    if snapshot.is_symlink() or validator._sha256(snapshot) != fixture["sha256"]:
        raise ValueError("fixture archive hash mismatch")
    members = validator._archive_members(snapshot)
    member_hashes = {name: _sha(data) for name, data in sorted(members.items())}
    if member_hashes != fixture["member_sha256"]:
        raise ValueError("fixture member manifest mismatch")
    payload_wheel = (
        kit_root / "blind-tester-payload/artifacts" / kit["wheel"]["filename"]
    )
    if (
        payload_wheel.is_symlink()
        or not payload_wheel.is_file()
        or validator._sha256(payload_wheel) != kit["wheel"]["sha256"]
    ):
        raise ValueError("payload wheel mismatch")
    for tool in kit["runtime_tools"].values():
        path = Path(tool["path"])
        if (
            path.is_symlink()
            or not path.is_file()
            or not os.access(path, os.X_OK)
            or validator._sha256(path) != tool["sha256"]
        ):
            raise ValueError("runtime tool authority mismatch")
    return kit, fixture, payload_wheel


def init_session(args: argparse.Namespace) -> int:
    key = _safe_key(args.attestation_key)
    if (
        args.session.exists()
        or args.session.is_symlink()
        or _session_lock_path(args.session).exists()
        or _session_lock_path(args.session).is_symlink()
    ):
        raise ValueError("preassigned fixture session already exists")
    if args.session.name != f"{args.fixture}.session.json":
        raise ValueError("session must use the preassigned fixture filename")
    if args.session.parent.exists():
        if args.session.parent.is_symlink() or not args.session.parent.is_dir():
            raise ValueError("session directory authority is invalid")
        if stat.S_IMODE(args.session.parent.stat().st_mode) & 0o077:
            raise ValueError("session directory must be private")
    else:
        args.session.parent.mkdir(parents=True, mode=0o700)
    _create_session_lock(args.session)
    kit, fixture, payload_wheel = _load_anchored_kit(
        args.study_kit, args.study_kit_sha256, args.fixture
    )
    if args.repository.is_symlink() or args.sandbox.is_symlink():
        raise ValueError("repository and sandbox must not be symlinks")
    repository = args.repository.resolve(strict=True)
    sandbox = args.sandbox.resolve(strict=True)
    repository.relative_to(sandbox)
    session_root = args.session.parent.resolve()
    key_path = args.attestation_key.resolve()
    ledger_path = args.attempt_ledger.expanduser()
    if not ledger_path.is_absolute() or ledger_path.is_symlink():
        raise ValueError("attempt ledger must be an absolute non-symlink path")
    ledger_parent = ledger_path.parent.resolve(strict=True)
    ledger_path = ledger_parent / ledger_path.name
    if stat.S_IMODE(ledger_parent.stat().st_mode) & 0o077:
        raise ValueError("attempt ledger parent must be private")
    if any(
        session_root.is_relative_to(forbidden)
        or key_path.is_relative_to(forbidden)
        or ledger_path.is_relative_to(forbidden)
        for forbidden in (repository, sandbox, args.study_kit.resolve().parents[1])
    ):
        raise ValueError("private evidence authority must be outside controlled roots")
    if ledger_path.is_relative_to(session_root):
        raise ValueError("attempt ledger must remain outside the session set")
    if not repository.is_dir() or not (repository / ".git").is_dir():
        raise ValueError("repository must be a restored fixture Git root")
    venv = args.venv.resolve()
    venv.relative_to(sandbox)
    if venv.exists() or venv.is_symlink():
        raise ValueError("study virtual environment must be absent")
    _assert_restored_fixture(
        repository, fixture, Path(kit["runtime_tools"]["git"]["path"])
    )
    codex_home = (
        repository / "fixture-codex-home"
        if args.fixture in {"fixture-03", "fixture-05"}
        else sandbox / "codex-home"
    )
    paths = {
        "HOME": sandbox / "home",
        "XDG_CONFIG_HOME": sandbox / "xdg-config",
        "XDG_CACHE_HOME": sandbox / "xdg-cache",
        "XDG_DATA_HOME": sandbox / "xdg-data",
        "TMPDIR": sandbox / "tmp",
        "CODEX_HOME": codex_home,
    }
    for path in paths.values():
        if path.is_symlink():
            raise ValueError("controlled environment path must not be a symlink")
        if not path.exists():
            path.mkdir(parents=True)
        path.resolve().relative_to(sandbox)
    environment = {
        "sandbox_root": str(sandbox),
        **{name: str(path.resolve()) for name, path in paths.items()},
        "PATH": f"{venv / 'bin'}:/usr/bin:/bin",
    }
    codex_version = "absent"
    codex_authority: dict[str, Any] | None = None
    if args.fixture != "fixture-01":
        if args.codex is None:
            raise ValueError("supported-Codex fixtures require --codex")
        codex_command, codex_authority = _codex_wrapper_command(args.codex)
        wrapper_dir = sandbox / "bin"
        if wrapper_dir.exists() or wrapper_dir.is_symlink():
            raise ValueError("controlled Codex wrapper directory must be absent")
        wrapper_dir.mkdir(mode=0o700)
        wrapper = wrapper_dir / "codex"
        wrapper.write_text(
            "#!/bin/sh\nexec "
            + " ".join(shlex.quote(part) for part in codex_command)
            + ' "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
        codex_authority.update(
            {
                "wrapper_path": str(wrapper),
                "wrapper_sha256": validator._sha256(wrapper),
            }
        )
        environment["PATH"] = f"{venv / 'bin'}:{wrapper_dir}:/usr/bin:/bin"
        version = subprocess.run(
            (str(wrapper), "--version"),
            env={**environment, "LC_ALL": "C"},
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
        match = re.search(r"\b0\.143\.([0-9]+)\b", version)
        if match is None:
            raise ValueError("Codex version must be 0.143.x")
        codex_version = f"0.143.{match.group(1)}"
    condition_observations = _initial_condition_observations(
        repository, fixture, environment, codex_version
    )
    runtime_python_version = subprocess.run(
        (
            str(Path(kit["runtime_tools"]["python"]["path"])),
            "-c",
            "import platform; print(platform.python_version())",
        ),
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    state: dict[str, Any] = {
        "schema_version": "pcodex.first-run-recorder-state.v1",
        "status": "recording",
        "study_kit": str(args.study_kit.resolve()),
        "study_kit_sha256": validator._sha256(args.study_kit),
        "attempt_ledger": str(ledger_path),
        "payload_wheel": str(payload_wheel),
        "payload_wheel_sha256": kit["wheel"]["sha256"],
        "runtime_python": str(Path(kit["runtime_tools"]["python"]["path"])),
        "runtime_python_version": runtime_python_version,
        "tester_id": args.tester_id,
        "fixture": fixture,
        "repository_root": str(repository),
        "venv_root": str(venv),
        "controlled_environment": environment,
        "codex_version": codex_version,
        "codex_authority": codex_authority,
        "installed_runtime_authority_sha256": None,
        "condition_observations": condition_observations,
        "cursor": 0,
        "timer_origin_ns": None,
        "events": [],
        "failed_attempts": [],
        "preservation": {},
        "review": None,
    }
    _capture_checkpoint(state, "before")
    _write_state(args.session, state, key)
    print(f"next operation: {fixture['required_operations'][0]}")
    return 0


def run_next(args: argparse.Namespace) -> int:
    with _session_transition_lock(args.session):
        return _run_next_locked(args)


def _run_next_locked(args: argparse.Namespace) -> int:
    key = _safe_key(args.attestation_key)
    state = _read_state(args.session, key)
    if state["status"] != "recording":
        raise ValueError("session is not in the recording state")
    operations = state["fixture"]["required_operations"]
    cursor = int(state["cursor"])
    if cursor >= len(operations):
        print("journey complete; review is required")
        return 0
    operation = operations[cursor]
    if args.operation != operation:
        raise ValueError(f"next operation is {operation}")
    argv, resolved, execution_argv = _operation_argv(operation, state)
    if operation in {"artifact_verify", "package_install"} and (
        validator._sha256(Path(state["payload_wheel"])) != state["payload_wheel_sha256"]
    ):
        state["failed_attempts"].append(
            {
                "sequence": cursor + 1,
                "operation": operation,
                "category": "payload_wheel_authority_changed",
            }
        )
        state["status"] = "failed_closed"
        _write_state(args.session, state, key)
        raise ValueError("payload wheel authority changed during the study")
    if operation not in {"artifact_verify", "venv_create", "package_install"}:
        _verify_codex_authority(state)
        if validator._installed_runtime_authority(
            Path(state["venv_root"])
        ) != state.get("installed_runtime_authority_sha256"):
            state["failed_attempts"].append(
                {
                    "sequence": cursor + 1,
                    "operation": operation,
                    "category": "installed_runtime_authority_changed",
                }
            )
            state["status"] = "failed_closed"
            _write_state(args.session, state, key)
            raise ValueError("installed pCodex authority changed during the study")
    if operation == "package_install" and state["timer_origin_ns"] is None:
        state["timer_origin_ns"] = time.monotonic_ns()
    origin = state["timer_origin_ns"]
    started = (
        None
        if origin is None
        else 0.0
        if operation == "package_install"
        else (time.monotonic_ns() - origin) / 1_000_000_000
    )
    expected_writes = validator.EXPECTED_RESULTS[operation][1]
    no_write_before = (
        _filesystem_snapshot(
            Path(state["repository_root"]),
            Path(state["controlled_environment"]["sandbox_root"]),
        )
        if not expected_writes
        else None
    )
    try:
        completed = subprocess.run(
            execution_argv,
            cwd=state["repository_root"],
            env={
                **_controlled_environment(state),
                "LC_ALL": "C",
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        state["failed_attempts"].append(
            {
                "sequence": cursor + 1,
                "operation": operation,
                "category": exc.__class__.__name__,
            }
        )
        state["status"] = "failed_closed"
        _write_state(args.session, state, key)
        raise ValueError(
            "command execution failed; begin a fresh study session"
        ) from exc
    ended = None if origin is None else (time.monotonic_ns() - origin) / 1_000_000_000
    if no_write_before is not None:
        no_write_after = _filesystem_snapshot(
            Path(state["repository_root"]),
            Path(state["controlled_environment"]["sandbox_root"]),
        )
        if no_write_after != no_write_before:
            state["failed_attempts"].append(
                {
                    "sequence": cursor + 1,
                    "operation": operation,
                    "category": "no_write_filesystem_delta",
                }
            )
            state["status"] = "failed_closed"
            _write_state(args.session, state, key)
            raise ValueError("no-write filesystem observation detected a change")
    if len(completed.stdout) > 1024 * 1024 or len(completed.stderr) > 1024 * 1024:
        state["failed_attempts"].append(
            {
                "sequence": cursor + 1,
                "operation": operation,
                "category": "stream_limit_exceeded",
            }
        )
        state["status"] = "failed_closed"
        _write_state(args.session, state, key)
        raise ValueError("command evidence exceeds the bounded stream limit")
    try:
        result = validator._derived_result(operation, completed.stdout)
    except ValueError:
        result = {
            "structured": True,
            "result_sha256": _sha(completed.stdout),
            "status": "BLOCKED",
            "operation_status": "invalid",
            "writes_performed": False,
        }
    runtime_authority: str | None = None
    runtime_authority_error = False
    should_measure_runtime = operation not in {"artifact_verify", "venv_create"} and (
        operation != "package_install" or completed.returncode == 0
    )
    if should_measure_runtime:
        try:
            runtime_authority = validator._installed_runtime_authority(
                Path(state["venv_root"])
            )
        except (OSError, ValueError):
            runtime_authority_error = True
        if operation == "package_install" and runtime_authority is not None:
            state["installed_runtime_authority_sha256"] = runtime_authority
        elif (
            operation != "package_install"
            and not runtime_authority_error
            and runtime_authority != state.get("installed_runtime_authority_sha256")
        ):
            state["failed_attempts"].append(
                {
                    "sequence": cursor + 1,
                    "operation": operation,
                    "category": "installed_runtime_authority_changed_during_command",
                }
            )
            state["status"] = "failed_closed"
            _write_state(args.session, state, key)
            raise ValueError("installed pCodex authority changed during the command")
    event = {
        "sequence": cursor + 1,
        "operation": operation,
        "argv": argv,
        "resolved_executable": resolved,
        "started_seconds": started,
        "completed_seconds": ended,
        "exit_code": completed.returncode,
        "stdout_base64": base64.b64encode(completed.stdout).decode("ascii"),
        "stderr_base64": base64.b64encode(completed.stderr).decode("ascii"),
        "result": result,
        "runtime_authority_sha256": runtime_authority,
        "no_write_observation_sha256": no_write_before,
    }
    if runtime_authority_error:
        state["failed_attempts"].append(
            {
                "sequence": cursor + 1,
                "operation": operation,
                "category": "installed_runtime_authority_unavailable",
            }
        )
        state["status"] = "failed_closed"
        _write_state(args.session, state, key)
        print(
            "installed pCodex authority could not be verified; "
            "begin a fresh study session",
            file=sys.stderr,
        )
        return 1
    evidence = _command_evidence(event, state)
    command = {
        key_: value
        for key_, value in event.items()
        if key_ not in {"stdout_base64", "stderr_base64"}
    }
    command.update(
        {
            "stdout_sha256": _sha(completed.stdout),
            "stderr_sha256": _sha(completed.stderr),
            "evidence_sha256": "0" * 64,
            "sensitivity_reviewed": True,
        }
    )
    if not validator._successful_command(
        command,
        evidence,
        state["fixture"].get(
            "wheel_sha256", _sha(Path(state["payload_wheel"]).read_bytes())
        ),
    ):
        state["failed_attempts"].append(event)
        state["status"] = "failed_closed"
        _write_state(args.session, state, key)
        print(
            f"operation failed closed: {operation}; begin a fresh study session",
            file=sys.stderr,
        )
        return 1
    state["events"].append(event)
    state["cursor"] = cursor + 1
    checkpoint = CHECKPOINT_AFTER[state["fixture"]["id"]].get(operation)
    if checkpoint:
        _capture_checkpoint(state, checkpoint)
    if state["cursor"] == len(operations):
        _derive_post_conditions(state)
    _write_state(args.session, state, key)
    if state["cursor"] == len(operations):
        print("journey complete; run review then finalize")
    else:
        print(f"next operation: {operations[state['cursor']]}")
    return 0


def review_session(args: argparse.Namespace) -> int:
    with _session_transition_lock(args.session):
        return _review_session_locked(args)


def _review_session_locked(args: argparse.Namespace) -> int:
    key = _safe_key(args.attestation_key)
    state = _read_state(args.session, key)
    report = json.loads(args.review_manifest.read_text(encoding="utf-8"))
    required = {
        "no_prior_knowledge_attested",
        "command_reviews",
        "condition_reviews",
        "preservation_reviews",
        "undocumented_help",
        "failures",
        "documentation",
        "completed",
        "signer_id",
    }
    if set(report) != required or report["no_prior_knowledge_attested"] is not True:
        raise ValueError("review manifest is incomplete")
    if report["completed"] is not True or int(state["cursor"]) != len(
        state["fixture"]["required_operations"]
    ):
        raise ValueError("journey is incomplete")
    expected_reviews = [
        {
            "sequence": event["sequence"],
            "stdout_sha256": _sha(base64.b64decode(event["stdout_base64"])),
            "stderr_sha256": _sha(base64.b64decode(event["stderr_base64"])),
            "approved": True,
        }
        for event in state["events"]
    ]
    if report["command_reviews"] != expected_reviews:
        raise ValueError("every captured stream requires exact sensitivity approval")
    expected_condition_reviews = [
        {
            "condition": condition,
            "observation_sha256": _sha(base64.b64decode(encoded)),
            "approved": True,
        }
        for condition, encoded in sorted(state["condition_observations"].items())
    ]
    if report["condition_reviews"] != expected_condition_reviews:
        raise ValueError(
            "every condition observation requires exact sensitivity approval"
        )
    expected_preservation_reviews = [
        {
            "checkpoint": checkpoint,
            "surface": surface,
            "measurement_sha256": _sha(base64.b64decode(encoded)),
            "approved": True,
        }
        for checkpoint, values in sorted(state["preservation"].items())
        for surface, encoded in sorted(values.items())
    ]
    if report["preservation_reviews"] != expected_preservation_reviews:
        raise ValueError(
            "every preservation measurement requires exact sensitivity approval"
        )
    if state["failed_attempts"]:
        raise ValueError("failed sessions cannot be reviewed as qualifying evidence")
    if not re.fullmatch(r"coordinator-[a-z0-9]{8,32}", report["signer_id"]):
        raise ValueError("invalid coordinator signer ID")
    state["review"] = report
    state["status"] = "reviewed"
    _write_state(args.session, state, key)
    return 0


def build_review_manifest(args: argparse.Namespace) -> int:
    with _session_transition_lock(args.session):
        return _build_review_manifest_locked(args)


def _build_review_manifest_locked(args: argparse.Namespace) -> int:
    key = _safe_key(args.attestation_key)
    state = _read_state(args.session, key)
    if state["status"] != "recording" or int(state["cursor"]) != len(
        state["fixture"]["required_operations"]
    ):
        raise ValueError("completed recording is required for review preparation")
    if not re.fullmatch(r"coordinator-[a-z0-9]{8,32}", args.signer_id):
        raise ValueError("invalid coordinator signer ID")
    output = args.output.expanduser()
    if not output.is_absolute() or output.is_symlink() or output.exists():
        raise ValueError("review manifest output must be an absent absolute path")
    parent = output.parent.resolve(strict=True)
    if stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise ValueError("review manifest parent must be private")
    report = {
        "no_prior_knowledge_attested": False,
        "command_reviews": [
            {
                "sequence": event["sequence"],
                "stdout_sha256": _sha(base64.b64decode(event["stdout_base64"])),
                "stderr_sha256": _sha(base64.b64decode(event["stderr_base64"])),
                "approved": False,
            }
            for event in state["events"]
        ],
        "condition_reviews": [
            {
                "condition": condition,
                "observation_sha256": _sha(base64.b64decode(encoded)),
                "approved": False,
            }
            for condition, encoded in sorted(state["condition_observations"].items())
        ],
        "preservation_reviews": [
            {
                "checkpoint": checkpoint,
                "surface": surface,
                "measurement_sha256": _sha(base64.b64decode(encoded)),
                "approved": False,
            }
            for checkpoint, values in sorted(state["preservation"].items())
            for surface, encoded in sorted(values.items())
        ],
        "undocumented_help": [],
        "failures": [],
        "documentation": {
            "sufficient": False,
            "missing_instruction": "replace with the tester's exact reviewed finding",
        },
        "completed": False,
        "signer_id": args.signer_id,
    }
    _atomic_private_file(
        output, json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    print(output)
    return 0


def finalize_session(args: argparse.Namespace) -> int:
    with _session_transition_lock(args.session):
        return _finalize_session_locked(args)


def _finalize_session_locked(args: argparse.Namespace) -> int:
    key = _safe_key(args.attestation_key)
    state = _read_state(args.session, key)
    if (
        state["status"] not in {"reviewed", "finalizing", "finalized"}
        or state["review"] is None
    ):
        raise ValueError("review is required before finalization")
    private_root = _prepare_finalization_output(args, state, key)
    evidence_dir = private_root / "evidence"
    attestation_dir = private_root / "attestations"
    receipt_dir = private_root / "receipts"
    command_items: list[dict[str, Any]] = []
    command_hashes: list[str] = []
    for event in state["events"]:
        evidence = _command_evidence(event, state)
        digest = _store_content(evidence_dir, ".evidence", evidence)
        stdout = base64.b64decode(event["stdout_base64"])
        stderr = base64.b64decode(event["stderr_base64"])
        command_items.append(
            {
                key_: value
                for key_, value in event.items()
                if key_
                not in {
                    "stdout_base64",
                    "stderr_base64",
                    "runtime_authority_sha256",
                    "no_write_observation_sha256",
                }
            }
            | {
                "stdout_sha256": _sha(stdout),
                "stderr_sha256": _sha(stderr),
                "evidence_sha256": digest,
                "sensitivity_reviewed": True,
            }
        )
        command_hashes.append(digest)
    condition_items: list[dict[str, str]] = []
    condition_hashes: list[str] = []
    for condition in state["fixture"]["conditions"]:
        encoded_observation = state["condition_observations"].get(condition)
        if not isinstance(encoded_observation, str):
            raise ValueError("required condition observation is missing")
        observation = base64.b64decode(encoded_observation)
        evidence = {
            "schema_version": "pcodex.first-run-study-evidence.v1",
            "kind": "condition",
            "tester_id": state["tester_id"],
            "fixture_id": state["fixture"]["id"],
            "study_kit_sha256": state["study_kit_sha256"],
            "condition": condition,
            "observation_base64": encoded_observation,
            "observation_sha256": _sha(observation),
            "observed": True,
            "sensitivity_reviewed": True,
        }
        digest = _store_content(evidence_dir, ".evidence", evidence)
        condition_hashes.append(digest)
        condition_items.append({"condition": condition, "evidence_sha256": digest})
    preservation_items: list[dict[str, Any]] = []
    preservation_hashes: list[str] = []
    for checkpoint in state["fixture"]["required_preservation_checkpoints"]:
        values = state["preservation"].get(checkpoint)
        if not isinstance(values, dict):
            raise ValueError("required preservation checkpoint is missing")
        for surface in state["fixture"]["preservation_surfaces"]:
            encoded = values[surface["name"]]
            measurement = base64.b64decode(encoded)
            evidence = {
                "schema_version": "pcodex.first-run-study-evidence.v1",
                "kind": "preservation",
                "tester_id": state["tester_id"],
                "fixture_id": state["fixture"]["id"],
                "study_kit_sha256": state["study_kit_sha256"],
                "surface": surface["name"],
                "checkpoint": checkpoint,
                "measurement_base64": encoded,
                "measurement_sha256": _sha(measurement),
                "sensitivity_reviewed": True,
            }
            digest = _store_content(evidence_dir, ".evidence", evidence)
            preservation_hashes.append(digest)
            preservation_items.append(
                {
                    "surface": surface["name"],
                    "checkpoint": checkpoint,
                    "sha256": _sha(measurement),
                    "evidence_sha256": digest,
                    "sensitivity_reviewed": True,
                }
            )
    kit = json.loads(Path(state["study_kit"]).read_text(encoding="utf-8"))
    study = {
        name: kit[name]
        for name in (
            "qualification_receipt_sha256",
            "receipt_schema_sha256",
            "kit_schema_sha256",
            "evidence_schema_sha256",
            "study_protocol_sha256",
            "validator_sha256",
            "restorer_sha256",
            "recorder_sha256",
            "study_authority_sha256",
            "canonical_document_manifest_sha256",
        )
    }
    study["study_kit_sha256"] = state["study_kit_sha256"]
    dry_run = next(item for item in command_items if item["operation"] == "run_dry_run")
    review = state["review"]
    receipt: dict[str, Any] = {
        "schema_version": "pcodex.first-run-study-receipt.v1",
        "anonymous_tester_id": state["tester_id"],
        "no_prior_knowledge_attested": True,
        "attestation_evidence_sha256": "0" * 64,
        "study": study,
        "artifact": {
            "filename": Path(state["payload_wheel"]).name,
            "sha256": _sha(Path(state["payload_wheel"]).read_bytes()),
            "product_version": "0.3.0b1",
            "candidate_commit": kit["candidate_commit"],
        },
        "runtime": {
            "platform": "macos" if sys.platform == "darwin" else "linux",
            "architecture": platform.machine(),
            "python_version": state["runtime_python_version"],
            "codex_version": state["codex_version"],
            "repository_root": state["repository_root"],
        },
        "fixture": {
            "id": state["fixture"]["id"],
            "sha256": state["fixture"]["sha256"],
            "conditions": state["fixture"]["conditions"],
        },
        "timing": {
            "timer_start_operation": "package_install",
            "first_use_seconds": dry_run["completed_seconds"],
            "completion_seconds": command_items[-1]["completed_seconds"],
        },
        "commands": command_items,
        "condition_evidence": condition_items,
        "preservation_evidence": preservation_items,
        "undocumented_help": review["undocumented_help"],
        "failures": review["failures"],
        "documentation": review["documentation"],
        "completed": True,
    }
    attestation = {
        "schema_version": "pcodex.first-run-study-evidence.v1",
        "kind": "attestation",
        "tester_id": state["tester_id"],
        "fixture_id": state["fixture"]["id"],
        "study_kit_sha256": state["study_kit_sha256"],
        "statement": "I had no prior internal knowledge of pCodex and followed only the supplied canonical documentation and frozen task card.",
        "signed_at_utc": state["finalization_signed_at_utc"],
        "signer_id": review["signer_id"],
        "signer_role": "study_coordinator_witness",
        "command_evidence_manifest_sha256": validator._canonical_json_sha256(
            command_hashes
        ),
        "condition_evidence_manifest_sha256": validator._canonical_json_sha256(
            condition_hashes
        ),
        "preservation_evidence_manifest_sha256": validator._canonical_json_sha256(
            preservation_hashes
        ),
        "receipt_claims_sha256": validator._receipt_claims_sha256(receipt),
    }
    attestation["signature"] = {
        "algorithm": "hmac-sha256",
        "value": hmac.new(key, _json_bytes(attestation), hashlib.sha256).hexdigest(),
    }
    receipt["attestation_evidence_sha256"] = _store_content(
        attestation_dir, ".attestation", attestation
    )
    receipt_path = receipt_dir / f"{state['tester_id']}.json"
    receipt_bytes = (
        json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    _atomic_private_file(receipt_path, receipt_bytes)
    receipt_sha256 = validator._sha256(receipt_path)
    if state["status"] == "finalized":
        if state.get("receipt_sha256") != receipt_sha256:
            raise ValueError("finalized receipt no longer matches session authority")
        print(receipt_path)
        return 0
    state["status"] = "finalized"
    state["receipt_sha256"] = receipt_sha256
    _write_state(args.session, state, key)
    print(receipt_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init")
    initialize.add_argument("--session", type=Path, required=True)
    initialize.add_argument("--study-kit", type=Path, required=True)
    initialize.add_argument("--study-kit-sha256", required=True)
    initialize.add_argument(
        "--fixture", choices=sorted(validator.FIXTURES), required=True
    )
    initialize.add_argument("--tester-id", required=True)
    initialize.add_argument("--repository", type=Path, required=True)
    initialize.add_argument("--venv", type=Path, required=True)
    initialize.add_argument("--sandbox", type=Path, required=True)
    initialize.add_argument("--codex", type=Path)
    initialize.add_argument("--attestation-key", type=Path, required=True)
    initialize.add_argument("--attempt-ledger", type=Path, required=True)
    initialize.set_defaults(handler=init_session)
    run = subparsers.add_parser("run-next")
    run.add_argument("--session", type=Path, required=True)
    run.add_argument("--operation", required=True)
    run.add_argument("--attestation-key", type=Path, required=True)
    run.set_defaults(handler=run_next)
    prepare_review = subparsers.add_parser("build-review-manifest")
    prepare_review.add_argument("--session", type=Path, required=True)
    prepare_review.add_argument("--output", type=Path, required=True)
    prepare_review.add_argument("--signer-id", required=True)
    prepare_review.add_argument("--attestation-key", type=Path, required=True)
    prepare_review.set_defaults(handler=build_review_manifest)
    review = subparsers.add_parser("review")
    review.add_argument("--session", type=Path, required=True)
    review.add_argument("--review-manifest", type=Path, required=True)
    review.add_argument("--attestation-key", type=Path, required=True)
    review.set_defaults(handler=review_session)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--session", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    finalize.add_argument("--attestation-key", type=Path, required=True)
    finalize.set_defaults(handler=finalize_session)
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
