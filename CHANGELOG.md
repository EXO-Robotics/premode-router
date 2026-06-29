# Changelog

## v0.2.6.6

- Local validation and macOS portability cleanup for the v2.6 release-candidate line.
- Bumped package version to `0.2.6.6`.
- Replaced the smoke test's GNU `timeout` dependency with `scripts/run_with_timeout.py`.
- Documented no-install `PYTHONPATH=src python -m premode.cli ...` validation commands.
- Clarified Python >=3.11, macOS system Python, `tomllib`, virtualenv, and pytest setup requirements.
- Added end-to-end CLI validation for `review-patch --since-compile` in a temporary Git worktree.
- Clarified benchmark language for total repo-token savings, cacheable-prefix percent, and dynamic-suffix percent.
- Did not implement `premode lint-agents`; v2.7 remains planning-only.

## v0.2.6.5

- Release-candidate cleanup for external Codex testing.
- Bumped package version to `0.2.6.5`.
- Simplified `README.md` into a user-facing quickstart and command reference.
- Simplified `IMPLEMENTATION_REPORT.md` and `FINAL_PACKAGE_INDEX.md` for current-version clarity.
- Standardized validation commands across public docs.
- Documented `premode review-patch --since-compile` as the default local workflow.
- Kept benchmark budget-exceeded cases visible as diagnostic output and compacted Packet V3 self-metadata so the built-in lite benchmark fits under budget.
- Added `CODEX_ONE_SHOT_PROMPT_v2.7.0.md` for the next Agent Config Linter slice without implementing the command yet.

## v0.2.6.4

- Release-candidate polish for benchmark output and docs.
- Added top-level `prompt_count` for quick JSON parsing.
- Added benchmark cache split percentages at per-prompt and summary levels.
- Surfaced budget-exceeded prompt details with over-budget amount and likely reason.
- Documented `premode review-patch --since-compile` as the default local workflow.

## v0.2.6.3

- Added `premode benchmark` for prompt-suite token and routing reports.
- Added optional benchmark review-loop metrics via `--include-review` and `--since-compile`.
- Added example benchmark prompt suite.
- Added release-candidate docs for benchmark usage.

## v0.2.6.2

- Added compile-time worktree baseline snapshots.
- Added `premode review-patch --since-compile`.
- Split preexisting, post-compile, and agent-candidate changes.
- Added base-ref fallback metadata.
- Split findings into blocking, warning, and info.

## v0.2.6.1

- Hardened review evidence parsing.
- Bound auto-discovered logs to `packet_sha256`.
- Added `evidence_present_but_unbound`.
- Fixed `0 failed` false failure handling.
- Classified rename/copy old paths.
- Ignored Pre-mode runtime index metadata during review.

## v0.2.6.0

- Added `premode review-patch`.
- Added structured saved `review_contract`.
- Added scope/risk classification and merge-readiness output.

## v0.2.5.7

- Added cache-aware Packet V3.
- Added `--cache-optimized`, `--packet-version`, and saved packet artifacts.
- Made `pcodex` use lite profile, repo map, Packet V3, and save-by-default behavior.

## v0.2.5.6

- Added universal stress harness covering Python, Rust, Go, TypeScript/pnpm, Swift/iOS, native C++/SCons, mixed monorepos, control-plane repos, adversarial fixtures, and tiny repos.
