# B0 precision/recall and root cause

The receipt-derived packet metrics are:

| metric | value | interpretation |
|---|---:|---|
| selected paths | 488 | all B0 cells |
| selected paths read | 11 | observed use, not model preference in general |
| unused-path rate | 477/488 (97.7%) | packet waste |
| required-path omissions | 34 | validator-required paths not supplied |
| omitted required paths later read | 29 | expansion after packet failure |
| tasks requiring expansion | 27/35 | B0 receipt field |

The private trace generator records candidate presence, evidence, score,
filter, category, ordering, read/edit behavior, and point of loss for every
non-glob required path. Inventory presence and candidate/ranking recall are
receipt-derived proxies: the frozen compiler does not expose a single
authoritative candidate-set identifier in this study. They must not be
interpreted as a new algorithmic metric.

The dominant failure is **over-admission followed by packet projection**, with
a separate **relational/authority recall deficit**. “Agent ignored correct
path” is a mediator in the receipts, not evidence that B0 should broaden its
packet. The synthetic marker text in every task is a confound and limits
generalization.
