from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .tuning import TuningProfileError, load_compile_tuning_profile

STATE_SCHEMA_VERSION = "pcodex.state.v1"
DEFAULT_ALGORITHM = "literal_symbol"
DEFAULT_TUNING_PROFILE = ".premode/tuning/repo_profile.json"
VALID_MODES = {"off", "on", "tuned"}


class PcodexStateError(ValueError):
    """Raised when pCodex mode state cannot be read or written safely."""


def find_repo_root(start: Path | str | None = None) -> Path:
    current = Path.cwd() if start is None else Path(start)
    current = current.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def state_path_for_repo(repo_root: Path | str) -> Path:
    return find_repo_root(repo_root) / ".premode" / "pcodex_state.json"


def default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "enabled": True,
        "mode": "on",
        "algorithm": DEFAULT_ALGORITHM,
        "tuning_profile": None,
    }


def _state_for_mode(mode: str, *, tuning_profile: str | None = None) -> dict[str, Any]:
    if mode == "off":
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "enabled": False,
            "mode": "off",
            "algorithm": DEFAULT_ALGORITHM,
            "tuning_profile": None,
        }
    if mode == "on":
        return default_state()
    if mode == "tuned":
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "enabled": True,
            "mode": "tuned",
            "algorithm": DEFAULT_ALGORITHM,
            "tuning_profile": tuning_profile or DEFAULT_TUNING_PROFILE,
        }
    raise PcodexStateError(f"Invalid pCodex mode: {mode}")


def validate_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PcodexStateError("Invalid pCodex state: expected JSON object")
    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise PcodexStateError("Invalid pCodex state: schema_version must be pcodex.state.v1")
    mode = str(payload.get("mode") or "").strip()
    if mode not in VALID_MODES:
        raise PcodexStateError("Invalid pCodex state: mode must be off, on, or tuned")
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise PcodexStateError("Invalid pCodex state: enabled must be boolean")
    algorithm = str(payload.get("algorithm") or "").strip()
    if algorithm != DEFAULT_ALGORITHM:
        raise PcodexStateError("Invalid pCodex state: algorithm must be literal_symbol")
    tuning_profile = payload.get("tuning_profile")
    if mode == "tuned":
        if enabled is not True:
            raise PcodexStateError("Invalid pCodex state: tuned mode requires enabled true")
        if not isinstance(tuning_profile, str) or not tuning_profile.strip():
            raise PcodexStateError("Invalid pCodex state: tuned mode requires tuning_profile")
    else:
        if tuning_profile is not None:
            raise PcodexStateError("Invalid pCodex state: tuning_profile must be null unless mode is tuned")
        if enabled is not (mode == "on"):
            raise PcodexStateError("Invalid pCodex state: enabled does not match mode")
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "enabled": enabled,
        "mode": mode,
        "algorithm": DEFAULT_ALGORITHM,
        "tuning_profile": tuning_profile,
    }


def read_pcodex_state(repo_root: Path | str) -> dict[str, Any]:
    path = state_path_for_repo(repo_root)
    if not path.exists():
        state = default_state()
        state["_state_status"] = "missing_default"
        return state
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        state = validate_state(payload)
    except (OSError, json.JSONDecodeError, PcodexStateError) as exc:
        state = default_state()
        state["_state_status"] = "invalid_default"
        state["_state_error"] = str(exc)
        return state
    state["_state_status"] = "loaded"
    return state


def write_pcodex_state(repo_root: Path | str, state: dict[str, Any]) -> Path:
    root = find_repo_root(repo_root)
    payload = validate_state(state)
    path = state_path_for_repo(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def set_mode_on(repo_root: Path | str) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    state = _state_for_mode("on")
    path = write_pcodex_state(root, state)
    return {**state, "state_path": _display_path(root, path), "state_status": "written"}


def set_mode_off(repo_root: Path | str) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    state = _state_for_mode("off")
    path = write_pcodex_state(root, state)
    return {**state, "state_path": _display_path(root, path), "state_status": "written"}


def _display_path(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _display_profile(repo_root: Path, profile: Path | str) -> str:
    path = Path(profile)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            return str(path)
    return path.as_posix()


def validate_tuning_profile_for_mode(repo_root: Path | str, profile: Path | str) -> dict[str, Any]:
    try:
        loaded = load_compile_tuning_profile(repo_root, profile)
    except TuningProfileError as exc:
        raise PcodexStateError(str(exc)) from exc
    return {
        "valid": True,
        "profile_path": _display_profile(find_repo_root(repo_root), profile),
        "validation_status": loaded["validation"].get("status"),
    }


def set_mode_tuned(repo_root: Path | str, profile: Path | str = DEFAULT_TUNING_PROFILE) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    validation = validate_tuning_profile_for_mode(root, profile)
    state = _state_for_mode("tuned", tuning_profile=validation["profile_path"])
    path = write_pcodex_state(root, state)
    return {
        **state,
        "state_path": _display_path(root, path),
        "state_status": "written",
        "tuning_profile_valid": True,
        "tuning_validation_status": validation["validation_status"],
    }


def status_payload(repo_root: Path | str, *, validate_tuned: bool = True) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    path = state_path_for_repo(root)
    state = read_pcodex_state(root)
    state_status = str(state.pop("_state_status", "loaded"))
    state_error = state.pop("_state_error", None)
    payload = {
        **state,
        "state_path": _display_path(root, path),
        "state_exists": path.exists(),
        "state_status": state_status,
        "state_error": state_error,
    }
    if validate_tuned and payload["mode"] == "tuned":
        try:
            validation = validate_tuning_profile_for_mode(root, str(payload["tuning_profile"]))
        except PcodexStateError as exc:
            payload["tuning_profile_valid"] = False
            payload["tuning_profile_error"] = str(exc)
        else:
            payload["tuning_profile_valid"] = True
            payload["tuning_validation_status"] = validation["validation_status"]
    else:
        payload["tuning_profile_valid"] = None
    return payload
