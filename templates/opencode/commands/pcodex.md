---
description: Show pCodex control-plane guidance and safe starter commands.
---
# pCodex

Use terminal `pcodex` commands as the reliable control plane.

```bash
pcodex doctor || true
pcodex status
pcodex status --json
pcodex run --dry-run "Hypothetical task. Do not modify files."
```

Command boundaries:

```text
OpenCode slash commands are OpenCode-specific.
Do not imply Codex slash commands.
Do not use subagents by default.
Do not force automatic routing.
Do not mutate real Codex config without explicit approval.
```
