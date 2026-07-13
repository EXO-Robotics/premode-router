# Corpus Setup Summary

Classification: `corpus_ready_full_scouting_started`

The private local scouting corpus is ready. It contains seven pinned public
repositories, 35 frozen g2 development-scouting tasks, and 35 validators that
each passed clean-correct, mutated-failing, incomplete-repair, and patch-apply
self-tests. The earlier g1 fixture generation was rejected before the full
panel after smoke exposed a marker-consistency defect; g2 uses new task IDs.

The final setup smoke completed 8/8 paired runs with identical arm starts,
8/8 validator passes, 8/8 native COMPLETE receipts, zero unsafe outcomes, and
verified disposable-fixture cleanup. The frozen initial panel then completed
70/70 runs. One second repetition covered the four discordant task pairs.

No B0 ranking, packet, threshold, eligibility, fallback, or abstention behavior
was modified. No private repository code, private remote, prompt, transcript,
model output, validator implementation, absolute local path, active worktree,
dependency cache, model file, or corpus clone is tracked in this branch.
