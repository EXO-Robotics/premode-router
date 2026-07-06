# Codex One-Shot Prompt — Pre-mode Router v2.4.5 Intake Hygiene

You are implementing Pre-mode Router v2.4.5: Intake Hygiene + Packet Overhead Control.

Do not implement v2.5 repo map, impact map, AST extraction, local assist, embeddings, tree-sitter, ctags, patch review, or agent config linting.

Goal:
Harden v2.4.4 after evaluation against OpenClaw and a Rust/Cargo fixture. v2.4.4 correctly generalized intake, but it needs cleaner policy classification, cleaner log evidence, clearer control-plane patch boundaries, and better behavior on small repos.

Required changes:

1. Split CI from infra-sensitive policy
- `.github/workflows/*` should contribute `ci_sensitive`.
- `infra_sensitive` should require real infra markers such as Terraform, Kubernetes, Helm, Ansible, Pulumi, Docker Compose deployment files, or cloud IaC markers.
- CI files alone must not trigger Terraform/Kubernetes/Helm destructive-command warnings.

2. Clean logs before first-error extraction
- Strip ANSI/control sequences.
- Dedupe repeated identical error lines.
- Downgrade logs under history/archive/generated/output/proof dirs unless directly requested by future prompt-aware logic.

3. Split control-plane/OpenClaw patch-boundary categories
Add specialized categories:

```json
{
  "authority_read_only": [],
  "state_mutation_requires_explicit_authorization": [],
  "evidence_only_generated_outputs": [],
  "allowed_source_edits": [],
  "allowed_config_if_justified": [],
  "forbidden_runtime_mutation": []
}
```

Keep generic categories for backward compatibility.

4. Add tiny/small repo packet mode foundation
- Add `packet_mode`: `tiny`, `standard`, or `deep`.
- Use `tiny` when eligible readable repo tokens are within the hard packet budget and no high-risk traits are present.
- Do not drop critical policy for proof/control-plane repos just to fit tiny mode.

5. Separate selected context budget from total packet budget
Add metrics:
- `selected_context_tokens`
- `policy_metadata_tokens`
- `output_contract_tokens`
- `budget_exceeded_by`
- `over_budget_reason`

6. Documentation
Document evaluator commands:

```bash
python -m pip install -e .
python -m pytest -q
```

or:

```bash
PYTHONPATH=src python -m pytest -q
```

Validation:

```bash
python -m pip install -e .
python -m pytest -q
bash scripts/smoke_test.sh
premode detect --json
premode compile "Find the right files for a safe Rust CLI patch that changes argument handling without touching packaging or release scripts." --profile lite --json
```
