# pCodex Product Contract

Status: authoritative for the Codex-first `0.3.0b1` private technical beta. The machine-readable companion is `premode.product.json`. Implementation and tests remain authoritative when prose is wrong.

## Product promise

pCodex accepts the exact user task, ranks likely repository paths, and returns bounded path guidance with minimal optional anchors through the canonical packet. It preserves the task exactly; it does not rewrite, summarize, decompose, or replace it. The canonical model-facing renderer is `canonical_core_v1`, with `TASK`, `LIKELY FILES`, and optional `PRIMARY`, `VERIFY`, and `SUPPORT` path sections.

pCodex is a context-selection and routing product. It is not a planner, local reasoning engine, autonomous agent, hosted service, or replacement for Codex. Unsupported task classes produce an explicit conservative fallback or exact abstention. Empty path guidance is valid.

## Beta boundary

Phase A is Codex-first `0.3.0b1` beta readiness. The supported runtime is the local Codex CLI terminal workflow. The production package is `premode-router`, requires Python 3.11 or newer, and is currently source-visible proprietary beta software. No package-registry publication, production readiness, or universal platform support is asserted.

Phase B remains the post-beta program to the full 90/100 roadmap in `docs/PRODUCT_ROADMAP.md`. It still requires production OpenClaw integration, broader platform and lifecycle proof, a frozen 10-repository/100-task held-out corpus, reproducible public evidence, and three reproducible case studies. Phase A does not weaken or replace those gates.

OpenClaw is advanced and experimental in `0.3.0b1`; it is not production-supported. Existing profiles, templates, fixtures, and research remain available but do not constitute an OpenClaw execution integration.

## Public and non-public surfaces

The normal public commands are:

```text
pcodex setup
pcodex status
pcodex run --dry-run "<task>"
pcodex run "<task>"
pcodex doctor
pcodex review --since-compile
pcodex off
pcodex cleanup --local-state --dry-run
pcodex cleanup --local-state --yes
pcodex uninstall --dry-run
pcodex uninstall --yes
premode review-patch --since-compile
```

`cleanup --local-state` is the legacy bounded cleanup surface for known repo-local generated state. `uninstall` is the receipt-driven lifecycle foundation: preview is a pure read and apply removes only state whose ownership and installed hash are proven. It is not a broad directory cleaner.

`first-run`, `on`, `tuned`, `tune`, `ui`, `compile`, `integrate codex`, MCP, plugin initialization, benchmarks, stress tools, labs, hooks, and tuning internals are advanced, internal, or research surfaces as classified in `docs/PUBLIC_SURFACES.md` and `premode.product.json`.

## Ranking authority and packet authority

`ProductionRankingProviderV1` is the sole product-facing ranking seam. Its contract and version are documented in `docs/ALGORITHM_INTEGRATION_INTERFACE.md`. It accepts:

- `exact_task`;
- `resolved_repository_context`;
- `supported_execution_options`.

It returns `routing_mode`, `primary_paths`, `verify_paths`, `support_paths`, `abstention_reason`, a content-free `decision_receipt`, and `provider_version`.

The product interface is independent of experiment candidates, observer internals, and model infrastructure. The current behavior is wrapped by `IncumbentManifestRankingProviderV1` without changing its ranking semantics. Provider output consumed by the canonical renderer contains no experiment identities. Unknown provider versions fail safely.

The canonical packet remains version `v5`, variant `tool_assisted_anchors_internal`, strategy `literal_symbol`, rendered publicly as `canonical_core_v1`. Internal anchors, diagnostics, candidate evidence, observer data, benchmark metadata, and experiment identities do not enter the model-facing packet.

## Read, write, and privacy boundary

Compilation may read repository metadata and eligible files within ignore, sensitivity, and task-root boundaries. pCodex may read repo-local configuration/state and the installed Codex executable's capabilities. It must not treat ignored secrets as model-facing context.

Normal commands do not mutate global Codex configuration. Integration writes require explicit state-changing commands. The authoritative state inventory is `premode.product.json`; `docs/PUBLIC_SURFACES.md` is its human-readable map.

Two existing lifecycle receipts have complementary, non-overlapping authority. The current source installer continues to own `install_manifest.json`, which binds and validates the isolated source-install root and is consumed by `scripts/install_pcodex_from_source.sh --uninstall`. The `pcodex.install-state.v1` receipt is the per-file authority for managed repo/Codex integration state and drives `pcodex uninstall`. Neither supersedes the other. Managed receipts contain ownership metadata and hashes, not raw prompts or model packets. Receipt and target writes are atomic, versioned, and permission-conscious. A receipt is written only after the target operation succeeds; a failed receipt write rolls back a newly created managed file. Unknown future receipt schemas are never downgraded.

An item may be automatically removed only when pCodex proves ownership, the current hash still matches the installed hash or an explicitly safe generated variant, removal is bounded to the managed root, and the state-changing action was approved. User-modified files and unrelated configuration entries are preserved. Missing, corrupt, future-schema, path-escape, symlink, or unknown-owner state fails closed with a conflict or manual-action report.

Uninstall preview reports `will_remove`, `will_restore`, `will_preserve`, `conflict`, `not_found`, `unknown_owner`, and `requires_manual_action`. Preview does not create state, refresh caches, record telemetry, update timestamps, create packet or temporary files, mutate receipts, change Codex configuration, or launch Codex/OpenClaw.

The beta executor can currently remove regular files created through the managed-state API when the receipt, separate ownership marker, owner, safe managed-root binding, and installed hash all match. Preexisting identical files are preserved. Removal of the current isolated source-install root remains under its existing manifest-validated installer command; `pcodex uninstall` does not duplicate that broad-root responsibility. Plugin marketplace/MCP entry removal, partial installs without receipts, and OpenClaw/research state are intentionally deferred.

## Explicitly unsupported claims

The beta does not promise universal task coverage, universal token or cost savings, improved patch quality across repositories, autonomous planning, production OpenClaw support, hosted-agent interception, automatic MCP invocation, automatic global configuration, public package availability, or hidden ranking behavior not backed by the algorithm lane.

## Authority map

- Product promise, scope, lifecycle: this document and `premode.product.json`.
- Surface and state classification: `premode.product.json`, summarized by `docs/PUBLIC_SURFACES.md`.
- Ranking seam: `docs/ALGORITHM_INTEGRATION_INTERFACE.md`, `src/premode/production_ranking.py`, and its JSON schema.
- Canonical packet: `src/premode/core_packet.py` plus characterization tests.
- Install-state receipt: `src/premode/managed_state.py` and `schemas/pcodex.install-state.schema.json`.
- First run: `docs/FIRST_RUN.md`.
- Claims: `docs/CLAIMS_AND_LIMITATIONS.md`.
- Version: root `pyproject.toml`, mirrored by `src/premode/__init__.py` and checked by tests.
- Historical material: `docs/history/`; never current operating authority.
