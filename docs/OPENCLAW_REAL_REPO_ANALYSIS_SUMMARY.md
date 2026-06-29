# OpenClaw Real-Repo Analysis Summary

## Verdict

v2.4.2 worked as a preflight/context governor, but OpenClaw exposed a dedicated control-plane need.

The strongest finding:

> Pre-mode is not just a context compressor. It is a control-plane compression layer.

## Tested outcome

Real-repo testing showed extremely high raw repo savings, but also showed that vanilla framework detection selected nested Node/Web authority when OpenClaw-specific authority markers should have dominated.

The important practical comparison was against a realistic manual OpenClaw packet of about 74k tokens. Tuned Pre-mode packets were roughly 14k–20k tokens, or about 70%–80% smaller.

## Main failures before v2.4.3

- Nested `executor/package.json` caused Node/Web to win active detection.
- Current authority surfaces were not clearly separated from generated/historical proof artifacts.
- Bridge-write, Unreal, Blender, and task-queue mutation danger zones were only covered if user rules were manually seeded.
- Savings display could round extremely high percentages to `100.0%`, which looked too hand-wavy.

## v2.4.3 response

- Added `openclaw_control_plane` adapter.
- Made detection marker-driven so generic repos do not falsely activate it.
- Root stays at `.` when OpenClaw authority markers are present.
- Added proof-policy packet section.
- Added authority/evidence-only/danger-zone metadata.
- Added OpenClaw templates.
- Increased savings display precision.

## Next required OpenClaw improvements

- v2.5 repo map with basic control-plane and Python symbol extraction.
- v2.5 packet modes, especially `diff_only`, `logs_only`, `rules_only`, `standard`, and `deep`.
- v2.6 patch review governor for dirty-branch verification and proof-claim checks.
- Later excerpt tiers for very large authority/proof files.
