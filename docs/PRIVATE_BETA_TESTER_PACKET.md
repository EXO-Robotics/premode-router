# Historical Private-Beta Tester Packet

This document preserves the older source-checkout tester flow for history and compatibility only. It is not canonical and must not be given to new invited-beta testers. Use `docs/GETTING_STARTED.md` and the canonical set declared in `premode.product.json`.

pCodex is a local context compiler wrapper around Pre-mode. It does not replace Codex, does not publish packages, does not provide native `/pcodex` slash commands, and does not prove hosted/internal Codex subagent interception.

## Clone And Install

The repository is publicly visible and proprietary. Use the public HTTPS clone path below; no private-repository credential or SSH-key setup is required. Do not print tokens, dump secrets, or modify SSH keys during dogfood.

```bash
git clone https://github.com/EXO-Robotics/premode-router.git
cd premode-router
git checkout Private-Beta
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
```

The source installer builds from the checked-out source tree into `~/.pcodex-alpha` by default. It does not publish packages, install pCodex packages from PyPI, run live Codex tasks, or mutate real Codex config unless the explicitly named real-registration option is used.

## Development Checkout

Use this only when the tester needs repo-local development commands or focused pytest checks:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
```

The default `literal_symbol` strategy is included in the core editable install. The separate plugin package is only a compatibility fixture.

Editable installs may create `src/premode_router.egg-info/`. That is generated packaging metadata and should remain untracked.

If pytest checks are part of the dogfood pass, install the dev extra:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

No-install module smoke works without console scripts:

```bash
PYTHONPATH=src python -m premode.cli detect --json
```

Console scripts such as `premode` and `pcodex` require the source installer or editable install path above.

## First-Run And Advisory Checks

Run advisory checks when reporting state to support or another reviewer without mutating repo-local generated state:

```bash
pcodex doctor --advisory --json
pcodex status --advisory --json
pcodex first-run --advisory --json
```

Run normal setup when local state creation or repair is intended:

```bash
pcodex doctor
pcodex first-run --json
pcodex setup
pcodex status
pcodex first-run --json
```

Expected first-run signals:

- `schema_version` is `pcodex.first_run.v1` for `pcodex first-run --json`.
- `codex_launch` is `not_executed`.
- `global_codex_config_mutation` is `false`.
- `next_action` names the next local setup or dry-run step.

## Dry-Run First

Run dry-run before any live Codex execution:

```bash
pcodex run --dry-run --json "Hypothetical Private-Beta tester smoke. Do not modify files."
```

Expected dry-run signals:

- `codex_launch` is `not_executed`.
- The result is local preflight/transform evidence, not a live task result.
- Any configured/effective mode details remain out of band.

Do not run live Codex unless that is separately approved for the specific tester pass. Live execution should use a disposable file or disposable repository first, and the tester must inspect `git diff --name-only` afterward.

## Cleanup Preview

Preview known repo-local generated state cleanup:

```bash
pcodex cleanup --local-state --dry-run --json
```

Apply cleanup only when intentionally removing generated repo-local pCodex/LCC state:

```bash
pcodex cleanup --local-state --yes
```

Do not use `pcodex cleanup --dry-run --json` without `--local-state`; the current CLI rejects that unscoped form.

## Optional Development Validation

Use focused local checks when the tester has a development checkout and the dev extra is installed:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m py_compile src/premode/*.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_lab73dq_pcodex_install_surface_hardening.py
.venv/bin/premode stress --profile lite --json
```

CPU-A parallel warm-index scoring, warm-index behavior, IntentV2 selectors, and parallel scoring remain internal opt-in selector surfaces. Do not describe them as defaults.

## Reporting Checklist

Report compact command/output summaries only:

- branch and commit SHA;
- source install result and `install_manifest.json` presence;
- advisory doctor/status result summaries;
- first-run schema and `codex_launch` value;
- dry-run command and whether `codex_launch` stayed `not_executed`;
- cleanup preview command and whether it stayed scoped with `--local-state`;
- any file changes from a separately approved live run.

Do not paste secrets, full environment dumps, raw prompts beyond the intended tester task, packet text, source snippets, or unreviewed generated state.

## Claim Boundaries

Do not claim:

- open-source rights or public package availability;
- PyPI or `pipx install premode-router` availability;
- token savings, guaranteed savings, or monetary savings;
- production readiness;
- public benchmark proof;
- native Codex `/pcodex` slash-command integration;
- automatic MCP invocation by installed Codex;
- hosted/internal Codex subagent interception;
- CPU-A, warm-index, IntentV2, or parallel scoring as defaults.

Use this phrasing instead: source-visible proprietary Private-Beta, local-first pCodex command flow, dry-run-first validation, and command-backed local evidence.
