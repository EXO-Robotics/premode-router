---
name: pcodex-dry-run
description: Preview a pCodex task locally with pcodex run --dry-run.
---
# pCodex Dry Run

Use this skill to preview a requested task without launching live Codex.

Resolve the pCodex executable before running commands:

```sh
PCODEX_BIN="$(./.agents/skills/pcodex/bin/resolve-pcodex.sh)" || exit $?
```

Resolver order:

1. `./.venv/bin/pcodex`
2. `$HOME/.pcodex-alpha/bin/pcodex`
3. `command -v pcodex`

If the resolver fails, report its install guidance exactly enough to be useful, but do not print environment dumps, secrets, raw prompts, or full filesystem listings.


Preferred command:

- `$PCODEX_BIN run --dry-run "<task>" --json`

Confirm `codex_launch` reports `not_executed` before treating the preview as safe. Do not modify application source files. Optional MCP wiring is explicit and user-approved; terminal commands remain the reliable control plane.

If the user requires no file modifications at all, first inspect `$PCODEX_BIN status --advisory --json`. If generated `.premode` state is missing or stale and `pcodex run --dry-run` would refresh generated state, do not run it. Report that dry-run is blocked until generated-state refresh is explicitly allowed or a no-write dry-run mode exists.
