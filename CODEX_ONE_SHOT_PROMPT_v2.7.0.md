# Codex One-Shot Prompt — v2.7.0 Agent Config Linter

You are working in the `premode-router` repo.

Goal: implement `v2.7.0 — Agent Config Linter`.

Base: v2.6.5 release-candidate cleanup.

Do not modify review-patch, benchmark, repo-map, packet rendering, or Codex execution behavior unless tests require a small compatibility fix.

## Product goal

Add a local linter for agent guidance files. Pre-mode should inspect the repo's AI-agent instruction surface and report stale, unsafe, conflicting, bloated, or tool-specific guidance before an agent runs.

## Command surface

Implement:

```bash
premode lint-agents
premode lint-agents --json
premode lint-agents --fix-plan
premode lint-agents --out .premode/out/agent_lint_report.json
```

`--fix-plan` must only suggest edits. It must not mutate files in v2.7.0.

## Files to scan

Primary guidance:

```text
AGENTS.md
CODEX.md
CLAUDE.md
.cursor/rules/*
.windsurfrules
.windsurf/rules/*
.opencode/*
opencode.json
.premode/rules.md
```

Secondary lower-trust guidance:

```text
README.md
CONTRIBUTING.md
docs/*
```

## Findings to detect

- stale commands
- conflicting instructions
- unsafe instructions
- prompt-injection-like guidance
- context bloat
- duplicate rules
- tool-specific leakage
- missing test/build commands
- over-broad edit permissions
- missing secret-handling policy

## Suggested output shape

```json
{
  "schema_version": 1,
  "lint_kind": "agent_config_lint",
  "repo_root": ".",
  "project_kind": "python",
  "guidance_files_scanned": [],
  "summary": {
    "files_scanned": 0,
    "findings_total": 0,
    "blocked": 0,
    "warnings": 0,
    "info": 0,
    "estimated_guidance_tokens": 0
  },
  "findings": [],
  "fix_plan": []
}
```

Finding shape:

```json
{
  "severity": "warning",
  "category": "stale_command",
  "file": "AGENTS.md",
  "line": 12,
  "snippet": "npm test",
  "message": "Guidance references npm test, but this repo does not appear to be a Node project.",
  "suggested_fix": "Replace with the detected Python test command."
}
```

## Minimum tests

Add tests for:

- no guidance files
- scans `AGENTS.md`
- stale `npm test` command in Python repo
- conflicting test guidance
- unsafe `ignore failing tests` instruction
- prompt-injection-like README text
- context bloat
- missing verification guidance
- `--fix-plan` does not mutate files
- JSON output
- `--out` writes report

## Validation

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite --json
premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
premode lint-agents --json
```

Final report must include commands run and exact test evidence.
