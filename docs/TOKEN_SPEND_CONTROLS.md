# Token Spend Controls

## Core line

Pre-mode does not make the model cheaper by being smaller. It makes the task cheaper by making the model read less, explore less, rerun less, and review less.

## Four token-spend categories

### 1. Initial context tokens

v2.4.1 attacks this with:

- evidence packet V2
- full-text / summary / manifest tiers
- hard packet budgets
- command discovery
- safety filtering
- context savings metrics

### 2. Agent exploration tokens

v2.5 attacks this with:

- repo map
- impact map
- related tests
- verification order
- packet modes
- agent exploration guidance

### 3. Tool-loop and retry tokens

v2.5 attacks this with:

- log slicing
- log deduplication
- test-target narrowing
- cascade-error suppression

### 4. Review and follow-up tokens

v2.6 attacks this with:

- patch review governor
- scope compliance report
- test-claim verification
- packet-boundary comparison
- future delta packet support

## Context receipt

Every compile should eventually print a compact local receipt. This illustrative sample is not a generalized savings claim:

```text
Context receipt:
- Packet mode: standard
- Full text: 1 file / 3,617 tokens
- Summaries: 1 file / 109 tokens
- Manifest: 41 files / 2,511 tokens
- Rules/output/overhead: 3,617 tokens
- Total: 9,854 / 12,000
- Estimated local packet reduction: 85.6% in this sample
```

This makes the value visible without reading JSON.

## Why-included explanations

Every full-text file should explain why it was included:

```json
{
  "path": "src/premode/compiler.py",
  "tier": "full_text",
  "reason": "dirty_file",
  "evidence_flags": ["dirty_file"],
  "estimated_tokens": 3200
}
```

Large excluded files should explain why they were omitted:

```json
{
  "path": "docs/large_spec.md",
  "reason": "low evidence and high token cost",
  "estimated_tokens": 9000
}
```

## Max full-text file policy

Future config:

```json
{
  "max_full_text_file_tokens": 5000,
  "large_file_policy": "summarize_unless_direct_evidence"
}
```

Rule:

A file over `max_full_text_file_tokens` can only be full text if directly mentioned, dirty, or tied to the first meaningful error.

## Future excerpt tier

Long-term context tiers should become:

```text
full_text
excerpt
summary
manifest
```

For large evidence files:

```json
{
  "excerpt_files": [
    {
      "path": "src/app/big_controller.swift",
      "ranges": ["120-190", "340-390"],
      "reason": "symbols referenced by error"
    }
  ]
}
```

Do not build this in v2.5 Patch 1.

## Packet modes

v2.5 Patch 3B should add:

```text
no_repo_context
rules_only
diff_only
logs_only
repo_map_only
standard
deep
```

Simple tasks should not receive full repo context.

## Grouped manifests

Large manifest lists should compress into grouped records:

```json
{
  "manifest_groups": [
    {
      "group": "src/premode/*.py",
      "count": 18,
      "excluded_reason": "not directly implicated",
      "top_examples": ["src/premode/plugin.py"]
    }
  ]
}
```

## Token ROI

Diagnostic-only scoring:

```json
{
  "path": "src/premode/compiler.py",
  "estimated_tokens": 3200,
  "evidence_score": 1400,
  "roi": 0.44,
  "tier": "full_text"
}
```

ROI should explain selection, not replace evidence-based rules.
