# CODEX ONE-SHOT PROMPT — v2.5.3 Trust + Output Hardening

You are implementing Pre-mode Router v2.5.3.

Goal: make repo-map output safer, compile output more explainable, and large-file/context decisions easier to audit. Do not implement patch review, token ROI, delta packets, local assist, embeddings, Tree-sitter, ctags, agent config linting, or auto-running tests.

Required changes:

1. Repo-map output safety
- Add `premode map --summary-json`.
- Add `premode map --compact-json`.
- Add `premode map --json --max-files N`.
- Add `premode map --json --force-stdout`.
- If full repo-map JSON is too large for safe stdout, emit a compact warning/recommendation unless `--force-stdout` is used.
- Prefer `premode map --out .premode/out/repo_map.json` for full artifacts.

2. Context receipt
- Add `context_receipt` to compile JSON output.
- Receipt should report packet mode, profile, repo-map enabled, total packet tokens, hard budget, selected context tokens, policy metadata tokens, output contract tokens, budget status, and file counts.

3. Why-included / why-excluded explanations
- Full-text and summary files should include `why_included`.
- Manifest-only / excluded files should include `why_excluded` where useful.
- Keep packet rendering compact so these explanations do not blow the agent input budget.

4. Large-file policy
- Add `max_full_text_file_tokens` to profiles.
- Large files should not become full text unless directly mentioned, error-linked, repo-map entrypoint evidence is strong, or explicitly requested.
- Large guidance files should not become full text merely because a fresh repo marks them dirty/untracked.

5. Preserve v2.5.2 behavior
- Existing impact-map accuracy, console-script re-export resolution, OpenClaw compact governance, and lite `--use-repo-map` budget behavior must not regress.

Validation:

```bash
python -m pip install --no-build-isolation --no-deps -e .
python -m pytest -q
bash scripts/smoke_test.sh
premode map --summary-json
premode map --json --max-files 10
premode map --out .premode/out/repo_map.json
premode compile "Find the right files for a safe Python CLI patch that changes command-line argument handling without touching packaging or release scripts." --profile lite --use-repo-map --json
```

Expected:
- compact map output works
- max-file capped map output works
- full repo-map artifact output works
- compile JSON includes `context_receipt`
- selected context includes `why_included`
- manifest/excluded context includes `why_excluded`
- large files are protected
- lite compile with repo map remains under budget for the package evaluator prompt
