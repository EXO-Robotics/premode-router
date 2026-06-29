# OpenClaw Control-Plane Hardening — v2.4.3 to v2.4.4

OpenClaw remains a supported concrete profile, but v2.4.4 generalizes its lessons into the new generic intake layer. The OpenClaw profile now sits on top of reusable traits such as proof-governed control plane, authority-surface-driven, generated-artifact-heavy, and nested-executor-present.

Use this doc as the OpenClaw-specific profile note, not as the only control-plane policy model.

---

# v2.4.3 OpenClaw / Control-Plane Hardening

## Why this patch exists

Real-repo testing against OpenClaw showed that language/framework detection is not enough for proof-governed control-plane repos.

Vanilla v2.4.2 correctly compressed huge repositories, but OpenClaw was initially detected as a nested Node/Web project because `executor/package.json` looked like the strongest framework marker. That is technically plausible, but semantically wrong for OpenClaw.

OpenClaw's true project type is closer to:

```text
openclaw_control_plane
proof_governed_control_plane
```

The important question is not only "what language is this?" It is:

```text
What files define current authority?
What files are evidence-only?
What files are dangerous to mutate?
What proof type is valid for this task?
What stale/generated surfaces should be ignored or downgraded?
```

## What v2.4.3 adds

- `openclaw_control_plane` adapter
- marker-driven OpenClaw/control-plane detection
- OpenClaw adapter outranks generic Node/Web when authority markers are present
- root stays at `.` instead of nested `executor`
- authority surface ranking
- generated/historical evidence-only patterns
- dangerous mutation zone metadata
- OpenClaw proof-policy packet section
- safe command discovery profile
- savings precision avoids false `100.0%` displays
- OpenClaw setup templates

## Detection markers

The adapter looks for combinations of:

```text
AGENTS.md
WORKFLOW.md
PROJECT/tasks.json
PROJECT/AI/worker_start/WORKER_START_HERE.md
PROJECT/state/worker_start/WORKER_STARTER_CONTEXT_V1.json
PROJECT/state/task_queue_normalized_latest.json
PROJECT/state/path_authority_latest.json
PROJECT/state/artifact_authority_latest.json
_claw_output/
tools/gamebot/
tools/symphony/
```

Plain Python/Markdown/JSON files are not enough to activate this adapter. Generic repos with `AGENTS.md` should not be misclassified as OpenClaw.

## Authority surfaces

Preferred current authority surfaces:

```text
AGENTS.md
WORKFLOW.md
PROJECT/AI/worker_start/WORKER_START_HERE.md
PROJECT/state/worker_start/WORKER_STARTER_CONTEXT_V1.json
PROJECT/state/task_queue_normalized_latest.json
PROJECT/state/path_authority_latest.json
PROJECT/state/artifact_authority_latest.json
PROJECT/AI/OUTPUT_HYGIENE_GUARDRAILS.md
ARTIFACT_STORAGE.md
EXTERNAL_ARTIFACTS_INDEX.md
```

Generated/historical surfaces are downgraded unless task-named:

```text
_claw_output/
PROJECT/state/history/
PROJECT/state/archive/
PROJECT/artifacts/generated/
logs/
proof/
proofs/
```

## Proof policy

When the control-plane adapter is active, compiled packets include:

```json
{
  "proof_policy": {
    "do_not_claim_runtime_from_static_or_browser_evidence": true,
    "do_not_claim_collision_or_input_proof_without_same_run_evidence": true,
    "do_not_mutate_bridge_unreal_or_blender_without_authorization": true,
    "do_not_mutate_project_task_queue_without_authorization": true,
    "do_not_treat_historical_proof_as_current_truth": true,
    "human_review_required_for_public_synthesis": true
  }
}
```

## Safe command profile

The OpenClaw profile can suggest safe validators such as:

```bash
pytest tests/symphony -q
pytest tests/spatial -q
python tools/gamebot/task_queue.py --help
```

It also emits dangerous command notes for bridge/UE/Blender mutation classes. These are not runnable suggestions.

## Recommended usage

Before an agent acts:

```bash
premode compile "Review the current OpenClaw task queue proof packet. Do not mutate bridge-write, Unreal, Blender, or PROJECT/tasks.json unless explicitly authorized."   --profile lite   --out .premode/out/openclaw_preflight_packet.md   --json-out .premode/out/openclaw_preflight_packet.json
```

For verification/handoff:

```bash
premode compile "Review the dirty OpenClaw changes against the requested proof-governed task. Treat _claw_output as evidence-only unless task-named. Do not claim runtime proof from static/browser evidence."   --profile standard   --out .premode/out/openclaw_verify_packet.md   --json-out .premode/out/openclaw_verify_packet.json
```

## What still belongs to v2.5/v2.6

v2.4.3 does not add:

- repo map
- impact map
- packet modes
- token ROI
- manifest grouping
- diff-only packets
- patch review governor
- local assist
- embeddings
- vector DB

Those remain in the v2.5/v2.6 roadmap.


## v2.4.5 boundary refinement

OpenClaw/control-plane packets now include semantic patch-boundary categories:

```text
authority_read_only
state_mutation_requires_explicit_authorization
evidence_only_generated_outputs
allowed_source_edits
allowed_config_if_justified
forbidden_runtime_mutation
```

This keeps authority/state/generated/runtime surfaces clearer than one broad allowed/forbidden list.
