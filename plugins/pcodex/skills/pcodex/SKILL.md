---
name: pcodex
description: Use when the user explicitly asks for a pCodex status check or no-write context preflight for an exact task.
---
# pCodex

Preserve the user's task text exactly. Use the installed `pcodex` command as
the supported control plane; do not assume a source checkout or workspace
`.agents` helper exists.

Resolve the executable with the plugin-local
`skills/pcodex/bin/resolve-pcodex.sh` when the plugin root is available. If the
host does not expose that root, use `command -v pcodex`. If neither succeeds,
report that `premode-router` must be installed in the active environment.

Start with literal no-write checks:

- `pcodex status --advisory --json`
- `pcodex doctor --advisory --json`
- `pcodex run --dry-run --json "<exact user task>"`

Do not write integration state, launch Codex, enable MCP, invoke experimental
ranking behavior, or claim automatic interception. Writes require a separate,
explicit user-approved lifecycle command.
