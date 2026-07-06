---
name: pcodex-subagent-routing
description: pCodex instruction-level routing guidance for local alpha testing.
---
# pCodex Subagent Routing

Use this skill before spawning or delegating local subagents in this repo when pCodex is available.

## Purpose

Route Codex-created local subagent prompts through pCodex before dispatch. pCodex is the adapter layer; `premode-plugin-literal-symbol` remains only the context-selection strategy.

## When To Use

Use when Codex creates, delegates, spawns, or runs a local subagent/task-agent prompt for this repo. Do not use this skill to claim control over hosted/internal Codex subagents.

## Commands

- `.venv/bin/pcodex status`
- `.venv/bin/pcodex doctor`
- `.venv/bin/pcodex run --dry-run "<task>"`
- `.venv/bin/premode compile --plugin literal_symbol`

## API

Use the local adapter contract when available:

```python
from pathlib import Path
from premode.pcodex_subagent import transform_subagent_prompt

raw_subagent_prompt = "the exact prompt Codex created"
result = transform_subagent_prompt(raw_subagent_prompt, Path.cwd())
dispatch_prompt = result.prompt
```

Canonical flow:

1. Codex writes the exact raw subagent prompt it intends to send.
2. pCodex transforms that exact prompt through `transform_subagent_prompt`.
3. The subagent is dispatched with `result.prompt`.
4. If pCodex is disabled or transformation fails, dispatch the raw prompt unchanged and report the fallback out of band.

## Boundaries

The model-facing transformed prompt may include only the raw Codex-created prompt and the compact literal-symbol V5 packet. Diagnostics and routing metadata stay out of band.

Forbidden in model-facing subagent prompts:

- `TASK_CLASS`
- `SUPPORT_RELATIONS`
- snippets or file blocks
- diagnostics, tool traces, warnings, confidence, validation guidance, command suggestions, review metadata, or do-not-edit language
- secrets or full environment dumps

Do not patch hosted Codex/Web UI. Real Codex internal subagent interception requires a local source hook, local source patch, or official extension point.
