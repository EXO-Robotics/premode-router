from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import sys
from typing import Any

from .pcodex_mcp import TOOL_INPUT_SCHEMA, TOOL_NAME, pcodex_transform_subagent_prompt_tool
from .pcodex_subagent import CompileRunner


TOOLS = [
    {
        "name": TOOL_NAME,
        "description": "Transform a Codex-created local subagent prompt through pCodex before dispatch.",
        "inputSchema": TOOL_INPUT_SCHEMA,
    }
]


def _response(id_value: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    out = {"jsonrpc": "2.0", "id": id_value}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def _tool_result_payload(result: Any) -> dict[str, Any]:
    structured = result.as_dict()
    return {
        "content": [{"type": "text", "text": json.dumps(structured, sort_keys=True)}],
        "structuredContent": structured,
    }


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    cwd: Path | None = None,
    compile_runner: CompileRunner | None = None,
) -> dict[str, Any]:
    if name != TOOL_NAME:
        raise ValueError(f"unsupported tool: {name}")
    if "project_root" in arguments:
        raise ValueError("project_root is server-bound and cannot be supplied by a tool call")
    prompt = arguments.get("subagent_prompt")
    if not isinstance(prompt, str):
        raise ValueError("subagent_prompt is required")
    project_root = (cwd or Path.cwd()).resolve()
    if not project_root.is_dir():
        raise ValueError("bound workspace root is not a directory")
    parent_prompt = arguments.get("parent_prompt")
    spawn_metadata = arguments.get("spawn_metadata")
    dry_run = arguments.get("dry_run")
    result = pcodex_transform_subagent_prompt_tool(
        prompt,
        project_root=project_root,
        parent_prompt=parent_prompt if isinstance(parent_prompt, str) else None,
        spawn_metadata=spawn_metadata if isinstance(spawn_metadata, dict) else None,
        dry_run=bool(dry_run),
        compile_runner=compile_runner,
    )
    return _tool_result_payload(result)


def handle_request(
    request: dict[str, Any],
    *,
    cwd: Path | None = None,
    compile_runner: CompileRunner | None = None,
) -> dict[str, Any]:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        return _response(
            request_id,
            result={
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pcodex", "version": "0.1.0-alpha"},
            },
        )
    if method == "tools/list":
        return _response(request_id, result={"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        try:
            result = call_tool(
                str(params.get("name") or ""),
                params.get("arguments") if isinstance(params.get("arguments"), dict) else {},
                cwd=cwd,
                compile_runner=compile_runner,
            )
        except Exception as exc:
            return _response(request_id, error={"code": -32000, "message": str(exc)})
        return _response(request_id, result=result)
    return _response(request_id, error={"code": -32601, "message": "method not found"})


def handle_line(
    line: str,
    *,
    cwd: Path | None = None,
    compile_runner: CompileRunner | None = None,
) -> dict[str, Any]:
    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return _response(None, error={"code": -32700, "message": f"invalid JSON: {exc.msg}"})
    if not isinstance(request, dict):
        return _response(None, error={"code": -32600, "message": "request must be a JSON object"})
    return handle_request(request, cwd=cwd, compile_runner=compile_runner)


def serve() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        response = handle_line(line)
        sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
        sys.stdout.flush()
    return 0
