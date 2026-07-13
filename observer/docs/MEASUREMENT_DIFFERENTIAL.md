# Observer measurement differential

The observer records recommendation safety, packet quality, agent behavior,
safety attribution, run outcome, and measurement status as separate versioned
contracts. A model validation failure cannot make a packet unsafe, and an
ordinary wrong path remains a packet-quality defect rather than a safety defect.

Recommendation safety is derived from the exact packet path projection through
the production candidate-admissibility policy. Missing packet hashes, missing
filesystem resolution, unsupported schemas, and contradictory fields fail
closed. Legacy `unsafe` remains present only as superseded telemetry.

Safety-critical Git reads use an isolated configuration and reject repository
execution settings, nested attribute drivers, redirected metadata, and
unreadable control files. Filesystem checks reject traversal, escapes, aliases
to protected targets, unusual objects, and multiply-linked regular files.

Historical reconstruction never mutates its source and emits only a source hash
plus corrected derived fields. Legacy field presence is not treated as proof of
packet bytes or an execution-time filesystem snapshot, so incomplete historical
evidence remains indeterminate. Public summaries contain bounded aggregate
status counts only; prompts, transcripts, repository paths, and raw evidence are
excluded.

Promotion requires a compatible complete receipt, a recommendation-safe packet,
complete recommendation and quality evidence, non-causal safety attribution,
safe execution, and scope adherence.
