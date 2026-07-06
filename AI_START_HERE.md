# AI Start Here

This is the canonical operating entrypoint for AI agents working in this repo. Read this file, `premode.ai.json`, and `AGENTS.md` before using historical docs or prompts.

## 1. What this repo is

Pre-mode Router is a private local context compiler and routing formatter for AI coding agents. It runs before an agent action to select compact repo context and format a model-facing packet.

Pre-mode is not a local reasoning engine, task planner, autonomous agent, or replacement for the coding agent.

## 2. Current status

The current repo state is source-visible proprietary development alpha. The lead runtime surface is pCodex, a local wrapper around the Pre-mode `literal_symbol` path for Codex CLI workflows.

## 3. License posture

This repository is proprietary and all rights reserved. Source visibility does not grant permission to use, copy, publish, distribute, commercialize, host, train on, or sublicense the software. Do not describe this repo as open source.

## 4. Supported runtime

The supported runtime is Codex CLI through explicit terminal commands. Terminal `pcodex` commands are the guaranteed control plane.

Do not assume `/pcodex` slash commands, native hosted Codex UI integration, automatic MCP invocation, native installed-Codex schema discovery, or real internal Codex subagent interception.

## 5. Python requirement

Python `>=3.11` is required.

## 6. Current public source install

Use this path for a fresh public source clone:

```bash
git clone https://github.com/EXO-Robotics/premode-router.git
cd premode-router
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
pcodex doctor || true
pcodex setup --no-mcp
pcodex status
pcodex run --dry-run "Hypothetical setup verification task. Do not modify files."
```

The source installer builds from the checked-out repo. It does not publish packages, does not install the pCodex packages from PyPI, does not run live Codex tasks, and does not mutate real Codex config unless explicitly asked through the installer option that does so.

## 7. Current development install

Use this path inside a development checkout:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -e packages/premode-plugin-literal-symbol
```

Prefer repo-local entrypoints after editable install:

```bash
.venv/bin/premode --help
.venv/bin/pcodex status
```

## 8. Future public package install

This command is future/not active unless package publication exists:

```bash
# Future public package path only after package publication exists:
pipx install premode-router
```

Nothing in this repo state confirms a package-registry release.

## 9. Primary pCodex workflow

Start with dry-run before real execution:

```bash
pcodex doctor || true
pcodex status
pcodex setup --no-mcp
pcodex run --dry-run "<task>"
pcodex run "<task>"
premode review-patch --since-compile
```

Use terminal `pcodex` commands. Inspect `git diff --name-only` after real runs.

## 10. Manual Pre-mode compile/review workflow

Use manual compile/review when you need the packet and review surface without launching Codex:

```bash
premode compile --plugin literal_symbol "<task>" --profile lite --json
premode review-patch --since-compile
```

## 11. Benchmark workflow

Benchmarking measures packet size, context selection, expectation hits, budget status, and optional review-loop metrics. It does not prove a live agent will produce a good patch.

```bash
premode benchmark --profile lite --json
premode stress --profile lite --json
```

## 12. Tuning workflow

Tuning selects or validates repo-local defaults. It is not a universal savings claim and is not a live Codex task.

Current supported pCodex tuning flow:

```bash
pcodex tune
pcodex tune --validate
pcodex tune --verify
pcodex status --json
```

Distinctions:

- Benchmarking is measurement.
- Tuning is selecting or validating repo-local defaults.
- Validation proves the selected behavior remains safe enough for the configured local flow.

See `docs/TUNING.md` and `examples/tuning_prompts.json`.

## 13. Validation workflow

Use focused validation before committing agent-operability changes:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
premode detect --json
premode benchmark --profile lite --json
```

For source checkouts with a local venv, prefer:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m py_compile src/premode/*.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
.venv/bin/premode detect --json
.venv/bin/premode benchmark --profile lite --json
.venv/bin/premode stress --profile lite --json
```

## 14. Files agents may edit

Agents may edit source, tests, docs, examples, scripts, templates, package metadata, and repo-root operating docs when the user request requires it and validation passes.

Common editable paths:

- `src/`
- `tests/`
- `packages/premode-plugin-literal-symbol/`
- `docs/`
- `examples/`
- `scripts/`
- `templates/`
- `README.md`
- `AGENTS.md`
- `AI_START_HERE.md`
- `premode.ai.json`
- `pyproject.toml`

## 15. Files agents should not edit by default

Do not edit these by default:

- `.premode/out/`
- `.premode/audit/`
- `.premode/metrics/`
- `.premode/pcodex_state.json`
- `.pcodex/`
- `.agents/plugins/`
- generated outputs
- runtime caches
- `dist/`
- `build/`
- `*.egg-info/`

Only edit or version tuning artifacts when the user explicitly asks and the contents have been reviewed.

## 16. Generated/runtime paths

Generated/runtime paths include:

- `.premode/out/`
- `.premode/audit/`
- `.premode/metrics/`
- `.premode/tuning/`
- `.premode/pcodex_state.json`
- `.pcodex/`
- `PCODEX_SETUP_REPORT.md`
- `dist/`
- `build/`
- `.pytest_cache/`

Keep generated/runtime outputs out of commits unless the user explicitly asks to version a reviewed artifact.

## 17. Experimental/deferred surfaces

These surfaces are experimental, deferred, or not guaranteed:

- native slash-command support
- automatic internal Codex subagent interception
- automatic MCP invocation
- native installed-Codex schema discovery
- hosted Codex UI integration
- public package install until package publication exists

## 18. Troubleshooting commands

```bash
pcodex doctor || true
pcodex status
pcodex status --json
pcodex setup --no-mcp
pcodex run --dry-run "Hypothetical troubleshooting task. Do not modify files."
premode detect --json
premode benchmark --profile lite --json
git status --short
git diff --check
```

If direct Codex execution fails, verify Codex CLI before debugging pCodex:

```bash
codex --version
```

## 19. Canonical docs map

- `AI_START_HERE.md`: current AI operating entrypoint.
- `premode.ai.json`: machine-readable AI operating manifest.
- `AGENTS.md`: Codex-specific boundaries, routing, lab, and commit rules.
- `README.md`: product overview, source install path, command reference, and claims boundary.
- `docs/TUNING.md`: benchmark/tune/validate guide.
- `docs/DAILY_USE.md`: pCodex daily terminal flow.
- `docs/PASTEABLE_CODEX_BOOTSTRAP.md`: pasteable repo bootstrap prompt.
- `docs/PRIVATE_ALPHA_INSTALL.md`: private alpha and source install details.
- `docs/CLAIMS_AND_LIMITATIONS.md`: supported and unsupported claims.
- `docs/history/`: preserved historical prompts and reports, not current operating instructions.
