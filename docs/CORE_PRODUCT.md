# pCodex core product

pCodex is a deterministic local file-routing and context-structure layer for coding agents.

Its normal flow is:

```text
exact user prompt
-> ordered likely repository paths
-> optional primary, verification, and support labels
-> optional concise anchors
-> one compact packet for Codex
```

pCodex preserves the exact prompt. It does not summarize the task, plan the implementation, solve the coding problem, or send raw repository contents by default.

## Canonical packet

The normal packet contains only:

- the exact task once;
- ordered likely paths;
- useful optional roles;
- at most one useful optional anchor per path;
- one instruction to inspect those paths first and expand only when required.

Empty role sections and absent anchors are omitted. A path-only packet is valid. Audit data, hashes, timings, inventories, diagnostics, tuning information, experimental identifiers, and raw file contents are not model-facing packet fields.

## Normal commands

```bash
pcodex setup
pcodex status
pcodex run --dry-run "<task>"
pcodex run "<task>"
pcodex review --since-compile
pcodex off
pcodex cleanup --local-state --dry-run
pcodex doctor
```

`doctor` is optional maintenance. Start with dry-run before a real Codex launch.

## Current authority and compatibility

The current deterministic locator, repository-map reconciliation, compiler ordering, role projection, and literal/symbol anchor projection remain the compatibility-preserved production default. This is not a claim that the current ranking algorithm is strategically final.

Older packet renderers, direct compile controls, tuning, benchmarking, MCP scaffolds, and research selectors remain callable for compatibility or developer work. Existing verified tuning may still affect `on` for compatibility, but plain setup is narrow. These surfaces are intentionally absent from the primary help path.

## Guardrails

pCodex retains repository-root containment, traversal and symlink safety, narrow obvious-credential filename exclusion, compact no-content packet output, deterministic fallback, and bounded cleanup. It does not claim to control which files Codex may later open.
