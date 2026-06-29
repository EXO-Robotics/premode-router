# CODEX ONE-SHOT PROMPT — v2.6.4 Release Candidate Polish

Implement a small release-candidate polish pass on top of v2.6.3. Do not add Agent Config Linter yet.

Required changes:

1. Benchmark JSON should include top-level `prompt_count` while preserving `summary.prompt_count`.
2. Benchmark per-case output should include `cacheable_prefix_percent` and `dynamic_suffix_percent`.
3. Benchmark summary should include `average_cacheable_prefix_percent` and `average_dynamic_suffix_percent`.
4. Benchmark summary should include `budget_exceeded_prompts` with name, packet_tokens, budget, over_by, and likely_reason.
5. Human benchmark output should surface budget-exceeded prompt details.
6. README/docs should make this the primary local workflow:

```bash
premode setup
pcodex "Fix the failing test without expanding scope"
premode review-patch --since-compile
premode benchmark --profile lite
```

7. Validation docs should prefer:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite
premode benchmark --profile lite --json
```

Validation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v263_benchmark.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v260_review_patch.py -q
bash scripts/smoke_test.sh
premode stress --profile lite --json
premode benchmark --profile lite --json
```
