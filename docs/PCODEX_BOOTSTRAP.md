# pCodex Bootstrap

pCodex is a private local wrapper and toggle layer around the lead Pre-mode path:

```bash
premode compile --plugin literal_symbol
```

It keeps `literal_symbol` as the default algorithm and passes pCodex state to child processes through `PCODEX_*` environment variables.

## Commands

```bash
pcodex install
pcodex doctor
pcodex doctor --advisory
pcodex doctor --advisory --json
pcodex first-run
pcodex first-run --json
pcodex first-run --advisory
pcodex first-run --advisory --json
pcodex setup
pcodex setup --json
pcodex setup --skip-tune
pcodex setup --no-mcp
pcodex status
pcodex status --json
pcodex status --advisory
pcodex status --advisory --json
pcodex cleanup --local-state --dry-run
pcodex cleanup --local-state --yes
pcodex on
pcodex off
pcodex tuned
pcodex tuned --profile .premode/tuning/repo_profile.json
pcodex tune
pcodex tune --static-only
pcodex tune --validate
pcodex tune --verify
pcodex compile "Fix the failing test"
pcodex run "Fix the failing test"
pcodex run --dry-run "Fix the failing test"
pcodex mcp-server
```

## Local Modes

pCodex supports three repo-local modes:

- `off`: raw prompt, no pCodex transform
- `on`: best safe available pCodex behavior
- `tuned`: force tuned behavior or fail clearly

`pcodex on` writes repo-local state for smart on mode. Smart on uses tuned behavior only when `.premode/tuning/repo_profile.json` validates and `.premode/tuning/VERIFY_RESULTS.json` has verdict `PASS`. Otherwise it safely falls back to generalized `literal_symbol`.

`pcodex off` writes repo-local state for raw-prompt mode. `pcodex tuned` validates `.premode/tuning/repo_profile.json` before writing strict tuned state; use `--profile` to select a different validated profile. Strict tuned mode fails clearly when the profile is missing or invalid.

If mode state is missing, pCodex reports the safe default `on`. Invalid state falls back to raw prompt for MCP transforms and blocks `pcodex run` before launching Codex.

`pcodex status` reports configured mode, effective mode, algorithm, tuning status/profile, MCP status, Codex CLI availability, fallback state, local telemetry counters, savings-estimate availability, and state path. `pcodex status --json` prints the same dashboard in machine-readable form with `schema_version: pcodex.status.v1`.

`pcodex doctor` reports local wrapper readiness. It does not print secrets or full environment dumps.

`pcodex first-run` prints a content-free first-run receipt. The JSON form reports install provenance when an install manifest exists, public mode, plugin alias, inventory/topology/cache/lock summaries, one next action, and cleanup commands. It does not include raw prompts, source bodies, snippets, secrets, packet text, inventory path lists, topology path lists, or environment values.

Use `--advisory` with `status`, `doctor`, or `first-run` for read-only/no-write support receipts. Advisory commands report missing or stale state without refreshing it, include `writes_performed=false`, and do not create `.premode/`, lockfiles, cache manifests, inventory, topology, telemetry, audit, metrics, temp packets, MCP registration, Codex config/home, install state, or runtime outputs. Advisory mode does not launch Codex.

## Setup

`pcodex setup` is the recommended default path after install:

```bash
pcodex setup
```

It runs local checks, optionally attempts isolated Codex MCP registration, runs one-step tuning unless `--skip-tune` is provided, writes `tuned` only when verification is `PASS`, writes `on` for skipped or non-PASS tuning, and prints a concise dashboard. Use `--json` for automation. Use `--no-mcp` to skip MCP registration. Real Codex config mutation requires the explicit `--real-codex-registration` flag.

For first-run value, prefer `pcodex setup --skip-tune --no-mcp` so tuning and MCP are not prerequisites.

## Cleanup

Preview known repo-local generated state cleanup:

```bash
pcodex cleanup --local-state --dry-run
```

Apply cleanup:

```bash
pcodex cleanup --local-state --yes
```

Cleanup is limited to known generated state under `.premode/` and preserves `.pcodex/`, source files, `.gitignore`, `.premodeignore`, and user config.

## Tuning

Run the one-step local tuning pipeline:

```bash
pcodex tune
```

Advanced maintenance commands remain available:

```bash
pcodex tune --static-only
pcodex tune --validate
pcodex tune --verify
```

The default tuning profile path is `.premode/tuning/repo_profile.json`. `pcodex tune --verify` is an offline compile-only local-selection verifier, not a live Codex success guarantee.

## Compile

`pcodex compile` compiles through the `literal_symbol` plugin alias when available:

```bash
pcodex compile "Fix the failing test"
```

If the plugin alias is unavailable, pCodex falls back to the explicit equivalent V5 literal-symbol flags and reports that fallback out of band.

## Run And Dry Run

`pcodex run --dry-run` does not execute Codex. It reports the current mode, whether a transform would be applied, the tuning profile when tuned mode is active, the planned Pre-mode command when applicable, planned Codex invocation, pCodex child environment keys, packet path when a packet is produced, and redacted prompt previews.

Large-repo safety is automatic and metadata-only. For media-asset lookup prompts, pCodex uses a path/stat fast path that reports `context_selection_mode=asset_media_fast_path`, selected paths, candidate counts, and `content_reads=0`; it does not read image, blend, archive, or other media contents into the packet. For broad repository prompts that exceed the local selection budget, compile reports `compile_degraded=true` and `compile_degraded_reason=large_repo_budget_exceeded` in JSON while sending only the canonical user task as the model-facing packet. Normal code-edit tasks keep the default `literal_symbol` packet path.

`pcodex run --dry-run` also reports configured and effective mode. `pcodex run` can invoke Codex locally. In effective `off` mode it sends the raw prompt. In effective `on` mode it compiles through generalized `literal_symbol`. In effective `tuned` mode it compiles with `--tuning`. Strict `tuned` mode validates the tuning profile before any Codex launch.

Do not use `pcodex run` for private live tasks unless that execution is explicitly approved for the current task.

## Environment Propagation

pCodex propagates wrapper state through:

- `PCODEX_ENABLED`
- `PCODEX_ALGORITHM`
- `PCODEX_PACKET_STRATEGY`
- `PCODEX_PROJECT_ROOT`
- `PCODEX_CONFIG`
- `PCODEX_CONFIG_PATH`

The algorithm value is `literal_symbol`.

## MCP Server

`pcodex mcp-server` starts the dependency-free stdio MCP server candidate. It exposes `pcodex_transform_subagent_prompt` and reads/writes JSON-RPC over stdin/stdout only.

The transform respects off/on/tuned state. `off` returns the raw prompt. `on` appends the generalized compact packet. `tuned` appends a tuned compact packet when the profile validates; tuned failure returns the raw prompt plus out-of-band error metadata.

The transform also reports configured and effective mode in metadata. Smart `on` uses tuned packets only for verified PASS profiles; otherwise it appends the generalized compact packet and records fallback metadata out of band.

## Not Yet Proven

pCodex does not yet prove:

- automatic internal Codex subagent routing
- real pre-dispatch Codex interception
- hosted Codex UI integration
- native installed-Codex schema discovery
- production-ready public release behavior
