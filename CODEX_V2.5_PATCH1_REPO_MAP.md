# Codex Prompt — Pre-mode Router v2.5 Patch 1: Repo Map Foundation

You are implementing **Pre-mode Router v2.5 Patch 1: Repo Map Foundation**.

## Important scope rules

This patch must remain agent-agnostic. Do not hardcode Codex behavior into `repo_map.py`.

The repo map is a neutral repository-intelligence artifact that later renderers can use for Codex, OpenCode, Aider, Claude Code, or generic JSON workflows.

Do not implement compile integration, impact maps, packet modes, token ROI, manifest grouping, delta packets, local assist, embeddings, tree-sitter, ctags, patch review, agent config linting, or auto-running commands in this patch.

Do not implement cache commands in this patch, even though the roadmap mentions future cache support.

Specifically, do not add:

```bash
premode map --cache
premode cache status
premode cache clean
```

Those are future work after the basic repo-map foundation is stable.

## Goal

Add a deterministic repo-map generator that can be used by later v2.5 patches to reduce context and agent exploration.

## Required changes

### 1. Create `src/premode/repo_map.py`

It should produce JSON-serializable repo-map output:

```json
{
  "schema_version": 1,
  "root": ".",
  "repo_map_sha256": "...",
  "generated_at": "...",
  "files": {
    "src/premode/compiler.py": {
      "language": "python",
      "kind": "source",
      "bytes": 12345,
      "sha256": "...",
      "imports": [],
      "classes": [],
      "functions": [],
      "methods": [],
      "test_functions": [],
      "related_tests": [],
      "referenced_by": [],
      "risk_notes": []
    }
  },
  "edges": []
}
```

### 2. Python AST support

For `.py` files, use `ast` only.

Extract:

- imports
- top-level classes
- top-level functions
- class methods
- pytest-style test functions

Rules:

- Do not execute user code.
- Do not import user modules.
- Do not require third-party parsers.

### 3. Lightweight non-Python summaries

For v2.5 Patch 1:

- Markdown: headings
- JSON/TOML/YAML: top-level keys where safe
- fallback: path, kind, bytes, sha256


### 3A. Lightweight Swift scanner

For `.swift` files, add a conservative regex-level scanner. Do not use tree-sitter, SourceKit, SwiftSyntax, or any third-party parser in this patch.

Extract where simple and safe:

- `struct`
- `class`
- `enum`
- `protocol`
- `extension`
- `func`
- top-level/simple `var` and `let` declarations
- SwiftUI `View` structs when the declaration line includes `: View`
- `ObservableObject` / `@Observable` classes where visible in source text

Example output shape:

```json
{
  "language": "swift",
  "symbols": [
    "struct GameState",
    "class GameSessionViewModel",
    "func advanceDay",
    "func resolveEventChoice",
    "struct DayReport"
  ]
}
```

Rules:

- This is a lightweight symbol scanner, not a Swift parser.
- Do not execute build tools.
- Do not inspect assets.
- Do not make repo-map relevance promote files to full text. Later compile integration must keep that rule.

### 4. Respect existing safety/index rules

Repo map must not include:

- ignored files
- blocked files
- binary files
- unsafe paths
- secret-like files

Repo map cache/output must not store file content.

### 5. Add CLI

Add:

```bash
premode map
premode map --json
premode map --out .premode/out/repo_map.json
```

Default text output should be concise:

```text
Project root: .
Files mapped: 42
Python files: 18
Edges: 0
Output: .premode/out/repo_map.json
```

Only show output path if written.

### 6. Deterministic hashing

Compute `repo_map_sha256` from stable JSON content.

Rules:

- Do not let nondeterministic timestamps change the hash.
- If `generated_at` is included, keep it outside the hash or use the existing deterministic time behavior.
- Same repo state should produce the same `repo_map_sha256`.

### 7. Add tests

Add tests for:

- Python AST extraction
- import extraction
- classes/functions/methods
- pytest test function extraction
- Markdown heading extraction
- JSON/TOML/YAML top-level key extraction
- Swift lightweight symbol extraction
- ignored/unsafe files excluded
- `premode map --json`
- `premode map --out`
- deterministic `repo_map_sha256` for unchanged repo
- existing v2.4.1/v2.4.2 tests still pass

### 8. Update docs lightly

Update:

```text
README.md
IMPLEMENTATION_REPORT.md
docs/PRODUCT_ROADMAP.md
```

Say v2.5 Patch 1 adds deterministic repo-map foundation.

Do not claim full token-spend controls are implemented yet.

## Validation

Run:

```bash
python -m pip install -e ".[dev]"
pytest -q
bash scripts/smoke_test.sh
premode map --json
premode map --out .premode/out/repo_map.json
```

Expected:

- all tests pass
- repo-map JSON is valid
- repo map does not include file content
- `repo_map_sha256` is stable
- no v2.4.1/v2.4.2 regressions

## v2.4.3 OpenClaw baseline requirement

Before v2.5 Patch 1, preserve the v2.4.3 control-plane behavior:

- OpenClaw/control-plane markers must outrank nested Node/Web executor markers.
- Repo map output must remain agent-agnostic.
- For Swift files, include the lightweight Swift scanner requirement from v2.4.2/v2.5 planning.
- For OpenClaw/control-plane files, do not treat generated proof/history bundles as current authority.
- Do not remove or weaken the proof-policy packet section.

Patch 1 still must not implement compile integration, packet modes, cache commands, local assist, embeddings, tree-sitter, ctags, or patch review.

