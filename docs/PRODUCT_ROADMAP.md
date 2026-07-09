# Product Roadmap — Pre-mode Router

## Product identity

Pre-mode Router is a local-first deterministic preflight, context-control, and patch-governance layer for AI coding agents.

Codex CLI is the first supported runtime. The long-term direction is agent-agnostic.

## Roadmap summary

```text
v2.4.1 = trustworthy evidence packet + hard budget
v2.4.2 = Swift/iOS real-repo hardening
v2.4.3 = OpenClaw/control-plane hardening
v2.4.4 = generic repo intake traits + policy packs
v2.4.5 = intake hygiene, CI/infra split, log cleanup, tiny-mode foundation
v2.5   = repo map + impact map + token-spend controls
v2.6   = patch review governor
v2.7   = agent config linter
v3.0   = optional local assist
```

## v2.4.2 — Swift/iOS Real-Repo Hardening

Implemented before v2.5 because real Swift/Xcode testing showed hardening was needed.

Fixes:

- compile-time Xcode root-marker preservation
- long source-path redaction/path-extraction safety
- `Day Report` / receipt intent routing
- generated `.premode/` dirty-state filtering
- Swift/iOS command override docs
- Goldpine-style rules/memory templates


## v2.4.4 — General Intake Layer

Implemented before v2.5 because the OpenClaw pass exposed a broader detection issue.

v2.4.4 adds a reusable intake model before adapter-specific decisions:

- repo shape and nested project marker detection
- authority surfaces and current-state surfaces
- generated/history/evidence-only surfaces
- binary asset-heavy surfaces
- dangerous mutation zones
- safe validators and dangerous command patterns
- policy packs for proof/control-plane, generated artifacts, nested executors, binary assets, infra, migrations, and docs-authority repos

This prevents future hardening from becoming one named project adapter per edge case.

## v2.5 controlled implementation sequence

Do not implement v2.5 as one giant Codex pass.

### v2.5 Patch 1 — Repo Map Foundation

Ready for Codex one-shot.

Build:

- `src/premode/repo_map.py`
- `premode map`
- `premode map --json`
- `premode map --out`
- Python AST extraction
- Markdown/config summaries
- deterministic `repo_map_sha256`
- tests
- light docs

Do not build:

- compile integration
- impact maps
- packet modes
- token ROI
- manifest grouping
- delta packets
- cache commands
- local assist
- embeddings
- tree-sitter
- ctags
- patch review
- agent config linting
- auto-running commands

Important:

The roadmap includes future cache support, but Patch 1 should not implement:

```bash
premode map --cache
premode cache status
premode cache clean
```

Those can come after the basic repo-map foundation is stable.

### v2.5 Patch 2 — Impact Map + Compile Integration

Build:

- `premode compile --use-repo-map`
- `repo_map_summary`
- `impact_map`
- related tests
- verification order
- repo-map-aware context scoring

Hard rule:

> Repo-map relevance alone must not promote files to full text.

### v2.5 Patch 3A — Budget Report + Context Receipt + Why-Included

Build:

- `--budget-report`
- section-level packet budget
- default context receipt
- why-included explanations
- large-excluded-file explanations
- max full-text tokens per file

### v2.5 Patch 3B — Manifest Grouping + Packet Modes + Token ROI

Build:

- grouped manifest compression
- packet mode classification:
  - `no_repo_context`
  - `rules_only`
  - `diff_only`
  - `logs_only`
  - `repo_map_only`
  - `standard`
  - `deep`
- token ROI diagnostics

### v2.5 Patch 3C — Log Dedupe + Packet Hashes + Guidance

Build:

- log slicing and deduplication
- `packet_sha256`
- `repo_map_sha256`
- changed-files-since-last-packet foundation
- basic output-token control
- agent exploration guidance

## v2.6 — Patch Review Governor

Goal: run after the agent and check whether the patch stayed inside the packet boundary.

Commands:

```bash
premode review-patch
premode review-patch --against main
premode review-patch --packet .premode/out/last_packet.json
```

Review:

- planned files vs actual changed files
- allowed files vs unexpected files
- forbidden files touched
- tests claimed vs evidence found
- dependency/config changes
- secret-like additions
- large generated files
- deleted/weakened tests
- agent exploration budget violations

## v2.7 — Agent Config Linter

Commands:

```bash
premode lint-agents
premode agents doctor
premode agents normalize
```

Scan:

```text
AGENTS.md
CLAUDE.md
.cursor/rules/*
.windsurfrules
.github/copilot-instructions.md
.premode/rules.md
README.md
```

Detect:

- context bloat
- stale commands
- conflicting instructions
- unsafe instructions
- duplicated rules
- tool-specific leakage
- missing setup/test commands

## v3.0 — Optional Local Assist

Only after deterministic schemas are stable.

Local assist should emit schema-validated JSON only:

```json
{
  "file_rerank": [],
  "root_cause_hypotheses": [],
  "patch_plan": [],
  "risk_notes": []
}
```

The deterministic core validates all model suggestions.

## v2.4.3 OpenClaw / control-plane hardening

Real-repo testing against OpenClaw showed that language/framework detection is not enough for proof-governed control-plane repositories.

v2.4.3 adds an `openclaw_control_plane` adapter that detects OpenClaw-style authority markers, keeps the active root at `.`, outranks nested Node/Web executor folders, ranks current authority surfaces ahead of generated/historical artifacts, and emits a proof-policy packet section.

This keeps the product direction general: OpenClaw is the first concrete profile for a broader `proof_governed_control_plane` / `authority_surface_ranking` mode.

New docs/templates:

```text
docs/OPENCLAW_CONTROL_PLANE_HARDENING.md
docs/OPENCLAW_REAL_REPO_ANALYSIS_SUMMARY.md
docs/templates/openclaw/.premodeignore
docs/templates/openclaw/rules.md
docs/templates/openclaw/project_memory.md
docs/templates/openclaw/commands.json
```

v2.4.3 also increases savings display precision so very high savings do not misleadingly round to `100.0%`.


## v2.4.5 Intake Hygiene

- `ci_sensitive` is separate from `infra_sensitive`.
- log evidence is cleaned/deduped and stale generated/history logs are downgraded.
- control-plane patch boundaries are semantic instead of only generic allowed/forbidden lists.
- tiny packet mode reduces overhead for small low-risk repos.
- selected-context and policy-metadata token metrics are reported separately.


## v2.5.0 status

Folded in:

- deterministic repo map foundation
- `premode map`, `premode map --json`, and `premode map --out`
- Python AST extraction plus lightweight Rust/Swift/JS/TS/config summaries
- manifest-derived entrypoints from Cargo, package.json, pyproject, and Package.swift
- minimal `premode compile --use-repo-map` integration
- compact `repo_map_summary` and initial `impact_map` output

Next v2.5 work:

- richer impact map with direct dependencies/dependents
- related-test and verification-order narrowing
- budget receipt and why-included output
- manifest grouping and token ROI
- packet/repo-map hash metadata and exploration guidance

## v2.5.1 — Impact-map hardening

- Compact repo-map summaries by profile.
- Keep lite `--use-repo-map` packets under budget.
- Add direct dependencies, direct dependents, related tests, and verification order to impact hints.
- Preserve the full-text guardrail: repo-map relevance alone is advisory.


## v2.5.2 — Impact accuracy and governance compression

Status: implemented.

This patch closes two findings from v2.5.1 evaluation:

1. Manifest entrypoints can point at package facades instead of implementation files.
2. Proof-governed/control-plane packets need compact default governance in lite mode.

The next patch should not add local assist or embeddings yet. Recommended next work:

- v2.5.3: source/test matching hardening across Rust, Swift, JS/TS, and package managers.
- v2.5 Patch 3A: budget receipt, why-included explanations, and manifest grouping.


## v2.5.3 — Trust + Output Hardening

This release hardens output and explainability without adding new model-dependent intelligence.

Added:

- `premode map --summary-json`
- `premode map --compact-json`
- `premode map --json --max-files N`
- `premode map --json --force-stdout`
- large stdout safety for full repo-map JSON
- compile `context_receipt`
- `why_included` on full-text and summary context
- `why_excluded` on manifest/excluded context
- `max_full_text_file_tokens` profile policy
- large guidance-file protection

Validation target:

```bash
python -m pip install --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
bash scripts/smoke_test.sh
premode map --summary-json
premode map --json --max-files 10
premode map --out .premode/out/repo_map.json
premode compile "Find the right files for a safe Python CLI patch that changes command-line argument handling without touching packaging or release scripts." --profile lite --use-repo-map --json
```

### v2.5.4 — Universal-facing hardening

Status: implemented in 0.2.5.4.

Focus:
- Trust boundaries for README/docs/examples.
- Stale-log evidence gating.
- Mixed-monorepo task-root bias from prompt-mentioned files.
- Allow/forbid boundary conflict reporting.
- Go/Rust/TypeScript impact-routing improvements.

Followed by v2.5.5 native/negative hardening and v2.5.6 universal stress harness.


## v2.5.6 — Universal Stress Harness

Status: implemented.

Purpose: turn manual cross-repo evaluation into a deterministic local QA gate before v2.6 patch review.

Fixtures:

- Python src-layout framework
- Python CLI facade/re-export
- Rust Cargo CLI
- Go CLI/root-command layout
- TypeScript pnpm monorepo
- Swift/iOS app
- Native C++/SCons engine repo
- Mixed monorepo
- Proof-governed control plane
- Adversarial README/secret fixture
- Tiny low-risk repo

Commands:

```bash
premode stress
premode stress --json
premode stress --out .premode/out/stress_report.json
```

Next milestone: v2.6 Patch Review Governor.
