# pCodex MCP Status

pCodex includes a local stdio MCP-compatible surface for transforming Codex-created subagent prompts through the current `literal_symbol` path.

## Alpha History

- alpha3 introduced the MCP-compatible transform adapter and stdio server candidate.
- alpha4 fixed installed `pcodex mcp-server` command routing so the registered command starts the pCodex MCP server instead of falling through to the Codex wrapper.

## Server Surface

Command:

```bash
pcodex mcp-server
```

Tool name:

```text
pcodex_transform_subagent_prompt
```

The server is stdio-only. It does not bind sockets, start a network listener, launch Codex, print secrets, or dump the environment.

## Mode-Aware Transform

The MCP transform reads repo-local pCodex mode state:

- `off`: returns the raw prompt and marks `transform_applied=false`
- `on`: uses best safe available behavior, appending a tuned packet only when a valid profile exists and `VERIFY_RESULTS.json` verdict is `PASS`; otherwise it appends the generalized `literal_symbol` packet
- `tuned`: validates the configured tuning profile and appends a tuned packet

If strict tuned mode cannot validate the profile, the transform returns the raw prompt and reports the error only in out-of-band metadata. The raw prompt is preserved in every mode.

The tool result includes configured mode and effective mode in metadata. Fallback telemetry is local-only and stores counters/reasons only; it does not store prompts, source snippets, secrets, or file contents.

## Proven In Alpha4

The command-backed local MCP harness proved:

- `pcodex mcp-server` starts the stdio MCP server
- `tools/list` exposes `pcodex_transform_subagent_prompt`
- `tools/list` exposes the input schema
- `tools/call` can transform a safe dummy prompt
- the raw prompt is preserved
- the compact packet is appended
- routing metadata stays out of band

Isolated installed Codex registration/list/get also worked:

```bash
export CODEX_HOME=/example/pcodex-lab/codex_home
codex mcp add pcodex -- pcodex mcp-server
codex mcp list
codex mcp get pcodex
codex mcp remove pcodex
```

Use an isolated `CODEX_HOME` for labs when possible. If a real local Codex config must be used, confirm the remove path first and clean up with:

```bash
codex mcp remove pcodex
```

## Not Yet Proven

The alpha4 result does not prove:

- native installed-Codex schema discovery
- automatic installed-Codex MCP tool invocation
- real pre-dispatch subagent interception
- hosted Codex UI integration
- production-ready MCP integration
- native slash-command support

Instruction files may tell Codex to call the tool before local subagent dispatch, but instruction-level routing is not a hard dispatch hook.
