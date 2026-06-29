# Codex One-Shot Prompt — v2.6.5 Release Candidate Cleanup

You are working in the `premode-router` repo.

Goal: implement `v2.6.5 — Release Candidate Cleanup` from base `0.2.6.4`.

Do not implement v2.7 Agent Config Linter yet. Do not add new large features. Keep review-patch, benchmark, repo-map, packet, and Codex execution behavior stable unless tests require a small cleanup.

Required work:

1. Bump version to `0.2.6.5` in `pyproject.toml` and `src/premode/__init__.py`.
2. Clean public docs:
   - `README.md` should be a concise user-facing quickstart.
   - `IMPLEMENTATION_REPORT.md` should summarize the current release, not the full historical plan.
   - `FINAL_PACKAGE_INDEX.md` should be a short package contents map.
   - `CHANGELOG.md` should include v0.2.6.5 and a concise v2.6.x history.
   - `docs/BENCHMARK.md`, `docs/REVIEW_PATCH.md`, `docs/PACKET_V3.md`, and `docs/SECURITY_MODEL.md` should be deeper guides, not copies of the README.
3. Standardize validation commands everywhere:
   - `python -m pip install --no-index --no-build-isolation --no-deps -e .`
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
   - `bash scripts/smoke_test.sh`
   - `premode stress --profile lite --json`
   - `premode benchmark --profile lite --json --out .premode/out/benchmark_report.json`
4. Make the primary workflow consistent:
   - `premode setup`
   - `pcodex "Fix the failing test without expanding scope"`
   - `premode review-patch --since-compile`
   - `premode benchmark --profile lite`
5. Keep benchmark budget-exceeded prompts surfaced. Do not hide over-budget diagnostics.
6. Add `CODEX_ONE_SHOT_PROMPT_v2.7.0.md` describing the next Agent Config Linter slice, but do not implement `premode lint-agents` yet.
7. Add/update tests proving:
   - benchmark JSON still exposes top-level `prompt_count`, `summary.prompt_count`, budget-exceeded prompt details, and cache split percentages.
   - docs mention `review-patch --since-compile` as the primary local workflow.
   - `CODEX_ONE_SHOT_PROMPT_v2.7.0.md` exists.
   - `premode lint-agents` is not implemented in v2.6.5.

Validation:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite --json
premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
premode compile "Fix the failing test without expanding scope" --profile lite --use-repo-map --cache-optimized --save --json
premode review-patch --since-compile --json
```

Final response format:

- summary
- files_changed
- docs_changed
- benchmark_result
- validation_commands_run
- tests_passed
- remaining_risks
- next_recommended_patch
