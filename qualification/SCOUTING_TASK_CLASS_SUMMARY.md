# Scouting Task Class Summary

The frozen g2 task corpus contains 35 tasks: five per repository and seven per
class.

| Task class | Tasks | Initial paired runs | Initial successes | STANDARD | B0 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Localized source repair | 7 | 14 | 14 | 7/7 | 7/7 |
| Test-only repair | 7 | 14 | 11 | 6/7 | 5/7 |
| Configuration/tooling repair | 7 | 14 | 14 | 7/7 | 7/7 |
| Documentation tied to implementation | 7 | 14 | 13 | 6/7 | 7/7 |
| Cross-module change | 7 | 14 | 10 | 6/7 | 4/7 |

All validators are hidden from the model and enforce exact known-good hashes
plus forbidden-change checks. Mutation patches and expected paths remain in the
private corpus. The model sees only the exact natural-language task and its
disposable mutated repository.
