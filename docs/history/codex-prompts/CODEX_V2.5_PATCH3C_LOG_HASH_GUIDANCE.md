# Codex Prompt — Pre-mode Router v2.5 Patch 3C: Log Dedupe + Packet Hashes + Guidance

Assume v2.5 Patch 3B is complete.

Do not add local assist, embeddings, patch review, agent config linting, daemon watchers, cloud dashboards, or auto-running commands in this patch.

## Goal

Reduce retry/tool-loop tokens and prepare for future delta packets.

## Required changes

### 1. Add log slicing and deduplication

```json
{
  "log_summary": {
    "first_root_error": "...",
    "unique_error_families": 3,
    "cascade_errors_suppressed": 184,
    "included_lines": 40,
    "omitted_lines": 2400,
    "repeated_errors": [
      {
        "message": "Cannot find Foo in scope",
        "count": 37
      }
    ]
  }
}
```

Rules:

- keep first meaningful/root-like error
- dedupe repeated errors by normalized message
- count repeated error families
- suppress cascaded duplicates
- preserve redaction

### 2. Add packet/repo-map hash metadata

```json
{
  "packet_sha256": "...",
  "base_packet_sha256": null,
  "repo_map_sha256": "...",
  "changed_files_since_last_packet": [],
  "reusable_sections": [
    "project_detection",
    "commands",
    "rules_memory",
    "repo_map_summary"
  ]
}
```

Store:

```text
.premode/out/last_packet.json
.premode/out/last_packet.sha256
.premode/out/repo_map.json
```

Full `--delta` behavior can come later.

### 3. Add output-token control

Output contract should say:

```text
Do not restate the full packet.
Do not paste unchanged files.
Keep final report under 300 words unless risks remain.
Mention commands only if they were actually run or are explicitly proposed.
```

### 4. Add agent exploration guidance

```json
{
  "agent_exploration_budget": {
    "max_extra_files_to_open": 5,
    "prefer_files": ["src/premode/compiler.py"],
    "avoid_files": ["README.md", "docs/*"],
    "ask_before_expanding_scope": true
  }
}
```

This is advisory until v2.6 patch review can compare actual behavior.

## Validation

Run:

```bash
python -m pip install -e ".[dev]"
pytest -q
bash scripts/smoke_test.sh
premode compile "Fix the build" --profile lite --use-repo-map --budget-report --json
```

Expected:

- log summary has dedupe fields
- packet/repo-map hashes present
- changed-files foundation present
- output-token guidance present
- agent exploration guidance present
- packet remains under lite budget
