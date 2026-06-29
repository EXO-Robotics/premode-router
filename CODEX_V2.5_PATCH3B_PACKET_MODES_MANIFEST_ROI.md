# Codex Prompt — Pre-mode Router v2.5 Patch 3B: Manifest Grouping + Packet Modes + Token ROI

Assume v2.5 Patch 3A is complete.

Do not add log dedupe, delta behavior, local assist, embeddings, patch review, or agent config linting in this patch.

## Goal

Reduce packet bloat for large repos and avoid unnecessary repo context for simple tasks.

## Required changes

### 1. Add grouped manifest compression

```json
{
  "manifest_groups": [
    {
      "group": "src/premode/*.py",
      "count": 18,
      "excluded_reason": "not directly implicated",
      "top_examples": ["src/premode/plugin.py"]
    }
  ],
  "individual_manifest_files": []
}
```

Rules:

- keep top N high-signal manifest files individually
- group low-signal manifest entries by path pattern/kind
- preserve counts and reasons
- grouped manifests should reduce packet tokens

### 2. Add packet mode classification

Modes:

```text
no_repo_context
rules_only
diff_only
logs_only
repo_map_only
standard
deep
```

Examples:

```text
Write a commit message -> diff_only
Explain this pasted error -> logs_only
Draft AGENTS.md -> rules_only or repo_map_only
Fix the failing tests -> standard
Understand this large codebase -> deep
```

### 3. Add token ROI diagnostics

```json
{
  "token_roi": [
    {
      "path": "src/premode/compiler.py",
      "estimated_tokens": 3200,
      "evidence_score": 1400,
      "roi": 0.44,
      "tier": "full_text"
    }
  ]
}
```

ROI is diagnostic. Selection remains evidence-based.

## Validation

Run:

```bash
python -m pip install -e ".[dev]"
pytest -q
bash scripts/smoke_test.sh
premode compile "Write a commit message" --profile lite --json
premode compile "Fix the build" --profile lite --use-repo-map --budget-report --json
```

Expected:

- manifest grouping present when manifests are numerous
- simple tasks avoid unnecessary repo context
- `token_roi` present
- packet remains under lite budget
