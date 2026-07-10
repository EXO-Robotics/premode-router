# pCodex Bootstrapper Design

This document defines the first pasteable pCodex onboarding UX. The goal is a bounded setup path a user can paste into an agent while opened in a repository:

1. Inspect the repo.
2. Install or locate pCodex.
3. Create repo-local agent UX files.
4. Patch generated-state hygiene into `.gitignore`.
5. Run doctor/status/setup/dry-run verification only.
6. Write `PCODEX_SETUP_REPORT.md`.

pCodex remains a private local context compiler and routing formatter. Terminal `pcodex` commands are the reliable control plane.

## Targets

### Codex Target

Codex integration should write project-local instruction surfaces:

- `AGENTS.md` pCodex section, patched or created
- `.codex/skills/pcodex/SKILL.md`
- `.codex/skills/pcodex-status/SKILL.md`
- `.codex/skills/pcodex-dry-run/SKILL.md`
- `.codex/skills/pcodex-tune/SKILL.md`
- `.gitignore` bounded pCodex generated-state section

Codex skills are the primary Codex-facing reusable instruction target. Codex custom prompt files are not the primary integration target.

Optional MCP setup is explicit opt-in only. A project-scoped `.codex/config.toml` snippet may be documented for review, but the bootstrapper must not mutate real `~/.codex/config.toml` without explicit approval.

The Codex target must not claim built-in `/pcodex` command support. Skills may appear in client UI depending on client support, but terminal `pcodex` commands are the guaranteed interface.

### OpenCode Target

OpenCode integration should write OpenCode-specific command files:

- `.opencode/commands/pcodex.md`
- `.opencode/commands/pcodex-status.md`
- `.opencode/commands/pcodex-dry-run.md`
- `.opencode/commands/pcodex-tune.md`
- `.gitignore` bounded pCodex generated-state section

Optional guidance files may include:

- `.opencode/agents/pcodex-router.md`
- `opencode.json` instruction entry

OpenCode command files are OpenCode-specific. They must not imply Codex command support.

### Generic Terminal Target

The generic target is the fallback for every agent:

```bash
git clone https://github.com/EXO-Robotics/premode-router.git "$HOME/.pcodex-tools/premode-router"
cd "$HOME/.pcodex-tools/premode-router"
scripts/install_pcodex_from_source.sh --install-root "$HOME/.pcodex-alpha"
"$HOME/.pcodex-alpha/bin/pcodex" doctor || true
"$HOME/.pcodex-alpha/bin/pcodex" status
"$HOME/.pcodex-alpha/bin/pcodex" setup
"$HOME/.pcodex-alpha/bin/pcodex" run --dry-run "Hypothetical setup verification task. Do not modify files."
```

Plain `pcodex setup` is the default setup command for onboarding and skips MCP registration. Real registration requires separate explicit approval.

## Safety Boundaries

- Do not publish packages.
- Do not change repository license posture.
- Do not mutate real `~/.codex/config.toml` by default.
- Do not run live Codex tasks during bootstrap.
- Do not dispatch subagents during bootstrap.
- Do not modify source code except setup files.
- Keep generated files project-local by default.
- Use terminal `pcodex` commands as the primary supported control plane.
- Do not claim built-in `/pcodex` command support.
- Do not claim automatic MCP invocation.
- Do not claim real internal Codex subagent interception.
- Do not claim guaranteed savings.
- Do not delete generated state during bootstrap unless explicitly requested.
- Do not blanket-ignore all `.premode/`; ignore only expected generated state unless a repo deliberately chooses a wider policy.

## Generated State Hygiene

The pasteable bootstrap prompts should patch or create `.gitignore` with this bounded section and append it only once:

```gitignore
# pCodex generated local state
.premode/pcodex_state.json
.premode/out/
.premode/audit/
.premode/metrics/
.premode/tuning/
.pcodex/
```

Normal pCodex use may create `.premode/` and `.pcodex/` files, including `.premode/lcc.lock.json`, `.premode/out/cache_manifest.json`, and local tuning outputs under `.premode/tuning/`. The setup report should mention that this generated local state is expected and should remain untracked unless the user deliberately versions reviewed tuning artifacts.

## Generated Report

Every pasteable bootstrap should write `PCODEX_SETUP_REPORT.md` with:

- `PASS`
- `WARN`
- `FILES CREATED OR UPDATED`
- `NOT TOUCHED`
- `NEXT STEPS`
- `First Real Prompt After Bootstrap`

Warnings should be written as expected alpha states, not failures by default:

- `NEEDS_ADJUSTMENT` tuning is normal for a fresh repo until tuning and verification pass.
- MCP status may be unknown when setup used `--no-mcp`.
- Savings estimates may be unavailable until enough local telemetry exists.
- Generated local state is expected and should remain untracked.
- Missing native `/pcodex` slash commands are not bootstrap failure; terminal `pcodex` commands remain the primary supported control plane.
