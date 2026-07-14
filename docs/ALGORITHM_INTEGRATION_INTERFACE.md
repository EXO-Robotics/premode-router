# Production Ranking Integration Interface

`ProductionRankingProviderV1` is the authoritative algorithm-agnostic seam between pCodex lifecycle/product code and whichever ranking implementation the algorithm lane promotes.

## Version and implementation

- Interface: `ProductionRankingProviderV1`
- Provider version: `production-ranking-provider.v1`
- Request schema: `pcodex.production-ranking-request.v1`
- Result schema: `pcodex.production-ranking-result.v1`
- Python contract: `src/premode/production_ranking.py`
- Process-boundary schema: `schemas/production-ranking-provider-v1.schema.json`
- Contract compatibility policy: `docs/CONTRACT_COMPATIBILITY.md`
- Current compatibility adapter: `src/premode/production_ranking_incumbent.py`

The interface module imports no observer, Qwen, lab, or candidate implementation. Provider selection can change without reopening CLI, setup, repair, uninstall, plugin, or documentation logic.

## Input

`ProductionRankingRequestV1` carries:

- `exact_task`: the exact user task as a Python string; providers must not normalize or rewrite it;
- `resolved_repository_context`: already-resolved context supplied by core product code;
- `supported_execution_options`: versioned options the product supports.

## Output

`ProductionRankingResultV1` carries:

- `routing_mode`: `narrow`, `broad`, `fallback`, or `abstain`;
- deterministic ordered `primary_paths`, `verify_paths`, and `support_paths`;
- `abstention_reason`, required only for abstention;
- a content-free `decision_receipt`;
- `provider_version` and result `schema_version`.

Empty path arrays are valid. Fallback and abstention are explicit states, not exceptions. Unknown provider/result versions and provider/result version mismatches fail safely. Public serialization never includes candidate evidence or experiment identities.

The canonical packet adapter projects only path categories and routing mode. It does not know the incumbent algorithm's internal candidate, evidence, confidence, observer, or model infrastructure.

## Compatibility provider

`IncumbentManifestRankingProviderV1` wraps the current `routing-decision.v1` behavior without changing ranking semantics. Its decision receipt contains the task hash, path counts, routing mode, and source contract only. The exact task is verified against resolved repository context before ranking.

The product lane does not choose, tune, or reinterpret ranking behavior. A later promoted provider must satisfy this interface and the existing interchangeability, deterministic serialization, exact-task, abstention, isolation, and packet-compatibility tests.

## Frozen production decision for 0.3.0b1

The sanitized authority is `release/algorithm-handoff.v1.json`, validated by `schemas/pcodex.algorithm-handoff.v1.schema.json` and `scripts/validate_algorithm_handoff.py`.

The frozen decision is `no_candidate_promoted`: pCodex retains `IncumbentManifestRankingProviderV1` at algorithm baseline `b9aede455c8d49217ef0a67e8dec0c8cf2c565a6`. This is a product-integration decision, not a claim that the incumbent passed the final release corpus. A nine-case synthetic public-safe behavior freeze runs through the real canonical compile pipeline. It covers narrow explicit-symbol guidance, broad source/test guidance, broad explicit duplicate boundaries, representative fixture shapes for each of the five declared duplicate/authority abstention classes, an explicit provider-returned fallback result, exact-task-once rendering, and canonical packet projection. These are safety/result probes, not a causal isolation study of every ambiguity mechanism. Wheel and sdist qualification recompute the same fingerprint outside the source checkout.

`fallback` is a versioned provider result accepted by `ProductionRankingProviderV1`; it is not an exception handler. The incumbent does not automatically convert provider failures to fallback. Provider failures fail closed, while low-confidence incumbent results use first-class abstention and preserve the exact task.

The handoff records only public-safe classes, aggregate receipt counts, limitations, and integrity hashes. It contains no model transcript, raw evaluation task, expected patch, hidden validator, observer database, or experimental runtime. The underlying bounded evidence supports retaining the incumbent; it does not support general token savings, cross-model qualification, universal repository support, or G6 held-out release qualification.
