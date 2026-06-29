# Codex v2.5 Patch Plan — Split Implementation

Do not implement all of v2.5 in one giant pass.

Use:

```text
CODEX_V2.5_PATCH1_REPO_MAP.md
CODEX_V2.5_PATCH2_IMPACT_COMPILE.md
CODEX_V2.5_PATCH3A_BUDGET_RECEIPT.md
CODEX_V2.5_PATCH3B_PACKET_MODES_MANIFEST_ROI.md
CODEX_V2.5_PATCH3C_LOG_HASH_GUIDANCE.md
```

## Patch order

1. Repo Map Foundation
2. Impact Map + Compile Integration
3. Budget Report + Context Receipt + Why-Included
4. Manifest Grouping + Packet Modes + Token ROI
5. Log Dedupe + Packet Hashes + Guidance

## Hard rules

- Keep the system agent-agnostic.
- Codex CLI is the first runtime, not the only future runtime.
- Do not add local assist, Ollama, embeddings, vector DBs, tree-sitter, ctags, daemons, patch review, or agent config linting in v2.5 Patch 1.
- Repo-map relevance alone must not promote files to full text.
- Preserve all v2.4.1 trust-hardening and v2.4.2 Swift/iOS hardening behavior.
