from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Any

from . import pcodex_bootstrap as pcodex


CompileRunner = Callable[[Path, str, str | None], dict[str, Any]]


@dataclass(frozen=True)
class SubagentTransformResult:
    prompt: str
    enabled: bool
    algorithm: str = pcodex.PCODEX_PACKET_STRATEGY
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
    config = pcodex.resolve_config(project_root)
    base_metadata: dict[str, Any] = {
        "parent_prompt_present": parent_prompt is not None,
        "spawn_metadata_keys": sorted((spawn_metadata or {}).keys()),
        "dry_run": dry_run,
        "config_source": config.source,
    }
    if not config.enabled:
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=False,
            metadata={**base_metadata, "status": "disabled_raw_prompt"},
        )

    runner = compile_runner or pcodex.compile_pcodex_packet
    try:
        compiled = runner(project_root, subagent_prompt, profile)
    except Exception as exc:
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            error=f"{type(exc).__name__}: {exc}",
            metadata={**base_metadata, "status": "compile_failed_raw_prompt"},
        )

    packet = str(compiled.get("packet") or "")
    if not packet:
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            error="compile runner returned no packet",
            metadata={**base_metadata, "status": "compile_failed_raw_prompt"},
        )
    packet_path = None if dry_run else _write_packet(packet)
    route = str(compiled.get("route") or "")
    transformed = compose_transformed_prompt(subagent_prompt, packet)
    return SubagentTransformResult(
        prompt=transformed,
        enabled=True,
        packet_path=packet_path,
        used_fallback=route == "explicit_fallback",
        route=route or None,
        metadata={
            **base_metadata,
            "status": "transformed",
            "premode_command": compiled.get("premode_command"),
            "packet_sha256": compiled.get("packet_sha256"),
            "model_facing_sections": compiled.get("model_facing_sections"),
        },
    )
