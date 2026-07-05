from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import pcodex_bootstrap as pcodex
from .pcodex_subagent import CompileRunner, transform_subagent_prompt


MODEL_FACING_SECTIONS = ["TASK", "PRIMARY_FILES", "RELATED_TESTS", "END_PREMODE_CONTEXT_PACKET_V5"]

TOOL_NAME = "pcodex_transform_subagent_prompt"

TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subagent_prompt": {"type": "string"},
        "project_root": {"type": ["string", "null"]},
        "parent_prompt": {"type": ["string", "null"]},
        "spawn_metadata": {"type": ["object", "null"], "additionalProperties": True},
        "dry_run": {"type": ["boolean", "null"]},
    },
    "required": ["subagent_prompt"],
    "additionalProperties": False,
}

TOOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "transformed_prompt": {"type": "string"},
        "enabled": {"type": "boolean"},
        "algorithm": {"const": pcodex.PCODEX_PACKET_STRATEGY},
        "used_fallback": {"type": "boolean"},
        "error": {"type": ["string", "null"]},
        "metadata": {"type": "object", "additionalProperties": True},
    },
    "required": ["transformed_prompt", "enabled", "algorithm", "used_fallback", "error", "metadata"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class PcodexToolResult:
    transformed_prompt: str
    enabled: bool
    algorithm: str
    used_fallback: bool
    error: str | None
    metadata: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "transformed_prompt": self.transformed_prompt,
            "enabled": self.enabled,
            "algorithm": self.algorithm,
            "used_fallback": self.used_fallback,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


def _project_root_or_cwd(project_root: Path | str | None) -> Path:
    if project_root is None:
        return Path.cwd()
    return Path(project_root)


def _safe_spawn_metadata(spawn_metadata: Mapping[str, object] | None) -> dict[str, str]:
    if not spawn_metadata:
        return {}
    return {str(key): type(value).__name__ for key, value in spawn_metadata.items()}


def pcodex_transform_subagent_prompt_tool(
    subagent_prompt: str,
    *,
    project_root: Path | str | None = None,
    parent_prompt: str | None = None,
    spawn_metadata: Mapping[str, object] | None = None,
    dry_run: bool | None = False,
    compile_runner: CompileRunner | None = None,
    profile: str | None = "lite",
) -> PcodexToolResult:
    if not isinstance(subagent_prompt, str) or not subagent_prompt:
        return PcodexToolResult(
            transformed_prompt=str(subagent_prompt or ""),
            enabled=False,
            algorithm=pcodex.PCODEX_PACKET_STRATEGY,
            used_fallback=False,
            error="subagent_prompt is required",
            metadata={
                "status": "invalid_input_raw_prompt",
                "packet_path": None,
                "input_prompt_preserved": True,
                "model_facing_sections": MODEL_FACING_SECTIONS,
            },
        )

    root = _project_root_or_cwd(project_root)
    result = transform_subagent_prompt(
        subagent_prompt,
        root,
        parent_prompt=parent_prompt,
        spawn_metadata=_safe_spawn_metadata(spawn_metadata),
        dry_run=bool(dry_run),
        compile_runner=compile_runner,
        profile=profile,
    )
    metadata: dict[str, object] = {
        "packet_path": result.packet_path,
        "input_prompt_preserved": subagent_prompt in result.prompt,
        "model_facing_sections": result.metadata.get("model_facing_sections") or MODEL_FACING_SECTIONS,
        "status": result.metadata.get("status"),
        "route": result.route,
        "dry_run": bool(dry_run),
    }
    if result.error:
        metadata["error_status"] = result.metadata.get("status")
    return PcodexToolResult(
        transformed_prompt=result.prompt,
        enabled=result.enabled,
        algorithm=result.algorithm,
        used_fallback=result.used_fallback,
        error=result.error,
        metadata=metadata,
    )


def _metadata_for_result(result: PcodexToolResult, *, status: str = "transformed") -> dict[str, object]:
    return {
        "tool": TOOL_NAME,
        "status": status,
        "enabled": result.enabled,
        "algorithm": result.algorithm,
        "used_fallback": result.used_fallback,
        "error": result.error,
        "metadata": dict(result.metadata),
    }


def transform_spawn_agent_payload(
    payload: Mapping[str, object],
    *,
    project_root: Path | str | None = None,
    parent_prompt: str | None = None,
    dry_run: bool | None = False,
    compile_runner: CompileRunner | None = None,
    profile: str | None = "lite",
) -> dict[str, object]:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        transformed = dict(payload)
        transformed["pcodex"] = {
            "tool": TOOL_NAME,
            "status": "unsupported_payload",
            "enabled": False,
            "algorithm": pcodex.PCODEX_PACKET_STRATEGY,
            "error": "spawnAgent payload requires a non-empty prompt field",
        }
        return transformed

    result = pcodex_transform_subagent_prompt_tool(
        prompt,
        project_root=project_root,
        parent_prompt=parent_prompt,
        spawn_metadata=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else None,
        dry_run=dry_run,
        compile_runner=compile_runner,
        profile=profile,
    )
    transformed = dict(payload)
    transformed["prompt"] = result.transformed_prompt
    transformed["pcodex"] = _metadata_for_result(result)
    return transformed


def transform_collab_agent_tool_call_payload(
    payload: Mapping[str, object],
    *,
    project_root: Path | str | None = None,
    parent_prompt: str | None = None,
    dry_run: bool | None = False,
    compile_runner: CompileRunner | None = None,
    profile: str | None = "lite",
) -> dict[str, object]:
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    nested_prompt: object = None
    if isinstance(arguments, Mapping):
        nested_prompt = arguments.get("prompt")
    top_level_prompt = payload.get("prompt")
    prompt = nested_prompt if isinstance(nested_prompt, str) else top_level_prompt
    if tool != "spawnAgent" or not isinstance(prompt, str) or not prompt:
        transformed = dict(payload)
        transformed["pcodex"] = {
            "tool": TOOL_NAME,
            "status": "unsupported_payload",
            "enabled": False,
            "algorithm": pcodex.PCODEX_PACKET_STRATEGY,
            "error": "collabAgentToolCall payload requires tool=spawnAgent and a non-empty prompt",
        }
        return transformed

    result = pcodex_transform_subagent_prompt_tool(
        prompt,
        project_root=project_root,
        parent_prompt=parent_prompt,
        spawn_metadata=payload,
        dry_run=dry_run,
        compile_runner=compile_runner,
        profile=profile,
    )
    transformed = dict(payload)
    if isinstance(arguments, Mapping) and isinstance(nested_prompt, str):
        transformed["arguments"] = {**dict(arguments), "prompt": result.transformed_prompt}
    else:
        transformed["prompt"] = result.transformed_prompt
    transformed["pcodex"] = _metadata_for_result(result)
    return transformed
