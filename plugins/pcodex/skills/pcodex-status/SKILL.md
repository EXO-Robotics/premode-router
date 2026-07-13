---
name: pcodex-status
description: Inspect pCodex status, doctor output, mode, tuning, and readiness.
---
# pCodex Status

Use this skill to inspect pCodex readiness without changing application source files.

Use terminal `pcodex` commands as the reliable control plane.

Resolve the installed executable with the plugin-local
`skills/pcodex/bin/resolve-pcodex.sh` when the plugin root is exposed, or use
`command -v pcodex`. Do not consult checkout-local or legacy alpha paths.


Preferred safe checks:

- `pcodex status --advisory --json`
- `pcodex doctor --advisory --json`

Review configured mode, effective mode, algorithm, tuning state, MCP status, fallback state, and next recommended action. Optional MCP wiring is explicit and user-approved. Do not launch live Codex from this skill.
