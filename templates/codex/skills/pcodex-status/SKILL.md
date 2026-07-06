---
name: pcodex-status
description: Check pCodex installation, mode, tuning, MCP, and Codex CLI compatibility before running coding tasks.
---
# pCodex Status

Use this skill to inspect pCodex health without modifying files or running live Codex tasks.

Run:

```bash
pcodex doctor || true
pcodex status
pcodex status --json
```

Summarize:

- configured mode
- effective mode
- tuning status
- fallback state
- MCP status
- Codex CLI availability/version warnings
- Codex config warnings

Do not modify files. Do not run live Codex tasks. Do not register MCP unless the user explicitly asks.
