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
pcodex status
pcodex status --json
pcodex on
pcodex off
pcodex tuned
pcodex tuned --profile .premode/tuning/repo_profile.json
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
- `on`: generalized `literal_symbol` transform
- `tuned`: `literal_symbol` transform with a validated tuning profile

`pcodex on` writes repo-local state for generalized mode. `pcodex off` writes repo-local state for raw-prompt mode. `pcodex tuned` validates `.premode/tuning/repo_profile.json` before writing tuned state; use `--profile` to select a different validated profile.

If mode state is missing, pCodex reports the safe default `on`. Invalid state falls back to raw prompt for MCP transforms and blocks `pcodex run` before launching Codex.

`pcodex status` reports mode, state path, tuning profile, whether `premode` and `codex` are available, and whether the `literal_symbol` plugin alias resolves. `pcodex status --json` prints the same state in machine-readable form.

`pcodex doctor` reports local wrapper readiness. It does not print secrets or full environment dumps.

## Tuning

Generate, validate, and verify repo-local tuning artifacts:

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

`pcodex run` can invoke Codex locally. In `off` mode it sends the raw prompt. In `on` mode it compiles through generalized `literal_symbol`. In `tuned` mode it validates the tuning profile before any Codex launch and then compiles with `--tuning`.

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

## Not Yet Proven

pCodex does not yet prove:

- automatic internal Codex subagent routing
- real pre-dispatch Codex interception
- hosted Codex UI integration
- native installed-Codex schema discovery
- production-ready public release behavior
