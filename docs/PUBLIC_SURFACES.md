# Public Surface and Managed-State Classification

`premode.product.json` is the authoritative machine-readable registry. This document is its reviewer-oriented map; it does not create a second registry.

## Surface classes

| Classification | Active surfaces |
| --- | --- |
| `public_core` | `premode` production package, `canonical_core_v1`, `ProductionRankingProviderV1` |
| `public_codex` | public pCodex commands, receipt-driven install/repair/uninstall lifecycle, repo-local pCodex skills/plugin assets |
| `advanced` | first-run/on/tuned/tune/ui/compile/integrate, MCP, plugin initialization, OpenClaw repository profile |
| `experimental` | OpenClaw execution-integration work |
| `research` | observer/Qwen evidence, labs, live-token harnesses, experimental candidates |
| `deprecated` | private-alpha naming, legacy installer and plugin state |
| `historical` | `docs/history/` and superseded version documents |
| `internal` | routing diagnostics, candidate evidence, caches, receipts, temporary atomic files |

## Stateful boundaries

Every stateful entry records owner, creation trigger, read/write behavior, sensitivity, schema, cleanup, repair, uninstall, conflict, and user-modification policy in `premode.product.json`.

Production-owned repo-local state includes generated `.premode` packets, receipts, indexes, mode/tuning metadata, the deterministic `.premode/pcodex-install.json` lifecycle marker, and the managed install-state receipt when created by a state-changing operation. The current isolated source install separately retains `pcodex.install_manifest.v1` as its install-root provenance/ownership authority and uses the source installer's validated `--uninstall`; it is not deprecated or replaced by the per-file receipt. Repo/user `.pcodex` configuration is user-owned and preserved by lifecycle repair/uninstall. Codex plugin files may be owned per file, but unrelated marketplace entries, unrelated MCP servers, global Codex configuration, and user-modified files are never removed by name-based scanning.

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

`pcodex install` previews and `pcodex install --apply` establishes the per-file lifecycle authority plus a reinstall-validation receipt bound to the exact authority hash. `pcodex repair --dry-run` is literal no-write; `pcodex repair --yes` restores only a missing receipt-proven generated item whose authoritative product bytes match the installed hash. A missing ownership marker additionally requires the current reinstall-validation proof. Modified or alternate filesystem objects are preserved. Repair uses no-follow directory descriptors, private staging, no-replace commit for missing leaves, file fsync, atomic authority replacement, best-effort parent fsync, and rollback if receipt completion fails.

`pcodex uninstall --dry-run` is the public removal preview. `pcodex uninstall --yes` is the bounded executor. It removes receipt-proven regular single-link files created by pCodex and emits a versioned operation receipt. A separate root/receipt ownership marker and descriptor-relative transient quarantine prevent copied receipts, broad-root deletion, symlink redirection, hard-link removal, and pathname replacement races from becoming removal authority. The uninstall receipt is an intentional-absence tombstone only while it remains bound to the exact current authority receipt hash; reinstall invalidates that tombstone by committing a new receipt. Plugin-registration surgery remains deferred until the canonical plugin workload establishes exact registration authority.

Status and doctor report a versioned lifecycle state with `READY`, `NEEDS_ACTION`, or `BLOCKED`, one recommended action, and numeric lifecycle exit-code meaning. They do not repair. Compatibility command exits remain informational; state-changing repair and uninstall return failure on blocked apply.

## Sensitivity

Repository paths, hashes bound to local roots, configuration metadata, receipts, logs, inventories, and audit data are private unless explicitly classified `public_safe`. Install-state never stores raw prompts or model packets. Public output must not expose observer data or experiment candidate identities.
