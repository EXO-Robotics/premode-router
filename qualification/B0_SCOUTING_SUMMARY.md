# B0 Scouting Summary

Status: `corpus_ready_full_scouting_started`

Two development studies coexist on this branch. Their task sources, run
counts, observers, and timing boundaries differ, so their aggregates must not
be pooled.

## Diverse public-repository corpus

The frozen initial panel completed 35 STANDARD and 35 B0 runs.

| Metric | STANDARD | B0 |
| --- | ---: | ---: |
| Objective success | 32/35 | 30/35 |
| Total tokens | 754,751 | 1,472,115 |
| Requests | 229 | 273 |
| Searches | 56 | 83 |
| Agent wall time | 1,163.57 s | 1,320.38 s |
| Unsafe/unknown-scope executions | 3 | 6 |
| Exact success | 31 | 6 |
| Success with expansion | 0 | 21 |

B0 used 95.1% more total tokens, 19.2% more requests, and 48.2% more
searches, while recording two fewer objective successes. Four task pairs were
discordant. One second repetition found one stable B0-negative cross-module
case, one stable B0-positive documentation case, and two unstable pairs that
became concordant failures. No algorithm repair or B0 change was made.

## Earlier synthetic development study

The earlier study used 30 tasks across six independently structured synthetic
repositories. Its 60-run primary panel and 72 targeted repeats produced 132
counted analytical runs; 62 superseded-validator or observer-invalid runs were
preserved and excluded. All 66 finally counted B0 runs produced native COMPLETE
receipts. Both arms completed 27/30 primary tasks. B0 used 237,822 agent tokens
versus 257,942 for STANDARD, but had a worse p95 token tail. It reproduced one
B0-positive and one B0-negative quality effect.

The earlier study identified unrelated verification-path distraction as its
eligible narrow repair cluster and lower-authority duplicate exposure as its
highest-severity single-task defect. Compiler wall time was not captured in
that study.

Both studies are diagnostic evidence, not release or marketing qualification.
