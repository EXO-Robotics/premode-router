---
description: Check pCodex status and summarize mode, tuning, fallback, and warnings.
---
# pCodex Status

Run:

```bash
pcodex doctor || true
pcodex status
pcodex status --json
```

Do not modify files. Do not run live Codex tasks. Do not register MCP unless explicitly requested.

Summarize configured mode, effective mode, tuning, fallback, MCP, Codex CLI warnings, Codex config warnings, generated local state, and savings-estimate availability.

Fresh repos may report tuning verification as `NEEDS_ADJUSTMENT` until tuning and verification pass. MCP status may be unknown when setup used `--no-mcp`. Savings estimates may be unavailable until telemetry exists.
