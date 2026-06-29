# Packet V3 Guide

`PREMODE_COMPILED_PACKET_V3` is the cache-aware packet format used by `premode compile --cache-optimized` and by the default `pcodex` path.

## Why V3 exists

Prompt caching works best when repeated content appears as a stable prefix. V3 keeps stable repo/profile/schema content before prompt-specific task data.

## Structure

```text
CACHEABLE PREFIX
1. Packet schema/version
2. Stable agent contract
3. Stable output contract
4. Stable safety rules
5. Stable repo profile
6. Stable project detection / repo profile summary
7. Stable repo map summary
8. Stable command/test matrix
9. Stable patch-boundary schema / policy shape

DYNAMIC SUFFIX
10. User task
11. Dirty files
12. Current diff summary
13. Current logs/errors
14. Likely files/tests and patch boundary
15. Context receipt
16. Audit/hash metadata
17. Selected repository context
```

## Commands

```bash
premode compile "Fix the bug" --profile lite --use-repo-map --cache-optimized --save --json
premode compile "Fix the bug" --packet-version v2
```

`pcodex` defaults to Packet V3, repo map enabled, lite profile, and saved artifacts.

## Metrics

Compile JSON includes:

```text
packet_version
cacheable_prefix_tokens
dynamic_suffix_tokens
cacheable_prefix_sha256
dynamic_suffix_sha256
repo_map_sha256
compiled_packet_sha256
review_contract
pre_agent_worktree_state
```

## Saved artifacts

```text
.premode/out/last_packet.md
.premode/out/last_packet.json
.premode/out/last_context_receipt.json
.premode/out/last_repo_map_summary.json
```
