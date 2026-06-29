# Market Positioning — Pre-mode Router

## Direct verdict

There is a market, but the product should not be positioned as another coding agent.

The strongest category is:

> A universal preflight, context-control, and patch-governance layer for AI coding agents.

The coding agents do the work. Pre-mode makes sure the work starts with the right context, stays in scope, uses the right commands, avoids secrets, and produces something auditable.

## Core positioning

Use:

> Pre-mode is a local-first deterministic preflight and patch-governor for AI coding agents.

Then specify:

> Codex CLI is the first supported runtime.

## Problem

AI coding agents are powerful, but they commonly:

- over-read repositories
- waste tokens on irrelevant files
- run from the wrong directory
- hallucinate commands
- expose secrets
- chase cascaded errors
- modify files outside the requested scope
- produce patches that are hard to audit

## Solution

Before the agent:

```text
detect project
discover commands
filter secrets
compress context
build evidence packet
define patch boundary
```

After the agent, future roadmap:

```text
compare patch to boundary
verify test claims
flag scope creep
produce audit report
```

## Target users

Early users:

- Codex CLI power users
- Claude Code users with large repos
- Cursor/Cline/OpenCode users worried about context spend
- solo developers using multiple agents
- small teams without AI governance tooling
- open-source maintainers reviewing agent PRs

Later users:

- teams with multiple AI coding tools
- teams with privacy/security requirements
- teams with high token spend
- teams with monorepos
- teams reviewing many AI-generated patches

## Differentiation

| Product | What it does | Where Pre-mode fits |
|---|---|---|
| Codex CLI | coding agent | Pre-mode prepares smaller, safer packets before Codex runs |
| Claude Code | terminal coding agent | Pre-mode can provide evidence packets and patch review |
| Cursor/Cline/OpenCode | agent runtimes / IDE agents | Pre-mode can provide neutral context control |
| Aider | coding tool with repo map | Pre-mode can be more governance and agent-agnostic focused |
| Sourcegraph/Amp | enterprise code intelligence/agent platform | Pre-mode can be local-first, lightweight, CLI-native |

## Token-spend line

> Pre-mode does not make the model cheaper by being smaller. It makes the task cheaper by making the model read less, explore less, rerun less, and review less.

## Public MVP story

```bash
pipx install premode-router
cd my-repo
premode setup
pcodex "Fix the failing tests"
```

Expected visible value:

```text
Detected: Python project at .
Commands: pytest
Context: 2 full-text files, 6 summaries, 42 manifest files
Estimated context savings: 81%
Patch boundary: 4 allowed edit files
Privacy: 3 files blocked, 0 secrets leaked
```

Future post-agent value:

```bash
premode review-patch
```

```text
Scope: PASS
Tests: NOT VERIFIED
Unexpected files: none
Risk: medium
Recommended next step: run pytest
```

## v2.4.3 OpenClaw / control-plane hardening

Real-repo testing against OpenClaw showed that language/framework detection is not enough for proof-governed control-plane repositories.

v2.4.3 adds an `openclaw_control_plane` adapter that detects OpenClaw-style authority markers, keeps the active root at `.`, outranks nested Node/Web executor folders, ranks current authority surfaces ahead of generated/historical artifacts, and emits a proof-policy packet section.

This keeps the product direction general: OpenClaw is the first concrete profile for a broader `proof_governed_control_plane` / `authority_surface_ranking` mode.

New docs/templates:

```text
docs/OPENCLAW_CONTROL_PLANE_HARDENING.md
docs/OPENCLAW_REAL_REPO_ANALYSIS_SUMMARY.md
docs/templates/openclaw/.premodeignore
docs/templates/openclaw/rules.md
docs/templates/openclaw/project_memory.md
docs/templates/openclaw/commands.json
```

v2.4.3 also increases savings display precision so very high savings do not misleadingly round to `100.0%`.
