from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .compiler import PACKET_MARKER, LEGACY_PACKET_MARKER
from .config import premode_dir
from .indexer import load_index
from .paths import find_repo_root


def _no_raw(text: str, prompt: str) -> str:
    # Avoid accidentally echoing exact raw prompt in hook messages.
    return text.replace(prompt, "[raw prompt redacted]") if prompt else text


def handle_user_prompt_submit(payload: dict[str, Any], mode: str, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or Path(payload.get("cwd") or ".").resolve()
    prompt = str(payload.get("prompt") or "")
    idx = load_index(repo_root)

    if mode == "strict":
        if PACKET_MARKER in prompt or LEGACY_PACKET_MARKER in prompt:
            return {"continue": True, "systemMessage": "Pre-mode compiled packet detected."}
        reason = "Pre-mode strict mode blocked an uncompiled prompt. Run `premode init && premode index`, then use `premode codex \"<task>\"`, or pass a Pre-mode compiled packet through `codex exec -`."
        if idx is None:
            reason = "Pre-mode index is missing. Run `premode init && premode index`, then use `premode codex \"<task>\"`."
        return {"decision": "block", "reason": _no_raw(reason, prompt)}

    # augment mode: never heavy-index inside the hook; use existing index only.
    if idx is None:
        return {"systemMessage": "Pre-mode index is missing. Run `premode init && premode index` for context augmentation."}
    entries = idx.get("entries", [])[:20]
    context = "Pre-mode index summary: " + ", ".join(e.get("path", "") for e in entries if e.get("path"))
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def handle_subagent_start(payload: dict[str, Any], repo_root: Path | None = None) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": "Use existing Pre-mode context and avoid expanding scope. Do not request raw prompt text.",
        }
    }


def handle_subagent_stop(payload: dict[str, Any], repo_root: Path | None = None) -> dict[str, Any]:
    return {"continue": True, "systemMessage": "Pre-mode subagent monitor completed."}


def dispatch(payload: dict[str, Any], mode: str = "augment", repo_root: Path | None = None) -> dict[str, Any]:
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        return handle_user_prompt_submit(payload, mode, repo_root)
    if event == "SubagentStart":
        return handle_subagent_start(payload, repo_root)
    if event == "SubagentStop":
        return handle_subagent_stop(payload, repo_root)
    return {"continue": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["strict", "augment"], default="augment")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    result = dispatch(payload, args.mode, Path(payload.get("cwd") or ".").resolve())
    sys.stdout.write(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
