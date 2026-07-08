---
name: pcodex
description: Use terminal pcodex commands for safe pCodex overview and workflow checks.
---
# pCodex

Use terminal `pcodex` commands as the reliable control plane for this repo.

Resolve the pCodex executable before running commands:

```sh
PCODEX_BIN="$(./.agents/skills/pcodex/bin/resolve-pcodex.sh)" || exit $?
```

Resolver order:

1. `./.venv/bin/pcodex`
2. `$HOME/.pcodex-alpha/bin/pcodex`
3. `command -v pcodex`

If the resolver fails, report its install guidance exactly enough to be useful, but do not print environment dumps, secrets, raw prompts, or full filesystem listings.


Start with safe local checks:

- `$PCODEX_BIN status --json`
- `$PCODEX_BIN doctor --json`
- `$PCODEX_BIN run --dry-run "<task>"`

Keep setup and previews local. Do not launch live Codex from this skill. Do not modify application source files. Optional MCP wiring is explicit and user-approved; terminal commands remain the guaranteed interface.
