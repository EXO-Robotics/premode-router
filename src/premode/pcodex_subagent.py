from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Any

from . import pcodex_bootstrap as pcodex


CompileRunner = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class SubagentTransformResult:
    prompt: str
    enabled: bool
    algorithm: str = pcodex.PCODEX_PACKET_STRATEGY
    mode: str | None = None
    effective_mode: str | None = None
    transform_applied: bool = False
    tuning_profile: str | None = None
    packet_path: str | None = None
    used_fallback: bool = False
    error: str | None = None
    route: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _write_packet(packet: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="pcodex_subagent_packet_", suffix=".md", delete=False)
    with handle:
        handle.write(packet)
    return handle.name


def compose_transformed_prompt(subagent_prompt: str, packet: str) -> str:
    if packet.startswith("TASK\n"):
        return packet.rstrip() + "\n"
    return f"{subagent_prompt.rstrip()}\n\n---\n\n{packet.strip()}\n"


def transform_subagent_prompt(
    subagent_prompt: str,
    project_root: Path,
    *,
    parent_prompt: str | None = None,
    spawn_metadata: Mapping[str, str] | None = None,
    dry_run: bool = False,
    compile_runner: CompileRunner | None = None,
    profile: str | None = "lite",
) -> SubagentTransformResult:
    mode_state = pcodex.resolve_mode_state(project_root, validate_tuned=True, require_runnable=False)
    mode = str(mode_state.get("configured_mode") or mode_state.get("mode") or "on")
    effective_mode = str(mode_state.get("effective_mode") or mode)
    tuning_profile = str(mode_state["effective_tuning_profile"]) if effective_mode == "tuned" and mode_state.get("effective_tuning_profile") else None
    fallback = mode_state.get("fallback") if isinstance(mode_state.get("fallback"), dict) else {}
    fallback_reason = str(fallback.get("last_reason")) if fallback.get("active") and fallback.get("last_reason") else None
    base_metadata: dict[str, Any] = {
        "parent_prompt_present": parent_prompt is not None,
        "spawn_metadata_keys": sorted((spawn_metadata or {}).keys()),
        "dry_run": dry_run,
        "config_source": "pcodex_state",
        "state_status": mode_state.get("state_status"),
        "state_error": mode_state.get("state_error"),
        "mode": mode,
        "configured_mode": mode,
        "effective_mode": effective_mode,
        "transform_applied": False,
        "tuning_profile": tuning_profile,
        "tuning": mode_state.get("tuning"),
        "fallback": fallback,
    }
    if mode_state.get("state_status") == "invalid_default":
        error = str(mode_state.get("state_error") or "Invalid pCodex mode state")
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=False,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            error=error,
            metadata={**base_metadata, "status": "invalid_state_raw_prompt", "error": error},
        )
    tuning = mode_state.get("tuning") if isinstance(mode_state.get("tuning"), dict) else {}
    if mode == "tuned" and not tuning.get("profile_valid"):
        error = str(tuning.get("profile_error") or "Invalid pCodex tuning profile")
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            error=error,
            metadata={**base_metadata, "status": "tuned_profile_invalid_raw_prompt", "error": error},
        )
    if effective_mode == "off":
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=False,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=None,
            metadata={**base_metadata, "status": "disabled_raw_prompt"},
        )

    runner = compile_runner or pcodex.compile_pcodex_packet
    try:
        compiled = pcodex.run_compile_runner(runner, project_root, subagent_prompt, profile, tuning_profile=tuning_profile)
    except Exception as exc:
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            error=f"{type(exc).__name__}: {exc}",
            metadata={**base_metadata, "status": "compile_failed_raw_prompt"},
        )

    packet = str(compiled.get("packet") or "")
    if not packet:
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            error="compile runner returned no packet",
            metadata={**base_metadata, "status": "compile_failed_raw_prompt"},
        )
    telemetry = pcodex.record_runtime_telemetry(
        project_root,
        configured_mode=mode,
        effective_mode=effective_mode,
        fallback_reason=fallback_reason,
    )
    packet_path = None if dry_run else _write_packet(packet)
    route = str(compiled.get("route") or "")
    transformed = compose_transformed_prompt(subagent_prompt, packet)
    return SubagentTransformResult(
        prompt=transformed,
        enabled=True,
        mode=mode,
        effective_mode=effective_mode,
        transform_applied=True,
        tuning_profile=tuning_profile,
        packet_path=packet_path,
        used_fallback=route == "explicit_fallback",
        route=route or None,
        metadata={
            **base_metadata,
            "status": "transformed",
            "transform_applied": True,
            "premode_command": compiled.get("premode_command"),
            "packet_sha256": compiled.get("packet_sha256"),
            "model_facing_sections": compiled.get("model_facing_sections"),
            "telemetry": telemetry.get("telemetry"),
        },
    )
