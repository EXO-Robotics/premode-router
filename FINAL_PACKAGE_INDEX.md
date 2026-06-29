# Final Package Index — v0.2.6.16 Swift Edit Bucket Recovery + Remaining Docs Downrank

This package is the current release-candidate base for external Codex testing.

## Core package

```text
pyproject.toml
src/premode/__init__.py
src/premode/cli.py
src/premode/compiler.py
src/premode/codex_exec.py
src/premode/review_patch.py
src/premode/benchmark.py
src/premode/stress.py
src/premode/repo_map.py
src/premode/adapters.py
src/premode/command_discovery.py
src/premode/intake.py
src/premode/indexer.py
src/premode/config.py
src/premode/paths.py
src/premode/redaction.py
src/premode/safe_reader.py
src/premode/git_state.py
scripts/run_with_timeout.py
```

## Primary commands

```text
premode setup
premode detect
premode index
premode map
premode compile
premode codex
pcodex
premode review-patch
premode benchmark
premode stress
premode stats
premode plugin install-local
premode lab compare
```

## Main workflow

```bash
premode setup
pcodex "Fix the failing test without expanding scope"
premode review-patch --since-compile
premode benchmark --profile lite
```

## Tests

```text
tests/test_v263_benchmark.py
tests/test_v269_metadata_root.py
tests/test_v267_codex_cli_compat.py
tests/test_v260_review_patch.py
tests/test_v257_cache_packet.py
tests/test_v256_universal_stress.py
tests/test_v255_native_negative.py
tests/test_v254_universal_hardening.py
tests/test_v253_output_hardening.py
tests/test_v252_impact_accuracy.py
tests/test_v251_impact_budget.py
tests/test_v250_repo_map.py
```

Additional tests cover package layout, paths, privacy/Codex wrapper behavior, adapters, command discovery, hooks/plugin/MCP, deterministic time, safe reader, profiles, ignore/index behavior, context tiers, and source mutation guardrails.

## Docs

```text
README.md
IMPLEMENTATION_REPORT.md
CHANGELOG.md
docs/IMPLEMENTATION_REPORT.md
docs/REVIEW_PATCH.md
docs/BENCHMARK.md
docs/PACKET_V3.md
docs/SECURITY_MODEL.md
```

Historical planning docs are retained for traceability but are not the public quickstart.

## Examples

```text
examples/benchmark_prompts.json
```

## Codex handoff prompts

Current next-slice prompt:

```text
CODEX_ONE_SHOT_PROMPT_v2.7.0.md
```

Historical prompts are retained as internal trace artifacts.

## Validation

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
PYTHONPATH=src python -m premode.cli compile "Fix the failing test" --profile lite --cache-optimized --json
PYTHONPATH=src python -m premode.cli benchmark --profile lite --json
```
