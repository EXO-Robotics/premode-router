# Codex One-Shot Prompt — v2.4.4 General Intake Layer

This patch has been applied in this bundle. It is retained for auditability.

Goal: Generalize the OpenClaw/control-plane lessons into a reusable intake/classification layer before v2.5 repo-map work.

Implemented scope:

- `src/premode/intake.py`
- generic repo traits
- policy packs
- OpenClaw profile on top of generic traits
- intake report wired into `detect_projects` and `compile_prompt`
- generic scoring hints for authority/evidence/binary surfaces
- dangerous mutation zones wired into patch boundaries
- compact packet intake-policy section
- generic intake regression tests

Validation expected:

```bash
python -m pip install -e ".[dev]"
pytest -q
bash scripts/smoke_test.sh
premode detect --json
premode compile "Review the current control-plane task packet without mutating generated artifacts." --profile lite --json
```

Expected result: tests pass, OpenClaw profile still works, ordinary repos are not overclassified, and generic control-plane/infra/migration/asset-heavy patterns produce intake traits instead of project-specific adapters.
