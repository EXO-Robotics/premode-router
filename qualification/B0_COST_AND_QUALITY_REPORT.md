# B0 cost and quality

Primary-panel estimates use exactly one valid result per task and arm. Targeted repeats are not pooled into aggregate effect estimates.

| Metric | B0 | STANDARD | B0 minus STANDARD |
|---|---:|---:|---:|
| Task success | 27/30 | 27/30 | 0 |
| Validation pass | 27/30 | 28/30 | -1 |
| Input tokens | 222,532 | 246,103 | -23,571 |
| Output tokens | 15,290 | 11,839 | +3,451 |
| Agent tokens | 237,822 | 257,942 | -20,120 |
| Requests | 179 | 211 | -32 |
| File reads | 128 | 143 | -15 |
| Unique file reads | 89 | 120 | -31 |
| Repeated reads | 39 | 23 | +16 |
| Searches | 20 | 29 | -9 |
| Agent execution wall time | 775.0 s | 795.4 s | -20.4 s |
| Scope violations | 1 | 0 | +1 |
| Recommendation-safety failures | 0 | 0 | 0 |

Median agent tokens were 7,180 for B0 and 8,232 for STANDARD. B0's p95 was worse: 13,654 versus 12,623. Failed-task cost was 35,876 tokens for B0 and 37,213 for STANDARD. The headline is therefore lower central exploration cost with a meaningful B0 tail and one repeated scope regression.

B0 compilation occurred before the recorded timer. Wall time is agent execution, not complete-task wall time; this is the study's remaining measurement debt.

Task classifications:

| Classification | Tasks |
|---|---:|
| `b0_quality_and_efficiency_win` | 1 |
| `b0_efficiency_win` | 10 |
| `equivalent` | 11 |
| `standard_efficiency_win` | 5 |
| `b0_regression` | 1 |
| `agent_only_failure` | 2 |
| all other categories | 0 |
