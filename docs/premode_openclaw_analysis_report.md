# Pre-mode Router v2.4.2 — OpenClaw / ExampleGame Analysis Report

## Validation performed

- Package: `/mnt/data/premode-router-v2.4.2-swift-ios-hardening.zip`
- Package extracted to: `/mnt/data/premode-router`
- OpenClaw repo extracted from: `/mnt/data/openclaw_repo.zip`
- OpenClaw extracted root: `/mnt/data/openclaw_repo_extracted/openclaw_repo`

### Package validation

```text
python -m pytest -q
58 passed

bash scripts/smoke_test.sh
smoke test passed
```

### OpenClaw detection result

Vanilla v2.4.2 detects OpenClaw as a multi-project repo, but chooses the Node/Web adapter with active root `executor` because package.json markers outrank the repo-level OpenClaw control-plane structure.

Detected projects:

- Node/Web, root `executor`, confidence ~0.95–0.99
- Python, root `tools` or `PROJECT` depending index path set, confidence ~0.62
- Unity false-positive-ish marker from `frontend-r3f/src/assets`, confidence ~0.54

This is the biggest OpenClaw-specific weakness.

## Token simulation results

| Run | Active adapter/root | Eligible readable repo tokens | Packet total tokens | Context tokens | Full / summary / manifest | Estimated savings vs eligible |
|---|---:|---:|---:|---:|---:|---:|
| OpenClaw vanilla clean lite | node / executor | 67,948,617 | 20,495 | 6,250 | 3 / 20 / 3 | 99.9698% |
| OpenClaw tailored lite | node / executor | 17,570,943 | 14,312 | 6,237 | 3 / 18 / 1 | 99.9185% |
| OpenClaw explicit tailored lite | node / executor | 17,570,943 | 15,464 | 6,270 | 5 / 16 / 1 | 99.9120% |
| OpenClaw explicit tailored standard | node / executor | 17,570,943 | 19,854 | 10,970 | 5 / 5 / 0 | 99.8870% |
| OpenClaw explicit tailored pro | node / executor | 17,570,943 | 39,519 | 29,993 | 7 / 13 / 1 | 99.7751% |

Manual reference-packet comparison:

A realistic manual OpenClaw packet containing AGENTS.md, README.md, WORKFLOW.md, worker start, execution queue policy/contract, methodology lessons, the full OpenClaw prompt design system, AAA playbook, and executive summary is approximately 74,065 tokens. Compared with that manual packet:

- tailored lite: ~80.7% smaller
- explicit tailored lite: ~79.1% smaller
- explicit tailored standard: ~73.2% smaller
- explicit tailored pro: ~46.6% smaller

## Main findings

1. v2.4.2 works as a token firewall.
2. It is not yet an OpenClaw-smart router.
3. It needs an OpenClaw adapter or repo profile before it should govern serious OpenClaw Codex runs.
4. It needs v2.5 repo map / impact map / packet modes to avoid selecting stale proof artifacts and historical evidence.
5. For ExampleGame, the Swift/iOS hardening is directly useful now: Xcode root detection, long Swift path extraction, Day Report routing, and `.premode` dirty-state cleanup are exactly the issues seen in the Qwen/Opus workflow.

## Recommended next implementation sequence

1. v2.5 Patch 1: repo map foundation.
2. Add OpenClaw adapter/profile.
3. v2.5 Patch 2: impact map and compile integration.
4. v2.5 Patch 3A–3C: budget receipt, packet modes, manifest grouping, token ROI, log dedupe, packet hashes, and exploration guidance.
5. v2.6: patch review governor.
