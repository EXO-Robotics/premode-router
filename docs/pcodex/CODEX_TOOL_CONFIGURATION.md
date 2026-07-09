# pCodex Codex Tool Configuration

This document describes the local tool configuration candidate for pCodex subagent prompt transformation. See `docs/PCODEX_MCP_STATUS.md` for the current alpha4 proof boundary.

## Tool Server Candidate

pCodex exposes a dependency-free stdio server candidate:

```bash
pcodex mcp-server
```

The server exposes one tool:

```text
pcodex_transform_subagent_prompt
```

The tool accepts a Codex-created local subagent prompt and returns a transformed prompt plus out-of-band pCodex metadata.

## Candidate Codex Registration

Installed Codex supports local stdio MCP server registration through `codex mcp add`.

Conceptual command:

```bash
codex mcp add pcodex -- pcodex mcp-server
```

Repo-local command when using the project virtual environment:

```bash
codex mcp add pcodex -- .venv/bin/pcodex mcp-server
```

Do not apply these commands automatically from tests or lab scripts. They mutate user-level Codex configuration.

## Intended Use

The intended workflow is:

1. Codex creates a local `spawnAgent` or `collabAgentToolCall` prompt.
2. Codex calls `pcodex_transform_subagent_prompt` with the exact prompt.
3. pCodex routes the prompt through `transform_subagent_prompt`.
4. Codex dispatches the subagent using the returned transformed prompt.

## Alpha4 Proof Boundary

Alpha4 local evidence shows that the same command used in Codex MCP registration can start the local stdio server, expose `pcodex_transform_subagent_prompt` through `tools/list`, expose its schema through that command-backed MCP path, and transform a safe dummy prompt.

Installed Codex can register/list/get the server in an isolated `CODEX_HOME`, but native installed-Codex schema discovery and automatic tool invocation are not yet proven.

## Enforcement Status

This configuration candidate does not prove installed Codex calls the tool before subagent dispatch. Until that is confirmed, AGENTS.md and the pCodex skill remain the instruction-level routing layer.

Do not claim pCodex automatically controls hosted/internal Codex subagents. Do not patch hosted Codex/Web UI.

## Safety

The server is stdio-only. It does not start a network listener. It does not print secrets, API keys, token values, or full environment dumps. Diagnostics and routing metadata remain out of the model-facing prompt.
