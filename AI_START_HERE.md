# AI Start Here

This is the canonical operating entrypoint for AI agents working in this repo. Read this file, `premode.ai.json`, `AGENTS.md`, `docs/CORE_PRODUCT.md`, `docs/FIRST_RUN.md`, and `docs/PRIVATE_BETA_TESTER_PACKET.md` before using historical docs or prompts.

## 1. What this repo is

Pre-mode Router is a private deterministic file-routing and context-structure layer for AI coding agents. It preserves the exact task, ranks likely repository paths, and formats one compact packet.

Pre-mode is not a local reasoning engine, task planner, autonomous agent, or replacement for the coding agent.

## 2. Current status

The current repo state is source-visible proprietary Private-Beta. The lead runtime surface is pCodex, a local wrapper around the Pre-mode `literal_symbol` path for Codex CLI workflows.

## 3. License posture

This repository is proprietary and all rights reserved. Source visibility does not grant permission to use, copy, publish, distribute, commercialize, host, train on, or sublicense the software. Do not describe this repo as open source.

## 4. Supported runtime

The supported runtime is Codex CLI through explicit terminal commands. Terminal `pcodex` commands are the current control plane.

Do not assume `/pcodex` slash commands, native hosted Codex UI integration, automatic MCP invocation, native installed-Codex schema discovery, or real internal Codex subagent interception.

`plugins/pcodex` is the sole canonical plugin source and ships in wheel and sdist artifacts. `.agents/plugins/marketplace.json` is mixed registration state, not content authority. Historical `.agents/skills/pcodex*` and `premode-router` trees are legacy migration inputs only.

Use `pcodex integrate codex --dry-run` before `--write`. Status, repair, reversible disable, uninstall, and conservative migration share the same receipt-bound command family. `--with-mcp` is explicit and never implied by normal plugin installation.

The plugin-local resolver uses `PCODEX_BIN` or `pcodex` on `PATH`. It does not depend on a source checkout, target-repository helper, sibling repository, or legacy alpha install.

## 5. Python requirement

Python `>=3.11` is required.

## 6. Current source install and first run

Use `docs/FIRST_RUN.md` as the canonical Private-Beta first-run path. Use `docs/PRIVATE_BETA_TESTER_PACKET.md` for tester-facing setup and reporting. From a source checkout:

```bash
cd premode-router
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
pcodex doctor || true
pcodex first-run --json
pcodex setup
pcodex status
pcodex first-run
pcodex first-run --json
pcodex status --advisory --json
pcodex integrate codex --dry-run
pcodex ui --json
pcodex run --dry-run "Hypothetical setup verification task. Do not modify files."
pcodex cleanup --local-state --dry-run
```

The source installer builds from the checked-out repo, prunes generated/runtime state from the temporary build copy, and writes `install_manifest.json` under the install root. It does not publish packages, does not install the pCodex packages from PyPI, does not run live Codex tasks, and does not mutate real Codex config unless explicitly asked through the installer option that does so.

## 7. Current development install

Use this path inside a development checkout:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
```

The default `literal_symbol` strategy is bundled in `premode-router`; the separate plugin tree is retained only for third-party compatibility testing.

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
pcodex doctor --json
pcodex status
pcodex first-run --json
pcodex setup
pcodex run --dry-run "<task>"
pcodex run "<task>"
premode review-patch --since-compile
```

Use terminal `pcodex` commands. Inspect `git diff --name-only` after real runs.

Status JSON reports the public mode (`on`, `off`, or `tuned`) and the explicit effective state:

- `OFF_RAW`: no Pre-mode transform.
- `ON_GENERALIZED`: generalized `literal_symbol` packet.
- `ON_TUNED_VERIFIED`: compatibility-preserved `on` state when an existing verified repo-local profile is present.
- `TUNED_STRICT`: strict tuned mode; invalid or unverified tuning fails.
- `SAFE_PASSTHROUGH`: raw prompt passthrough when LCC cannot safely compile.

Read-only advisory receipts are available for paste-safe support:

```bash
pcodex status --advisory --json
pcodex doctor --advisory --json
pcodex first-run --advisory --json
```

Advisory mode may read existing state and report missing/stale state, but it must not write or repair `.premode/`, telemetry, cache manifests, lockfiles, inventory, topology, temp packets, MCP/Codex config, or runtime outputs. It does not launch Codex and does not prove native installed-Codex interception.

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

## 12. Developer tuning compatibility workflow

Tuning is a developer/compatibility surface, not part of the narrow default setup. For compatibility, `on` still activates an existing valid profile with a `PASS` verifier result. Tuning is not a universal savings claim and is not a live Codex task.

Current supported pCodex tuning flow:

```bash
pcodex tune
pcodex tune --static-only
pcodex tune --validate
pcodex tune --verify
pcodex tuned --profile .premode/tuning/repo_profile.json
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
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
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
- `.premode/lcc.lock.json`
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
- `.premode/lcc.lock.json`
- `.premode/out/cache_manifest.json`
- `.premode/inventory/files.json`
- `.premode/topology/repo_topology.json`
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

## 18. Cleanup and repair

Preview repo-local generated state cleanup:

```bash
pcodex cleanup --local-state --dry-run
```

Apply repo-local generated state cleanup:

```bash
pcodex cleanup --local-state --yes
```

This cleanup surface preserves source files, `.pcodex/`, `.gitignore`, `.premodeignore`, and user config. Use `docs/FIRST_RUN.md` for the full repair path.

## 19. Troubleshooting commands

```bash
pcodex doctor || true
pcodex doctor --json
pcodex status
pcodex status --json
pcodex status --advisory --json
pcodex setup
pcodex first-run --json
pcodex first-run --advisory --json
pcodex run --dry-run "Hypothetical troubleshooting task. Do not modify files."
pcodex cleanup --local-state --dry-run
premode detect --json
premode benchmark --profile lite --json
git status --short
git diff --check
```

If direct Codex execution fails, verify Codex CLI before debugging pCodex:

```bash
codex --version
```

## 20. Canonical docs map

- `AI_START_HERE.md`: current AI operating entrypoint.
- `premode.ai.json`: machine-readable AI operating manifest.
- `AGENTS.md`: Codex-specific boundaries, routing, lab, and commit rules.
- `docs/FIRST_RUN.md`: canonical Private-Beta first-run, receipt, cleanup, and repair path.
- `docs/PRIVATE_BETA_TESTER_PACKET.md`: tester-facing install, dry-run, cleanup, reporting, and claim-boundary checklist.
- `README.md`: product overview, source install path, command reference, and claims boundary.
- `docs/TUNING.md`: benchmark/tune/validate guide.
- `docs/INCREMENTAL_TUNING.md`: tuning staleness and future incremental tuning design.
- `docs/CONTENT_FREE_TELEMETRY.md`: content-free local state and telemetry boundary.
- `docs/DAILY_USE.md`: pCodex daily terminal flow.
- `docs/PASTEABLE_CODEX_BOOTSTRAP.md`: pasteable repo bootstrap prompt.
- `docs/PRIVATE_ALPHA_INSTALL.md`: Private-Beta source install and legacy private-alpha bundle details.
- `docs/CLAIMS_AND_LIMITATIONS.md`: supported and unsupported claims.
- `docs/history/`: preserved historical prompts and reports, not current operating instructions.
