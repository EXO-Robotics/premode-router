from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SKILLS: dict[str, str] = {
    "premode-router": """---
name: premode-router
description: Use when a Codex task should be routed through Pre-mode compiled context before model execution.
---

# Pre-mode Router

Prefer `premode codex "<task>"` for privacy-safe prompt replacement. Hook strict mode is only a guardrail; it receives the raw prompt and cannot prevent other matching hooks from receiving hook input.
""",
    "compile-repair": """---
name: compile-repair
description: Use for fixing build, compile, test, Xcode, pytest, or CI failures with minimal scoped edits.
---

# Compile Repair

1. Read the Pre-mode task classification, repo state, selected files, and relevant log errors.
2. Reproduce or reason from the first meaningful error before editing.
3. Change the smallest set of files needed to restore the build/test gate.
4. Run the relevant verification command and report exact pass/fail results.
5. Do not add unrelated features or refactors while the build is red.
""",
    "controlled-patch": """---
name: controlled-patch
description: Use when the user asks for a bounded patch, not a broad rewrite or product expansion.
---

# Controlled Patch

Keep scope tight. Preserve existing behavior unless the task explicitly changes it. Prefer small files, deterministic tests, and a final report that separates completed work from risks/deferred work.
""",
    "log-triage": """---
name: log-triage
description: Use when logs, stack traces, build output, or crash reports are part of the task.
---

# Log Triage

Start with first meaningful errors, not the last noisy cascade. Connect any fix to a specific failure signature. If logs are truncated, mention that and avoid overclaiming.
""",
    "branch-review": """---
name: branch-review
description: Use when the task involves reviewing work from another agent, branch, commit, or patch set.
---

# Branch Review

Check branch name, HEAD, dirty files, recent commits, and diff summary. Identify what the previous agent changed, what is safe to keep, what needs rework, and what should not be committed yet.
""",
}


def install_local_plugin(repo_root: Path, scope: str = "repo") -> dict[str, str]:
    if scope != "repo":
        raise ValueError("MVP supports repo scope only. Use --scope repo.")
    market_root = repo_root / ".agents" / "plugins"
    plugin_root = market_root / "plugins" / "premode-router"
    (plugin_root / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_root / "skills").mkdir(parents=True, exist_ok=True)
    (plugin_root / "hooks").mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": "premode-router",
        "version": "0.2.0",
        "description": "Privacy-safe local context compiler, task router, and Codex stdin wrapper.",
        "skills": "./skills/",
        "hooks": "./hooks/hooks.json",
        "mcpServers": "./.mcp.json",
        "interface": {
            "displayName": "Pre-mode Router",
            "shortDescription": "Compile classified repo context before Codex runs.",
            "developerName": "Local",
            "category": "Developer Tools",
            "capabilities": ["Read"],
        },
    }
    (plugin_root / ".codex-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    skill_paths: dict[str, str] = {}
    for name, text in SKILLS.items():
        folder = plugin_root / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "SKILL.md"
        path.write_text(text, encoding="utf-8")
        skill_paths[name] = str(path)

    hooks = {
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "python3 ${PLUGIN_ROOT}/hooks/premode_hook.py --mode strict", "statusMessage": "Checking Pre-mode compiled prompt"}]}
            ],
            "SubagentStart": [
                {"hooks": [{"type": "command", "command": "python3 ${PLUGIN_ROOT}/hooks/premode_hook.py --mode augment", "statusMessage": "Adding Pre-mode subagent context"}]}
            ],
            "SubagentStop": [
                {"hooks": [{"type": "command", "command": "python3 ${PLUGIN_ROOT}/hooks/premode_hook.py --mode augment", "statusMessage": "Recording Pre-mode subagent stop"}]}
            ],
        }
    }
    (plugin_root / "hooks" / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
    hook_script = """#!/usr/bin/env python3
from premode.hook import main
raise SystemExit(main())
"""
    hp = plugin_root / "hooks" / "premode_hook.py"
    hp.write_text(hook_script, encoding="utf-8")
    hp.chmod(0o755)

    mcp = {"premode": {"command": "premode", "args": ["mcp-server"]}}
    (plugin_root / ".mcp.json").write_text(json.dumps(mcp, indent=2) + "\n", encoding="utf-8")

    marketplace = {
        "name": "local-pemode-marketplace",
        "interface": {"displayName": "Local Pre-mode Plugins"},
        "plugins": [
            {
                "name": "premode-router",
                "source": {"source": "local", "path": "./plugins/premode-router"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Developer Tools",
            }
        ],
    }
    market_root.mkdir(parents=True, exist_ok=True)
    (market_root / "marketplace.json").write_text(json.dumps(marketplace, indent=2) + "\n", encoding="utf-8")
    return {
        "marketplace": str(market_root / "marketplace.json"),
        "plugin_root": str(plugin_root),
        "manifest": str(plugin_root / ".codex-plugin" / "plugin.json"),
        "hooks": str(plugin_root / "hooks" / "hooks.json"),
        "mcp": str(plugin_root / ".mcp.json"),
        "skills": skill_paths,
    }
