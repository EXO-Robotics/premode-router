# Pasteable Codex Bootstrap

Paste the block below into Codex while opened in the repo you want to configure.

````text
Configure this repository for pCodex.

Goal:
Install or locate pCodex, create repo-local Codex skills, patch AGENTS.md, patch .gitignore for pCodex generated local state, run read-only verification and dry-run only, and write PCODEX_SETUP_REPORT.md.

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
- Do not claim native slash-command support.
- Do not claim automatic Codex MCP invocation.
- Do not claim internal Codex subagent interception.
- Do not claim guaranteed savings.
- If MCP is mentioned, keep it optional and explicit opt-in only.
- Do not delete generated pCodex state during bootstrap unless I explicitly ask.

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

6. Patch or create `.gitignore` with this bounded section. Append it only once. Do not blanket-ignore all `.premode/`, do not ignore source files, docs, templates, or setup files, and do not delete generated state during bootstrap.

```bash
python3 - <<'PY'
from pathlib import Path

p = Path(".gitignore")
section = """# pCodex generated local state
.premode/pcodex_state.json
.premode/lcc.lock.json
.premode/out/
.premode/audit/
.premode/metrics/
.premode/tuning/
.pcodex/
"""
text = p.read_text() if p.exists() else ""
if "# pCodex generated local state" not in text:
    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    text += section
    p.write_text(text)
PY
```

7. Create repo-local Codex skill files:
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

Generated `.premode/` and `.pcodex/` local state, including `.premode/tuning/`, can appear during normal use. Keep it untracked unless the user deliberately chooses to version tuning artifacts.

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

Summarize configured mode, effective mode, tuning status, fallback state, MCP status, Codex CLI availability/version warnings, Codex config warnings, generated local state, and savings-estimate availability.

Fresh repos may report tuning verification as `NEEDS_ADJUSTMENT` until tuning and verification pass. MCP status may be unknown when setup used `--no-mcp`. Savings estimates may be unavailable until telemetry exists.

Do not modify files. Do not run live Codex tasks. Do not register MCP unless explicitly requested.
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

`on` uses tuned behavior only when a valid tuning profile exists and the verifier has a `PASS` result. Otherwise, `on` falls back to generalized `literal_symbol`. `NEEDS_ADJUSTMENT` is normal for a fresh repo until tuning and verification pass. Do not claim guaranteed savings.
```

8. Validate generated Codex skill YAML frontmatter:

```bash
python3 - <<'PY'
from pathlib import Path
paths = [
    Path(".codex/skills/pcodex/SKILL.md"),
    Path(".codex/skills/pcodex-status/SKILL.md"),
    Path(".codex/skills/pcodex-dry-run/SKILL.md"),
    Path(".codex/skills/pcodex-tune/SKILL.md"),
]
errors = []
for p in paths:
    if not p.exists():
        errors.append(f"{p}: missing")
        continue
    text = p.read_text()
    if not text.startswith("---\n"):
        errors.append(f"{p}: missing opening YAML frontmatter")
        continue
    if "\n---\n" not in text[4:]:
        errors.append(f"{p}: missing closing YAML frontmatter")
if errors:
    print("\n".join(errors))
    raise SystemExit(1)
print("pCodex Codex skill frontmatter checks passed")
PY
```

9. Patch or create AGENTS.md with this bounded pCodex section:

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
```

10. Run dry-run only:
   - "$PCODEX_BIN" run --dry-run "Hypothetical setup verification task. Do not modify files."

11. Write PCODEX_SETUP_REPORT.md with this structure:

```markdown
# pCodex Setup Report

## PASS
- pCodex installed or reused:
- pCodex binary:
- `pcodex doctor` ran:
- `pcodex status` ran:
- `pcodex setup --no-mcp` ran:
- Dry-run completed:
- `transform_applied`:
- `codex_launch`:

## WARN
- Tuning verifier:
- MCP status:
- Savings estimate:
- Codex CLI/config warnings:
- Generated local state:
- Skill/slash UI availability:

## FILES CREATED OR UPDATED
- `.codex/skills/pcodex/SKILL.md`
- `.codex/skills/pcodex-status/SKILL.md`
- `.codex/skills/pcodex-dry-run/SKILL.md`
- `.codex/skills/pcodex-tune/SKILL.md`
- `AGENTS.md`
- `.gitignore`
- `PCODEX_SETUP_REPORT.md`

## NOT TOUCHED
- Real Codex config:
- MCP config:
- Live Codex task:
- Package registry:
- License files:

## NEXT STEPS
1. Run `pcodex status`.
2. Run `pcodex run --dry-run "<your task>"`.
3. Inspect `git diff --name-only`.
4. Run a first real prompt only on a disposable or low-risk file.
5. Record whether Codex shows pCodex skills in the UI, but do not assume native `/pcodex` slash commands.
```

Report warning states plainly:
- `NEEDS_ADJUSTMENT` tuning is normal for a fresh repo until tuning/verifier passes.
- MCP unknown is expected when setup uses `--no-mcp`.
- Savings estimate may be unavailable until telemetry exists.
- Generated `.premode/` and `.pcodex/` local state is expected and should remain untracked unless deliberately versioning tuning artifacts.
- Skill UI availability depends on the Codex client. Do not treat missing native `/pcodex` slash commands as bootstrap failure.

12. Add this section to PCODEX_SETUP_REPORT.md after NEXT STEPS:

```markdown
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

Do not use `/pcodex` slash commands as the guaranteed path.
Use terminal `pcodex` commands.
```

13. Final notes:
   - Use $pcodex-status, $pcodex-dry-run, etc. only if Codex exposes installed skills in the client.
   - Use terminal pcodex commands as the guaranteed control plane.
   - Do not assume /pcodex commands.
   - Do not run the first real prompt until after the dry-run has passed and the target file is disposable or low-risk.
````
