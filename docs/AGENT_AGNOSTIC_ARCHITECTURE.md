# Agent-Agnostic Architecture

## Goal

Pre-mode should be Codex-first, but not Codex-only.

The core product should generate a neutral evidence packet. Agent-specific behavior should live in renderers/adapters.

## Current MVP

Codex CLI is the first supported runtime:

```bash
pcodex "Fix the build"
```

This path should remain strong and safe.

## Future direction

Add target renderers:

```bash
premode compile "Fix the build" --target codex
premode compile "Fix the build" --target opencode
premode compile "Fix the build" --target aider
premode compile "Fix the build" --target generic
premode compile "Fix the build" --target json
```

Internal model:

```text
EvidencePacket
  -> Markdown renderer
  -> Codex renderer
  -> OpenCode renderer
  -> Aider renderer
  -> JSON renderer
```

## Future agent adapter config

Possible future config:

```json
{
  "agents": {
    "codex": {
      "command": "codex",
      "exec_args": ["exec", "-C", "{repo}", "-"],
      "stdin_prompt": true,
      "privacy_mode": "stdin_only"
    },
    "opencode": {
      "command": "opencode",
      "exec_args": ["run", "--cwd", "{repo}"],
      "stdin_prompt": true,
      "privacy_mode": "stdin_preferred"
    },
    "generic": {
      "command": null,
      "output": "markdown"
    }
  }
}
```

Possible future commands:

```bash
premode agent list
premode agent doctor codex
premode agent doctor opencode
premode run --agent codex "Fix the build"
premode run --agent opencode "Fix the build"
```

## Naming guidance

Keep current names for compatibility:

```text
pcodex
codex_exec.py
```

But avoid adding unnecessary Codex-only names in future generic modules.

Prefer future names like:

```text
agent_exec.py
agent_adapters.py
AGENT_PATCH_PROMPT.md
EvidencePacket
PacketRenderer
```

## Design rule

The repo map, impact map, token budget report, context receipt, evidence summary, and patch boundary should be agent-neutral artifacts.

Codex-specific logic should only control how the packet is executed or rendered for Codex.

## v2.4.4 intake model

The neutral core now starts with an intake report before agent-specific rendering. This keeps Codex/OpenCode/Aider/Claude-style support from depending on one-off project adapters.

The intake model emits:

- `traits`
- `policy_packs`
- `authority_model`
- `artifact_model`
- `mutation_model`
- `command_model`
- `intake_warnings`

Agent renderers should consume the compact policy summary, not the full raw intake report, unless the user asks for JSON/audit detail.


## v2.4.5 intake hygiene

The agent-agnostic core now emits `packet_mode`, `selected_context_tokens`, and `policy_metadata_tokens`, so renderers can choose compact packets for small low-risk repos while preserving fuller policy packets for proof/control-plane, infra, migration, generated-artifact, and binary-asset-heavy repos.
