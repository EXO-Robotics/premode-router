# CODEX_ONE_SHOT_PROMPT_v2.6.1 — Review Evidence Integrity Hardening

Implement Pre-mode Router v2.6.1 as a focused hardening patch on top of v2.6.0. Do not add benchmark mode, auto-running tests, auto-fixing, auto-reverting, local assist, embeddings, Tree-sitter, cloud dashboard, GitHub PR comments, or team policy features.

Required fixes:

1. Ignore `.premode/index/*` as Pre-mode runtime metadata during `review-patch`.
2. Fix test evidence parsing so `10 passed, 0 failed` is passing evidence and non-zero failed/error counts are failing evidence.
3. Bind auto-discovered `.premode/out/*.log` evidence to current `packet_sha256`; unbound or stale logs must report `evidence_present_but_unbound`, not pass or block.
4. Return a failed-test recommendation when bound failed evidence exists.
5. Extract explicit negative prompt paths from raw prompt text before repo index matching.
6. Classify both old and new paths for git rename/copy records.
7. Strengthen native C++/SCons stress to require concrete likely-file routing.
8. Add regression tests for all above cases.

Validation:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite
```

Do not claim test success without command evidence.
