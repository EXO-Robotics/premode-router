---
name: pcodex-tune
description: Run or verify local pCodex tuning artifacts without claiming guaranteed savings.
---
# pCodex Tune

Use this skill for local pCodex tuning maintenance.

Commands:

```bash
pcodex tune
pcodex tune --validate
pcodex tune --verify
pcodex status --json
```

`on` uses tuned behavior only when a valid tuning profile exists and the verifier has a `PASS` result. Otherwise, `on` falls back to generalized `literal_symbol`. `tuned` is strict and should fail clearly when tuning artifacts are missing or invalid. `NEEDS_ADJUSTMENT` is normal for a fresh repo until tuning and verification pass.

Do not claim guaranteed savings. Tuning is repo-specific and must be verified locally.
