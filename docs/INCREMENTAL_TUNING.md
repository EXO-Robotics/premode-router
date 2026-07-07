# Incremental Tuning And Staleness

This document describes the intended repo-local staleness model for pCodex tuning. It is a design/operability guide, not a claim that all future incremental commands are implemented.

## Purpose

Incremental tuning should let pCodex decide whether existing `.premode/tuning/` artifacts are still safe to use after ordinary repo changes. It should avoid rerunning full tuning when source changes are irrelevant, while failing closed when a profile may be stale.

## Current Behavior

Current supported commands are:

```bash
pcodex tune
pcodex tune --validate
pcodex tune --verify
pcodex status --json
```

`pcodex on` uses verified tuning only when the profile is valid and `VERIFY_RESULTS.json` has verdict `PASS`. Otherwise it falls back to generalized `literal_symbol`.

`pcodex tuned` is strict. It requires a valid profile and `VERIFY_RESULTS.json` verdict `PASS`; missing, invalid, or unverified tuning fails clearly.

## Staleness Signals

Allowed staleness inputs are content-free or locally derived:

- tuning profile hash
- verifier-results hash
- repo HEAD
- branch name
- path-taxonomy file hash
- source/test map hash
- prompt-route file hash
- effective state
- validation/verifier verdict
- timestamps
- status reasons

Do not store prompt text, source snippets, secrets, file contents, or expanded diagnostics in control-plane state.

## Staleness Categories

- `clean`: profile and verifier artifacts match the latest accepted local state.
- `docs_only_change`: documentation paths changed; tuning may need verification only.
- `tests_only_change`: tests changed without source graph changes.
- `source_graph_change`: source files, imports, or source/test relationships changed.
- `package_config_change`: package metadata, command config, or dependency shape changed.
- `branch_or_head_change`: branch or HEAD differs from the last accepted lockfile.
- `large_change`: many files changed or repo shape changed enough that partial refresh is unsafe.
- `unknown_change`: change classification is unavailable or ambiguous.

Supporting raw reasons may include `missing`, `invalid`, `unverified`, `verify_needs_adjustment`, `verify_fail`, `profile_hash_changed`, or `verify_hash_changed`.

## Recommended Actions

- `no_action`: keep current verified tuning.
- `verify_only`: rerun verification without regenerating static artifacts.
- `light_refresh`: refresh low-risk generated metadata and verify.
- `source_test_map_refresh`: refresh source/test relationships and verify.
- `command_profile_refresh`: refresh command/package profile metadata and verify.
- `partial_retune`: regenerate affected tuning artifacts and verify.
- `full_retune`: rerun full tuning generation, validation, and verification.

## Current Fallback Policy

For `on` mode:

- clean verified tuning may resolve to `ON_TUNED_VERIFIED`
- missing, invalid, stale, or non-PASS tuning resolves to `ON_GENERALIZED`
- invalid pCodex state resolves to `SAFE_PASSTHROUGH`

For `tuned` mode:

- clean verified tuning resolves to `TUNED_STRICT`
- missing, invalid, stale, or non-PASS tuning fails before a real Codex run

## Planned Incremental Commands

The following commands are planned/future unless implemented in the current CLI:

```bash
pcodex tune --explain-stale
pcodex tune --verify-only
pcodex tune --incremental
pcodex tune --full
```

Future commands should update only generated tuning artifacts under `.premode/tuning/`, then run validation and verification before enabling tuned behavior.

## Lockfile Interaction

`.premode/lcc.lock.json` records hashes and effective-state metadata for the local control plane. It is generated/runtime state and must remain ignored.

The lockfile can help identify stale tuning, but it is not a source of model-facing context and is not a package registry or deployment manifest.

## Cache Manifest Interaction

`.premode/out/cache_manifest.json` records content-free prefix/cache metadata for local observability. It may help compare whether a repo/mode/profile combination is a cache candidate. It does not guarantee provider prompt caching or token savings.

## Safe Actions

Safe default actions:

- run `pcodex status --json`
- run `pcodex tune --validate`
- run `pcodex tune --verify`
- stay in `pcodex on` generalized mode when stale
- use `pcodex run --dry-run "<task>"` before real execution

Avoid destructive cleanup unless explicitly requested. Prefer moving generated tuning artifacts to a backup location if their provenance is unclear.

## Validation

Before relying on tuned behavior after any incremental update:

```bash
pcodex tune --validate
pcodex tune --verify
pcodex status --json
pcodex run --dry-run "<representative task>"
```

Benchmarking can inform the decision:

```bash
premode benchmark --profile lite --json
premode stress --profile lite --json
```

Benchmarking is measurement; tuning selects repo-local behavior; validation proves the selected behavior remains safe enough for the local flow.
