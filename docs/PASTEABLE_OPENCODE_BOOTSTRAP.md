# Pasteable OpenCode Bootstrap

Paste the block below into OpenCode while opened in the repo you want to configure.

````text
Configure this repository for pCodex and OpenCode.

Goal:
Install or locate pCodex, create OpenCode command files, patch AGENTS.md, patch .gitignore for pCodex generated local state, run doctor/status/setup/dry-run only, and write PCODEX_SETUP_REPORT.md.

Constraints:
- Do not publish packages.
- Do not change license posture.
- Do not mutate ~/.codex/config.toml unless explicitly approved.
- Do not run live Codex tasks during bootstrap.
- Do not dispatch subagents.
- Do not modify source code except setup files.
- Do not claim guaranteed savings.
- Do not claim native Codex slash-command support.
- Do not claim automatic Codex MCP invocation.
- Do not claim internal Codex subagent interception.
- Use terminal pcodex commands as the reliable control plane.
- Do not delete generated pCodex state during bootstrap unless I explicitly ask.

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
   "$PCODEX_BIN" setup
5. Patch or create `.gitignore` with this bounded section. Append it only once. Do not blanket-ignore all `.premode/`, do not ignore source files, docs, templates, or setup files, and do not delete generated state during bootstrap.

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

6. Create OpenCode command files:
   - .opencode/commands/pcodex.md
   - .opencode/commands/pcodex-status.md
   - .opencode/commands/pcodex-dry-run.md
   - .opencode/commands/pcodex-tune.md
7. Validate generated OpenCode command YAML frontmatter:

```bash
python3 - <<'PY'
from pathlib import Path
paths = [
    Path(".opencode/commands/pcodex.md"),
    Path(".opencode/commands/pcodex-status.md"),
    Path(".opencode/commands/pcodex-dry-run.md"),
    Path(".opencode/commands/pcodex-tune.md"),
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
print("pCodex OpenCode command frontmatter checks passed")
PY
```

8. Patch or create AGENTS.md with a bounded pCodex section.
9. Run dry-run only:
   "$PCODEX_BIN" run --dry-run "Hypothetical setup verification task. Do not modify files."
10. Write PCODEX_SETUP_REPORT.md using PASS, WARN, FILES CREATED OR UPDATED, NOT TOUCHED, NEXT STEPS, and First Real Prompt After Bootstrap sections.

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

Generated `.premode/` and `.pcodex/` local state, including `.premode/tuning/`, can appear during normal use. Keep it untracked unless the user deliberately chooses to version tuning artifacts.

OpenCode commands are OpenCode-specific. Do not imply Codex command support. Do not use subagents by default. Do not force automatic routing. Do not claim guaranteed savings.
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

Summarize configured mode, effective mode, tuning status, fallback state, MCP status, Codex CLI warnings, Codex config warnings, generated local state, and savings-estimate availability.

Fresh repos may report tuning verification as `NEEDS_ADJUSTMENT` until tuning and verification pass. MCP status may be unknown when setup used `--no-mcp`. Savings estimates may be unavailable until telemetry exists.

Do not modify files. Do not run live Codex tasks. Do not register MCP unless explicitly requested.
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

Report `transform_applied`, `route`, `effective_mode`, `algorithm`, and `codex_launch`. The expected dry-run launch field is `codex_launch: not_executed`.

Do not run non-dry-run commands unless explicitly requested.
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

Explain that `on` uses tuned behavior only when a valid profile and `PASS` verifier result exist. `NEEDS_ADJUSTMENT` is normal for a fresh repo until tuning and verification pass. Do not claim guaranteed savings.
```

PCODEX_SETUP_REPORT.md structure:

```markdown
# pCodex Setup Report

## PASS
- pCodex installed or reused:
- pCodex binary:
- `pcodex doctor` ran:
- `pcodex status` ran:
- `pcodex setup` ran:
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
- `.opencode/commands/pcodex.md`
- `.opencode/commands/pcodex-status.md`
- `.opencode/commands/pcodex-dry-run.md`
- `.opencode/commands/pcodex-tune.md`
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
5. Use OpenCode commands only in OpenCode; do not assume Codex native `/pcodex` slash commands.
```

Report warning states plainly:
- `NEEDS_ADJUSTMENT` tuning is normal for a fresh repo until tuning/verifier passes.
- MCP unknown is expected after the narrow default setup.
- Savings estimate may be unavailable until telemetry exists.
- Generated `.premode/` and `.pcodex/` local state is expected and should remain untracked unless deliberately versioning tuning artifacts.

First real prompt guidance to include in the report:

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
- Only PCODEX_FIRST_REAL_PROMPT.md changed.
- The file contains `- pCodex first real prompt passed.`

If anything else changes, stop and inspect the diff.

Do not use `/pcodex` slash commands as the supported path.
Use terminal `pcodex` commands.

Expected OpenCode command names:
- /pcodex-status
- /pcodex-dry-run
- /pcodex-tune

These slash commands are OpenCode-specific.
````
