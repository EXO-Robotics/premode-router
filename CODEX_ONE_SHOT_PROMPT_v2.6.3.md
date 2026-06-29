# CODEX ONE-SHOT PROMPT — v2.6.3 Benchmark + Release Candidate

Implement `v2.6.3` as the benchmark/release-candidate slice.

Required:

- Add `premode benchmark`.
- Accept `--repo`, `--prompts`, `--profile`, `--json`, `--out`.
- Default to repo-map + cache-optimized Packet V3.
- Report eligible repo tokens, packet tokens, savings %, cacheable prefix tokens, dynamic suffix tokens, likely files, related tests, budget exceeded, and optional review readiness.
- Support prompt suites as either a list of strings or `{ "prompts": [...] }`.
- Do not auto-run tests, auto-fix patches, or mutate source files.
- Add docs and examples.

Validation:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite
premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
```
