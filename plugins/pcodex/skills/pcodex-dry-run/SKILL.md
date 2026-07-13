---
name: pcodex-dry-run
description: Preview a pCodex task locally with pcodex run --dry-run.
---
# pCodex Dry Run

Use this skill to preview a requested task without launching live Codex.

Resolve the installed executable with the plugin-local
`skills/pcodex/bin/resolve-pcodex.sh` when the plugin root is exposed, or use
`command -v pcodex`. Do not consult checkout-local or legacy alpha paths.


Preferred command:

- `pcodex run --dry-run "<exact user task>" --json`

Confirm `codex_launch` reports `not_executed` before treating the preview as safe. Do not modify application source files. Optional MCP wiring is explicit and user-approved; terminal commands remain the reliable control plane.

If the user requires no file modifications at all, first inspect `pcodex status
--advisory --json`. If generated state is missing or stale, preserve the exact
task and report the advisory next action instead of refreshing state.
