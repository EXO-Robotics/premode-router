# Review Patch Guide

`premode review-patch` checks whether an agent patch obeyed the saved Pre-mode packet contract.

## Default local workflow

```bash
premode setup
pcodex "Fix the failing test without expanding scope"
premode review-patch --since-compile
```

`--since-compile` uses the git HEAD and dirty/untracked baseline captured when the packet was compiled. Unchanged pre-existing files are reported as informational and do not drive merge readiness.

## Branch/PR workflow

```bash
premode review-patch --against main --json --out .premode/out/review_report.json
```

Use this when you want to compare the current branch against a named base ref.

## Inputs

By default, review-patch reads:

```text
.premode/out/last_packet.json
```

You can override it:

```bash
premode review-patch --packet .premode/out/last_packet.json
```

Optional agent claims file:

```bash
premode review-patch --claims .premode/out/agent_report.md
```

## Output categories

```text
allowed_files_changed
unexpected_files_changed
forbidden_files_touched
prompt_forbidden_files_touched
secret_like_paths_touched
generated_or_state_mutation
dependency_or_build_files_changed
ci_files_changed
docs_only_changed
tests_changed
preexisting_changes
post_compile_changes
agent_candidate_changes
blocking_findings
warning_findings
info_findings
```

## Merge readiness

```text
pass     patch appears inside the saved contract
warning  human review needed for scope/evidence/config risk
blocked  forbidden, secret-like, generated/state, prompt-forbidden, or failed-test evidence found
```

`review-patch` is a review governor. It should inform human/Opus review, not replace it.

## Validation

```bash
premode compile "Fix the failing test without expanding scope" --profile lite --use-repo-map --cache-optimized --save --json
premode review-patch --since-compile --json
```
