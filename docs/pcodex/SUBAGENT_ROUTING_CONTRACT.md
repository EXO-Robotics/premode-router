# pCodex Subagent Routing Contract

pCodex is the local adapter layer that can route prompts through Pre-mode before a Codex invocation. The literal-symbol plugin remains the strategy package; it does not own subagent dispatch behavior.

## Layers

- Soft layer: `AGENTS.md` and this skill-style guidance tell Codex how to behave in this repo.
- Medium layer: `transform_subagent_prompt` provides a local adapter contract for transforming Codex-created subagent prompts.
- Future hard layer: a local editable Codex source hook or official extension point can call the same adapter before subagent dispatch.

## Wrapper Toggle

The wrapper supports:

- `pcodex status`
- `pcodex doctor`
- `pcodex on`
- `pcodex off`
- `pcodex run --dry-run "<task>"`
- `premode compile --plugin literal_symbol`

pCodex defaults to the `literal_symbol` algorithm. Disabled mode returns raw prompts unchanged. Failure mode returns raw prompts unchanged with out-of-band error metadata.

## Subagent Transform Contract

The adapter contract is:

```python
transform_subagent_prompt(subagent_prompt, project_root, parent_prompt=None, spawn_metadata=None)
```

Required behavior:

1. Preserve the exact Codex-created subagent prompt.
2. Compile context from that exact prompt through `premode compile --plugin literal_symbol` or the explicit literal-symbol fallback route.
3. Compose a transformed prompt from the raw prompt and the compact V5 packet.
4. Keep routing metadata, diagnostics, and failures out of the model-facing prompt.
5. If pCodex is disabled or transformation fails, return the raw prompt unchanged and report fallback metadata out of band.

## MCP/Tool Transform Candidate

pCodex can expose the same transform contract as a local tool-compatible adapter:

```python
pcodex_transform_subagent_prompt_tool(subagent_prompt, project_root=None)
```

The tool adapter is designed for `spawnAgent` and `collabAgentToolCall`-style payloads. It extracts the Codex-created prompt, calls `transform_subagent_prompt`, returns the transformed prompt in the original prompt field, preserves unknown payload fields, and adds pCodex routing metadata out of band.

This remains a candidate workflow until Codex is configured or confirmed to call the tool before dispatch. It does not prove hosted/internal Codex interception.

## pCodex MCP/Tool Server Candidate

pCodex can expose the transform adapter through a dependency-free stdio server candidate:

```bash
pcodex mcp-server
```

The intended local tool name is `pcodex_transform_subagent_prompt`. The server candidate accepts JSON tool calls, delegates to `pcodex_transform_subagent_prompt_tool`, and returns transformed prompt text plus out-of-band metadata. It does not open a network listener and does not dump environment variables or secrets.

Installed Codex can register local stdio MCP servers with `codex mcp add`, but pre-dispatch enforcement is not proven unless Codex is configured or confirmed to call this tool before `spawnAgent` dispatch. AGENTS.md and skill instructions remain the instruction-level routing layer.

## Instruction Behavior

Repo instructions and the pCodex skill tell Codex: when creating a local subagent prompt, route the Codex-created prompt through pCodex before dispatch. This is instruction-level behavior guidance, not a hard guarantee for hosted/internal Codex subagents.

## Tested

Current tests cover:

- pCodex env/config propagation
- `transform_subagent_prompt`
- local tool-compatible prompt transformation
- `spawnAgent` and `collabAgentToolCall`-style payload adapters
- stdio tool-server request handling
- disabled/failure fallback
- fake dispatcher receiving the transformed prompt
- instruction-file wording and claim boundaries

## Not Guaranteed

pCodex does not automatically control hosted/internal Codex subagents. Real internal interception requires a local Codex dispatch hook, local source patch, or official extension point.

Hosted Codex/Web UI should not be patched or claimed as supported from this repo.

## Model-Facing Boundary

Allowed model-facing packet sections are TASK, PRIMARY_FILES, RELATED_TESTS, and END. Do not include `TASK_CLASS` or `SUPPORT_RELATIONS` as allowed model-facing output. Do not include snippets, diagnostics, confidence text, validation guidance, command suggestions, review metadata, do-not-edit language, secrets, or full environment dumps in model-facing subagent prompts.
