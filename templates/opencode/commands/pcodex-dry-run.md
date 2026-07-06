---
description: Run pCodex dry-run for a task without launching a real Codex run.
---
# pCodex Dry Run

Run:

```bash
pcodex run --dry-run "<task>"
```

Report `transform_applied`, `route`, `effective_mode`, `algorithm`, and `codex_launch`.

The expected dry-run launch field is `codex_launch: not_executed`.

Do not run non-dry-run commands unless explicitly requested.
