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
- generated local state
- savings-estimate availability

Fresh repos may report tuning verification as `NEEDS_ADJUSTMENT` until tuning and verification pass. MCP status may be unknown when setup used `--no-mcp`. Savings estimates may be unavailable until telemetry exists.

Do not modify files. Do not run live Codex tasks. Do not register MCP unless the user explicitly asks.
