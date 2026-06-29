from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from .ignore import IgnoreMatcher
from .redaction import redact_text
from .safe_reader import safe_read
from .profiles import ResourceCaps


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.encode("utf-8", errors="replace")) // 4)


def _first_nonempty_line(text: str, limit: int = 180) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return ""


def _python_summary(text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {"language": "python", "parse_error": str(exc), "first_nonempty_line": _first_nonempty_line(text)}
    imports: list[str] = []
    classes: list[str] = []
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.module or "").split(".")[0])
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
    return {
        "language": "python",
        "imports": sorted({x for x in imports if x})[:30],
        "classes": classes[:30],
        "functions": functions[:40],
    }


def _markdown_summary(text: str) -> dict[str, Any]:
    headings = [line.strip() for line in text.splitlines() if line.lstrip().startswith("#")]
    return {"language": "markdown", "headings": headings[:30], "first_nonempty_line": _first_nonempty_line(text)}


def _json_summary(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except Exception as exc:
        return {"language": "json", "parse_error": str(exc), "first_nonempty_line": _first_nonempty_line(text)}
    if isinstance(data, dict):
        return {"language": "json", "top_level_keys": list(data.keys())[:50]}
    if isinstance(data, list):
        return {"language": "json", "top_level_type": "array", "length": len(data)}
    return {"language": "json", "top_level_type": type(data).__name__}


def _toml_summary(text: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except Exception as exc:
        return {"language": "toml", "parse_error": str(exc), "first_nonempty_line": _first_nonempty_line(text)}
    return {"language": "toml", "top_level_keys": list(data.keys())[:50]}


def _yaml_like_summary(text: str) -> dict[str, Any]:
    keys: list[str] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:", line)
        if m:
            keys.append(m.group(1))
    return {"language": "yaml-like", "top_level_keys": keys[:50], "first_nonempty_line": _first_nonempty_line(text)}


def summarize_text(path: str, text: str, kind: str | None = None) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    redacted = redact_text(text).text
    if suffix == ".py":
        summary = _python_summary(redacted)
    elif suffix in {".md", ".rst"} or Path(path).name.lower() in {"readme", "agents.md"}:
        summary = _markdown_summary(redacted)
    elif suffix == ".json":
        summary = _json_summary(redacted)
    elif suffix == ".toml":
        summary = _toml_summary(redacted)
    elif suffix in {".yaml", ".yml"}:
        summary = _yaml_like_summary(redacted)
    else:
        summary = {"language": suffix.lstrip(".") or "text", "first_nonempty_line": _first_nonempty_line(redacted)}
    summary.update({"path": path, "kind": kind, "estimated_tokens": _estimate_tokens(json.dumps(summary, sort_keys=True))})
    return summary


def summarize_file(repo_root: Path, entry: dict[str, Any], caps: ResourceCaps, ignore: IgnoreMatcher | None = None) -> dict[str, Any]:
    path = str(entry.get("path", ""))
    result = safe_read(repo_root, path, caps, ignore or IgnoreMatcher.from_repo(repo_root), max_bytes=min(65536, caps.max_file_bytes), purpose="summary")
    if not result.allowed:
        return {"path": path, "kind": entry.get("kind"), "summary_error": result.reason, "bytes": int(entry.get("bytes", 0) or 0)}
    summary = summarize_text(result.path, result.content, str(entry.get("kind") or ""))
    summary["bytes"] = int(entry.get("bytes", 0) or result.bytes_read or 0)
    summary["truncated_for_summary"] = result.truncated
    return summary
