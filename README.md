# Pre-mode Router

Pre-mode Router is a private local context compiler and routing formatter for AI coding agents.

It runs before an agent action to select compact repo context and format a model-facing packet. It is not a local reasoning engine, planner, or replacement for the coding agent. The current private alpha path is centered on the V5 `literal_symbol` plugin and the local pCodex wrapper.

## For AI agents

Start with:

- `AI_START_HERE.md`
- `premode.ai.json`
- `AGENTS.md`
- `docs/FIRST_RUN.md`

These files define the current install, setup, validation, benchmark, tuning, and safety boundaries for agents. Do not infer current behavior from historical prompt files. Historical prompts live under `docs/history/` and are not current operating instructions.

## Current Private Alpha

Base package version: `v0.2.6.24`.

Current lead command:

```bash
premode compile --plugin literal_symbol "Fix the failing test"
```

Explicit repo tuning is available only when a validated local profile is supplied:

```bash
premode compile --plugin literal_symbol --tuning .premode/tuning/repo_profile.json "Fix the failing test"
```

The `literal_symbol` plugin maps to:

```text
--packet-version v5
--packet-variant tool_assisted_anchors_internal
--packet-strategy literal_symbol
```

`ranked_paths_plus_anchors` remains the fallback and comparison baseline. `literal_symbol_config_gated`, `literal_symbol_collision_filter`, and `literal_symbol_import_rank_json_only` are not defaults.

## What pCodex Is

pCodex is a private local wrapper layer around the lead Pre-mode path. It provides local toggle, compile, run, dry-run, and stdio MCP server commands for routing Codex-created prompts through Pre-mode before local action when explicitly used.

Current pCodex command surface:

```bash
pcodex install
pcodex doctor
pcodex doctor --json
pcodex first-run
pcodex first-run --json
pcodex first-run --advisory --json
pcodex setup
pcodex setup --json
pcodex setup --skip-tune
pcodex setup --no-mcp
pcodex status
pcodex status --json
pcodex status --advisory
pcodex status --advisory --json
pcodex doctor --advisory
pcodex doctor --advisory --json
pcodex first-run --advisory
pcodex first-run --advisory --json
pcodex on
pcodex off
pcodex tuned
pcodex tuned --profile .premode/tuning/repo_profile.json
pcodex tune
pcodex tune --static-only
pcodex tune --validate
pcodex tune --verify
pcodex integrate codex --dry-run
pcodex integrate codex --write
pcodex integrate codex --write --with-mcp
pcodex plugin init --local-marketplace --dry-run
pcodex plugin init --local-marketplace
pcodex ui
pcodex ui --json
pcodex compile "Fix the failing test"
pcodex run --dry-run "Fix the failing test"
pcodex cleanup --local-state --dry-run
pcodex cleanup --local-state --yes
pcodex mcp-server
```

Mode meanings:

- `off`: raw prompt, no pCodex transform
- `on`: best safe available pCodex behavior
- `tuned`: force tuned behavior or fail clearly

The explicit effective states are `OFF_RAW`, `ON_GENERALIZED`, `ON_TUNED_VERIFIED`, `TUNED_STRICT`, and `SAFE_PASSTHROUGH`.

`on` resolves to effective tuned behavior only when a valid profile exists and `.premode/tuning/VERIFY_RESULTS.json` has verdict `PASS`. Otherwise, `on` falls back to generalized `literal_symbol`. `tuned` remains strict: missing, invalid, or unverified tuned state fails before `pcodex run` launches Codex, and MCP tuned failures return the raw prompt with out-of-band metadata instead of appending a stale packet.

`pcodex setup` is the recommended default configuration path. It runs local checks, optional isolated MCP registration, one-step tuning, safe mode selection, and prints a concise dashboard. Real Codex config mutation remains opt-in only.

`pcodex tune` now runs static generation, validation, and verification by default. The `--static-only`, `--validate`, and `--verify` flags remain available for focused maintenance.

`pcodex status` reports configured mode, effective mode, effective state, tuning status, MCP status, Codex CLI availability, fallback state, local telemetry counters, lockfile status, cache-manifest status, and savings-estimate availability. The savings estimate is local-only and unavailable until enough data exists; it is not a guaranteed or monetary savings claim.

`pcodex status --advisory`, `pcodex doctor --advisory`, and `pcodex first-run --advisory` are read-only/no-write support surfaces. They may inspect existing state and report missing/stale state, but they do not create `.premode/`, refresh caches, write lockfiles, write telemetry/audit/metrics, write temp packets, register MCP, alter Codex config, repair state, or launch Codex. The JSON receipts include `writes_performed=false`, `would_write`, and `would_refresh` fields and are designed to be paste-safe.

`pcodex first-run --json` reports install provenance, mode, plugin alias, next action, and cleanup commands without launching Codex or mutating global Codex config. `pcodex first-run --advisory --json` performs no writes.

`pcodex run`, `pcodex run --dry-run`, and the MCP transform respect effective mode. Their configured/effective mode details are reported out of band.

Local control-plane files include `.premode/pcodex_state.json`, `.premode/lcc.lock.json`, and `.premode/out/cache_manifest.json`. These are generated/runtime files and must not store prompt text, source snippets, secrets, or file contents. They use hashes, mode names, timestamps, counters, and status reasons only.

## Codex-Native UX Surface

The repo-local Codex UX surface lives in `.agents/skills`, `.agents/plugins/marketplace.json`, and top-level `plugins/`. The pCodex plugin scaffold is local-only under `plugins/pcodex`; it is the intended discovery surface for a local Codex plugin marketplace and does not imply public marketplace publication or production approval.

Generated pCodex skills resolve the executable with `.agents/skills/pcodex/bin/resolve-pcodex.sh`, checking `./.venv/bin/pcodex`, `$HOME/.pcodex-alpha/bin/pcodex`, then `pcodex` on `PATH`. If none exists, the skill reports paste-safe setup guidance instead of a raw command-not-found error.

`pcodex cleanup --local-state --dry-run` previews bounded cleanup of known generated repo-local pCodex state. `pcodex cleanup --local-state --yes` applies only that bounded cleanup. Unknown pCodex subcommands fail closed and do not launch Codex.

Terminal `pcodex` commands remain the guaranteed control plane. A custom `/pcodex` slash command is not supported or claimed. MCP is optional and explicit: `pcodex integrate codex --write --with-mcp` writes only repo-local scaffold files and does not register MCP globally or mutate `~/.codex/config.toml`. Dry-run and setup/integration preview commands do not launch live Codex tasks.

`pcodex mcp-server` exposes the local MCP tool name `pcodex_transform_subagent_prompt`. Alpha4 proves the command-backed local MCP path can start the stdio server, list the tool/schema through `tools/list`, and transform a safe dummy prompt. Native installed-Codex schema discovery, automatic Codex tool invocation, and real internal subagent interception are not yet proven.

## Supported Claims

On the measured local same-run matrix of six prompts, `literal_symbol` reduced derived cache-adjusted input by 17.02% versus standard and 11.68% versus `ranked_paths_plus_anchors`, with zero scope issues and zero model-facing leakage.

This is a measured local same-run matrix result. It is not a universal token-savings guarantee.

## Unsupported Claims

Do not claim:

- universal token savings
- savings on all Codex tasks
- production-ready Codex interception
- automatic internal Codex subagent routing
- native installed-Codex schema discovery
- hosted Codex UI integration
- public package release readiness

## Private Status

This repository and the literal-symbol plugin package are private and proprietary. Nothing here has been published to PyPI or another external registry. Access to the repository does not grant permission to use, copy, publish, distribute, commercialize, host, train on, or sublicense the software.

## Source Install And First Run

For the canonical private-beta first-run path, see [pCodex first run](docs/FIRST_RUN.md).

From a source checkout, install pCodex into an isolated local environment from the checked-out source tree:

```bash
cd premode-router
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
~/.pcodex-alpha/bin/pcodex first-run --json
~/.pcodex-alpha/bin/pcodex setup --skip-tune --no-mcp
~/.pcodex-alpha/bin/pcodex status
~/.pcodex-alpha/bin/pcodex first-run
~/.pcodex-alpha/bin/pcodex first-run --json
~/.pcodex-alpha/bin/pcodex run --dry-run "Hypothetical dummy task: inspect this repo. Do not modify files."
~/.pcodex-alpha/bin/pcodex cleanup --local-state --dry-run
```

The source installer builds and installs `premode-router` and `premode-plugin-literal-symbol` from the local checkout into `~/.pcodex-alpha` by default. It verifies the installed `pcodex` help, first-run, cleanup, and unknown-command fail-closed surface. It does not publish packages, does not install from PyPI for the pCodex packages, does not run live Codex tasks, and does not mutate real Codex config unless `--real-codex-registration` is passed explicitly.

Current install means the source install above or the development editable install below. Future public package installation, such as `pipx install premode-router`, is not active unless package publication exists.

The private-alpha bundle installer is separate:

```bash
scripts/install_pcodex_private_alpha.sh --artifact-root /path/to/pcodex-private-alpha-v0.3.0
```

That bundle installer requires `dist_core/` and `dist_plugin/` wheel artifacts and is not expected to work from a source-only public clone.

## Fastest repo bootstrap

1. Open the target repo in Codex.
2. Paste the prompt from [Pasteable Codex bootstrap](docs/PASTEABLE_CODEX_BOOTSTRAP.md).
3. Let Codex create repo-local skills, `AGENTS.md`, `.gitignore`, and `PCODEX_SETUP_REPORT.md`.
4. Use terminal `pcodex status` and `pcodex run --dry-run` as the reliable control plane.

Related onboarding docs:

- [Pasteable Codex bootstrap](docs/PASTEABLE_CODEX_BOOTSTRAP.md)
- [Pasteable OpenCode bootstrap](docs/PASTEABLE_OPENCODE_BOOTSTRAP.md)
- [pCodex daily use](docs/DAILY_USE.md)
- [MacBook dogfood notes](docs/MACBOOK_DOGFOOD.md)

## Daily Use From Source Install

Before the first real `pcodex run`, verify the installed Codex CLI directly:

```bash
codex --version
codex exec -C "$PWD" --sandbox workspace-write --ephemeral - <<'EOF'
Edit only a disposable file. Do not modify source files.
EOF
```

If direct Codex fails, update or fix Codex CLI and local Codex config before debugging pCodex. `pcodex doctor` and `pcodex status --json` include Codex CLI/config preflight fields when available.

Daily-use starter flow:

```bash
pcodex status
pcodex first-run --json
pcodex setup --skip-tune --no-mcp
pcodex status --json
pcodex status --advisory --json
pcodex first-run --json
pcodex run --dry-run "Hypothetical dummy task: inspect this repo. Do not modify files."
pcodex cleanup --local-state --dry-run
pcodex run "Edit only a disposable test file. Do not modify any other files."
git diff --name-only
```

Use terminal `pcodex` commands. Do not use `/pcodex` slash commands yet, do not rely on native Codex UI integration yet, start with dry-run, use explicit `pcodex run` for any Codex execution, run the first real prompt against disposable files or repositories, and inspect the resulting diff.

For pasteable onboarding, use the bounded prompts in [Pasteable Codex bootstrap](docs/PASTEABLE_CODEX_BOOTSTRAP.md) or [Pasteable OpenCode bootstrap](docs/PASTEABLE_OPENCODE_BOOTSTRAP.md). These prompts configure repo-local pCodex UX files. Terminal `pcodex` commands remain the guaranteed control plane. Codex skills are the Codex-facing surface; OpenCode commands are OpenCode-specific.

## Quick Local Setup

Python >=3.11 is required. macOS system Python may be too old; Python 3.9 will not work because tomllib requires Python 3.11+ unless a backport dependency is added.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -e packages/premode-plugin-literal-symbol
```

No-install module smoke:

```bash
PYTHONPATH=src python -m premode.cli detect --json
```

No-install module smoke works with `PYTHONPATH=src`; console scripts like `premode` and `pcodex` require an editable or source install.

Smoke commands:

```bash
.venv/bin/premode compile --plugin literal_symbol --help
.venv/bin/premode compile --plugin literal_symbol "Inspect hello.txt" --profile lite --json
.venv/bin/premode compile --plugin literal_symbol --tuning .premode/tuning/repo_profile.json "Inspect hello.txt" --profile lite --json
.venv/bin/pcodex doctor
.venv/bin/pcodex first-run --json
.venv/bin/pcodex setup --no-mcp
.venv/bin/pcodex status
.venv/bin/pcodex status --json
.venv/bin/pcodex tune
.venv/bin/pcodex tune --help
.venv/bin/pcodex run --dry-run "Inspect hello.txt"
.venv/bin/pcodex cleanup --local-state --dry-run
.venv/bin/pcodex mcp-server --help
```

## Docs Map

- [Claims and limitations](docs/CLAIMS_AND_LIMITATIONS.md)
- [pCodex first run](docs/FIRST_RUN.md)
- [AI agent start here](AI_START_HERE.md)
- [AI operating manifest](premode.ai.json)
- [Tuning guide](docs/TUNING.md)
- [Incremental tuning design](docs/INCREMENTAL_TUNING.md)
- [Content-free telemetry](docs/CONTENT_FREE_TELEMETRY.md)
- [V5 literal-symbol strategy](docs/V5_LITERAL_SYMBOL.md)
- [Plugin system](docs/PLUGIN_SYSTEM.md)
- [pCodex tuning](docs/PCODEX_TUNING.md)
- [pCodex bootstrap commands](docs/PCODEX_BOOTSTRAP.md)
- [pCodex MCP status](docs/PCODEX_MCP_STATUS.md)
- [Private alpha install](docs/PRIVATE_ALPHA_INSTALL.md)
- [pCodex daily use](docs/DAILY_USE.md)
- [MacBook dogfood notes](docs/MACBOOK_DOGFOOD.md)
- [Pasteable Codex bootstrap](docs/PASTEABLE_CODEX_BOOTSTRAP.md)
- [Pasteable OpenCode bootstrap](docs/PASTEABLE_OPENCODE_BOOTSTRAP.md)
- [Bootstrapper design](docs/BOOTSTRAPPER_DESIGN.md)
- [Integration commands plan](docs/INTEGRATION_COMMANDS_PLAN.md)
- [Release/archive hygiene](docs/RELEASE_ARCHIVE_HYGIENE.md)
- [pCodex subagent routing contract](docs/pcodex/SUBAGENT_ROUTING_CONTRACT.md)

## Validation

Focused validation for this alpha surface:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m py_compile src/premode/*.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_lab73aq_plugin_alias_discovery.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_lab73bc_pcodex_mcp_entrypoint_fix.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q packages/premode-plugin-literal-symbol/tests
.venv/bin/premode stress --profile lite --json
```

Full local pytest command:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Review and benchmark smoke:

```bash
premode review-patch --since-compile
premode benchmark --profile lite
```

Estimated savings is a local heuristic that compares the compiled packet to the eligible repo surface. Cacheable-prefix percent measures how much of the remaining packet is positioned for provider prefix caching.

Use `premode review-patch` for local patch-boundary review. It is a human review aid, not automatic merge approval.

## License

Proprietary and all rights reserved. See [LICENSE](LICENSE).
