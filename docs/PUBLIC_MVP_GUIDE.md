# Public MVP Guide

## Product category

Pre-mode is a local AI-coding preflight and patch-governance layer.

It is not another coding agent.

## First wedge

Codex CLI power users.

Codex is the first supported runtime because:

- it has a clear CLI workflow
- it supports stdin-driven execution
- users already care about context, cost, and scope
- the wrapper can remain local-first and auditable

## Public install story

Future public story:

```bash
pipx install premode-router
cd my-repo
premode setup
pcodex "Fix the failing tests"
```

## Value shown immediately

Pre-mode should print a short receipt:

```text
Detected: Python project at .
Commands: pytest
Context: 2 full-text files, 6 summaries, 42 manifest files
Estimated context savings: 81%
Patch boundary: 4 allowed edit files
Privacy: 3 files blocked, 0 secrets leaked
```

## What not to claim

Do not claim:

- replaces Codex
- replaces Claude Code
- local model offload is complete
- full autonomous governance is complete
- works perfectly for every repo

Use:

- Codex-first
- agent-agnostic architecture
- deterministic preflight
- context control
- patch governance roadmap

## First demo

Best demo script:

```bash
premode detect --json
premode compile "Fix the build" --profile lite --json
pcodex "Fix the build"
```

Show:

- active root detection
- packet token savings
- full-text vs summary vs manifest tiers
- patch boundary
- privacy report
- strict stdin routing for Codex
