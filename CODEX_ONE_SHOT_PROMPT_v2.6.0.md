# CODEX ONE-SHOT PROMPT — v2.6.0 Patch Review Governor

Implement Pre-mode Router v2.6.0: Patch Review Governor.

Do not implement auto-running tests, auto-fixing, auto-reverting, local assist, embeddings, Tree-sitter, cloud dashboard, GitHub PR comments, or team policy features.

Goal:

```text
compile packet before agent
→ save packet contract
→ agent edits repo
→ review patch against saved contract
```

Required result:

```bash
premode review-patch --against main --packet .premode/out/last_packet.json --json
```

The command must classify changed files, compare them against `review_contract`, detect missing or unsupported test claims, and report merge readiness as `pass`, `warning`, or `blocked`.

Validation target:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite
```
