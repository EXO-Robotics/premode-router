# Release Archive Hygiene

This repository can produce two different local artifact types: research archives and private alpha package archives. Both must avoid secrets, runtime ledgers, private lab outputs, and local machine state.

## Research Archive

A research archive may include lab reports, benchmark summaries, decision matrices, and supporting JSON artifacts when they are explicitly approved for the audience.

Before sharing a research archive, remove or redact:

- private repo prompts
- secrets and tokens
- local usernames and machine-specific paths
- full packets from private repositories
- runtime ledgers
- raw Codex task transcripts unless approved

## Private Alpha Package Or Archive

A private alpha package/archive is for local install smoke only. It should contain source, tests, docs, examples, scripts, and package metadata needed for local validation.

It must exclude:

- `__pycache__/`
- `.pytest_cache/`
- `.DS_Store`
- `.premode/out/`
- `.premode/audit/`
- `.premode/metrics/`
- `.premode/index/`
- `.pcodex/`
- `usage_ledger.jsonl`
- private lab artifacts
- large temporary outputs
- local env files
- secrets

## Current Repo Hygiene

`.gitignore`, `MANIFEST.in`, and package-data excludes should block common Python caches, OS files, Pre-mode runtime outputs, pCodex local config, JSONL ledgers, local env files, and secret-like files.

Do not delete existing lab artifacts during docs or package-hygiene work unless the generated artifact lives inside the active lab directory and the lab explicitly calls for cleanup.

## Local Archive Smoke

For the next private alpha artifact lab, create the archive in a clean temporary directory, install it into a fresh virtual environment, and verify:

```bash
premode compile --plugin literal_symbol
pcodex doctor
pcodex status
pcodex run --dry-run
pcodex mcp-server --help
```

Do not publish the archive to PyPI or any external registry.
