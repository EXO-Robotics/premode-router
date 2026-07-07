# pCodex Daily Use

This is the current private-alpha terminal flow for a public source clone. It uses explicit `pcodex` commands and keeps real Codex config mutation opt-in.

## Install From Public Source Clone

```bash
git clone https://github.com/EXO-Robotics/premode-router.git
cd premode-router
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
```

## Before First Real Run

Check the local Codex CLI first:

```bash
codex --version
codex exec -C "$PWD" --sandbox workspace-write --ephemeral - <<'EOF'
Edit only a disposable file. Do not modify source files.
EOF
```

If direct Codex fails, update or fix Codex CLI and local Codex config before debugging pCodex. `pcodex doctor` and `pcodex status --json` report Codex CLI version/config warnings when they can be detected.

## Daily-Use Smoke

```bash
pcodex status
pcodex setup --no-mcp
pcodex status --json
pcodex run --dry-run "Hypothetical dummy task: inspect this repo. Do not modify files."
```

Start the first real run against a disposable file or disposable clone:

```bash
cat > PCODEX_DAILY_USE_TEST.md <<'EOF'
# pCodex Daily Use Test
Initial line.
EOF
git add PCODEX_DAILY_USE_TEST.md
pcodex run --dry-run "Edit only PCODEX_DAILY_USE_TEST.md. Add one bullet under the heading saying: pCodex daily use smoke passed. Do not modify any other files."
pcodex run "Edit only PCODEX_DAILY_USE_TEST.md. Add one bullet under the heading saying: pCodex daily use smoke passed. Do not modify any other files."
git diff --name-only
git diff -- PCODEX_DAILY_USE_TEST.md
```

Expected first-run boundary:

- `pcodex run --dry-run` reports `transform_applied: true`
- the real run returns `0`
- only `PCODEX_DAILY_USE_TEST.md` changes
- source, docs, and scripts remain untouched

## Generated Local State

Normal pCodex use may create local state under `.premode/` and `.pcodex/`, including `.premode/pcodex_state.json`, `.premode/lcc.lock.json`, `.premode/out/`, `.premode/out/cache_manifest.json`, `.premode/audit/`, `.premode/metrics/`, and `.premode/tuning/`.

These files should generally remain untracked. Only version tuning artifacts deliberately, after reviewing what they contain and why the repo should carry them.

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

## Boundaries

- Use terminal `pcodex` commands.
- Do not use `/pcodex` slash commands yet.
- Do not rely on native Codex UI integration yet.
- Start with dry-run.
- Run the first real prompt against disposable files or disposable repositories.
- Inspect `git diff --name-only` after real runs.
- Real Codex MCP config registration remains explicit opt-in only.

## Pasteable Bootstrap

For one-paste repo onboarding, use:

- [Pasteable Codex bootstrap](PASTEABLE_CODEX_BOOTSTRAP.md)
- [Pasteable OpenCode bootstrap](PASTEABLE_OPENCODE_BOOTSTRAP.md)
- [Bootstrapper design](BOOTSTRAPPER_DESIGN.md)
- [Integration commands plan](INTEGRATION_COMMANDS_PLAN.md)

Pasteable bootstrap prompts configure repo-local pCodex UX files. Terminal `pcodex` commands remain the guaranteed control plane. Codex skills are the Codex-facing surface. OpenCode commands are OpenCode-specific.
