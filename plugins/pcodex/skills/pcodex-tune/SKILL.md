---
name: pcodex-tune
description: Run or inspect local pCodex tuning verification without live Codex.
---
# pCodex Tune

Use this skill for local tuning inspection or verification only.

Resolve the installed executable with the plugin-local
`skills/pcodex/bin/resolve-pcodex.sh` when the plugin root is exposed, or use
`command -v pcodex`. Do not consult checkout-local or legacy alpha paths.


Safe checks include:

- `pcodex status --advisory --json`
- `pcodex doctor --advisory --json`
- `pcodex tune --validate`
- `pcodex tune --verify`

Do not launch live Codex from this skill. Do not modify application source files. Optional MCP wiring is explicit and user-approved, and terminal `pcodex` commands remain the guaranteed interface.
