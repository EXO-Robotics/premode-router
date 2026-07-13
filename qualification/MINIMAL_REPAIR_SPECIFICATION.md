# Minimal repair specification

**One bounded direction:** stricter model-facing admission for low-evidence
non-PRIMARY paths.

* Target: packet-composition over-admission driven by lexical, test-path, and
  deterministic budget bonuses without independent relation or authority
  evidence. This includes uncategorized projected paths, not only the small
  VERIFY subset.
* Boundary: apply only to non-PRIMARY model-facing paths; do not alter
  candidate authority, hard denials, PRIMARY ranking, support qualification,
  route modes, packet wording, or budgets.
* Behavior: a non-PRIMARY path must retain an independent relation/authority
  signal (for example source/test, import, package ownership, explicit task
  anchor, or dirty-state relation); otherwise it remains diagnostic-only and is
  not model-facing.
* Expected effect: lower packet waste and search distraction; precision should
  rise. Required-path recall should be preserved for PRIMARY and independently
  related paths, but this must be verified rather than assumed.
* Affected classes: cross-module, test-only, and large-repository ambiguous
  tasks. Ordinary localized source tasks should be unchanged.
* Abstention: unchanged; this specification must not manufacture broadness or
  abstention.

Required tests: candidate-evidence and filter traces, packet golden hashes,
hard-denial and exact-passthrough tests, duplicate-basename and source/test
relation fixtures, and paired Qwen evaluation on the frozen public panel plus
a natural-repository holdout. Promotion gates are noninferior success, no new
unsafe outcomes, lower median complete-task cost, lower unused-path rate, and
no severe task-class regression.

This is a specification only. It was not implemented in this branch.
