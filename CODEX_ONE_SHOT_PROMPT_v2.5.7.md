# CODEX ONE-SHOT PROMPT — v2.5.7 Cache-Aware Packet V3

You are working in the `premode-router` repo.

Goal: implement `v2.5.7 — Cache-Aware Packet V3 + Agent Path Defaults`.

Do not implement `premode review-patch`, benchmark mode, OpenCode runner, Ollama/local assist, embeddings, vector DB, or broad tree-sitter support in this patch.

Required changes:

1. Add `PREMODE_COMPILED_PACKET_V3` with stable cacheable prefix before prompt-specific dynamic suffix.
2. Add `premode compile --packet-version v2|v3`.
3. Add `premode compile --cache-optimized` as the V3 selector.
4. Add `premode compile --save` writing `.premode/out/last_packet.md`, `last_packet.json`, `last_context_receipt.json`, and `last_repo_map_summary.json`.
5. Add cache metrics to compile JSON: `packet_version`, `cacheable_prefix_tokens`, `dynamic_suffix_tokens`, `cacheable_prefix_sha256`, `dynamic_suffix_sha256`, `packet_sha256`, and `repo_map_sha256`.
6. Make the Codex path default to profile `lite`, `use_repo_map=true`, `cache_optimized=true`, and saved artifacts.
7. Add opt-outs: `premode codex --no-repo-map`, `premode codex --no-cache-optimized`, and `premode codex --packet-version v2`.
8. Preserve the `codex exec ... -` stdin sentinel behavior. Never pass the raw prompt as a subprocess argument.
9. Keep V2 packet behavior available and existing V2 tests passing.
10. Add tests in `tests/test_v257_cache_packet.py`.

Validation:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite
```

Final response must include:

- summary
- files_changed
- behavior_changes
- commands_run
- tests_passed
- remaining_risks
- next_recommended_patch

Do not claim test success without command evidence.
