from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .indexer import load_index
from .compiler import inspect_prompt
from .paths import find_repo_root

TOOLS = [
    {
        "name": "premode_read_index",
        "description": "Read the existing Pre-mode index summary. Read-only.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "premode_inspect",
        "description": "Inspect which files Pre-mode would select for a task. Writes only under .premode/.",
        "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"], "additionalProperties": False},
    },
]


def call_tool(name: str, args: dict[str, Any], cwd: Path | None = None) -> dict[str, Any]:
    repo = find_repo_root(cwd or Path.cwd())
    if name == "premode_read_index":
        idx = load_index(repo) or {"entries": [], "entry_count": 0}
        return {"content": [{"type": "text", "text": json.dumps({"entry_count": idx.get("entry_count", len(idx.get("entries", []))), "entries": idx.get("entries", [])[:50]}, sort_keys=True)}]}
    if name == "premode_inspect":
        prompt = str(args.get("prompt") or "")
        result = inspect_prompt(repo, prompt)
        safe = {k: v for k, v in result.items() if k not in {"sanitized_user_intent"}}
        return {"content": [{"type": "text", "text": json.dumps(safe, sort_keys=True)}]}
    raise ValueError(f"unknown tool: {name}")


def _response(id_value: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    out = {"jsonrpc": "2.0", "id": id_value}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def serve() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            method = req.get("method")
            rid = req.get("id")
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "premode-router", "version": "0.1.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = req.get("params") or {}
                result = call_tool(params.get("name"), params.get("arguments") or {})
            else:
                sys.stdout.write(json.dumps(_response(rid, error={"code": -32601, "message": "method not found"})) + "\n")
                sys.stdout.flush()
                continue
            sys.stdout.write(json.dumps(_response(rid, result=result), sort_keys=True) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps(_response(None, error={"code": -32000, "message": str(exc)})) + "\n")
            sys.stdout.flush()
    return 0
