---
name: pcodex-tune
description: Run or inspect local pCodex tuning verification without live Codex.
---
# pCodex Tune

Use this skill for local tuning inspection or verification only.

Resolve the pCodex executable before running commands:

```sh
PCODEX_BIN="$(./.agents/skills/pcodex/bin/resolve-pcodex.sh)" || exit $?
```

Resolver order:

1. `./.venv/bin/pcodex`
2. `$HOME/.pcodex-alpha/bin/pcodex`
3. `command -v pcodex`

If the resolver fails, report its install guidance exactly enough to be useful, but do not print environment dumps, secrets, raw prompts, or full filesystem listings.


Safe checks include:

- `$PCODEX_BIN status --advisory --json`
- `$PCODEX_BIN doctor --advisory --json`
- `$PCODEX_BIN tune --validate`
- `$PCODEX_BIN tune --verify`

Do not launch live Codex from this skill. Do not modify application source files. Optional MCP wiring is explicit and user-approved, and terminal `pcodex` commands remain the guaranteed interface.
