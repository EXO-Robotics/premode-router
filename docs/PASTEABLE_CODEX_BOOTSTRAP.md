# Pasteable Codex Bootstrap

Paste the block below into Codex while opened in the repo you want to configure.

````text
Configure this repository for pCodex.

Goal:
Install or locate pCodex, create repo-local Codex skills, patch AGENTS.md, run read-only verification and dry-run only, and write PCODEX_SETUP_REPORT.md.

Constraints:
- Do not publish packages.
- Do not change license posture.
- Do not mutate ~/.codex/config.toml unless I explicitly approve it.
- Do not run live Codex tasks.
- Do not dispatch subagents.
- Do not modify source code except setup files.
- Prefer project-local files.
- Use terminal pcodex commands as the guaranteed interface.
- Do not claim /pcodex command support.
- If MCP is mentioned, keep it optional and explicit opt-in only.

Steps:

1. Inspect repo root and git status:
   - pwd
   - git status --short
   - git rev-parse --show-toplevel 2>/dev/null || pwd

2. Detect pCodex in this order:
   - command -v pcodex
   - test -x "$HOME/.pcodex-alpha/bin/pcodex"
   - test -x ".pcodex-tools/bin/pcodex"
   - set `PCODEX_BIN` to the selected executable

3. If pCodex is missing, install from the public source path:
   - mkdir -p "$HOME/.pcodex-tools"
   - if "$HOME/.pcodex-tools/premode-router" does not exist, clone https://github.com/EXO-Robotics/premode-router.git there
   - cd "$HOME/.pcodex-tools/premode-router"
   - git checkout Private-Beta
   - scripts/install_pcodex_from_source.sh --install-root "$HOME/.pcodex-alpha"
   - set `PCODEX_BIN="$HOME/.pcodex-alpha/bin/pcodex"`

4. Verify pCodex from the user repo:
   - "$PCODEX_BIN" doctor || true
   - "$PCODEX_BIN" status
   - "$PCODEX_BIN" status --json

5. Run setup without MCP registration:
   - "$PCODEX_BIN" setup --no-mcp

6. Create repo-local Codex skill files:
   - .codex/skills/pcodex/SKILL.md
   - .codex/skills/pcodex-status/SKILL.md
   - .codex/skills/pcodex-dry-run/SKILL.md
   - .codex/skills/pcodex-tune/SKILL.md

Use these exact bounded skill contents.

File: .codex/skills/pcodex/SKILL.md
```markdown
---
name: pcodex
description: Use terminal pCodex commands as the local context compiler control plane for this repo.
---
# pCodex

Use terminal commands as the reliable interface:

```bash
pcodex doctor || true
pcodex status
pcodex status --json
pcodex setup --no-mcp
pcodex run --dry-run "Hypothetical task. Do not modify files."
```

Prefer dry-run before real edits. Inspect `git diff --name-only` after any real run.

Do not assume `/pcodex` commands exist. Do not assume automatic MCP routing. Do not assume internal Codex subagent interception. Do not mutate real `~/.codex/config.toml` unless explicitly approved. Do not publish packages or change license posture. Do not claim guaranteed savings.
```

File: .codex/skills/pcodex-status/SKILL.md
```markdown
---
name: pcodex-status
description: Check pCodex installation, mode, tuning, MCP, and Codex CLI compatibility before running coding tasks.
---
# pCodex Status

Run:

```bash
pcodex doctor || true
pcodex status
pcodex status --json
```

Summarize configured mode, effective mode, tuning status, fallback state, MCP status, Codex CLI availability/version warnings, and Codex config warnings. Do not modify files. Do not run live Codex tasks. Do not register MCP unless explicitly requested.
```

File: .codex/skills/pcodex-dry-run/SKILL.md
```markdown
---
name: pcodex-dry-run
description: Run a pCodex dry-run for a task and report transform details without launching Codex.
---
# pCodex Dry Run

Run:

```bash
pcodex run --dry-run "<task>"
```

Report `transform_applied`, `route`, `effective_mode`, `algorithm`, `codex_launch`, and warnings. The expected dry-run launch field is `codex_launch: not_executed`. Do not run the non-dry-run command unless explicitly asked.
```

File: .codex/skills/pcodex-tune/SKILL.md
```markdown
---
name: pcodex-tune
description: Run or verify local pCodex tuning artifacts without claiming guaranteed savings.
---
# pCodex Tune

Run:

```bash
pcodex tune
pcodex tune --validate
pcodex tune --verify
pcodex status --json
```

`on` uses tuned behavior only when a valid tuning profile exists and the verifier has a `PASS` result. Otherwise, `on` falls back to generalized `literal_symbol`. Do not claim guaranteed savings.
```

7. Patch or create AGENTS.md with this bounded pCodex section:

```markdown
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
```

8. Run dry-run only:
   - "$PCODEX_BIN" run --dry-run "Hypothetical setup verification task. Do not modify files."

9. Write PCODEX_SETUP_REPORT.md with:
   - repo path
   - git status before/after
   - pcodex path
   - pcodex version/help summary if available
   - doctor/status summary
   - setup result
   - skills created
   - AGENTS.md updated yes/no
   - MCP config touched yes/no
   - real Codex config touched yes/no
   - dry-run result
   - warnings
   - next steps

10. Final notes:
   - Use $pcodex-status, $pcodex-dry-run, etc. only if Codex exposes installed skills in the client.
   - Use terminal pcodex commands as the guaranteed control plane.
   - Do not assume /pcodex commands.
````
