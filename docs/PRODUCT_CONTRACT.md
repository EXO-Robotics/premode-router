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
pcodex install
pcodex install --apply
pcodex setup
pcodex status
pcodex run --dry-run "<task>"
pcodex run "<task>"
pcodex doctor
pcodex review --since-compile
pcodex off
pcodex cleanup --local-state --dry-run
pcodex cleanup --local-state --yes
pcodex repair --dry-run
pcodex repair --yes
pcodex uninstall --dry-run
pcodex uninstall --yes
premode review-patch --since-compile
```

`pcodex install` previews the repository-local installation; `pcodex install --apply` creates the deterministic product-owned lifecycle marker and its authority receipt, while preserving the existing explicit user-config behavior. `cleanup --local-state` is the legacy bounded cleanup surface for known repo-local generated state. `repair` and `uninstall` are receipt-driven lifecycle surfaces: previews are pure reads, repair restores only missing known content with exact authority, and uninstall removes only state whose ownership and installed hash are proven. Neither command is a broad directory repairer or cleaner.

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

The literal meanings of advisory, preview, dry-run, and apply are defined in `docs/NO_WRITE_CONTRACT.md` and registered by `premode.product.json`. Advertised advisory, preview, and dry-run operations pass the typed `ADVISORY` policy through shared state boundaries. They do not write repository, user, integration, cache, receipt, telemetry, log, or temporary state and do not execute Codex, OpenClaw, or MCP. Missing, stale, corrupt, partial, and unknown-future state is reported without repair, refresh, or migration.

Compilation may read repository metadata and eligible files within ignore, sensitivity, and task-root boundaries. pCodex may read repo-local configuration/state and the installed Codex executable's capabilities. It must not treat ignored secrets as model-facing context.

Normal commands do not mutate global Codex configuration. Integration writes require explicit state-changing commands. The authoritative state inventory is `premode.product.json`; `docs/PUBLIC_SURFACES.md` is its human-readable map.

Two install authorities have complementary, non-overlapping scope. The current source installer continues to own `install_manifest.json`, which binds and validates the isolated source-install root and is consumed by `scripts/install_pcodex_from_source.sh --uninstall`. The `pcodex.install-state.v1` receipt is the per-file authority for managed repository/Codex integration state and drives `pcodex repair` and `pcodex uninstall`. Neither supersedes the other. The supported public lifecycle item is `.premode/pcodex-install.json`, whose exact deterministic content is part of product authority. `.pcodex/config.toml` remains user-owned and is preserved by repair and uninstall. Managed receipts contain ownership metadata and hashes, not raw prompts or model packets. Receipt and target writes are atomic, versioned, and permission-conscious. A receipt is written only after the target operation succeeds; a failed receipt write rolls back a newly created managed file. Unknown future receipt schemas are never downgraded.

An item may be automatically removed only when pCodex proves ownership, the current hash still matches the installed hash or an explicitly safe generated variant, removal is bounded to the managed root, and the state-changing action was approved. User-modified files and unrelated configuration entries are preserved. Missing, corrupt, future-schema, path-escape, symlink, or unknown-owner state fails closed with a conflict or manual-action report.

Repair preview reports `will_create`, `will_restore`, `will_replace_owned`, `will_preserve_modified`, `will_preserve_unrelated`, `conflict`, `not_found`, `unknown_owner`, `unsupported_registration`, `requires_manual_action`, and `already_healthy`. Uninstall preview reports `will_remove`, `will_restore`, `will_preserve`, `conflict`, `not_found`, `already_absent`, `unknown_owner`, `unsupported_registration`, and `requires_manual_action`. Preview does not create state, refresh caches, record telemetry, update timestamps, create packet or temporary files, mutate receipts, change Codex configuration, or launch Codex/OpenClaw.

Repair can restore a missing individually receipt-declared file only when authoritative product content hashes to the recorded installed hash. A missing ownership marker can be recreated only at the canonical receipt location when an extant exact generated item and a strict reinstall-validation receipt independently bind the same ownership ID and exact current authority-receipt hash; corrupt, stale, missing-proof, or mismatched markers fail closed. Modified files, hard links, symlinks, directories, unreadable state, unknown owners, unknown schemas, unsupported registrations, experimental state, and unknown content are preserved or blocked.

The uninstall executor can remove regular single-link files created through the managed-state API when the receipt, separate ownership marker, owner, safe managed-root binding, and installed hash all match. It uses descriptor-relative quarantine and validates identity/content before deletion. Its v2 operation receipt is an intentional-absence tombstone only while its authority hash matches the exact current install-state receipt; reinstall replaces that authority receipt, so stale uninstall evidence cannot suppress repair. Preexisting identical and user-modified files are preserved. Removal of the current isolated source-install root remains under its existing manifest-validated installer command; `pcodex uninstall` does not duplicate that broad-root responsibility. Plugin marketplace/MCP entry removal, partial installs without receipts, and OpenClaw/research state are intentionally deferred.

Crash recovery is bounded in this beta. Caught exceptions restore verified bytes before returning. A process death can leave an ownership- and receipt-hash-bound uninstall quarantine journal with per-item target mappings; status reports `interrupted_uninstall`, and later uninstall attempts fail closed without deleting or trusting that staging. Automatic crash resume is not supported: preserve the journal and inspect it manually. Repair uses atomic leaf commits and rolls back caught exceptions, but arbitrary power-loss journaling is not claimed.

The release-qualified evidence backend is macOS. There, replacement of an existing owned lifecycle receipt uses an atomic filesystem swap followed by validation of the displaced receipt and atomic swap-back on mismatch. Other platforms retain descriptor-relative validation but are not claimed to close the same final-component concurrent-swap window until separately qualified.

Status and doctor expose `READY`, `NEEDS_ACTION`, or `BLOCKED`, one recommended action, and the lifecycle exit-code meaning (`0`, `1`, or `2`) in versioned JSON. Their established command exit remains informational for compatibility. Advisory forms are literal no-write and never repair automatically.

## Explicitly unsupported claims

The beta does not promise universal task coverage, universal token or cost savings, improved patch quality across repositories, autonomous planning, production OpenClaw support, hosted-agent interception, automatic MCP invocation, automatic global configuration, public package availability, or hidden ranking behavior not backed by the algorithm lane.

## Authority map

- Product promise, scope, lifecycle: this document and `premode.product.json`.
- Surface and state classification: `premode.product.json`, summarized by `docs/PUBLIC_SURFACES.md`.
- Ranking seam: `docs/ALGORITHM_INTEGRATION_INTERFACE.md`, `src/premode/production_ranking.py`, and its JSON schema.
- Canonical packet: `src/premode/core_packet.py` plus characterization tests.
- Install-state receipt: `src/premode/managed_state.py` and `schemas/pcodex.install-state.schema.json`.
- Repair/uninstall plans and operation receipts: `src/premode/managed_state.py` and `schemas/pcodex.*-plan.schema.json`, `schemas/pcodex.*-operation.schema.json`.
- First run: `docs/FIRST_RUN.md`.
- Claims: `docs/CLAIMS_AND_LIMITATIONS.md`.
- Version: root `pyproject.toml`, mirrored by `src/premode/__init__.py` and checked by tests.
- Historical material: `docs/history/`; never current operating authority.
