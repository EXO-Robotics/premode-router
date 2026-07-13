# Public Surface and Managed-State Classification

`premode.product.json` is the authoritative machine-readable registry. This document is its reviewer-oriented map; it does not create a second registry.

## Surface classes

| Classification | Active surfaces |
| --- | --- |
| `public_core` | `premode` production package, `canonical_core_v1`, `ProductionRankingProviderV1` |
| `public_codex` | public pCodex commands, receipt-driven uninstall foundation, repo-local pCodex skills/plugin assets |
| `advanced` | first-run/on/tuned/tune/ui/compile/integrate, MCP, plugin initialization, OpenClaw repository profile |
| `experimental` | OpenClaw execution-integration work |
| `research` | observer/Qwen evidence, labs, live-token harnesses, experimental candidates |
| `deprecated` | private-alpha naming, legacy installer and plugin state |
| `historical` | `docs/history/` and superseded version documents |
| `internal` | routing diagnostics, candidate evidence, caches, receipts, temporary atomic files |

## Stateful boundaries

Every stateful entry records owner, creation trigger, read/write behavior, sensitivity, schema, cleanup, repair, uninstall, conflict, and user-modification policy in `premode.product.json`.

Production-owned repo-local state includes generated `.premode` packets, receipts, indexes, mode/tuning metadata, and the managed install-state receipt when created by a state-changing operation. The current isolated source install separately retains `pcodex.install_manifest.v1` as its install-root provenance/ownership authority and uses the source installer's validated `--uninstall`; it is not deprecated or replaced by the per-file receipt. Repo/user `.pcodex` configuration is preserved unless a valid receipt proves exact product ownership. Codex plugin files may be owned per file, but unrelated marketplace entries, unrelated MCP servers, global Codex configuration, and user-modified files are never removed by name-based scanning.

The following are explicitly not production-owned:

- observer databases, raw Qwen evidence, experiment runs, and algorithm promotion artifacts;
- OpenClaw runtime state, templates/fixtures created outside a receipt-proven product operation;
- legacy or partial installations whose ownership cannot be proven;
- arbitrary `.agents`, `.pcodex`, plugin, marketplace, MCP, cache, log, or temporary siblings.

## Lifecycle semantics

State-changing integrations share five lifecycle meanings:

- `preview`: pure read, no receipt or target mutation;
- `apply`: execute a bounded approved change and write a receipt only after success;
- `status`: classify current state without repair side effects;
- `repair`: restore only proven-owned, unmodified state; unknown state fails closed;
- `uninstall`: remove or restore only receipt-proven state, preserving all conflicts.

Literal advisory/preview/dry-run guarantees, the complete command classification, snapshot policy, and evidence limitations are maintained in `docs/NO_WRITE_CONTRACT.md` and registered by the manifest's `no_write_authority` object.

`pcodex uninstall --dry-run` is the public preview. `pcodex uninstall --yes` is the bounded executor. The current executor removes receipt-proven regular files created by pCodex and emits a versioned operation receipt. A separate root/receipt ownership marker and descriptor-relative transient quarantine prevent copied receipts, broad-root deletion, symlink redirection, and pathname replacement races from becoming removal authority. Plugin-registration surgery remains deferred until the canonical plugin workload establishes exact registration authority.

## Sensitivity

Repository paths, hashes bound to local roots, configuration metadata, receipts, logs, inventories, and audit data are private unless explicitly classified `public_safe`. Install-state never stores raw prompts or model packets. Public output must not expose observer data or experiment candidate identities.
