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

## Boundaries

- Use terminal `pcodex` commands.
- Do not use `/pcodex` slash commands yet.
- Do not rely on native Codex UI integration yet.
- Start with dry-run.
- Run the first real prompt against disposable files or disposable repositories.
- Inspect `git diff --name-only` after real runs.
- Real Codex MCP config registration remains explicit opt-in only.
