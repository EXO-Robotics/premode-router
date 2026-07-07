from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .lockfile import sha256_file
from .tuning import TuningProfileError, load_compile_tuning_profile

STATE_SCHEMA_VERSION = "pcodex.state.v1"
DEFAULT_ALGORITHM = "literal_symbol"
DEFAULT_TUNING_PROFILE = ".premode/tuning/repo_profile.json"
VALID_MODES = {"off", "on", "tuned"}
VALID_EFFECTIVE_MODES = {"off", "on", "tuned"}
EFFECTIVE_OFF_RAW = "OFF_RAW"
EFFECTIVE_ON_GENERALIZED = "ON_GENERALIZED"
EFFECTIVE_ON_TUNED_VERIFIED = "ON_TUNED_VERIFIED"
EFFECTIVE_TUNED_STRICT = "TUNED_STRICT"
EFFECTIVE_SAFE_PASSTHROUGH = "SAFE_PASSTHROUGH"
PACKET_VERSION = "v5"
PACKET_VARIANT = "tool_assisted_anchors_internal"
PACKET_STRATEGY = "literal_symbol"


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _optional_string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _fallback_payload(value: Any | None = None) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    return {
        "active": bool(data.get("active", False)),
        "last_reason": _optional_string_or_none(data.get("last_reason")),
        "last_at": _optional_string_or_none(data.get("last_at")),
    }


def _last_verify_payload(value: Any | None = None) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    return {
        "verdict": _optional_string_or_none(data.get("verdict")),
        "results_path": _optional_string_or_none(data.get("results_path")),
        "checked_at": _optional_string_or_none(data.get("checked_at")),
    }


def _telemetry_payload(value: Any | None = None) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    raw_counts = data.get("mode_counts")
    counts = raw_counts if isinstance(raw_counts, dict) else {}
    return {
        "compile_count": _optional_int(data.get("compile_count")),
        "mode_counts": {mode: _optional_int(counts.get(mode)) for mode in ("off", "on", "tuned")},
        "fallback_count": _optional_int(data.get("fallback_count")),
    }


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
    normalized = {
        "schema_version": STATE_SCHEMA_VERSION,
        "enabled": enabled,
        "mode": mode,
        "algorithm": DEFAULT_ALGORITHM,
        "tuning_profile": tuning_profile,
    }
    if "effective_mode" in payload:
        effective_mode = str(payload.get("effective_mode") or "").strip()
        if effective_mode in VALID_EFFECTIVE_MODES:
            normalized["effective_mode"] = effective_mode
    if "fallback" in payload:
        normalized["fallback"] = _fallback_payload(payload.get("fallback"))
    if "last_verify" in payload:
        normalized["last_verify"] = _last_verify_payload(payload.get("last_verify"))
    if "telemetry" in payload:
        normalized["telemetry"] = _telemetry_payload(payload.get("telemetry"))
    return normalized


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


def _resolve_profile_path(repo_root: Path, profile: Path | str) -> Path:
    path = Path(profile)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _verify_results_for_profile(repo_root: Path, profile: Path | str) -> tuple[Path, str]:
    profile_path = _resolve_profile_path(repo_root, profile)
    results_path = profile_path.parent / "VERIFY_RESULTS.json"
    return results_path, _display_path(repo_root, results_path)


def _profile_hash(repo_root: Path, profile: Path | str | None) -> str | None:
    if profile is None:
        return None
    return sha256_file(_resolve_profile_path(repo_root, profile))


def _verify_hash(repo_root: Path, profile: Path | str | None) -> str | None:
    if profile is None:
        return None
    results_path, _display = _verify_results_for_profile(repo_root, profile)
    return sha256_file(results_path)


def _last_verified_at(repo_root: Path, profile: Path | str | None) -> str | None:
    if profile is None:
        return None
    results_path, _display = _verify_results_for_profile(repo_root, profile)
    if not results_path.exists():
        return None
    try:
        payload = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("checked_at") or payload.get("created_at") or payload.get("updated_at")
    return str(value) if value else None


def _state_summary(state: str, public_mode: str, stale_reason: str | None = None) -> str:
    if state == EFFECTIVE_OFF_RAW:
        return "pCodex is off; prompts pass through unchanged."
    if state == EFFECTIVE_ON_TUNED_VERIFIED:
        return "pCodex is on and using verified repo-local tuning."
    if state == EFFECTIVE_ON_GENERALIZED:
        return "pCodex is on and using generalized literal_symbol."
    if state == EFFECTIVE_TUNED_STRICT:
        return "pCodex tuned mode is strict and verified."
    if state == EFFECTIVE_SAFE_PASSTHROUGH:
        return "pCodex is preserving the raw prompt because LCC cannot safely compile."
    return f"pCodex public mode {public_mode} resolved to {state}."


def _resolver_metadata(
    root: Path,
    *,
    public_mode: str,
    effective_mode: str,
    effective_state: str,
    tuning_profile: str | None,
    tuning: dict[str, Any],
    fallback_reason: str | None = None,
    safe_passthrough_reason: str | None = None,
) -> dict[str, Any]:
    stale_reason = None
    if tuning_profile and tuning.get("verify") != "PASS":
        stale_reason = str(tuning.get("fallback_reason") or f"verify_{str(tuning.get('verify') or 'missing').lower()}")
    return {
        "configured_mode": public_mode,
        "effective_mode": effective_mode,
        "effective_state": effective_state,
        "effective_tuning_profile": tuning_profile if effective_state in {EFFECTIVE_ON_TUNED_VERIFIED, EFFECTIVE_TUNED_STRICT} else None,
        "plugin_alias": DEFAULT_ALGORITHM,
        "packet_version": PACKET_VERSION,
        "packet_variant": PACKET_VARIANT,
        "packet_strategy": PACKET_STRATEGY,
        "tuning_profile_hash": _profile_hash(root, tuning_profile),
        "verify_results_hash": _verify_hash(root, tuning_profile),
        "last_verified_at": _last_verified_at(root, tuning_profile),
        "stale_reason": stale_reason,
        "fallback_reason": fallback_reason,
        "safe_passthrough_reason": safe_passthrough_reason,
        "user_visible_summary": _state_summary(effective_state, public_mode, stale_reason),
        "debug_details": {
            "public_mode": public_mode,
            "effective_mode_legacy": effective_mode,
            "tuning_verify": tuning.get("verify"),
            "tuning_validation": tuning.get("validation"),
            "state_machine_schema": "premode.effective_mode.v1",
        },
    }


def inspect_tuning_status(repo_root: Path | str, profile: Path | str | None) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    if profile is None:
        return {
            "profile": None,
            "validation": "missing",
            "verify": "missing",
            "results_path": None,
            "profile_valid": False,
            "profile_error": None,
            "fallback_reason": None,
        }
    display = _display_profile(root, profile)
    try:
        loaded = load_compile_tuning_profile(root, profile)
    except TuningProfileError as exc:
        results_path, results_display = _verify_results_for_profile(root, profile)
        return {
            "profile": display,
            "validation": "FAIL",
            "verify": "invalid",
            "results_path": results_display if results_path.exists() else None,
            "profile_valid": False,
            "profile_error": str(exc),
            "fallback_reason": "tuning_profile_invalid",
        }
    results_path, results_display = _verify_results_for_profile(root, loaded["profile_display"])
    if not results_path.exists():
        return {
            "profile": display,
            "validation": "PASS",
            "verify": "not_verified",
            "results_path": None,
            "profile_valid": True,
            "profile_error": None,
            "fallback_reason": "tuning_not_verified",
        }
    try:
        verify_payload = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "profile": display,
            "validation": "PASS",
            "verify": "invalid",
            "results_path": results_display,
            "profile_valid": True,
            "profile_error": None,
            "fallback_reason": f"verify_results_invalid:{exc.__class__.__name__}",
        }
    verdict = str(verify_payload.get("verdict") or "invalid").strip() or "invalid"
    fallback_reason = None if verdict == "PASS" else f"verify_{verdict.lower()}"
    return {
        "profile": display,
        "validation": "PASS",
        "verify": verdict,
        "results_path": results_display,
        "profile_valid": True,
        "profile_error": None,
        "fallback_reason": fallback_reason,
    }


def _profile_for_on(root: Path) -> str | None:
    default_profile = root / DEFAULT_TUNING_PROFILE
    if default_profile.exists():
        return DEFAULT_TUNING_PROFILE
    return None


def resolve_effective_mode(repo_root: Path | str, *, validate_tuned: bool = True) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    state = status_payload(root, validate_tuned=validate_tuned)
    configured_mode = str(state.get("mode") or "on")
    if state.get("state_status") == "invalid_default":
        tuning = inspect_tuning_status(root, None)
        meta = _resolver_metadata(
            root,
            public_mode=configured_mode,
            effective_mode="on",
            effective_state=EFFECTIVE_SAFE_PASSTHROUGH,
            tuning_profile=None,
            tuning=tuning,
            safe_passthrough_reason="invalid_pcodex_state",
        )
        return {
            **state,
            **meta,
            "tuning": tuning,
            "fallback": {"active": False, "last_reason": None, "last_at": None},
            "telemetry": _telemetry_payload(state.get("telemetry")),
        }
    if configured_mode == "off":
        tuning = inspect_tuning_status(root, None)
        meta = _resolver_metadata(
            root,
            public_mode="off",
            effective_mode="off",
            effective_state=EFFECTIVE_OFF_RAW,
            tuning_profile=None,
            tuning=tuning,
        )
        return {
            **state,
            **meta,
            "tuning": tuning,
            "fallback": _fallback_payload(state.get("fallback")),
            "telemetry": _telemetry_payload(state.get("telemetry")),
        }
    if configured_mode == "tuned":
        profile = str(state.get("tuning_profile") or DEFAULT_TUNING_PROFILE)
        tuning = inspect_tuning_status(root, profile)
        verified = bool(tuning["profile_valid"] and tuning["verify"] == "PASS")
        fallback_reason = None if verified else str(tuning.get("fallback_reason") or "tuned_not_verified")
        meta = _resolver_metadata(
            root,
            public_mode="tuned",
            effective_mode="tuned",
            effective_state=EFFECTIVE_TUNED_STRICT,
            tuning_profile=profile,
            tuning=tuning,
            fallback_reason=fallback_reason,
        )
        return {
            **state,
            **meta,
            "tuning": tuning,
            "fallback": _fallback_payload(state.get("fallback")),
            "telemetry": _telemetry_payload(state.get("telemetry")),
        }
    profile = _profile_for_on(root)
    tuning = inspect_tuning_status(root, profile)
    use_tuned = tuning["profile_valid"] and tuning["verify"] == "PASS"
    fallback_reason = tuning.get("fallback_reason") if profile else None
    fallback_state = _fallback_payload(state.get("fallback"))
    fallback = {
        "active": bool(fallback_reason),
        "last_reason": str(fallback_reason) if fallback_reason else fallback_state["last_reason"],
        "last_at": fallback_state["last_at"],
    }
    effective_state = EFFECTIVE_ON_TUNED_VERIFIED if use_tuned else EFFECTIVE_ON_GENERALIZED
    meta = _resolver_metadata(
        root,
        public_mode="on",
        effective_mode="tuned" if use_tuned else "on",
        effective_state=effective_state,
        tuning_profile=str(profile),
        tuning=tuning,
        fallback_reason=str(fallback_reason) if fallback_reason else None,
    )
    return {
        **state,
        **meta,
        "tuning": tuning,
        "fallback": fallback,
        "telemetry": _telemetry_payload(state.get("telemetry")),
    }


def record_runtime_telemetry(
    repo_root: Path | str,
    *,
    configured_mode: str,
    effective_mode: str,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    state = read_pcodex_state(root)
    state.pop("_state_status", None)
    state.pop("_state_error", None)
    telemetry = _telemetry_payload(state.get("telemetry"))
    telemetry["compile_count"] += 1
    mode_counts = telemetry["mode_counts"]
    if effective_mode in mode_counts:
        mode_counts[effective_mode] += 1
    fallback = _fallback_payload(state.get("fallback"))
    if fallback_reason:
        telemetry["fallback_count"] += 1
        fallback = {"active": True, "last_reason": str(fallback_reason), "last_at": _utc_now()}
    else:
        fallback = {"active": False, "last_reason": fallback["last_reason"], "last_at": fallback["last_at"]}
    state["effective_mode"] = effective_mode
    state["fallback"] = fallback
    state["telemetry"] = telemetry
    resolved = resolve_effective_mode(root)
    tuning = resolved.get("tuning") if isinstance(resolved.get("tuning"), dict) else {}
    state["last_verify"] = {
        "verdict": _optional_string_or_none(tuning.get("verify")),
        "results_path": _optional_string_or_none(tuning.get("results_path")),
        "checked_at": _utc_now(),
    }
    write_pcodex_state(root, state)
    return {"fallback": fallback, "telemetry": telemetry}


def set_mode_tuned(repo_root: Path | str, profile: Path | str = DEFAULT_TUNING_PROFILE) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    validation = validate_tuning_profile_for_mode(root, profile)
    tuning = inspect_tuning_status(root, validation["profile_path"])
    if tuning.get("verify") != "PASS":
        reason = tuning.get("fallback_reason") or "tuning_not_verified"
        raise PcodexStateError(f"Verified tuning is required for tuned mode: {reason}")
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
