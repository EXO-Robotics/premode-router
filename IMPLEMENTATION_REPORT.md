# Implementation Report — Pre-mode Router v0.2.6.15

## Release summary

`v0.2.6.15 — In-Repo Dirty Planning/Art Downrank + Source Recovery` keeps dirty planning/art-source files from dominating lite Swift/iOS source packets and recovers safe Swift source candidates for UI/tutorial prompts.

## Product loop

```text
premode compile / pcodex
→ saved Packet V3 + review contract
→ coding agent edits repo
→ premode review-patch --since-compile
→ scope/evidence/merge-readiness report
→ premode benchmark proof
```

## Current systems

- Repo detection and universal intake traits.
- Command discovery and package-manager detection.
- Repo map and impact hints.
- Secret suppression and generated/state/proof classification.
- Cache-aware `PREMODE_COMPILED_PACKET_V3`.
- Codex wrapper defaults: `lite`, repo map enabled, cache optimized, saved packet artifacts.
- Structured `review_contract` in saved compile JSON.
- Baseline-aware `review-patch --since-compile`.
- Packet-bound test evidence binding.
- Benchmark prompt suites and token-savings reports.
- Universal stress harness across 11 fixture shapes.

## v0.2.6.15 changes

- Bumped package version to `0.2.6.15`.
- Downranked dirty files under in-repo planning/art-source areas such as `Docs/Planning_Bundles`, `ArtSource`, `NPC_Models`, `System_Bibles`, `PATCH_NOTES*`, and app-reality alignment docs for Swift/iOS source prompts.
- Added Swift/iOS source recovery hints for safe Swift files under Views, ViewModels, Models, Systems, Features, and Screens.
- Added routing diagnostics for source recovery attempts, safe candidate counts, filtered counts, and filtered reasons.

## v0.2.6.14 changes

- Bumped package version to `0.2.6.14`.
- Changed compile stdout with both `--out` and `--json-out` to emit a compact receipt unless `--show-raw` is requested.
- Added semantic impact buckets for editable likely files, read-only support files, prompt-forbidden files, related tests, and verification order.
- Tightened OpenClaw/control-plane allowed edits when a prompt names one specific source file without asking for a broader refactor.
- Added phase and duration diagnostics to the smoke script.

## v0.2.6.13 changes

- Bumped package version to `0.2.6.13`.
- Added repo-map routing filters for `_external_references`, dependency folders, generated/proof/state/runtime outputs, build outputs, binaries, and caches.
- Applied the filter to `likely_files`, `related_tests`, dependency/dependent slices, and verification-order generation.
- Added compact routing diagnostics when boundary filtering removes candidate paths or the prompt explicitly says to avoid external/generated/build/cache paths.
- Mirrored the same boundary in selected-context routing while preserving explicit prompt-mentioned paths.

## v0.2.6.12 changes

- Bumped package version to `0.2.6.12`.
- Added a child-repo context boundary for selected child `task_root` values.
- Downgraded dirty parent authority/persona/guidance files to inherited summaries or manifest-only entries unless explicitly prompt-mentioned.
- Added packet evidence for inherited parent authority count, sample, and selected child root.
- Added a focused messy-parent OpenClaw fixture covering dirty parent guidance, sibling iOS repo, and external package noise.

## v0.2.6.11 changes

- Bumped package version to `0.2.6.11`.
- Added prompt-affinity scoring for `active_root_candidates` using root names and Unreal/OpenClaw, Goldpine/iOS/Swift/Xcode, and Node/web markers.
- Added candidate diagnostics for markers, marker bonuses, prompt-affinity bonuses, ignored/reference penalties, and direct-child ambiguity.
- Preserved v2.6.10 protection against `_external_references` and dependency package roots outranking visible child repos.
- Added lite authority-surface compaction so dirty runbook/history/memory/superpowers/handoff docs do not consume full-text context for source/gameplay prompts.
- Added focused tests for OpenClaw vs Goldpine prompt routing, ambiguous direct child roots, and OpenClaw-style dirty authority budget compaction.

## v0.2.6.10 changes

- Bumped package version to `0.2.6.10`.
- Added direct child `.git` root discovery before nested package-root promotion.
- Added `active_root_candidates` diagnostics with candidate score, penalty, source, and reasons.
- Strongly penalized `_external_references`, `node_modules`, dependency/vendor, build, generated, proof, and runtime artifact roots.
- Added a focused messy-parent fixture covering `openclaw_repo/.git`, `_external_references/.../package.json`, and `node_modules/.../package.json`.

## v0.2.6.9 changes

- Bumped package version to `0.2.6.9`.
- Added packet-facing dirty-file summaries by category/count/sample instead of raw large dirty lists.
- Added compact packet summaries for redactions, trust-boundary warnings, and current diff samples.
- Penalized deeply nested external/generated/proof/state/build-cache project roots during detection.
- Let OpenClaw authority markers choose their containing child repo when launched from a messy parent directory.
- Added focused tests for OpenClaw-style dirty metadata compaction and messy-parent nested root selection.

## v0.2.6.7 changes

- Bumped package version to `0.2.6.7`.
- Added Codex CLI capability detection from `codex exec --help`.
- Prefer `--approval-mode on-request`, fall back to `--ask-for-approval on-request`, or omit approval flags with warnings.
- Fall back from `-C` to `--cd`, then subprocess `cwd`, depending on supported flags.
- Omit unsupported optional Codex flags such as `--sandbox`, `--ephemeral`, and `--output-last-message` with JSON warnings.
- Added `codex_capabilities` and `codex_warnings` to dry-run and execution JSON.
- Added focused compatibility tests for approval, cwd, output, stdin sentinel, and raw prompt privacy.

## v0.2.6.6 changes

- Bumped package version to `0.2.6.6`.
- Replaced the smoke test's GNU `timeout` dependency with `scripts/run_with_timeout.py`.
- Added no-install `PYTHONPATH=src python -m premode.cli ...` validation commands.
- Clarified Python >=3.11, macOS system Python, `tomllib`, and pytest setup requirements.
- Added CLI end-to-end `review-patch --since-compile` validation in a temporary Git worktree.
- Clarified benchmark KPI language for total repo-token savings, cacheable-prefix percent, and dynamic-suffix percent.

## v2.6.x rollup

```text
v2.6.0 — Patch Review Governor
v2.6.1 — Review Evidence Hardening
v2.6.2 — Review Baseline Hardening
v2.6.3 — Benchmark + Release Candidate
v2.6.4 — Release Candidate Polish
v2.6.5 — Release Candidate Cleanup
v2.6.6 — Local Validation + macOS Portability Cleanup
v2.6.7 — Codex CLI Adapter Compatibility
v2.6.9 — Metadata Budget Compaction + Nested Root Selection
v2.6.10 — Direct Child Git Root Discovery
v2.6.11 — Prompt-Aware Repo Selection + Authority Surface Budget
v2.6.12 — Child Repo Context Boundary
v2.6.13 — Ignore-Boundary Routing Enforcement
v2.6.14 — Validation Reliability + Semantic Impact Buckets
v2.6.15 — In-Repo Dirty Planning/Art Downrank + Source Recovery
```

## Standard validation

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite --json
premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
```

No-install validation:

```bash
PYTHONPATH=src python -m premode.cli detect --json
PYTHONPATH=src python -m premode.cli benchmark --profile lite --json
```

Release-candidate workflow validation:

```bash
premode compile "Fix the failing test without expanding scope" --profile lite --use-repo-map --cache-optimized --save --json
premode review-patch --since-compile --json
```

## Known release-candidate note

`premode benchmark` may surface over-budget lite prompts. That is intentional diagnostic output. Over-budget entries include prompt name, packet tokens, budget, overage, and likely reason. Do not hide these failures; use them to tune policy metadata or selected context.

## Next recommended patch

`v2.7.0 — Agent Config Linter`

Planned command surface:

```bash
premode lint-agents
premode lint-agents --json
premode lint-agents --fix-plan
premode lint-agents --out .premode/out/agent_lint_report.json
```

v2.7 should scan agent guidance files for stale commands, conflicting instructions, unsafe guidance, prompt-injection-like text, context bloat, duplicate rules, tool-specific leakage, missing verification guidance, over-broad edit permissions, and secret-handling gaps. It should not mutate files in v2.7.0.
