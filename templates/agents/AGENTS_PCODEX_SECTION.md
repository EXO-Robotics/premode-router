## pCodex

This repo may use pCodex as a local context compiler before Codex tasks.

Use terminal commands as the reliable control plane:

- `pcodex doctor`
- `pcodex status`
- `pcodex setup --no-mcp`
- `pcodex on`
- `pcodex off`
- `pcodex tuned`
- `pcodex tune`
- `pcodex run --dry-run "..."`
- `pcodex run "..."`

Do not assume `/pcodex` commands exist unless Codex lists installed pCodex skills in the client UI.

Before real edits:

1. Run `pcodex status`.
2. Prefer `pcodex run --dry-run`.
3. Inspect `git diff --name-only`.

Do not assume native MCP auto-invocation or internal subagent interception.
