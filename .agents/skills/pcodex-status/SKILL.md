---
name: pcodex-status
description: Inspect pCodex status, doctor output, mode, tuning, and readiness.
---
# pCodex Status

Use this skill to inspect pCodex readiness without changing application source files.

Use terminal `pcodex` commands as the reliable control plane.

Resolve the pCodex executable before running commands:

```sh
PCODEX_BIN="$(./.agents/skills/pcodex/bin/resolve-pcodex.sh)" || exit $?
```

Resolver order:

1. `./.venv/bin/pcodex`
2. `$HOME/.pcodex-alpha/bin/pcodex`
3. `command -v pcodex`

If the resolver fails, report its install guidance exactly enough to be useful, but do not print environment dumps, secrets, raw prompts, or full filesystem listings.


Preferred safe checks:

- `$PCODEX_BIN status --advisory --json`
- `$PCODEX_BIN doctor --advisory --json`

Review configured mode, effective mode, algorithm, tuning state, MCP status, fallback state, and next recommended action. Optional MCP wiring is explicit and user-approved. Do not launch live Codex from this skill.
