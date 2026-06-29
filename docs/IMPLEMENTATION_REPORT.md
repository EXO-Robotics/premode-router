# Docs Implementation Report — v0.2.6.6

This document mirrors the root `IMPLEMENTATION_REPORT.md` for users browsing the `docs/` directory.

## Current release

`v0.2.6.6 — Local Validation + macOS Portability Cleanup`

Focus:

- concise public docs
- macOS-safe smoke validation
- installed and no-install validation commands
- `review-patch --since-compile` as the default local workflow
- Python >=3.11 and pytest setup requirements are explicit
- benchmark budget and cache KPI diagnostics remain visible
- v2.7 Agent Config Linter isolated to a handoff prompt only

## Core workflow

```bash
premode setup
pcodex "Fix the failing test without expanding scope"
premode review-patch --since-compile
premode benchmark --profile lite
```

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

## Next

`v2.7.0 — Agent Config Linter`, described in `CODEX_ONE_SHOT_PROMPT_v2.7.0.md`.
