# B0 path-lifecycle forensic report

Status: `root_cause_identified_multiple_mechanisms`

This is a diagnosis-only report. B0, ranking, thresholds, packet wording, and
the product branch were not changed. The 35-task receipt set is frozen at
scouting commit `58a1b1fa931a36d6bf42d21d05a441a41669b7f6`.

## Finding

The public-repository regression has two interacting mechanisms:

1. **Lexical candidate over-admission and packet composition.** The packet
   supplied 488 paths, but only 11 were read (477/488 unused). Deterministic
   keyword, adapter, test-path, and source-budget bonuses promoted many
   unrelated paths. The clearest trace had 21 selected paths, 14 unrelated
   test-data files, no required ownership file, eight reads, maximum turns,
   and 435,254 tokens.
2. **Low-recall relational/authority discovery.** 34 required paths were
   absent from the packet in the counted B0 receipts; 29 were later found by
   the agent. Cross-module B0 success was 4/7 versus STANDARD 6/7, and test-only
   success was 5/7 versus 6/7. This is consistent with missing relational or
   authority paths, but the evidence does not justify changing relation logic
   in this workload.

The observational/mechanistic confidence is high for packet waste and lexical
over-admission, and medium for the relational mechanism; no intervention was
run, so this is not a causal estimate. The 35 prompts use synthetic marker
suffixes in repository text, so the magnitude is benchmark-specific and must
not be generalized to natural repositories.

## Aggregate evidence

| arm | success | tokens | requests | searches | selected/read | wall time |
|---|---:|---:|---:|---:|---:|---:|
| STANDARD | 32/35 | 754,751 | 229 | 56 | n/a | 1,163.570s |
| B0 | 30/35 | 1,472,115 | 273 | 83 | 488/11 | 1,320.378s |

B0 omitted at least one required path in 27/35 cells. The counted receipts
were complete, fixture resets succeeded, and both arms used the frozen model,
validator, and task schedule.

## Root-cause classification

| mechanism | evidence | confidence |
|---|---|---|
| filtering/admission: weak lexical candidates admitted | 477 unused paths; repeated keyword/test/budget evidence; broad packets | high |
| packet composition: low-value paths consume projected packet | 488 selected, 14–114 per task, almost none read | high |
| candidate generation/authority discovery loss | 34 required omissions; 29 discovered later; cross-module/test-only regression | medium |
| agent interaction | later search and independent discovery after incomplete packets | high as mediator, not product root cause alone |

## Scope boundary

The result is not a release promotion and does not authorize a B1. No Qwen
confirmation runs were added: the existing 70 native-complete receipts already
establish the packet-use and cost pattern, while new model runs would not
separate the benchmark marker confound from a product mechanism.
