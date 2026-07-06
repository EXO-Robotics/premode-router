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
pcodex on
pcodex off
pcodex compile "Fix the failing test"
pcodex run "Fix the failing test"
pcodex run --dry-run "Fix the failing test"
pcodex mcp-server
```

## Local Toggle

`pcodex on` writes repo-local pCodex config enabling the wrapper path. `pcodex off` writes repo-local config disabling it.

`pcodex status` reports whether pCodex is enabled, which config source was used, whether `premode` and `codex` are available, and whether the `literal_symbol` plugin alias resolves.

`pcodex doctor` reports local wrapper readiness. It does not print secrets or full environment dumps.

## Compile

`pcodex compile` compiles through the `literal_symbol` plugin alias when available:

```bash
pcodex compile "Fix the failing test"
```

If the plugin alias is unavailable, pCodex falls back to the explicit equivalent V5 literal-symbol flags and reports that fallback out of band.

## Run And Dry Run

`pcodex run --dry-run` does not execute Codex. It reports the planned Pre-mode command, planned Codex invocation, pCodex child environment keys, packet path when enabled, and redacted prompt previews.

`pcodex run` can invoke Codex locally. Do not use it for private live tasks unless that execution is explicitly approved for the current task.

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

## Not Yet Proven

pCodex does not yet prove:

- automatic internal Codex subagent routing
- real pre-dispatch Codex interception
- hosted Codex UI integration
- native installed-Codex schema discovery
- production-ready public release behavior
