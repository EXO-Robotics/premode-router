# Implementation Report — Pre-mode Router v0.2.6.7

## Release summary

`v0.2.6.7 — Codex CLI Adapter Compatibility` is a narrow local compatibility patch for Codex CLIs that reject legacy execution flags. It detects `codex exec --help`, builds only supported adapter flags, keeps compiled packets on stdin, and reports capabilities/warnings in dry-run and execution JSON.

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
