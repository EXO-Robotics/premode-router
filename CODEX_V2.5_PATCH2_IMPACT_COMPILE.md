# Codex Prompt — Pre-mode Router v2.5 Patch 2: Impact Map + Compile Integration

You are implementing **Pre-mode Router v2.5 Patch 2: Impact Map + Compile Integration**.

Assume v2.5 Patch 1 is complete and `premode map` works.

Do not add packet modes, token ROI, manifest grouping, delta packet behavior, local assist, embeddings, tree-sitter, ctags, patch review, agent config linting, or auto-running commands in this patch.

## Goal

Wire the deterministic repo map into compile output so Pre-mode can produce an impact map, better verification order, and sharper context scoring without increasing full-text context by default.

## Required changes

### 1. Add compile flag

Add:

```bash
premode compile "Fix the build" --use-repo-map
```

When enabled:

- build or load `.premode/out/repo_map.json`
- include `repo_map_summary` in compile JSON
- include `impact_map` in compile JSON
- use repo-map relationships for related tests and verification order
- keep packet under existing hard budgets

### 2. Add concise repo-map summary

Compile output should include only a concise summary, not the full repo map.

Example:

```json
{
  "repo_map_summary": {
    "repo_map_sha256": "...",
    "mapped_file_count": 42,
    "python_file_count": 18,
    "edge_count": 12,
    "high_signal_files": [
      "src/premode/compiler.py",
      "tests/test_packet_v2.py"
    ]
  }
}
```

### 3. Add impact map

Minimum schema:

```json
{
  "impact_map": {
    "changed_or_target_files": ["src/premode/compiler.py"],
    "direct_dependencies": ["src/premode/log_scanner.py"],
    "direct_dependents": ["tests/test_packet_v2.py"],
    "related_tests": ["tests/test_packet_v2.py", "tests/test_context_tiers.py"],
    "verification_order": ["pytest tests/test_packet_v2.py", "pytest"]
  }
}
```

### 4. Context scoring rule

Repo-map signals can increase relevance, but:

> Repo-map relevance alone must not promote files to full text.

Full text still requires strong evidence from v2.4.1.

### 5. Tests and validation

Run:

```bash
python -m pip install -e ".[dev]"
pytest -q
bash scripts/smoke_test.sh
premode map --json
premode compile "Fix the campaign upkeep patch, don't expand scope, check what Qwen did, and make sure the app builds." --profile lite --use-repo-map --json
```

Expected:

- compile JSON includes `repo_map_summary`
- compile JSON includes `impact_map`
- verification order is narrow-to-broad when related tests are known
- full-text count does not increase by default
- packet stays under lite budget
- no v2.4.1 regressions
