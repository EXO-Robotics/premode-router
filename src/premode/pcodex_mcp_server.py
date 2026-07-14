from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, Callable, TextIO

from . import bounded_mcp_runtime as runtime
from .pcodex_bootstrap import PCODEX_PACKET_STRATEGY
from .pcodex_mcp import (
    MAX_PARENT_PROMPT_BYTES,
    MAX_PARENT_PROMPT_CHARACTERS,
    MAX_SPAWN_METADATA_BYTES,
    MAX_TASK_BYTES,
    MAX_TASK_CHARACTERS,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    pcodex_transform_subagent_prompt_tool,
)
from .pcodex_subagent import CompileRunner


PROTOCOL_VERSION = runtime.PROTOCOL_VERSION
SUPPORTED_PROTOCOL_VERSIONS = runtime.SUPPORTED_PROTOCOL_VERSIONS
WORKSPACE_ENV = runtime.WORKSPACE_ENV
MAX_REQUEST_BYTES = runtime.MAX_REQUEST_BYTES
MAX_CONCURRENT_REQUESTS = runtime.MAX_CONCURRENT_REQUESTS
MAX_JSON_DEPTH = runtime.MAX_JSON_DEPTH
MAX_JSON_NODES = runtime.MAX_JSON_NODES
WORKER_STOP_TIMEOUT_SECONDS = runtime.WORKER_STOP_TIMEOUT_SECONDS

ToolRequestError = runtime.ToolRequestError
WorkspaceBindingError = runtime.WorkspaceBindingError
WorkspaceBinding = runtime.WorkspaceBinding
ToolWork = runtime.ToolWork
multiprocessing = runtime.multiprocessing

bind_workspace = runtime.bind_workspace
_response = runtime._response
_error = runtime._error
_valid_request_id = runtime._valid_request_id
_utf8_size = runtime._utf8_size
_contains_forbidden_control = runtime._contains_forbidden_control
_reject_nonfinite = runtime._reject_nonfinite
_validate_json_shape = runtime._validate_json_shape
_loads_json = runtime._loads_json
_safe_relative_path = runtime._safe_relative_path


def workspace_from_environment(environ: Mapping[str, str]) -> WorkspaceBinding:
    return bind_workspace(environ.get(WORKSPACE_ENV))


def _validate_arguments(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolRequestError("tool arguments must be an object")
    if "project_root" in arguments:
        raise ToolRequestError(
            "project_root is server-bound and cannot be supplied by a tool call"
        )
    allowed = set(TOOL_INPUT_SCHEMA["properties"])
    if set(arguments) - allowed:
        raise ToolRequestError("tool arguments contain unsupported fields")
    prompt = arguments.get("subagent_prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ToolRequestError("subagent_prompt is required")
    if (
        len(prompt) > MAX_TASK_CHARACTERS
        or _utf8_size(prompt) > MAX_TASK_BYTES
        or _contains_forbidden_control(prompt)
    ):
        raise ToolRequestError("subagent_prompt exceeds the supported input boundary")
    parent_prompt = arguments.get("parent_prompt")
    if parent_prompt is not None:
        if not isinstance(parent_prompt, str):
            raise ToolRequestError("parent_prompt must be a string or null")
        if (
            len(parent_prompt) > MAX_PARENT_PROMPT_CHARACTERS
            or _utf8_size(parent_prompt) > MAX_PARENT_PROMPT_BYTES
            or _contains_forbidden_control(parent_prompt)
        ):
            raise ToolRequestError("parent_prompt exceeds the supported input boundary")
    spawn_metadata = arguments.get("spawn_metadata")
    if spawn_metadata is not None:
        if not isinstance(spawn_metadata, dict) or any(
            not isinstance(key, str) for key in spawn_metadata
        ):
            raise ToolRequestError("spawn_metadata must be an object or null")
        try:
            _validate_json_shape(spawn_metadata)
            encoded = json.dumps(
                spawn_metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (RecursionError, TypeError, ValueError) as exc:
            raise ToolRequestError("spawn_metadata must be JSON-compatible") from exc
        if len(spawn_metadata) > 128 or len(encoded) > MAX_SPAWN_METADATA_BYTES:
            raise ToolRequestError("spawn_metadata exceeds the supported input boundary")
    dry_run = arguments.get("dry_run")
    if dry_run is not None and not isinstance(dry_run, bool):
        raise ToolRequestError("dry_run must be a boolean or null")
    return dict(arguments)


def _tool_result_payload(result: Any) -> dict[str, Any]:
    raw = result.as_dict()
    metadata = raw.get("metadata")
    safe_metadata: dict[str, Any] = {}
    if isinstance(metadata, dict):
        selected = (
            [
                normalized
                for value in metadata.get("selected_paths", [])
                if (normalized := _safe_relative_path(value)) is not None
            ]
            if isinstance(metadata.get("selected_paths"), list)
            else []
        )
        status = metadata.get("status")
        safe_statuses = {
            "abstained_raw_prompt",
            "compile_failed_raw_prompt",
            "disabled_raw_prompt",
            "invalid_input_raw_prompt",
            "invalid_routing_decision_raw_prompt",
            "invalid_state_raw_prompt",
            "transformed",
            "tuned_profile_invalid_raw_prompt",
            "unsupported_payload",
        }
        safe_metadata = {
            "input_prompt_preserved": bool(metadata.get("input_prompt_preserved")),
            "selected_paths": selected,
            "status": status if status in safe_statuses else "bounded_result",
            "transform_applied": bool(raw.get("transform_applied")),
        }
        routing_mode = metadata.get("routing_mode")
        if routing_mode in {"narrow", "broad", "fallback", "abstain"}:
            safe_metadata["routing_mode"] = routing_mode
        error_status = metadata.get("error_status")
        if error_status in safe_statuses:
            safe_metadata["error_status"] = error_status
    error = raw.get("error")
    safe_error = (
        error
        if error
        in {
            None,
            "compile_failed",
            "invalid_routing_decision",
            "subagent_prompt is required",
        }
        else "configuration_invalid"
    )
    mode = raw.get("mode") if raw.get("mode") in {"off", "on", "tuned"} else None
    effective_mode = (
        raw.get("effective_mode")
        if raw.get("effective_mode") in {"off", "on", "tuned"}
        else None
    )
    safe_metadata["mode"] = mode
    tuning_profile = _safe_relative_path(raw.get("tuning_profile"))
    structured = {
        "transformed_prompt": str(raw.get("transformed_prompt") or ""),
        "enabled": bool(raw.get("enabled")),
        "algorithm": PCODEX_PACKET_STRATEGY,
        "mode": mode,
        "effective_mode": effective_mode,
        "transform_applied": bool(raw.get("transform_applied")),
        "tuning_profile": tuning_profile,
        "used_fallback": bool(raw.get("used_fallback")),
        "error": safe_error,
        "metadata": safe_metadata,
    }
    return {
        "content": [
            {"type": "text", "text": json.dumps(structured, sort_keys=True)}
        ],
        "structuredContent": structured,
    }


def _execute_codex_tool(
    name: str,
    arguments: dict[str, Any],
    workspace: WorkspaceBinding,
    compile_runner: CompileRunner | None,
) -> dict[str, Any]:
    if name != TOOL_NAME:
        raise ToolRequestError("unsupported tool", code=-32000)
    validated = _validate_arguments(arguments)
    project_root = workspace.assert_current()
    result = pcodex_transform_subagent_prompt_tool(
        validated["subagent_prompt"],
        project_root=project_root,
        parent_prompt=validated.get("parent_prompt"),
        spawn_metadata=validated.get("spawn_metadata"),
        dry_run=validated.get("dry_run") is True,
        compile_runner=compile_runner,
    )
    workspace.assert_current()
    return _tool_result_payload(result)


CODEX_BACKEND = runtime.ToolBackend(
    server_name="pcodex",
    tool_name=TOOL_NAME,
    description=(
        "Transform an exact coding task into bounded, repository-relative "
        "pCodex guidance."
    ),
    input_schema=TOOL_INPUT_SCHEMA,
    validate_arguments=_validate_arguments,
    execute=_execute_codex_tool,
    worker_name="pcodex-mcp-worker",
    allow_in_process_cwd_fallback=True,
)
TOOLS = CODEX_BACKEND.tools()


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    cwd: Path | None = None,
    workspace: WorkspaceBinding | None = None,
    compile_runner: CompileRunner | None = None,
) -> dict[str, Any]:
    if workspace is None:
        root = (cwd or Path.cwd()).resolve(strict=True)
        workspace = bind_workspace(root)
    return _execute_codex_tool(name, arguments, workspace, compile_runner)


class McpSession(runtime.McpSession):
    def __init__(
        self,
        workspace: WorkspaceBinding | None = None,
        compile_runner: CompileRunner | None = None,
        initialized: bool = False,
        ready: bool = False,
        shutting_down: bool = False,
        cancel_callback: Callable[[Any], None] | None = None,
    ) -> None:
        super().__init__(
            backend=CODEX_BACKEND,
            workspace=workspace,
            backend_context=compile_runner,
            initialized=initialized,
            ready=ready,
            shutting_down=shutting_down,
            cancel_callback=cancel_callback,
        )

    @property
    def compile_runner(self) -> CompileRunner | None:
        return self.backend_context

    @compile_runner.setter
    def compile_runner(self, value: CompileRunner | None) -> None:
        self.backend_context = value


class ProcessWorkerManager(runtime.ProcessWorkerManager):
    def __init__(
        self,
        *,
        session: McpSession,
        workspace: WorkspaceBinding,
        write_response: Callable[[dict[str, Any] | None], None],
        compile_runner: CompileRunner | None = None,
    ) -> None:
        super().__init__(
            session=session,
            workspace=workspace,
            write_response=write_response,
            backend=CODEX_BACKEND,
            backend_context=compile_runner,
        )


def handle_request(
    request: dict[str, Any],
    *,
    cwd: Path | None = None,
    compile_runner: CompileRunner | None = None,
    session: McpSession | None = None,
) -> dict[str, Any] | None:
    if session is None:
        session = McpSession(compile_runner=compile_runner)
        if request.get("method") != "initialize":
            session.initialized = True
            session.ready = True
    return session.handle(request, cwd=cwd)


def handle_line(
    line: str,
    *,
    cwd: Path | None = None,
    compile_runner: CompileRunner | None = None,
    session: McpSession | None = None,
) -> dict[str, Any] | None:
    if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
        return _error(None, -32600, "request exceeds the supported input boundary")
    try:
        request = _loads_json(line)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return _error(None, -32700, "invalid JSON")
    if not isinstance(request, dict):
        return _error(None, -32600, "request must be a JSON object")
    return handle_request(
        request,
        cwd=cwd,
        compile_runner=compile_runner,
        session=session,
    )


def serve(
    *,
    workspace: WorkspaceBinding | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    compile_runner: CompileRunner | None = None,
) -> int:
    return runtime.serve(
        backend=CODEX_BACKEND,
        workspace=workspace,
        stdin=stdin,
        stdout=stdout,
        backend_context=compile_runner,
    )
