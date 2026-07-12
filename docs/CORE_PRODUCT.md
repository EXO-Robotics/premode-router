# pCodex core product

pCodex is a deterministic local file-routing and context-structure layer for coding agents.

Its normal flow is:

```text
exact user prompt
-> normalized repository inventory
-> candidate-admissibility policy
-> ordered likely repository paths with out-of-band provenance
-> deterministic routing decision (narrow, broad, or abstain)
-> optional primary, verification, and support labels
-> optional concise anchors
-> one compact packet for Codex, or exact task passthrough on abstention
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

When routing abstains, the model receives the exact original task bytes and no
pCodex instruction, path, role, reason, confidence, or routing label. Observer
receipts remain out of band.

## Release authority

The release-intended product branch is `Release-Foundation`, established from
the approved production baseline
`7036f4c9ed5d5d6794938e921788e3ca611d0537`. The separate
`Observer-Development` branch remains the measurement and controlled-model
system; observer runtime code is not part of normal product imports. The target
technical-preview version is `0.3.0b1`.

This file is the canonical product contract. Benchmark reports, lab notes,
legacy packet documentation, and historical private-alpha instructions are
evidence or compatibility references rather than release authority.

## Candidate and routing contracts

Every candidate is normalized and root-resolved before scoring. Hard denials
for outside-root paths, symlink escapes, obvious credential paths, and pCodex
runtime state override explicit mentions and generated-file exceptions. Ignored
paths may be admitted only by the narrow explicit-path rule. Generated intent
may relax generated/vendor suppression but never a hard denial. Candidate
provenance, policy rules, confidence, ambiguity, and reasons are receipt-only.

`NARROW` emits a small primary/verification set and at most one strongly
qualified support path. `BROAD` emits a bounded wider set and at most three
strong or qualified support paths. `ABSTAIN` emits no packet and preserves
ordinary agent exploration at the model boundary. Weak support is never
model-facing. Packet metadata and rendered model-facing paths must agree.

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

The current deterministic locator, repository-map reconciliation, compiler ordering, role projection, and built-in literal/symbol ranker remain the compatibility-preserved production default. The normal core artifact contains this supported default ranker without an optional runtime dependency. This is not a claim that the current ranking algorithm is strategically final.

Older packet renderers, direct compile controls, tuning, benchmarking, MCP scaffolds, and research selectors remain callable for compatibility or developer work. Existing verified tuning may still affect `on` for compatibility, but plain setup is narrow. These surfaces are intentionally absent from the primary help path.

## Guardrails

pCodex retains repository-root containment, traversal and symlink safety, narrow obvious-credential filename exclusion, compact no-content packet output, deterministic fallback, and bounded cleanup. It does not claim to control which files Codex may later open.
