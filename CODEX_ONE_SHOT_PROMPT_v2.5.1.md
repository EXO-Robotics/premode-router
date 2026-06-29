# Pre-mode Router v2.5.1 — Impact Map Hardening + Repo-map Overhead Control

Goal: harden v2.5.0 repo-map compile integration without adding new major systems.

Scope:
- Keep the deterministic repo map foundation.
- Make `repo_map_summary` profile-aware and compact, especially for `lite`.
- Ensure `premode compile ... --profile lite --use-repo-map --json` does not exceed the hard packet budget due to repo-map metadata overhead.
- Add richer deterministic impact hints: likely files, direct dependencies, direct dependents, related tests, and verification order.
- Preserve the guardrail: repo-map relevance alone must not promote files to full text.

Do not add:
- embeddings
- local assist
- tree-sitter
- ctags
- cache commands
- delta packets
- patch review
- agent config linting

Validation:

```bash
python -m pip install --no-build-isolation --no-deps -e .
python -m pytest -q
bash scripts/smoke_test.sh
premode compile "Find the right files for a safe Rust CLI patch that changes argument handling without touching packaging or release scripts." --profile lite --use-repo-map --json
```

Expected:
- tests pass
- smoke test passes
- `budget_exceeded_by` is `0` for the evaluator compile unless selected full-text evidence alone exceeds budget
- `repo_map_summary` is present but compact in lite mode
- `impact_map` includes dependencies/dependents/related_tests/verification_order
- `repo_map_summary` in lite mode omits broad `notable_files`
