# AI Start Here

This is the AI-facing entrypoint for the pCodex product branch. Read `AGENTS.md`, `premode.ai.json`, `docs/PRODUCT_CONTRACT.md`, and `docs/GETTING_STARTED.md` before using historical or research material.

## Product boundary

pCodex is a local deterministic repository-context router. It preserves the exact task, ranks likely paths, and produces one canonical packet. It is not a planner, autonomous agent, hosted service, or replacement for Codex.

The repository is source-visible proprietary software. Do not call it open source. Do not claim public package availability, universal savings, automatic interception, production OpenClaw support, or complete MCP conformance.

## Canonical product surfaces

- Product authority: `docs/PRODUCT_CONTRACT.md` and `premode.product.json`
- Getting started: `docs/GETTING_STARTED.md`
- Codex: `docs/CODEX_INTEGRATION.md`
- Privacy and safety: `docs/PRIVACY_AND_SAFETY.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Limitations: `docs/KNOWN_LIMITATIONS.md`
- Migration, rollback, uninstall: `docs/MIGRATION.md`, `docs/ROLLBACK.md`, `docs/UNINSTALL.md`
- OpenClaw status: `docs/OPENCLAW_INTEGRATION.md`
- 90/100 gates: `docs/ROADMAP_TO_90.md` and `docs/PRODUCT_READINESS_GATE_LEDGER.md`

Documents under `docs/history/`, lab reports, pasteable bootstrap prompts, tuning guides, private-alpha plans, and observer/evaluation material are not product operating authority.

## Safe first inspection

From the target repository:

```console
pcodex doctor --advisory --json
pcodex status --advisory --json
pcodex run --dry-run "Inspect the requested change"
```

These commands are literal no-write surfaces. Do not substitute a stateful command when the user asked for advisory, preview, dry-run, report-only, or review-only work.

## Canonical Codex plugin

`plugins/pcodex` is the only supported plugin content source. Preview before writing:

```console
pcodex integrate codex --dry-run
pcodex integrate codex --write
pcodex integrate codex --status
```

MCP is absent by default. Legacy `.agents/skills/pcodex*` and `premode-router` trees are migration inputs, not current authority. Do not create target-local replacement skills, edit global Codex configuration, or delete legacy state without receipt-proven ownership.

## Development rules

- Do not modify ranking weights, eligibility, selected-path behavior, or packet wording unless the algorithm lane explicitly authorizes it.
- Production code must not import observer, Qwen, lab, live-token, or evaluation harness modules.
- Persisted and cross-process schemas are versioned and fail closed on unknown versions.
- Repair and uninstall preserve user-modified, unrelated, malformed, future-schema, and uncertain state.
- Commit, push, publish, tag, release, merge, and promotion are separate authorities.
