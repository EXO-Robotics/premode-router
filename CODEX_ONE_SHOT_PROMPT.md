# Pre-mode Router v2.5.6 — Universal Stress Harness

Goal: add a repeatable deterministic stress harness that tests Pre-mode across repo shapes before v2.6 patch-review governance is implemented.

This patch should not add patch review, local assist, embeddings, Tree-sitter, ctags, cloud features, or auto-running project test commands.

Required behavior:

1. Add a universal stress harness command:

```bash
premode stress
premode stress --json
premode stress --out .premode/out/stress_report.json
premode stress --keep
```

2. The harness should generate local fixtures, compile each with `--use-repo-map`, and report a scorecard.

Required fixture classes:

- Python src-layout framework
- Python CLI facade/re-export
- Rust Cargo CLI
- Go CLI/root-command layout
- TypeScript pnpm monorepo
- Swift/iOS app
- Native C++/SCons engine repo
- Mixed monorepo with Python worker under Node root
- Proof-governed control-plane repo
- Adversarial README/secret fixture
- Tiny low-risk repo

3. For each case, report:

- fixture name
- repo shape
- prompt
- detected project kind
- root and task root
- traits
- packet mode
- packet tokens
- selected context tokens
- policy metadata tokens
- budget exceeded amount
- full/summary/manifest counts
- likely files
- related tests
- allowed files
- forbidden files
- pass/fail status and failure reasons

4. Keep the harness deterministic and local-only.

5. Add tests for:

- fixture matrix coverage
- harness report schema
- pass/fail scorecard behavior
- token/boundary fields present
- mixed monorepo negative intent coverage
- secret fixture suppression

Validation:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
python -m pytest -q
bash scripts/smoke_test.sh
premode stress
premode stress --json
premode stress --out .premode/out/stress_report.json
```

Expected:

- all tests pass
- smoke passes
- stress harness returns 0 when all fixtures pass
- report shows pass/fail by fixture
- OpenClaw/control-plane is only one fixture in a broader matrix
