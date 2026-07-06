# Codex Prompt — Pre-mode Router v2.5 Patch 3A: Budget Report + Context Receipt + Why-Included

Assume v2.5 Patch 1 and Patch 2 are complete.

Do not add manifest grouping, packet modes, token ROI, log dedupe, delta behavior, local assist, embeddings, patch review, or agent config linting in this patch.

## Goal

Make token spend visible and explainable.

## Required changes

### 1. Add `--budget-report`

```bash
premode compile "Fix the build" --budget-report
```

Compile JSON should include section-level approximate token use:

```json
{
  "packet_budget": {
    "total": 12000,
    "used": 9752,
    "task_and_evidence": 1200,
    "repo_map_summary": 1600,
    "full_text": 3400,
    "summaries": 720,
    "manifest": 1100,
    "rules": 950,
    "output_contract": 380,
    "overhead": 402
  }
}
```

### 2. Add default context receipt

Text-mode compile should print:

```text
Context receipt:
- Packet mode: standard
- Full text: 1 file / 3,617 tokens
- Summaries: 1 file / 109 tokens
- Manifest: 41 files / 2,511 tokens
- Rules/output/overhead: 3,617 tokens
- Total: 9,854 / 12,000
- Savings: 85.6%
```

### 3. Add why-included explanations

Every full-text file should include:

```json
{
  "path": "src/premode/compiler.py",
  "tier": "full_text",
  "reason": "dirty_file",
  "evidence_flags": ["dirty_file"],
  "estimated_tokens": 3200
}
```

Large excluded files should include a reason:

```json
{
  "path": "docs/large_spec.md",
  "reason": "low evidence and high token cost",
  "estimated_tokens": 9000
}
```

### 4. Add max full-text token policy

Add config/profile field:

```json
{
  "max_full_text_file_tokens": 5000,
  "large_file_policy": "summarize_unless_direct_evidence"
}
```

Rule:

A file over `max_full_text_file_tokens` can only be full text if directly mentioned, dirty, or tied to first meaningful error.

Do not implement excerpt tiers yet.

## Validation

Run:

```bash
python -m pip install -e ".[dev]"
pytest -q
bash scripts/smoke_test.sh
premode compile "Fix the build" --profile lite --use-repo-map --budget-report --json
```

Expected:

- `packet_budget` present
- context receipt prints in text mode
- why-included/excluded explanations present
- max full-text token policy exists
- packet remains under lite budget
