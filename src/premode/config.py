from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ignore import DEFAULT_PREMODEIGNORE
from .packet_schema import TASK_PACKET_SCHEMA

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "resource_profile": "auto",
    "default_budget": 20000,
    "hard_packet_token_budget": 20000,
    "hard_full_text_file_count": 14,
    "hard_summary_count": 40,
    "hard_manifest_count": 120,
    "hard_log_line_count": 80,
    "respect_gitignore": True,
    "follow_symlinks_outside_repo": False,
    "memory_guard": {
        "enabled": True,
        "max_process_memory_mb": 4096,
        "warn_if_available_memory_below_mb": 2048,
    },
    "selection": {
        "always_include": ["AGENTS.md", "README.md", "README", "docs/", "build.log", "logs/build.log"],
    },
    "privacy": {
        "store_raw_prompt": False,
        "redact_secret_like_tokens": True,
    },
    "codex": {
        "binary": "codex",
        "sandbox": "workspace-write",
        "approval": "on-request",
        "ephemeral_default": True,
        "json_default": False,
        "output_last_message_default": ".premode/out/final.md",
    },
    "local_assist_lab": {
        "enabled": False,
        "provider": None,
        "model": None,
        "fallback_to_deterministic": True,
        "require_validation": True,
    },
}

DEFAULT_RULES = """# Pre-mode Project Rules

- Keep changes small, scoped, and reviewable.
- Prefer existing project architecture and conventions.
- Do not touch ignored, generated, asset, vendor, build output, or secret-like files unless explicitly requested.
- For build fixes, repair the first meaningful/root error before chasing cascades.
- Report changed files, commands run, tests passed, and remaining risks.
"""

DEFAULT_MEMORY = """# Project Memory

## Architecture Summary

## Current Active Work

## Known Constraints

## Last Good State

## Known Fragile Areas

## Do Not Touch Unless Asked
"""

DEFAULT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Pre-mode Codex Final Report",
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "files_changed", "commands_run", "tests_passed", "remaining_risks"],
    "properties": {
        "summary": {"type": "string"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "commands_run": {"type": "array", "items": {"type": "string"}},
        "tests_passed": {"type": "array", "items": {"type": "string"}},
        "remaining_risks": {"type": "array", "items": {"type": "string"}},
    },
}


def premode_dir(repo_root: Path) -> Path:
    return repo_root / ".premode"


def config_path(repo_root: Path) -> Path:
    return premode_dir(repo_root) / "config.json"


def _deep_merge(base: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(base))
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(repo_root: Path) -> dict[str, Any]:
    path = config_path(repo_root)
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    data = json.loads(path.read_text(encoding="utf-8"))
    return _deep_merge(DEFAULT_CONFIG, data)


def init_project(repo_root: Path) -> dict[str, Any]:
    # Import here to avoid config/adapters import cycle during startup.
    from .adapters import detect_projects
    from .command_discovery import discover_commands, write_discovered_commands, default_user_commands

    d = premode_dir(repo_root)
    for sub in ("index", "out", "audit", "metrics", "schemas", "logs", "memory"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    cfg = config_path(repo_root)
    if not cfg.exists():
        cfg.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    ignore = repo_root / ".premodeignore"
    if not ignore.exists():
        ignore.write_text(DEFAULT_PREMODEIGNORE, encoding="utf-8")
    rules = d / "rules.md"
    if not rules.exists():
        rules.write_text(DEFAULT_RULES, encoding="utf-8")
    memory = d / "memory" / "project_memory.md"
    if not memory.exists():
        memory.write_text(DEFAULT_MEMORY, encoding="utf-8")
    detection = detect_projects(repo_root)
    discovered_commands = discover_commands(repo_root, detection)
    discovered_commands_path = write_discovered_commands(repo_root, discovered_commands)
    commands = d / "commands.json"
    if not commands.exists():
        commands.write_text(json.dumps(default_user_commands(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        # Preserve user-edited overrides. Generated discovery now lives under .premode/out/.
        pass
    schema = d / "schemas" / "codex_final_report.schema.json"
    if not schema.exists():
        schema.write_text(json.dumps(DEFAULT_SCHEMA, indent=2) + "\n", encoding="utf-8")
    task_schema = d / "schemas" / "task_packet.schema.json"
    if not task_schema.exists():
        task_schema.write_text(json.dumps(TASK_PACKET_SCHEMA, indent=2) + "\n", encoding="utf-8")
    return {
        "premode_dir": str(d),
        "config": str(cfg),
        "premodeignore": str(ignore),
        "rules": str(rules),
        "memory": str(memory),
        "commands": str(commands),
        "discovered_commands": str(discovered_commands_path),
        "schema": str(schema),
        "task_schema": str(task_schema),
    }
