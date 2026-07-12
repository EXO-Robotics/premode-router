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

## Historical Codex CLI Finding

The initial MacBook Codex CLI version was `0.121.0` and failed real-run smoke with service-tier/config incompatibility symptoms. Updating Codex CLI to `0.142.5` allowed both direct Codex and pCodex real-prompt smoke to complete.

Live `codex exec` verification is explicit-only host CLI validation. The default fresh tester path below stays on pCodex advisory, first-run, dry-run, and cleanup-preview commands.

## Result

The v0.3.1 source install path supported a fresh source checkout, isolated install, dry-run transform, and one deliberately scoped real Codex launch. The real prompt edited only the disposable target file and the final file contained:

```text
- pCodex real prompt smoke passed.
```

This is historical dogfood evidence for the source install path. It is not a production-readiness claim, not a universal savings claim, not native slash-command support, not native installed-Codex schema discovery, and not automatic or internal Codex subagent interception.

## Fresh Private-Beta Tester Notes

The repository is publicly visible and proprietary. Use the public HTTPS clone path; do not create, print, or modify SSH keys during dogfood.

```bash
git clone https://github.com/EXO-Robotics/premode-router.git
cd premode-router
git checkout Private-Beta
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
```

Default tester preflight:

```bash
pcodex doctor --advisory --json
pcodex status --advisory --json
pcodex first-run --json
pcodex setup
pcodex status --json
pcodex run --dry-run --json "Hypothetical dogfood smoke. Do not modify files."
pcodex cleanup --local-state --dry-run --json
```

For development-checkout smoke, install the core package:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
```

The default `literal_symbol` strategy is bundled. The separate plugin tree is an optional compatibility fixture.

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
.venv/bin/pcodex run --dry-run --json "Hypothetical dogfood smoke. Do not modify files."
```

If focused selector, warm-index, or CPU-A checks are part of the dogfood pass, run them only in a dev checkout with `.[dev]` installed and report them as opt-in selector-surface checks, not default behavior.

Use only current CLI-supported smoke forms:

```bash
.venv/bin/pcodex tuned --help
.venv/bin/pcodex tune --help
.venv/bin/pcodex cleanup --local-state --dry-run --json
```

Do not use `pcodex tuned --advisory`, `pcodex tune --dry-run`, or `pcodex cleanup --dry-run --json`; those are unsupported command shapes in this CLI. Cleanup JSON remains safe when scoped explicitly with `--local-state`.

Report compact command/output summaries only. Do not paste secrets, full environment dumps, packet text, source snippets, token-saving claims, production-readiness claims, or public benchmark claims.
