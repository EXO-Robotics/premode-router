# Pre-mode Router

Pre-mode Router is a private local context compiler and routing formatter for AI coding agents.

It runs before an agent action to select compact repo context and format a model-facing packet. It is not a local reasoning engine, planner, or replacement for the coding agent. The current private alpha path is centered on the V5 `literal_symbol` plugin and the local pCodex wrapper.

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
pcodex setup
pcodex setup --json
pcodex setup --skip-tune
pcodex setup --no-mcp
pcodex status
pcodex status --json
pcodex on
pcodex off
pcodex tuned
pcodex tuned --profile .premode/tuning/repo_profile.json
pcodex tune
pcodex tune --static-only
pcodex tune --validate
pcodex tune --verify
pcodex compile "Fix the failing test"
pcodex run --dry-run "Fix the failing test"
pcodex mcp-server
```

Mode meanings:

- `off`: raw prompt, no pCodex transform
- `on`: best safe available pCodex behavior
- `tuned`: force tuned behavior or fail clearly

`on` resolves to effective tuned behavior only when a valid profile exists and `.premode/tuning/VERIFY_RESULTS.json` has verdict `PASS`. Otherwise, `on` falls back to generalized `literal_symbol`. `tuned` remains strict: invalid tuned state fails before `pcodex run` launches Codex, and MCP tuned failures return the raw prompt with out-of-band metadata instead of appending a stale packet.

`pcodex setup` is the recommended default configuration path. It runs local checks, optional isolated MCP registration, one-step tuning, safe mode selection, and prints a concise dashboard. Real Codex config mutation remains opt-in only.

`pcodex tune` now runs static generation, validation, and verification by default. The `--static-only`, `--validate`, and `--verify` flags remain available for focused maintenance.

`pcodex status` reports configured mode, effective mode, tuning status, MCP status, Codex CLI availability, fallback state, local telemetry counters, and savings-estimate availability. The savings estimate is local-only and unavailable until enough data exists; it is not a guaranteed or monetary savings claim.

`pcodex run`, `pcodex run --dry-run`, and the MCP transform respect effective mode. Their configured/effective mode details are reported out of band.

`pcodex mcp-server` exposes the local MCP tool name `pcodex_transform_subagent_prompt`. Alpha4 proves the command-backed local MCP path can start the stdio server, list the tool/schema through `tools/list`, and transform a safe dummy prompt. Native installed-Codex schema discovery, automatic Codex tool invocation, and real internal subagent interception are not yet proven.

## Supported Claims

On the measured public same-run matrix of six prompts, `literal_symbol` reduced derived cache-adjusted input by 17.02% versus standard and 11.68% versus `ranked_paths_plus_anchors`, with zero scope issues and zero model-facing leakage.

This is a measured public same-run matrix result. It is not a universal token-savings guarantee.

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

The console scripts like `premode` and `pcodex` require editable install.

Smoke commands:

```bash
.venv/bin/premode compile --plugin literal_symbol --help
.venv/bin/premode compile --plugin literal_symbol "Inspect hello.txt" --profile lite --json
.venv/bin/premode compile --plugin literal_symbol --tuning .premode/tuning/repo_profile.json "Inspect hello.txt" --profile lite --json
.venv/bin/pcodex doctor
.venv/bin/pcodex setup --no-mcp
.venv/bin/pcodex status
.venv/bin/pcodex status --json
.venv/bin/pcodex tune
.venv/bin/pcodex tune --help
.venv/bin/pcodex run --dry-run "Inspect hello.txt"
.venv/bin/pcodex mcp-server --help
```

## Docs Map

- [Claims and limitations](docs/CLAIMS_AND_LIMITATIONS.md)
- [V5 literal-symbol strategy](docs/V5_LITERAL_SYMBOL.md)
- [Plugin system](docs/PLUGIN_SYSTEM.md)
- [pCodex tuning](docs/PCODEX_TUNING.md)
- [pCodex bootstrap commands](docs/PCODEX_BOOTSTRAP.md)
- [pCodex MCP status](docs/PCODEX_MCP_STATUS.md)
- [Private alpha install](docs/PRIVATE_ALPHA_INSTALL.md)
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

Estimated savings compares the compiled packet to the eligible repo surface. Cacheable-prefix percent measures how much of the remaining packet is positioned for provider prefix caching.

Use `premode review-patch` for local patch-boundary review. It is a human review aid, not automatic merge approval.

## License

Proprietary and all rights reserved. See [LICENSE](LICENSE).
