---
name: pcodex-dry-run
description: Run a pCodex dry-run for a task and report transform details without launching Codex.
---
# pCodex Dry Run

Use this skill when the user wants to preview pCodex routing for a task without launching a real Codex task.

Run:

```bash
pcodex run --dry-run "<task>"
```

Report:

- `transform_applied`
- `route`
- `effective_mode`
- `algorithm`
- `codex_launch`
- warnings from status or dry-run output

The expected dry-run launch field is `codex_launch: not_executed`. Do not run the non-dry-run command unless the user explicitly asks.
