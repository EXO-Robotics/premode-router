from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import stat
from typing import Any, Callable, cast, Literal, NotRequired, TextIO, TypedDict

from . import bounded_mcp_runtime as runtime


TOOL_NAME = "premode_preflight"
MAX_TASK_CHARACTERS = 32_768
MAX_TASK_BYTES = 32_768
MAX_RESULT_ITEMS = 64
MAX_RESULT_LABEL_CHARACTERS = 256
TRANSPORT_SCHEMA_VERSION: Literal["pcodex.openclaw-mcp-preflight-result.v1"] = (
    "pcodex.openclaw-mcp-preflight-result.v1"
)
AuthorityClassificationNameV1 = Literal[
    "current_authority",
    "implementation",
    "verification",
    "support",
    "historical_or_generated_evidence",
    "dangerous_mutation_zone",
]


class PreflightToolRequestV1(TypedDict):
    """Versioned MCP transport arguments for ``premode_preflight``."""

    task: str
    profile: NotRequired[Literal["openclaw"]]


class AuthorityClassificationV1(TypedDict):
    path: str
    classification: AuthorityClassificationNameV1


class PreflightStructuredResultV1(TypedDict):
    """Versioned structured content returned over the MCP transport."""

    schema_version: Literal["pcodex.openclaw-mcp-preflight-result.v1"]
    status: Literal["ready", "fallback", "abstained", "backend_unavailable"]
    routing_mode: Literal["narrow", "broad", "fallback", "abstain"]
    likely_paths: list[str]
    authority_classifications: list[AuthorityClassificationV1]
    dangerous_mutation_zones: list[str]
    expected_validation_surfaces: list[str]
    receipt_id: str | None


class TextContentV1(TypedDict):
    type: Literal["text"]
    text: str


class PreflightToolResultV1(TypedDict):
    """MCP call result containing text and schema-bound structured content."""

    content: list[TextContentV1]
    structuredContent: PreflightStructuredResultV1


TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:pcodex:schema:openclaw-mcp-preflight-request:v1",
    "title": "OpenClawMcpPreflightRequestV1",
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_TASK_CHARACTERS,
        },
        "profile": {"type": "string", "enum": ["openclaw"]},
    },
    "required": ["task"],
    "additionalProperties": False,
}

TOOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:pcodex:schema:openclaw-mcp-preflight-result:v1",
    "title": "OpenClawMcpPreflightResultV1",
    "type": "object",
    "properties": {
        "schema_version": {"const": TRANSPORT_SCHEMA_VERSION},
        "status": {
            "type": "string",
            "enum": ["ready", "fallback", "abstained", "backend_unavailable"],
        },
        "routing_mode": {
            "type": "string",
            "enum": ["narrow", "broad", "fallback", "abstain"],
        },
        "likely_paths": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": MAX_RESULT_ITEMS,
            "uniqueItems": True,
        },
        "authority_classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "classification": {
                        "type": "string",
                        "enum": [
                            "current_authority",
                            "implementation",
                            "verification",
                            "support",
                            "historical_or_generated_evidence",
                            "dangerous_mutation_zone",
                        ],
                    },
                },
                "required": ["path", "classification"],
                "additionalProperties": False,
            },
            "maxItems": MAX_RESULT_ITEMS,
            "uniqueItems": True,
        },
        "dangerous_mutation_zones": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_RESULT_LABEL_CHARACTERS,
            },
            "maxItems": MAX_RESULT_ITEMS,
            "uniqueItems": True,
        },
        "expected_validation_surfaces": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": MAX_RESULT_ITEMS,
            "uniqueItems": True,
        },
        "receipt_id": {
            "anyOf": [
                {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._-]+$",
                },
                {"type": "null"},
            ]
        },
    },
    "required": [
        "schema_version",
        "status",
        "routing_mode",
        "likely_paths",
        "authority_classifications",
        "dangerous_mutation_zones",
        "expected_validation_surfaces",
        "receipt_id",
    ],
    "additionalProperties": False,
}

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
_contains_forbidden_control = runtime._contains_forbidden_control
_safe_relative_path = runtime._safe_relative_path

PreflightRunner = Callable[[Path, str, str | None], Mapping[str, Any]]


def workspace_from_environment(environ: Mapping[str, str]) -> WorkspaceBinding:
    return bind_workspace(environ.get(WORKSPACE_ENV))


def _validate_arguments(arguments: Any) -> PreflightToolRequestV1:
    if not isinstance(arguments, dict):
        raise ToolRequestError("tool arguments must be an object")
    allowed = set(TOOL_INPUT_SCHEMA["properties"])
    if set(arguments) - allowed:
        raise ToolRequestError("tool arguments contain unsupported fields")
    task = arguments.get("task")
    if not isinstance(task, str) or not task:
        raise ToolRequestError("task is required")
    if (
        len(task) > MAX_TASK_CHARACTERS
        or len(task.encode("utf-8")) > MAX_TASK_BYTES
        or _contains_forbidden_control(task)
    ):
        raise ToolRequestError("task exceeds the supported input boundary")
    profile = arguments.get("profile")
    if "profile" in arguments and profile != "openclaw":
        raise ToolRequestError("profile is unsupported")
    validated: PreflightToolRequestV1 = {"task": task}
    if profile == "openclaw":
        validated["profile"] = "openclaw"
    return validated


def _safe_workspace_path(value: Any, workspace: WorkspaceBinding) -> str | None:
    if isinstance(value, str):
        portable = value.replace("\\", "/")
        if len(portable) >= 2 and portable[1] == ":":
            return None
    normalized = _safe_relative_path(value)
    if normalized is None:
        return None
    current = workspace.root
    for part in Path(normalized).parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except OSError:
            return None
        if stat.S_ISLNK(info.st_mode):
            return None
    return normalized


def _bounded_paths(value: Any, workspace: WorkspaceBinding) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        normalized = _safe_workspace_path(item, workspace)
        if normalized is not None and normalized not in result:
            result.append(normalized)
        if len(result) >= MAX_RESULT_ITEMS:
            break
    return result


def _bounded_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or len(item) > MAX_RESULT_LABEL_CHARACTERS
            or _contains_forbidden_control(item)
        ):
            continue
        portable = item.replace("\\", "/")
        if len(portable) >= 2 and portable[1] == ":":
            continue
        path = Path(portable)
        if path.is_absolute() or ".." in path.parts:
            continue
        normalized = path.as_posix()
        if normalized not in result:
            result.append(normalized)
        if len(result) >= MAX_RESULT_ITEMS:
            break
    return result


def _sanitize_result(
    value: Mapping[str, Any], workspace: WorkspaceBinding
) -> PreflightStructuredResultV1:
    safe_statuses = {"ready", "fallback", "abstained", "backend_unavailable"}
    safe_modes = {"narrow", "broad", "fallback", "abstain"}
    safe_classes = {
        "current_authority",
        "implementation",
        "verification",
        "support",
        "historical_or_generated_evidence",
        "dangerous_mutation_zone",
    }
    likely_paths = _bounded_paths(value.get("likely_paths"), workspace)
    verification = _bounded_paths(value.get("expected_validation_surfaces"), workspace)
    classifications: list[AuthorityClassificationV1] = []
    raw_classifications = value.get("authority_classifications")
    if isinstance(raw_classifications, list):
        for item in raw_classifications:
            if not isinstance(item, Mapping):
                continue
            path = _safe_workspace_path(item.get("path"), workspace)
            classification = item.get("classification")
            if path is None or classification not in safe_classes:
                continue
            entry: AuthorityClassificationV1 = {
                "path": path,
                "classification": cast(AuthorityClassificationNameV1, classification),
            }
            if entry not in classifications:
                classifications.append(entry)
            if len(classifications) >= MAX_RESULT_ITEMS:
                break
    receipt_id = value.get("receipt_id")
    if not (
        isinstance(receipt_id, str)
        and 1 <= len(receipt_id) <= 128
        and all(
            character.isascii() and (character.isalnum() or character in "._-")
            for character in receipt_id
        )
    ):
        receipt_id = None
    status = value.get("status")
    routing_mode = value.get("routing_mode")
    return {
        "schema_version": TRANSPORT_SCHEMA_VERSION,
        "status": status if status in safe_statuses else "backend_unavailable",
        "routing_mode": routing_mode if routing_mode in safe_modes else "fallback",
        "likely_paths": likely_paths,
        "authority_classifications": classifications,
        "dangerous_mutation_zones": _bounded_labels(
            value.get("dangerous_mutation_zones")
        ),
        "expected_validation_surfaces": verification,
        "receipt_id": receipt_id,
    }


def unavailable_preflight_backend(
    _workspace: Path, _task: str, _profile: str | None
) -> Mapping[str, Any]:
    """Fail-safe seam used until the G4 application service is integrated."""

    return {
        "status": "backend_unavailable",
        "routing_mode": "fallback",
        "likely_paths": [],
        "authority_classifications": [],
        "dangerous_mutation_zones": [],
        "expected_validation_surfaces": [],
        "receipt_id": None,
    }


def production_preflight_backend(
    workspace: Path, task: str, profile: str | None
) -> Mapping[str, Any]:
    """Run the installed application service or fail without leaking details."""

    try:
        from .openclaw_preflight import openclaw_preflight_backend

        return openclaw_preflight_backend(workspace, task, profile)
    except Exception:
        return unavailable_preflight_backend(workspace, task, profile)


def _execute_openclaw_tool(
    name: str,
    arguments: dict[str, Any],
    workspace: WorkspaceBinding,
    runner: PreflightRunner | None,
) -> PreflightToolResultV1:
    if name != TOOL_NAME:
        raise ToolRequestError("unsupported tool", code=-32000)
    validated = _validate_arguments(arguments)
    root = workspace.assert_current()
    selected_runner = runner or production_preflight_backend
    try:
        raw_result = selected_runner(root, validated["task"], validated.get("profile"))
    except Exception as exc:
        raise RuntimeError("preflight backend failed") from exc
    if not isinstance(raw_result, Mapping):
        raise TypeError("invalid preflight backend result")
    workspace.assert_current()
    structured = _sanitize_result(raw_result, workspace)
    workspace.assert_current()
    return {
        "content": [{"type": "text", "text": json.dumps(structured, sort_keys=True)}],
        "structuredContent": structured,
    }


OPENCLAW_BACKEND = runtime.ToolBackend(
    server_name="pcodex-openclaw",
    tool_name=TOOL_NAME,
    description=(
        "Return bounded, read-only OpenClaw repository preflight guidance for "
        "the exact task."
    ),
    input_schema=TOOL_INPUT_SCHEMA,
    output_schema=TOOL_OUTPUT_SCHEMA,
    validate_arguments=_validate_arguments,
    execute=_execute_openclaw_tool,
    worker_name="pcodex-openclaw-mcp-worker",
)
TOOLS = OPENCLAW_BACKEND.tools()


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    workspace: WorkspaceBinding,
    preflight_runner: PreflightRunner | None = None,
) -> PreflightToolResultV1:
    return _execute_openclaw_tool(name, arguments, workspace, preflight_runner)


class McpSession(runtime.McpSession):
    def __init__(
        self,
        workspace: WorkspaceBinding | None = None,
        preflight_runner: PreflightRunner | None = None,
        initialized: bool = False,
        ready: bool = False,
        shutting_down: bool = False,
        cancel_callback: Callable[[Any], None] | None = None,
    ) -> None:
        super().__init__(
            backend=OPENCLAW_BACKEND,
            workspace=workspace,
            backend_context=preflight_runner,
            initialized=initialized,
            ready=ready,
            shutting_down=shutting_down,
            cancel_callback=cancel_callback,
        )

    @property
    def preflight_runner(self) -> PreflightRunner | None:
        return self.backend_context

    @preflight_runner.setter
    def preflight_runner(self, value: PreflightRunner | None) -> None:
        self.backend_context = value


class ProcessWorkerManager(runtime.ProcessWorkerManager):
    def __init__(
        self,
        *,
        session: McpSession,
        workspace: WorkspaceBinding,
        write_response: Callable[[dict[str, Any] | None], None],
        preflight_runner: PreflightRunner | None = None,
    ) -> None:
        super().__init__(
            session=session,
            workspace=workspace,
            write_response=write_response,
            backend=OPENCLAW_BACKEND,
            backend_context=preflight_runner,
        )


def handle_line(
    line: str,
    *,
    workspace: WorkspaceBinding | None = None,
    preflight_runner: PreflightRunner | None = None,
    session: McpSession | None = None,
) -> dict[str, Any] | None:
    return runtime.handle_line(
        line,
        backend=OPENCLAW_BACKEND,
        workspace=workspace,
        backend_context=preflight_runner,
        session=session,
    )


def serve(
    *,
    workspace: WorkspaceBinding | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    preflight_runner: PreflightRunner | None = None,
) -> int:
    return runtime.serve(
        backend=OPENCLAW_BACKEND,
        workspace=workspace,
        stdin=stdin,
        stdout=stdout,
        backend_context=preflight_runner,
    )
