# Repository Diversity Summary

The frozen corpus contains seven fresh public shallow partial clones. No active
product worktree and no previously sealed corpus was used.

| Repository ID | Primary shape | Tracked files | Packages | Max depth | Size class | Layout | Storage bytes |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: |
| `repo-001` | C/C++ | 61 | 0 | 3 | small | conventional | 156,484 |
| `repo-002` | Python | 1,086 | 37 | 7 | medium | monorepo-like | 24,938,541 |
| `repo-003` | JavaScript/TypeScript | 299 | 13 | 4 | small | monorepo | 2,429,684 |
| `repo-004` | Swift package | 270 | 17 | 5 | small | irregular | 2,730,855 |
| `repo-005` | Go control-plane monorepo | 30,831 | 97 | 15 | very large | monorepo | 319,258,838 |
| `repo-006` | legacy C/C++ | 4,378 | 18 | 5 | large | irregular/legacy | 23,801,412 |
| `repo-007` | documentation/config | 662 | 0 | 3 | medium | documentation-heavy | 12,812,811 |

Every repository is pinned to the exact clone commit, uses `--depth 1` and
`--filter=blob:none`, and retains a full checkout. Sparse checkout was rejected
because removing vendor, staging, tests, competing packages, documentation, or
legacy structure would make navigation artificially easy. Each repository
contributes 5/35 tasks (14.3%), below the 25% concentration limit.
