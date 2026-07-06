# Pasteable OpenCode Bootstrap

Paste the block below into OpenCode while opened in the repo you want to configure.

````text
Configure this repository for pCodex and OpenCode.

Goal:
Install or locate pCodex, create OpenCode command files, patch AGENTS.md, run doctor/status/setup/dry-run only, and write PCODEX_SETUP_REPORT.md.

Constraints:
- Do not publish packages.
- Do not change license posture.
- Do not mutate ~/.codex/config.toml unless explicitly approved.
- Do not run live Codex tasks during bootstrap.
- Do not dispatch subagents.
- Do not modify source code except setup files.
- Do not claim guaranteed savings.
- Use terminal pcodex commands as the reliable control plane.

Steps:

1. Inspect repo root and git status.
2. Locate pCodex with command -v pcodex, "$HOME/.pcodex-alpha/bin/pcodex", or a project-local tools path. Set PCODEX_BIN to the selected executable.
3. If missing, clone https://github.com/EXO-Robotics/premode-router.git into "$HOME/.pcodex-tools/premode-router" and run:
   scripts/install_pcodex_from_source.sh --install-root "$HOME/.pcodex-alpha"
   Then set PCODEX_BIN="$HOME/.pcodex-alpha/bin/pcodex".
4. Run:
   "$PCODEX_BIN" doctor || true
   "$PCODEX_BIN" status
   "$PCODEX_BIN" status --json
   "$PCODEX_BIN" setup --no-mcp
5. Create OpenCode command files:
   - .opencode/commands/pcodex.md
   - .opencode/commands/pcodex-status.md
   - .opencode/commands/pcodex-dry-run.md
   - .opencode/commands/pcodex-tune.md
6. Patch or create AGENTS.md with a bounded pCodex section.
7. Run dry-run only:
   "$PCODEX_BIN" run --dry-run "Hypothetical setup verification task. Do not modify files."
8. Write PCODEX_SETUP_REPORT.md.

OpenCode command contents:

File: .opencode/commands/pcodex.md
```markdown
---
description: Show pCodex control-plane guidance and safe starter commands.
---
# pCodex

Use terminal `pcodex` commands as the reliable control plane.

```bash
pcodex doctor || true
pcodex status
pcodex status --json
pcodex run --dry-run "Hypothetical task. Do not modify files."
```

OpenCode commands are OpenCode-specific. Do not imply Codex command support. Do not use subagents by default. Do not force automatic routing.
```

File: .opencode/commands/pcodex-status.md
```markdown
---
description: Check pCodex status and summarize mode, tuning, fallback, and warnings.
---
# pCodex Status

Run:

```bash
pcodex doctor || true
pcodex status
pcodex status --json
```

Do not modify files. Do not run live Codex tasks.
```

File: .opencode/commands/pcodex-dry-run.md
```markdown
---
description: Run pCodex dry-run for a task without launching a real Codex run.
---
# pCodex Dry Run

Run:

```bash
pcodex run --dry-run "<task>"
```

Report `transform_applied`, `route`, `effective_mode`, `algorithm`, and `codex_launch`. Do not run non-dry-run commands unless explicitly requested.
```

File: .opencode/commands/pcodex-tune.md
```markdown
---
description: Run or verify pCodex tuning artifacts without claiming guaranteed savings.
---
# pCodex Tune

Run:

```bash
pcodex tune
pcodex tune --validate
pcodex tune --verify
pcodex status --json
```

Explain that `on` uses tuned behavior only when a valid profile and `PASS` verifier result exist. Do not claim guaranteed savings.
```

Expected OpenCode command names:
- /pcodex-status
- /pcodex-dry-run
- /pcodex-tune

These slash commands are OpenCode-specific.
````
