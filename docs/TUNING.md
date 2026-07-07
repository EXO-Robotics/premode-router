# Tuning

This is the canonical tuning guide for AI operators. It explains how to compare, select, validate, and safely commit repo-local Pre-mode/pCodex tuning behavior.

## 1. Purpose

Tuning helps choose repo-local defaults for Pre-mode context selection. A tuned profile can make pCodex use repo-specific path taxonomy, vocabulary, source/test maps, phrase routes, hotspots, suppressions, and literal-symbol weights.

Tuning is useful only when the selected behavior preserves task fidelity, expected file/test coverage, packet boundaries, and review safety.

## 2. What tuning is not

Tuning is not:

- a live Codex task
- a guarantee of token savings
- a guarantee of better patches
- a license or distribution change
- a replacement for validation
- a reason to shrink packets when expected files or tests are missed
- permission to edit generated/runtime artifacts by default

## 3. Inputs

Useful tuning inputs include:

- a representative prompt suite
- expected files for each prompt
- expected tests for each prompt
- candidate strategy/profile settings
- benchmark metrics
- packet budget status
- review-patch outcome
- focused regression tests

Use `examples/tuning_prompts.json` as a compact starter suite.

## 4. Prompt-suite format

A prompt suite should be valid JSON with prompt names, prompt text, expected files, and expected tests:

```json
{
  "prompts": [
    {
      "name": "docs_only_update",
      "prompt": "Update the documentation without changing runtime behavior.",
      "expected_files": ["README.md"],
      "expected_tests": []
    }
  ]
}
```

Use multiple prompt classes. Do not select a strategy only because it reduces tokens on one prompt.

## 5. Expected files and expected tests

Expected files and expected tests are fidelity checks. A smaller packet is not a win if expected files/tests are missed or patch quality drops.

Record:

- prompt suite
- candidate strategies or profiles
- expected file hit rate
- expected test hit rate
- token and packet metrics
- packet budget status
- review-patch outcome

## 6. Current supported pCodex tuning flow

Current supported pCodex commands:

```bash
pcodex tune
pcodex tune --validate
pcodex tune --verify
pcodex status --json
pcodex run --dry-run "<representative task>"
```

`pcodex tune` runs static generation, validation, and offline verification by default. It does not run Codex or contact external services.

`pcodex tune --validate` validates existing artifacts.

`pcodex tune --verify` runs the local compile-only mini verifier.

`pcodex status --json` reports configured mode, effective mode, tuning state, fallback state, and related local status.

Strict `pcodex tuned` requires a valid profile plus `.premode/tuning/VERIFY_RESULTS.json` verdict `PASS`. General `pcodex on` may use verified tuning, but falls back to generalized `literal_symbol` when tuning is missing, stale, invalid, or not verified.

## 7. Benchmark-assisted tuning loop

Benchmarking is measurement. It helps compare packet size, budget status, and expected file/test hits.

```bash
premode benchmark --profile lite --json
premode stress --profile lite --json
```

Use benchmark output to compare candidates, then validate the selected behavior. Do not treat benchmark output alone as proof of live agent quality.

## 8. Future/Planned premode tune flow

A direct `premode tune` command is future/planned unless it exists in the current CLI. In this repo state, use current `pcodex tune` commands for supported tuning.

Future direct Pre-mode tuning should preserve the same distinctions:

- Benchmarking = measurement.
- Tuning = selecting or writing a repo-local default.
- Validation = proving the tuned/default behavior remains safe.

## 9. Success criteria

A tuning pass succeeds when:

- the prompt suite is representative
- generated tuning artifacts validate
- verifier result is acceptable for the repo
- expected file/test hit rates are not worse
- packet budgets remain acceptable or explicitly documented
- review-patch does not report unsafe boundary drift
- focused regression tests pass
- unsupported savings or production-readiness claims are not introduced

## 10. Failure criteria

A tuning pass fails or needs adjustment when:

- validation fails
- verifier returns `FAIL`
- expected files or tests are missed
- packet size improves but patch fidelity drops
- generated artifacts include secrets, source snippets, or local-only absolute paths that should not be versioned
- review-patch reports forbidden/generated/state mutation
- claims drift into guaranteed savings or production readiness

`NEEDS_ADJUSTMENT` means review and refinement are required before relying on tuned mode.

## 11. Savings versus fidelity

A smaller packet is not a win if expected files/tests are missed or patch fidelity drops. Prefer the smallest packet that still gives the coding agent the right files, tests, and safety contract.

Never claim universal savings or guaranteed tuned savings. Tuned behavior is repo-specific and must be verified locally.

## 12. Avoiding overfitting

Avoid overfitting by using multiple prompt classes:

- CLI change
- test fix
- docs-only change
- config-safe change
- scope-guarded patch

Do not tune only to the prompt that produced the best token reduction. Check that general behavior stays stable across ordinary maintenance tasks.

## 13. Restoring default behavior

Prefer backing up generated tuning artifacts before removal if unsure.

To return pCodex to generalized safe behavior:

```bash
pcodex on
```

If the user explicitly approves destructive cleanup of tuning artifacts, remove the generated tuning files:

```bash
rm -f .premode/tuning/repo_profile.json
rm -f .premode/tuning/VERIFY_RESULTS.json
pcodex status
```

Do not delete generated artifacts just to make `git status` cleaner unless the user asked for cleanup and the files are known generated state.

## 14. Generated artifacts

Tuning artifacts live under `.premode/tuning/` and may include:

- `.premode/tuning/repo_profile.json`
- `.premode/tuning/path_taxonomy.json`
- `.premode/tuning/repo_vocabulary.json`
- `.premode/tuning/source_test_map.json`
- `.premode/tuning/prompt_phrase_routes.json`
- `.premode/tuning/hotspots_and_suppressions.json`
- `.premode/tuning/literal_symbol_weights.json`
- `.premode/tuning/evaluation_prompts.jsonl`
- `.premode/tuning/TUNING_REPORT.md`
- `.premode/tuning/VALIDATION_REPORT.md`
- `.premode/tuning/VERIFY_REPORT.md`
- `.premode/tuning/VERIFY_RESULTS.json`

Keep generated/runtime outputs out of commits unless the user explicitly chooses to version reviewed tuning artifacts.

## 15. Safe commit guidance

Before committing a tuning-related change:

```bash
git status --short
git diff --stat
git diff --check
git diff --cached --stat
git diff --cached --check
```

Commit only intentional source, tests, docs, examples, or reviewed tuning artifacts. Do not stage `.premode/out/`, `.premode/audit/`, `.premode/metrics/`, `.premode/pcodex_state.json`, `.premode/lcc.lock.json`, `.pcodex/`, runtime caches, or unrelated generated output.
