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

Do not use `/pcodex` slash commands as the guaranteed path.
Use terminal `pcodex` commands.

Before real edits:

1. Run `pcodex status`.
2. Prefer `pcodex run --dry-run`.
3. Inspect `git diff --name-only`.

Generated `.premode/` and `.pcodex/` local state, including `.premode/tuning/`, can appear during normal use. Keep it untracked unless the user deliberately chooses to version tuning artifacts.

Do not assume native MCP auto-invocation or internal subagent interception.

## First Real Prompt After Bootstrap

Use a disposable or low-risk file first.

```bash
cat > PCODEX_FIRST_REAL_PROMPT.md <<'EOF'
# pCodex First Real Prompt
Initial line.
EOF
git add PCODEX_FIRST_REAL_PROMPT.md
pcodex run --dry-run "Edit only PCODEX_FIRST_REAL_PROMPT.md. Add one bullet under the heading saying: pCodex first real prompt passed. Do not modify any other files."
pcodex run "Edit only PCODEX_FIRST_REAL_PROMPT.md. Add one bullet under the heading saying: pCodex first real prompt passed. Do not modify any other files."
git status --short
git diff -- PCODEX_FIRST_REAL_PROMPT.md
git diff --name-only
```

Pass criteria:

- Only `PCODEX_FIRST_REAL_PROMPT.md` changed.
- The file contains `- pCodex first real prompt passed.`

If anything else changes, stop and inspect the diff.
