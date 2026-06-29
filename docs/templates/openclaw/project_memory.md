# OpenClaw Project Memory Template

## Current Active Work

Fill in current lane, seam, task ID, proof goal, and expected artifact.

## Current Authority Surfaces

- AGENTS.md
- WORKFLOW.md
- PROJECT/AI/worker_start/WORKER_START_HERE.md
- PROJECT/state/worker_start/WORKER_STARTER_CONTEXT_V1.json
- PROJECT/state/task_queue_normalized_latest.json
- PROJECT/state/path_authority_latest.json
- PROJECT/state/artifact_authority_latest.json

## Evidence Policy

- Runtime proof requires runtime evidence.
- Collision/input proof requires same-run collision/input evidence.
- Browser/static/editor evidence cannot prove runtime behavior alone.
- Historical proof is not current truth unless explicitly referenced by the active task.

## Dangerous Mutation Zones

- bridge-write commands
- Unreal/Blender mutation commands
- PROJECT/tasks.json
- queue/path/artifact authority state files
- _claw_output generated bundles

## Do Not Touch Unless Asked

- generated proof bundles
- public synthesis packets
- task queue authority files
- bridge/UE/Blender mutation surfaces
