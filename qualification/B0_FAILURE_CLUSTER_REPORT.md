# B0 failure clusters

## 1. Unrelated verification-path distraction

Classification: `irrelevant_path_distracted_agent`

- 3 unique tasks
- 2 confirmed-harm repository layouts
- 3 task classes
- high causal confidence for read/token cost

Causal chain: B0 added a verification path without an independent source-test, import, symbol, or task relation; the agent read that path in repeated cells; and median paired cost increased. Both arms preserved validated quality in two tasks. The third had one B0 completion flip, which is not treated as a reproducible quality regression.

This is the selected future repair priority because it clears the multi-task rule and has a narrow eligibility boundary.

## 2. Lower-authority duplicate exposure

Classification: `wrong_duplicate_authority`

- 1 confirmed defect task
- 1 confirmed-harm repository layout; related non-defect exposures span 2 layouts
- 1 reproducible task-quality regression
- high causal confidence

Causal chain: B0 changed the model-visible file guidance, the guidance included both the authoritative source and a lower-authority duplicate, the agent read and edited both, and scope validation failed. STANDARD found and edited only the authoritative source in all three repetitions.

Two related tasks exposed the same structural weakness without failing. Their agents read but did not mutate the unnecessary alternative. Those observations do not count as additional reproducible defects.

## 3. Other excess exploration

Four tasks were consistently cheaper under STANDARD. Three form the selected verification-distraction cluster. In the fourth, B0 supplied only the correct path and the agent nevertheless searched and reread it; that case is classified as model behavior, not a path-selection defect.

## Non-algorithm failures

Two tasks failed in both arms by exhausting the turn budget without mutation. One generation-related task failed 0/3 in both arms. No stable B0-specific causal chain was established for these failures.

The most important inconclusive cost area is one exact-abstention task: both arms succeeded 3/3, STANDARD was cheaper by 2,553 median paired tokens, and the arm advantage reversed once. With identical model input, no routing mechanism can be assigned.

The initial observer changed after the first panel. All 34 surviving initial arm cells were excluded and rerun; no reconstructed receipt remains counted. Compiler wall time was not captured.
