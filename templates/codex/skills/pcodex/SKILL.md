---
name: pcodex
description: Use terminal pCodex commands as the local context compiler control plane for this repo.
---
# pCodex

Use this skill when a repository has been configured for pCodex or when the user asks to inspect, configure, or run pCodex from terminal commands.

## Control Plane

Use terminal commands as the reliable interface:

```bash
pcodex doctor || true
pcodex status
pcodex status --json
pcodex setup --no-mcp
pcodex run --dry-run "Hypothetical task. Do not modify files."
```

Prefer dry-run before real edits. Inspect `git diff --name-only` after any real run.

## Boundaries

- Do not assume `/pcodex` commands exist.
- Do not assume automatic MCP routing.
- Do not assume internal Codex subagent interception.
- Do not mutate real `~/.codex/config.toml` unless the user explicitly approves it.
- Do not publish packages or change license posture.
- Do not claim guaranteed savings.

Terminal `pcodex` commands remain the guaranteed control plane.
