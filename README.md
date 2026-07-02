# Pre-mode Router

**Pre-mode Router is a local context compiler and routing formatter for AI coding agents.**

It runs before the agent to compile a smaller, safer, repo-aware work packet, then runs after the agent to review whether the patch stayed inside the saved context contract.

```text
Before the agent:
  detect repo shape
  discover commands
  filter secrets and generated/state outputs
  build repo-map impact hints
  compile a cache-aware Packet V3
  save a review contract

After the agent:
  compare the git patch against the saved contract
  flag scope drift and risky files
  verify test evidence binding
  report working-tree readiness
```

Pre-mode may classify files and suggest verification. It must not decide implementation strategy, infer complex product intent, overrule the coding agent's reasoning, or present candidate files as the only correct files.

Codex CLI is the first supported runtime through `pcodex`, but the packet/review core is designed to be agent-agnostic.

## Current version

`v0.2.6.24 — Data Packet Boundary`

This build tightens the product boundary:

- `premode compile` / `pcodex` produce saved Packet V3 artifacts.
- `premode compile --context-only` compiles candidate context and safety boundaries without strong allowed-edit narrowing.
- `premode review-patch --since-compile` checks whether the patch stayed inside the saved context contract.
- User-facing buckets prefer `candidate_edit_files`, `read_only_support_files`, `prompt_forbidden_files`, `safety_blocked_files`, `suggested_tests`, and `suggested_commands`.
- Legacy `likely_edit_files` and `allowed_edit_files` remain as compatibility aliases. `allowed_edit_files` means saved context contract boundary, not implementation correctness.
- Adapter expansion is frozen for MVP: new ecosystem support should prefer `.premode/profile.yml` or generic structural profiles unless a major safety false-positive requires core support.

## Python requirement

Python >=3.11 is required. macOS system Python may be too old; Python 3.9 will not work because tomllib requires Python 3.11+ unless a backport dependency is added.

Use `python3.11`, `python3.12`, or an activated virtual environment for local validation.

## No-install validation

From the extracted package root, module execution works without installing console scripts:

```bash
PYTHONPATH=src python -m premode.cli detect --json
PYTHONPATH=src python -m premode.cli compile "Fix the failing test" --profile lite --cache-optimized --json
PYTHONPATH=src python -m premode.cli compile "Fix the failing test" --profile lite --cache-optimized --context-only --json
PYTHONPATH=src python -m premode.cli benchmark --profile lite --json
```

The console scripts like `premode` and `pcodex` require editable install.

## Install for local development

From the extracted package root:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
```

## Dev setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install pytest
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

## Primary workflow

```bash
premode setup
pcodex "Fix the failing test without expanding scope"
premode review-patch --since-compile
premode benchmark --profile lite
```

Use `review-patch --since-compile` for local agent workflows. It compares against the compile-time git snapshot and ignores unchanged dirty/untracked files that already existed before the agent ran.

Use `review-patch --against main` for branch/PR-style review:

```bash
premode review-patch --against main --json --out .premode/out/review_report.json
```

## Manual compile/review flow

```bash
premode compile "Fix the failing test without expanding scope" \
  --profile lite \
  --use-repo-map \
  --cache-optimized \
  --context-only \
  --save \
  --json

# agent edits repo

premode review-patch --since-compile --json
```

Saved artifacts:

```text
.premode/out/last_packet.md
.premode/out/last_packet.json
.premode/out/last_context_receipt.json
.premode/out/last_repo_map_summary.json
```

## Benchmark

```bash
premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
```

Benchmark reports:

- eligible repo tokens
- compiled packet tokens
- estimated savings percentage
- cacheable prefix tokens and percent
- dynamic suffix tokens and percent
- candidate files and related tests
- budget-exceeded prompts with reason fields
- optional review readiness with `--include-review --since-compile`

Estimated savings compares the compiled packet to the eligible repo surface. Cacheable-prefix percent measures how much of the remaining packet is positioned for provider prefix caching. Dynamic-suffix percent measures the task-specific remainder that changes per prompt.

Budget-exceeded prompts are diagnostic, not hidden. A release candidate may surface over-budget cases so you can identify policy/metadata overhead or repo-context pressure.

## Validation commands

Use this standard validation set for release-candidate testing:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite --json
premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
```

Additional product-loop validation:

```bash
premode compile "Fix the failing test without expanding scope" --profile lite --use-repo-map --cache-optimized --save --json
premode review-patch --since-compile --json
```

## Command reference

```bash
premode setup
premode detect --json
premode compile "Fix the build" --profile lite --use-repo-map --cache-optimized --context-only --save --json
pcodex "Fix the build"
premode review-patch --since-compile
premode review-patch --against main --json
premode benchmark --profile lite --json
premode stress --profile lite --json
```

Primary MVP command surface: `premode setup`, `premode detect`, `premode compile`, `pcodex`, `premode review-patch`, `premode benchmark`, and `premode stress`.

Experimental/deferred command surfaces: `premode plugin`, `premode hook`, `premode mcp-server`, and `premode lab`. They remain available for local experiments but are not part of the MVP workflow.

`premode index`, `premode map`, `premode inspect`, `premode doctor`, and `premode stats` are support/diagnostic commands.

## Packet V3

Packet V3 is cache-aware:

```text
stable prefix:
  schema, agent contract, output contract, safety rules, repo profile, command matrix

dynamic suffix:
  task, dirty files, diff/logs, candidate files/tests, context receipt, hashes, selected context
```

V2 fallback remains available:

```bash
premode compile "Fix the bug" --packet-version v2
```

## Review-patch readiness levels

```text
pass     patch stayed inside saved context contract, no unresolved evidence issue
warning  unlisted/config/CI change, missing or unbound evidence, or justification required
blocked  safety-blocked/prompt-forbidden/secret/generated-state mutation or failed bound tests
```

`review-patch` is a human review governor, not an automatic merge approval.

It does not prove the patch is correct and does not claim the candidate files were the only valid files.

## Important docs

```text
docs/REVIEW_PATCH.md
docs/BENCHMARK.md
docs/PACKET_V3.md
docs/SECURITY_MODEL.md
docs/IMPLEMENTATION_REPORT.md
CHANGELOG.md
FINAL_PACKAGE_INDEX.md
CODEX_ONE_SHOT_PROMPT_v2.7.0.md
```

## License

This project is proprietary and all rights are reserved. Access to the repository does not grant permission to use, copy, modify, distribute, commercialize, or sublicense the software. Permission must be requested from Blake Grove.
