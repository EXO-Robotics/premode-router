# MacBook Dogfood Notes

Date: 2026-07-06

## v0.3.1 Real-Prompt Smoke

- Public branch: `Private-Beta`
- Public install method: `scripts/install_pcodex_from_source.sh`
- Install root used: `/tmp/pcodex-alpha-source-v031`
- Direct Codex smoke: passed after updating Codex CLI
- pCodex dry-run: passed
- pCodex real run: passed
- Changed files: `PCODEX_REAL_PROMPT_SMOKE.md` only
- Runtime state observed: `.premode/pcodex_state.json`
- Known non-blocking warning: `.codex/skills/pcodex-subagent-routing/SKILL.md` was missing YAML frontmatter before the v0.3.2 hardening patch

## Codex CLI Finding

The initial MacBook Codex CLI version was `0.121.0` and failed real-run smoke with service-tier/config incompatibility symptoms. Updating Codex CLI to `0.142.5` allowed both direct Codex and pCodex real-prompt smoke to complete.

If direct `codex exec` fails, update or fix Codex CLI and local Codex config before debugging pCodex.

## Result

The v0.3.1 source install path supported a fresh public clone, isolated install, dry-run transform, and one deliberately scoped real Codex launch. The real prompt edited only the disposable target file and the final file contained:

```text
- pCodex real prompt smoke passed.
```

This is private-alpha dogfood evidence for the public source install path. It is not a production-readiness claim, not a universal savings claim, not native slash-command support, not native installed-Codex schema discovery, and not automatic or internal Codex subagent interception.

## Fresh Private-Beta Tester Notes

Private repository SSH clone requires the tester's GitHub account and local SSH key to have access to `EXO-Robotics/premode-router`. Do not create, print, or modify SSH keys during dogfood. If SSH clone fails with `Permission denied (publickey)`, record that result and continue with the approved HTTPS clone path.

```bash
git clone https://github.com/EXO-Robotics/premode-router.git
cd premode-router
git checkout Private-Beta
```

For source-only smoke, install the core package and plugin:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -e packages/premode-plugin-literal-symbol
```

Editable installs may create `src/premode_router.egg-info/`; that is generated packaging metadata and should remain untracked.

Pytest is part of the repository `dev` extra. If focused tests are part of the dogfood pass, install the dev extra before running pytest:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

If the dev extra is not installed, skip pytest-only checks and run the non-pytest smoke commands instead:

```bash
.venv/bin/python -m py_compile src/premode/*.py
.venv/bin/premode compile --plugin literal_symbol --help
.venv/bin/pcodex first-run --json
.venv/bin/pcodex run --dry-run "Hypothetical dogfood smoke. Do not modify files."
```

Use only current CLI-supported smoke forms:

```bash
.venv/bin/pcodex tuned --help
.venv/bin/pcodex tune --help
.venv/bin/pcodex cleanup --local-state --dry-run --json
```

Do not use `pcodex tuned --advisory`, `pcodex tune --dry-run`, or `pcodex cleanup --dry-run --json`; those are unsupported command shapes in this CLI. Cleanup JSON remains safe when scoped explicitly with `--local-state`.
