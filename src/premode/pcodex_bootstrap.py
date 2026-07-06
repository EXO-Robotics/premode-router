from __future__ import annotations

import argparse
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any

from .codex_exec import CodexOptions, build_codex_invocation, run_codex
from .compiler import compile_prompt
from .pcodex_state import (
    DEFAULT_TUNING_PROFILE,
    PcodexStateError,
    record_runtime_telemetry,
    resolve_effective_mode,
    set_mode_off,
    set_mode_on,
    set_mode_tuned,
)
from .plugins import PluginAliasError, available_plugin_aliases, resolve_packet_plugin

PCODEX_PLUGIN_ALIAS = "literal_symbol"
PCODEX_PACKET_VERSION = "v5"
PCODEX_PACKET_VARIANT = "tool_assisted_anchors_internal"
PCODEX_PACKET_STRATEGY = "literal_symbol"
PCODEX_FALLBACK_VARIANT = "ranked_paths_plus_anchors"
CONFIG_ENV = "PCODEX_ENABLED"
CONFIG_PATH_ENV = "PCODEX_CONFIG"
CONFIG_PATH_ALIAS_ENV = "PCODEX_CONFIG_PATH"
ALGORITHM_ENV = "PCODEX_ALGORITHM"
PROJECT_ROOT_ENV = "PCODEX_PROJECT_ROOT"
PACKET_STRATEGY_ENV = "PCODEX_PACKET_STRATEGY"


@dataclass(frozen=True)
class PcodexConfig:
    enabled: bool = False
    source: str = "default"
    path: str | None = None
    algorithm: str = PCODEX_PACKET_STRATEGY


def _repo_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def _repo_config_path(repo_root: Path) -> Path:
    return repo_root / ".pcodex" / "config.toml"


def _user_config_path() -> Path:
    return Path.home() / ".pcodex" / "config.toml"


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _parse_algorithm(value: Any) -> str | None:
    if value is None:
        return PCODEX_PACKET_STRATEGY
    text = str(value).strip()
    return text if text == PCODEX_PACKET_STRATEGY else None


def _read_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    pcodex = data.get("pcodex")
    return pcodex if isinstance(pcodex, dict) else data


def resolve_config(cwd: Path | None = None, env: dict[str, str] | None = None) -> PcodexConfig:
    env = dict(os.environ if env is None else env)
    cwd = Path.cwd() if cwd is None else cwd
    env_algorithm = _parse_algorithm(env.get(ALGORITHM_ENV))
    if env_algorithm is None:
        return PcodexConfig(enabled=False, source=f"{ALGORITHM_ENV}:invalid", path=None)

    env_raw_value = env.get(CONFIG_ENV)
    env_value = _parse_bool(env_raw_value)
    if env_raw_value is not None and env_value is None:
        return PcodexConfig(enabled=False, source=f"{CONFIG_ENV}:invalid", path=None, algorithm=env_algorithm)
    if env_value is not None:
        return PcodexConfig(enabled=env_value, source=CONFIG_ENV, path=None, algorithm=env_algorithm)

    paths: list[tuple[str, Path]] = []
    config_path_value = env.get(CONFIG_PATH_ENV) or env.get(CONFIG_PATH_ALIAS_ENV)
    if config_path_value:
        source = CONFIG_PATH_ENV if env.get(CONFIG_PATH_ENV) else CONFIG_PATH_ALIAS_ENV
        paths.append((source, Path(config_path_value).expanduser()))
    repo_root = _repo_root(cwd)
    paths.extend([("repo", _repo_config_path(repo_root)), ("user", _user_config_path())])
    for source, path in paths:
        data = _read_config(path)
        enabled = _parse_bool(data.get("enabled"))
        algorithm = _parse_algorithm(data.get("algorithm"))
        if algorithm is None:
            return PcodexConfig(enabled=False, source=f"{source}:invalid", path=str(path))
        if enabled is not None:
            return PcodexConfig(
                enabled=enabled,
                source=source,
                path=str(path),
                algorithm=algorithm,
            )
        if path.exists():
            return PcodexConfig(enabled=False, source=f"{source}:invalid", path=str(path))
    return PcodexConfig()


def write_repo_config(cwd: Path, *, enabled: bool) -> Path:
    repo_root = _repo_root(cwd)
    path = _repo_config_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[pcodex]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        f"algorithm = \"{PCODEX_PACKET_STRATEGY}\"\n",
        encoding="utf-8",
    )
    return path


def _command_available(name: str) -> bool:
    if shutil.which(name) is not None:
        return True
    sibling = Path(sys.executable).with_name(name)
    return sibling.exists() and os.access(sibling, os.X_OK)


def _command_path(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    sibling = Path(sys.executable).with_name(name)
    if sibling.exists() and os.access(sibling, os.X_OK):
        return str(sibling)
    return None


def plugin_alias_available() -> bool:
    try:
        resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
    except PluginAliasError:
        return False
    return True


def _literal_symbol_kwargs() -> dict[str, str]:
    return {
        "packet_version": PCODEX_PACKET_VERSION,
        "packet_variant": PCODEX_PACKET_VARIANT,
        "packet_strategy": PCODEX_PACKET_STRATEGY,
    }


def _append_tuning_command(cmd: list[str], tuning_profile: str | None) -> list[str]:
    if tuning_profile:
        cmd.extend(["--tuning", tuning_profile])
    return cmd


def _premode_alias_command(prompt: str, repo_root: Path, profile: str | None, tuning_profile: str | None = None) -> list[str]:
    cmd = ["premode", "compile", prompt, "--repo", str(repo_root), "--plugin", PCODEX_PLUGIN_ALIAS]
    if profile:
        cmd.extend(["--profile", profile])
    return _append_tuning_command(cmd, tuning_profile)


def _premode_explicit_command(prompt: str, repo_root: Path, profile: str | None, tuning_profile: str | None = None) -> list[str]:
    cmd = [
        "premode",
        "compile",
        prompt,
        "--repo",
        str(repo_root),
        "--packet-version",
        PCODEX_PACKET_VERSION,
        "--packet-variant",
        PCODEX_PACKET_VARIANT,
        "--packet-strategy",
        PCODEX_PACKET_STRATEGY,
    ]
    if profile:
        cmd.extend(["--profile", profile])
    return _append_tuning_command(cmd, tuning_profile)


def _compile_runner_accepts_tuning(compile_runner: Any) -> bool:
    try:
        signature = inspect.signature(compile_runner)
    except (TypeError, ValueError):
        return False
    return "tuning_profile" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def run_compile_runner(
    compile_runner: Any,
    repo_root: Path,
    prompt: str,
    profile: str | None,
    *,
    tuning_profile: str | None = None,
) -> dict[str, Any]:
    if tuning_profile and _compile_runner_accepts_tuning(compile_runner):
        return compile_runner(repo_root, prompt, profile, tuning_profile=tuning_profile)
    return compile_runner(repo_root, prompt, profile)


def compile_pcodex_packet(
    repo_root: Path,
    prompt: str,
    profile: str | None = "lite",
    *,
    tuning_profile: str | None = None,
) -> dict[str, Any]:
    try:
        resolved = resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
        route = "plugin_alias"
        command = _premode_alias_command(prompt, repo_root, profile, tuning_profile)
        kwargs = resolved.as_compile_kwargs()
        plugin_resolution = resolved.as_dict()
    except PluginAliasError as exc:
        route = "explicit_fallback"
        command = _premode_explicit_command(prompt, repo_root, profile, tuning_profile)
        kwargs = _literal_symbol_kwargs()
        plugin_resolution = None
        fallback_reason = str(exc)
    else:
        fallback_reason = None
    compiled = compile_prompt(
        repo_root,
        prompt,
        profile,
        use_repo_map=True,
        cache_optimized=True,
        save=False,
        record_artifacts=False,
        tuning_profile=tuning_profile,
        **kwargs,
    )
    return {
        "status": "compiled",
        "route": route,
        "premode_command": command,
        "plugin_alias_resolution": plugin_resolution,
        "fallback_reason": fallback_reason,
        "packet": compiled["packet"],
        "packet_sha256": compiled.get("compiled_packet_sha256"),
        "packet_version": compiled.get("packet_version"),
        "packet_variant": compiled.get("packet_variant"),
        "packet_strategy": compiled.get("strategy_selected") or kwargs.get("packet_strategy"),
        "model_facing_sections": ["TASK", "PRIMARY_FILES", "RELATED_TESTS", "END_PREMODE_CONTEXT_PACKET_V5"],
        "tuning_profile": tuning_profile,
    }


def redact_text(text: str, limit: int = 800) -> str:
    redacted = re.sub(r"\b\S*(?:SECRET|TOKEN|PASSWORD|API[_-]?KEY)\S*\b", "<redacted>", text, flags=re.IGNORECASE)
    return redacted[:limit] + ("..." if len(redacted) > limit else "")


def compose_final_prompt(raw_task: str, packet: str | None) -> str:
    if packet:
        return packet
    return raw_task


def doctor(cwd: Path | None = None) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    config = resolve_config(cwd)
    return {
        "status": "ok",
        "repo_root": str(repo_root),
        "premode_executable_available": _command_available("premode"),
        "pcodex_executable_available": _command_available("pcodex"),
        "codex_executable_available": _command_available("codex"),
        "plugin_alias_available": plugin_alias_available(),
        "available_plugin_aliases": available_plugin_aliases(),
        "fallback_explicit_literal_symbol_available": True,
        "git_repo": (repo_root / ".git").exists(),
        "config": config.__dict__,
        "algorithm": PCODEX_PACKET_STRATEGY,
        "secrets_printed": False,
    }


def run_one_step_tune(repo_root: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    from .tuning import validate_tuning_artifacts, verify_tuning_profile, write_tuning_artifacts

    generation = write_tuning_artifacts(repo_root, out_dir=out_dir)
    validation = validate_tuning_artifacts(repo_root, out_dir=out_dir)
    verification = verify_tuning_profile(repo_root, out_dir=out_dir)
    verdict = str(verification.get("verdict") or "FAIL")
    if verdict == "PASS":
        status = "tuning_ready"
        next_step = "pcodex setup or pcodex tuned"
    elif verdict == "NEEDS_ADJUSTMENT":
        status = "needs_adjustment"
        next_step = "keep general literal_symbol mode and inspect VERIFY_REPORT.md"
    else:
        status = "failed"
        next_step = "keep general literal_symbol mode and repair tuning artifacts"
    return {
        "status": status,
        "repo_root": str(repo_root),
        "out_dir": str(out_dir or (repo_root / ".premode" / "tuning")),
        "generation_status": generation.get("status"),
        "validation_status": "PASS" if validation.get("status") == "pass" else "FAIL",
        "validation_failures": validation.get("failures", []),
        "verdict": verdict,
        "profile_validation_status": verification.get("profile_validation_status"),
        "evaluation_prompt_count": verification.get("evaluation_prompt_count"),
        "notes": verification.get("notes", []),
        "artifacts": {
            "repo_profile": str((out_dir or (repo_root / ".premode" / "tuning")) / "repo_profile.json"),
            "VALIDATION": str((out_dir or (repo_root / ".premode" / "tuning")) / "VALIDATION.json"),
            "VERIFY_RESULTS": str((out_dir or (repo_root / ".premode" / "tuning")) / "VERIFY_RESULTS.json"),
            "VERIFY_REPORT": str((out_dir or (repo_root / ".premode" / "tuning")) / "VERIFY_REPORT.md"),
        },
        "safety_summary": {
            "local_only": True,
            "source_edits": False,
            "model_facing_packet_expansion": False,
            "live_codex_tasks": False,
            "real_codex_config_mutation": False,
        },
        "next": next_step,
        "generation": generation,
        "validation": validation,
        "verification": verification,
    }


def _one_step_tune_exit_code(result: dict[str, Any]) -> int:
    verdict = result.get("verdict")
    if verdict in {"PASS", "NEEDS_ADJUSTMENT"}:
        return 0
    return 2


def _isolated_codex_home(repo_root: Path) -> Path:
    return repo_root / ".premode" / "pcodex_codex_home"


def _run_codex_mcp_command(args: list[str], *, codex_home: Path | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    if codex_home is not None:
        codex_home.mkdir(parents=True, exist_ok=True)
        env["CODEX_HOME"] = str(codex_home)
    completed = subprocess.run(
        ["codex", "mcp", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    return {
        "args": ["codex", "mcp", *args],
        "returncode": completed.returncode,
        "stdout": redact_text(completed.stdout, limit=1200),
        "stderr": redact_text(completed.stderr, limit=1200),
    }


def register_mcp_for_setup(
    repo_root: Path,
    *,
    no_mcp: bool = False,
    isolated: bool = True,
    real_codex_registration: bool = False,
) -> dict[str, Any]:
    if no_mcp:
        return {"status": "skipped", "reason": "no_mcp", "registered": False, "config_scope": "none"}
    if not _command_available("codex"):
        return {"status": "skipped", "reason": "codex_cli_missing", "registered": False, "config_scope": "none"}
    if real_codex_registration:
        codex_home = None
        config_scope = "real"
        warning = "This mutates real local Codex MCP config because --real-codex-registration was explicitly provided."
    else:
        codex_home = _isolated_codex_home(repo_root) if isolated else _isolated_codex_home(repo_root)
        config_scope = "isolated"
        warning = None
    pcodex_command = _command_path("pcodex") or "pcodex"
    add_result = _run_codex_mcp_command(["add", "pcodex", "--", pcodex_command, "mcp-server"], codex_home=codex_home)
    list_result = _run_codex_mcp_command(["list"], codex_home=codex_home)
    registered = add_result["returncode"] == 0
    status_value = "registered" if registered else "failed"
    return {
        "status": status_value,
        "registered": registered,
        "config_scope": config_scope,
        "codex_home": str(codex_home) if codex_home is not None else None,
        "warning": warning,
        "command": add_result,
        "list": list_result,
        "rollback": "codex mcp remove pcodex",
        "fatal": False,
    }


def setup(
    cwd: Path | None = None,
    *,
    skip_tune: bool = False,
    no_mcp: bool = False,
    isolated: bool = True,
    real_codex_registration: bool = False,
    tune_runner: Any | None = None,
    mcp_registrar: Any | None = None,
) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    doctor_result = doctor(repo_root)
    checks = {
        "premode_available": bool(doctor_result.get("premode_executable_available")),
        "pcodex_available": bool(doctor_result.get("pcodex_executable_available")),
        "literal_symbol_plugin_available": bool(doctor_result.get("plugin_alias_available")),
        "codex_available": bool(doctor_result.get("codex_executable_available")),
    }
    blocking = [name for name in ("premode_available", "literal_symbol_plugin_available") if not checks[name]]
    if blocking:
        mode_result = set_enabled(repo_root, True)
        return {
            "setup_status": "failed",
            "repo_root": str(repo_root),
            "checks": checks,
            "blocking_checks": blocking,
            "doctor": doctor_result,
            "mode": mode_result.get("mode"),
            "tuning_verdict": "SKIPPED",
            "mcp_status": "not_attempted",
            "fallback": "using general literal_symbol",
            "next_steps": ["repair local pCodex prerequisites", "rerun pcodex setup"],
            "codex_launch": "not_executed",
        }
    tune_result: dict[str, Any] | None = None
    tuning_verdict = "SKIPPED"
    if not skip_tune:
        runner = tune_runner or run_one_step_tune
        try:
            tune_result = runner(repo_root)
            tuning_verdict = str(tune_result.get("verdict") or "FAIL")
        except Exception as exc:
            tune_result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            tuning_verdict = "FAIL"
    if tuning_verdict == "PASS":
        try:
            mode_result = set_tuned(repo_root)
        except PcodexStateError as exc:
            mode_result = set_enabled(repo_root, True)
            tuning_verdict = "FAIL"
            tune_result = {**(tune_result or {}), "mode_error": str(exc)}
    else:
        mode_result = set_enabled(repo_root, True)
    registrar = mcp_registrar or register_mcp_for_setup
    mcp_result = registrar(
        repo_root,
        no_mcp=no_mcp,
        isolated=isolated,
        real_codex_registration=real_codex_registration,
    )
    mode = str(mode_result.get("mode") or "on")
    fallback = "general mode available" if mode == "tuned" else "using general literal_symbol"
    return {
        "setup_status": "complete",
        "repo_root": str(repo_root),
        "checks": checks,
        "blocking_checks": [],
        "doctor": doctor_result,
        "mode": mode,
        "tuning_verdict": tuning_verdict,
        "tune": tune_result,
        "mcp": mcp_result,
        "mcp_status": _format_mcp_status(mcp_result),
        "fallback": fallback,
        "next_steps": ["pcodex status", "pcodex run --dry-run \"Hypothetical dummy task: inspect login flow. Do not modify files.\""],
        "codex_launch": "not_executed",
    }


def status(cwd: Path | None = None) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    config = resolve_config(cwd)
    state = resolve_effective_mode(repo_root)
    configured_mode = str(state.get("configured_mode") or state.get("mode") or "on")
    effective_mode = str(state.get("effective_mode") or configured_mode)
    if config.source in {CONFIG_ENV, CONFIG_PATH_ENV, CONFIG_PATH_ALIAS_ENV, "repo", "user"} and not state["state_exists"]:
        configured_mode = "on" if config.enabled else "off"
        effective_mode = configured_mode
        state["enabled"] = config.enabled
        state["mode"] = configured_mode
        state["configured_mode"] = configured_mode
        state["effective_mode"] = effective_mode
        state["tuning_profile"] = None
        state["effective_tuning_profile"] = None
    tuning = state.get("tuning") if isinstance(state.get("tuning"), dict) else {}
    fallback = state.get("fallback") if isinstance(state.get("fallback"), dict) else {}
    telemetry = state.get("telemetry") if isinstance(state.get("telemetry"), dict) else {}
    mcp = {
        "codex_cli_available": _command_available("codex"),
        "registered": False,
        "config_scope": "unknown",
        "status": "unknown",
    }
    return {
        "schema_version": "pcodex.status.v1",
        "enabled": bool(state.get("enabled")),
        "configured_mode": configured_mode,
        "effective_mode": effective_mode,
        "mode": configured_mode,
        "algorithm": state.get("algorithm") or PCODEX_PACKET_STRATEGY,
        "tuning": {
            "profile": tuning.get("profile"),
            "validation": tuning.get("validation"),
            "verify": tuning.get("verify"),
            "results_path": tuning.get("results_path"),
        },
        "mcp": mcp,
        "fallback": {
            "active": bool(fallback.get("active")),
            "last_reason": fallback.get("last_reason"),
            "last_at": fallback.get("last_at"),
        },
        "telemetry": telemetry,
        "savings": {"available": False, "reason": "not_enough_data"},
        "state_path": state.get("state_path"),
        "state_exists": state.get("state_exists"),
        "state_status": state.get("state_status"),
        "state_error": state.get("state_error"),
        "state_schema_version": "pcodex.state.v1",
        "tuning_profile": tuning.get("profile"),
        "tuning_profile_valid": tuning.get("profile_valid"),
        "tuning_validation_status": tuning.get("validation"),
        "config_source": config.source,
        "config_path": config.path,
        "legacy_enabled": config.enabled,
        "premode_available": _command_available("premode"),
        "codex_available": mcp["codex_cli_available"],
        "plugin_alias_available": plugin_alias_available(),
    }


def _format_mcp_status(mcp_result: dict[str, Any]) -> str:
    status_value = str(mcp_result.get("status") or "unknown")
    scope = str(mcp_result.get("config_scope") or "none")
    if status_value == "registered":
        return f"registered in {scope} config"
    if status_value == "skipped":
        reason = mcp_result.get("reason")
        return f"skipped ({reason})" if reason else "skipped"
    if status_value == "failed":
        return f"registration failed in {scope} config"
    return status_value


def child_env_for(repo_root: Path, config: PcodexConfig | None = None) -> dict[str, str]:
    config = resolve_config(repo_root) if config is None else config
    env = {
        CONFIG_ENV: "1" if config.enabled else "0",
        ALGORITHM_ENV: PCODEX_PACKET_STRATEGY,
        PACKET_STRATEGY_ENV: PCODEX_PACKET_STRATEGY,
        PROJECT_ROOT_ENV: str(repo_root.resolve()),
    }
    if config.path and config.source in {"repo", CONFIG_PATH_ENV, CONFIG_PATH_ALIAS_ENV}:
        env[CONFIG_PATH_ENV] = config.path
        env[CONFIG_PATH_ALIAS_ENV] = config.path
    return env


def child_env_for_mode_state(repo_root: Path, mode_state: dict[str, Any]) -> dict[str, str]:
    return {
        CONFIG_ENV: "1" if str(mode_state.get("effective_mode") or mode_state.get("mode")) != "off" else "0",
        ALGORITHM_ENV: PCODEX_PACKET_STRATEGY,
        PACKET_STRATEGY_ENV: PCODEX_PACKET_STRATEGY,
        PROJECT_ROOT_ENV: str(repo_root.resolve()),
    }


def resolve_mode_state(repo_root: Path, *, validate_tuned: bool = True, require_runnable: bool = False) -> dict[str, Any]:
    mode_state = resolve_effective_mode(repo_root, validate_tuned=validate_tuned)
    if mode_state.get("state_status") == "invalid_default":
        message = mode_state.get("state_error") or "Invalid pCodex mode state"
        if require_runnable:
            raise PcodexStateError(str(message))
        return mode_state
    tuning = mode_state.get("tuning") if isinstance(mode_state.get("tuning"), dict) else {}
    if require_runnable and mode_state.get("configured_mode") == "tuned" and not tuning.get("profile_valid"):
        message = tuning.get("profile_error") or "Invalid pCodex tuning profile"
        raise PcodexStateError(str(message))
    return mode_state


def _state_tuning_profile(mode_state: dict[str, Any]) -> str | None:
    if mode_state.get("effective_mode") != "tuned":
        return None
    profile = mode_state.get("effective_tuning_profile") or mode_state.get("tuning_profile")
    return str(profile) if profile else None


def install(cwd: Path | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    path = _repo_config_path(repo_root)
    result = {
        "status": "dry_run" if dry_run else "installed",
        "repo_root": str(repo_root),
        "config_path": str(path),
        "would_write": not path.exists(),
        "doctor": doctor(cwd),
    }
    if not dry_run and not path.exists():
        write_repo_config(cwd, enabled=False)
        result["written"] = True
    else:
        result["written"] = False
    return result


def set_enabled(cwd: Path | None, enabled: bool) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    path = write_repo_config(cwd, enabled=enabled)
    mode_result = set_mode_on(cwd) if enabled else set_mode_off(cwd)
    return {
        "status": "enabled" if enabled else "disabled",
        **mode_result,
        "config_path": str(path),
        "legacy_config_path": str(path),
    }


def set_tuned(cwd: Path | None, profile: str | None = None) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    result = set_mode_tuned(cwd, profile or DEFAULT_TUNING_PROFILE)
    path = write_repo_config(cwd, enabled=True)
    return {"status": "tuned", **result, "config_path": str(path), "legacy_config_path": str(path)}


def format_status(payload: dict[str, Any]) -> str:
    tuning = payload.get("tuning") if isinstance(payload.get("tuning"), dict) else {}
    fallback = payload.get("fallback") if isinstance(payload.get("fallback"), dict) else {}
    telemetry = payload.get("telemetry") if isinstance(payload.get("telemetry"), dict) else {}
    mcp = payload.get("mcp") if isinstance(payload.get("mcp"), dict) else {}
    savings = payload.get("savings") if isinstance(payload.get("savings"), dict) else {}
    fallback_text = "active"
    if not fallback.get("active"):
        fallback_text = "none"
    elif fallback.get("last_reason"):
        fallback_text = f"active ({fallback.get('last_reason')})"
    mcp_status = str(mcp.get("status") or "unknown")
    if mcp_status == "unknown":
        mcp_text = "unknown"
    elif mcp.get("registered"):
        mcp_text = f"registered in {mcp.get('config_scope') or 'unknown'} config"
    else:
        mcp_text = "not registered"
    savings_text = "unavailable"
    if not savings.get("available"):
        savings_text = f"unavailable ({savings.get('reason') or 'unknown'})"
    lines = [
        f"pCodex: {'on' if payload.get('enabled') else 'off'}",
        f"Configured mode: {payload.get('configured_mode')}",
        f"Effective mode: {payload.get('effective_mode')}",
        f"Algorithm: {payload.get('algorithm')}",
        f"Tuning: {tuning.get('verify') or tuning.get('validation') or 'missing'}",
        f"Tuning profile: {tuning.get('profile') or 'none'}",
        f"MCP: {mcp_text}",
        f"Codex CLI: {'available' if mcp.get('codex_cli_available') else 'unavailable'}",
        f"Fallback: {fallback_text}",
        f"Telemetry: compile_count={telemetry.get('compile_count', 0)} fallback_count={telemetry.get('fallback_count', 0)}",
        f"Savings estimate: {savings_text}",
        f"State path: {payload.get('state_path')}",
    ]
    if payload.get("state_status") != "loaded":
        lines.append(f"State status: {payload.get('state_status')}")
    return "\n".join(lines)


def format_setup_dashboard(payload: dict[str, Any], *, verbose: bool = False) -> str:
    lines = [
        "pCodex setup complete." if payload.get("setup_status") == "complete" else "pCodex setup failed.",
        f"Mode: {payload.get('mode')}",
        f"Tuning: {payload.get('tuning_verdict')}",
        f"MCP: {payload.get('mcp_status')}",
        f"Fallback: {payload.get('fallback')}",
    ]
    if verbose:
        checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
        lines.append("Checks:")
        for key in sorted(checks):
            lines.append(f"  {key}: {str(checks[key]).lower()}")
        next_steps = payload.get("next_steps") if isinstance(payload.get("next_steps"), list) else []
        if next_steps:
            lines.append("Next steps:")
            lines.extend(f"  {step}" for step in next_steps)
        mcp = payload.get("mcp") if isinstance(payload.get("mcp"), dict) else {}
        warning = mcp.get("warning")
        if warning:
            lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def _write_temp_packet(packet: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="pcodex_packet_", suffix=".md", delete=False)
    with handle:
        handle.write(packet)
    return handle.name


def run_dry_run(
    repo_root: Path,
    prompt: str,
    profile: str | None = "lite",
    *,
    compile_runner: Any | None = None,
) -> dict[str, Any]:
    mode_state = resolve_mode_state(repo_root, validate_tuned=True, require_runnable=True)
    mode = str(mode_state.get("configured_mode") or mode_state["mode"])
    effective_mode = str(mode_state.get("effective_mode") or mode)
    tuning_profile = _state_tuning_profile(mode_state)
    child_env = child_env_for_mode_state(repo_root, mode_state)
    fallback = mode_state.get("fallback") if isinstance(mode_state.get("fallback"), dict) else {}
    fallback_reason = str(fallback.get("last_reason")) if fallback.get("active") and fallback.get("last_reason") else None
    base = {
        "status": "dry_run",
        "enabled": effective_mode != "off",
        "mode": mode,
        "configured_mode": mode,
        "effective_mode": effective_mode,
        "transform_applied": effective_mode != "off",
        "tuning_profile": tuning_profile,
        "tuning": mode_state.get("tuning"),
        "fallback": fallback,
        "state_status": mode_state.get("state_status"),
        "state_error": mode_state.get("state_error"),
        "config_source": "pcodex_state",
        "algorithm": PCODEX_PACKET_STRATEGY,
        "child_env": child_env,
        "child_env_keys": sorted(child_env),
        "raw_task_preview": redact_text(prompt),
        "codex_launch": "not_executed",
    }
    if effective_mode != "off":
        runner = compile_runner or compile_pcodex_packet
        compiled = run_compile_runner(runner, repo_root, prompt, profile, tuning_profile=tuning_profile)
        telemetry = record_runtime_telemetry(repo_root, configured_mode=mode, effective_mode=effective_mode, fallback_reason=fallback_reason)
        packet_path = _write_temp_packet(compiled["packet"])
        final_prompt = compose_final_prompt(prompt, compiled["packet"])
        invocation = build_codex_invocation(repo_root, CodexOptions(dry_run=True))
        return {
            **base,
            "premode_command": compiled["premode_command"],
            "codex_command": invocation.args,
            "packet_path": packet_path,
            "final_prompt_preview": redact_text(final_prompt),
            "packet_sha256": compiled["packet_sha256"],
            "route": compiled["route"],
            "telemetry": telemetry.get("telemetry"),
        }
    telemetry = record_runtime_telemetry(repo_root, configured_mode=mode, effective_mode=effective_mode)
    invocation = build_codex_invocation(repo_root, CodexOptions(dry_run=True))
    return {
        **base,
        "premode_command": None,
        "codex_command": invocation.args,
        "packet_path": None,
        "final_prompt_preview": redact_text(prompt),
        "telemetry": telemetry.get("telemetry"),
    }


def run_enabled(repo_root: Path, prompt: str, profile: str | None = "lite") -> dict[str, Any]:
    mode_state = resolve_mode_state(repo_root, validate_tuned=True, require_runnable=True)
    tuning_profile = _state_tuning_profile(mode_state)
    configured_mode = str(mode_state.get("configured_mode") or mode_state.get("mode") or "on")
    effective_mode = str(mode_state.get("effective_mode") or configured_mode)
    fallback = mode_state.get("fallback") if isinstance(mode_state.get("fallback"), dict) else {}
    fallback_reason = str(fallback.get("last_reason")) if fallback.get("active") and fallback.get("last_reason") else None
    record_runtime_telemetry(repo_root, configured_mode=configured_mode, effective_mode=effective_mode, fallback_reason=fallback_reason)
    child_env = child_env_for_mode_state(repo_root, mode_state)
    return run_codex(
        repo_root,
        prompt,
        profile,
        CodexOptions(
            dry_run=False,
            execute=True,
            packet_version=PCODEX_PACKET_VERSION,
            packet_variant=PCODEX_PACKET_VARIANT,
            packet_strategy=PCODEX_PACKET_STRATEGY,
            lane="pcodex",
            tuning_profile=tuning_profile,
            child_env=child_env,
        ),
    )


def run_disabled(repo_root: Path, prompt: str, mode_state: dict[str, Any] | None = None) -> dict[str, Any]:
    mode_state = mode_state or resolve_mode_state(repo_root, validate_tuned=False)
    child_env = child_env_for_mode_state(repo_root, mode_state)
    completed = subprocess.run(["codex", "exec", "-"], input=prompt, text=True, capture_output=True, check=False, cwd=repo_root, env={**os.environ, **child_env})
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "enabled": False,
        "mode": str(mode_state.get("mode") or "off"),
        "transform_applied": False,
        "child_env": child_env,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcodex")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--apply", action="store_true", help="Write repo-local pCodex config. Default is dry-run.")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--json", action="store_true", help="Print machine-readable pCodex mode state.")
    status_parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    setup_parser = sub.add_parser("setup")
    setup_parser.add_argument("--skip-tune", action="store_true", help="Skip tune/validate/verify and enable general mode.")
    setup_parser.add_argument("--no-mcp", action="store_true", help="Skip Codex MCP registration.")
    setup_parser.add_argument("--isolated", action="store_true", help="Use isolated Codex config for MCP registration. This is the default.")
    setup_parser.add_argument("--real-codex-registration", action="store_true", help="Explicitly mutate real local Codex MCP config.")
    setup_parser.add_argument("--verbose", action="store_true", help="Print detailed setup checks.")
    setup_parser.add_argument("--json", action="store_true", help="Print machine-readable setup result.")
    setup_parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    on = sub.add_parser("on")
    on.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    off = sub.add_parser("off")
    off.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    tuned = sub.add_parser("tuned")
    tuned.add_argument("--profile", default=DEFAULT_TUNING_PROFILE, help="Validated tuning profile to use for tuned mode.")
    tuned.add_argument("--repo-root", default=None, help="Repository root. Defaults to the current repo.")
    tune = sub.add_parser("tune")
    tune_group = tune.add_mutually_exclusive_group()
    tune_group.add_argument("--static-only", action="store_true", help="Generate static local tuning artifacts only.")
    tune_group.add_argument("--validate", action="store_true", help="Validate existing .premode/tuning artifacts without regenerating them.")
    tune_group.add_argument("--verify", action="store_true", help="Verify static tuning profile quality with compile-only local selection.")
    tune.add_argument("--repo-root", default=None, help="Repository root to tune. Defaults to the current repo.")
    tune.add_argument("--out-dir", default=None, help="Artifact directory. Must remain under .premode/tuning/.")
    sub.add_parser("mcp-server")
    comp = sub.add_parser("compile")
    comp.add_argument("prompt")
    comp.add_argument("--repo", default=None)
    comp.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    comp.add_argument("--dry-run", action="store_true")
    comp.add_argument("--json", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("prompt")
    run.add_argument("--repo", default=None)
    run.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    cwd = Path.cwd()
    repo_arg = getattr(args, "repo", None) or getattr(args, "repo_root", None)
    repo_root = _repo_root(Path(repo_arg).resolve() if repo_arg else cwd)
    if args.command == "doctor":
        print(json.dumps(doctor(repo_root), indent=2, sort_keys=True))
        return 0
    if args.command == "install":
        print(json.dumps(install(repo_root, dry_run=not args.apply), indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        payload = status(repo_root)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(format_status(payload))
        return 0
    if args.command == "setup":
        payload = setup(
            repo_root,
            skip_tune=args.skip_tune,
            no_mcp=args.no_mcp,
            isolated=True,
            real_codex_registration=args.real_codex_registration,
        )
        if args.real_codex_registration and not args.json:
            mcp = payload.get("mcp") if isinstance(payload.get("mcp"), dict) else {}
            warning = mcp.get("warning")
            if warning:
                print(f"Warning: {warning}", file=sys.stderr)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(format_setup_dashboard(payload, verbose=args.verbose))
        return 0 if payload.get("setup_status") == "complete" else 2
    if args.command == "on":
        print(json.dumps(set_enabled(repo_root, True), indent=2, sort_keys=True))
        return 0
    if args.command == "off":
        print(json.dumps(set_enabled(repo_root, False), indent=2, sort_keys=True))
        return 0
    if args.command == "tuned":
        try:
            print(json.dumps(set_tuned(repo_root, args.profile), indent=2, sort_keys=True))
        except PcodexStateError as exc:
            print(json.dumps({"status": "error", "error": str(exc), "mode": "tuned"}, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        return 0
    if args.command == "tune":
        from .tuning import validate_tuning_artifacts, verify_tuning_profile, write_tuning_artifacts

        try:
            if args.verify:
                result = verify_tuning_profile(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result.get("verdict") in {"PASS", "NEEDS_ADJUSTMENT"} else 1
            if args.validate:
                result = validate_tuning_artifacts(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result.get("status") == "pass" else 1
            if args.static_only:
                result = write_tuning_artifacts(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result.get("validation_status") == "pass" else 1
            result = run_one_step_tune(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
        except ValueError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2, sort_keys=True))
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return _one_step_tune_exit_code(result)
    if args.command == "mcp-server":
        from . import pcodex_mcp_server

        return pcodex_mcp_server.serve()
    if args.command == "compile":
        if args.dry_run:
            try:
                resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
                command = _premode_alias_command(args.prompt, repo_root, args.profile)
                route = "plugin_alias"
            except PluginAliasError as exc:
                command = _premode_explicit_command(args.prompt, repo_root, args.profile)
                route = "explicit_fallback"
                fallback_reason = str(exc)
            else:
                fallback_reason = None
            print(json.dumps({"status": "dry_run", "route": route, "premode_command": command, "fallback_reason": fallback_reason}, indent=2, sort_keys=True))
            return 0
        compiled = compile_pcodex_packet(repo_root, args.prompt, args.profile)
        if args.json:
            payload = {key: value for key, value in compiled.items() if key != "packet"}
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(compiled["packet"])
        return 0
    if args.command == "run":
        try:
            mode_state = resolve_mode_state(repo_root, validate_tuned=True, require_runnable=True)
        except PcodexStateError as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": str(exc),
                        "codex_launch": "not_executed",
                        "transform_applied": False,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        if args.dry_run:
            print(json.dumps(run_dry_run(repo_root, args.prompt, args.profile), indent=2, sort_keys=True))
            return 0
        if mode_state.get("effective_mode") != "off":
            result = run_enabled(repo_root, args.prompt, args.profile)
        else:
            result = run_disabled(repo_root, args.prompt, mode_state)
        print(json.dumps(result, indent=2, sort_keys=True))
        return int(result.get("returncode", 0) or 0)
    return 2
