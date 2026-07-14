# Local Context Compiler Roadmap to 90

Status: proposed completion program
Target: a 90/100 product-readiness release
Recommended duration: 12-16 weeks
Primary release surface: pCodex
First supported runtime: Codex
Specialized integration: OpenClaw

## 1. Purpose

This document turns the product review into an execution plan. It defines the work, tests, evidence, and release gates required to move Local Context Compiler / pCodex from a technically strong private beta to a coherent, installable, supportable product.

The next phase is a consolidation program. New ranking experiments should not enter the production path unless they resolve a release blocker or pass the held-out promotion gate defined here.

The intended launch promise is:

> pCodex gives coding agents the right repository paths first, locally, deterministically, and with a reviewable safety boundary.

The OpenClaw-specific promise is:

> pCodex distinguishes current authority from generated evidence before an agent touches a proof-governed workspace.

## 2. Definition of a 90/100 release

The release is not complete merely because all planned code exists. It is complete only when all of the following outcomes are demonstrated:

- A new user can install pCodex and reach a useful dry run in under five minutes.
- There is one canonical first-run path and one canonical production packet.
- The public CLI is small, comprehensible, and stable.
- Codex integration installs, verifies, upgrades, and uninstalls cleanly.
- OpenClaw support is an installable product adapter, not only a repository profile or benchmark harness.
- Dry-run, advisory, containment, privacy, and cleanup guarantees are enforced by tests.
- Releases are reproducible on every supported platform.
- Held-out end-to-end evaluations show improved agent outcomes without a material patch-quality regression.
- Public claims can be reproduced from published methods and artifacts.
- Documentation is tested against the current command and file surfaces.

The target public workflow is:

```bash
pcodex setup
pcodex status
pcodex run --dry-run "Fix the failing test"
pcodex run "Fix the failing test"
pcodex review --since-compile
```

The target public command set is:

```text
setup
status
run
review
integrate
doctor
uninstall
```

Tuning, benchmarking, raw compilation, observers, lab runners, alternative selectors, and compatibility surfaces remain available only as clearly labeled advanced, developer, or research functionality.

## 3. Program rules

These rules apply to every segment of the roadmap.

### 3.1 Promotion rules

- No feature reaches the production path without deterministic tests and a user-visible reason to exist.
- Packet-size reduction cannot compensate for worse task quality.
- A held-out quality regression blocks promotion even when token or latency metrics improve.
- Compile-only estimates must not be reported as live provider savings.
- Generated artifacts and experimental branches are not release evidence unless the release gate explicitly names them.
- Codex and OpenClaw behavior must be tested through the supported installation surface, not only through internal Python calls.

### 3.2 Change-control rules

- Preserve the exact user prompt in the canonical packet.
- Do not turn pCodex into a planner or local reasoning engine.
- Keep observer and experimental packages isolated from production imports.
- Make every state-changing integration operation previewable and reversible.
- Never overwrite a user-authored integration file without explicit approval and a conflict report.
- Version every persisted schema and every public machine-readable receipt.

### 3.3 Required evidence for every milestone

Each milestone must produce:

- A named release candidate commit.
- A clean-tree validation receipt.
- Test commands and summarized results.
- A list of supported claims.
- A list of remaining unsupported claims.
- Upgrade, rollback, and cleanup instructions when state or installation behavior changes.

## 4. Delivery sequence

| Gate | Segment | Recommended duration | Target score after gate |
|---|---|---:|---:|
| G0 | Product contract and freeze | 3-5 days | 65 |
| G1 | Product and CLI consolidation | 1-2 weeks | 72 |
| G2 | Core, privacy, and state hardening | 2-3 weeks | 78 |
| G3 | Production Codex integration | 2 weeks | 83 |
| G4 | Production OpenClaw adapter | 2-3 weeks | 87 |
| G5 | Distribution and release engineering | 1-2 weeks | 89 |
| G6 | Held-out product proof | 3-4 weeks, partly parallel | 90+ |

Gates are sequential even when implementation work overlaps. A later gate cannot compensate for a failed earlier gate.

## 5. Must-have segment A: product contract and scope freeze

### Objective

Create one authoritative definition of the product before restructuring code or adding integrations.

### Best completion approach

Run a short product-boundary workshop using the current CLI, canonical docs, package surfaces, and generated files. Classify every surface as core, product adapter, advanced, research, or deprecated. Record the result in a machine-readable product manifest and a short human-readable release contract.

Do not decide scope from historical roadmaps. Decide it from the narrow user promise and the behavior that can be supported and tested now.

### Required work

- Choose one public product name and consistent capitalization.
- Choose one versioning scheme across core, plugin, MCP server, and adapters.
- Declare one production branch and release-candidate workflow.
- Declare one canonical packet renderer and schema.
- Declare one production ranking path.
- Declare the supported Codex surfaces and version range.
- Declare the supported OpenClaw surfaces and version range.
- List every generated or persisted file and its ownership.
- Define `dry-run`, `advisory`, `setup`, `cleanup`, and `uninstall` precisely.
- Classify existing commands and packages:
  - core;
  - Codex product;
  - OpenClaw product;
  - advanced/developer;
  - research/observer;
  - deprecated/compatibility.
- Freeze production ranking changes until G6 unless a release blocker requires one.

### Required artifacts

- `docs/PRODUCT_CONTRACT.md`
- `premode.product.json`
- A public command inventory.
- A generated-state ownership table.
- A deprecation and migration table.

### Required tests

- Validate `premode.product.json` against a checked-in schema.
- Verify every declared public command exists.
- Verify every persisted path has a declared owner, cleanup policy, and sensitivity classification.
- Verify the production package does not import observer modules.
- Verify public version strings are derived from one version source.

### Completion gate G0

G0 passes only when a reviewer can answer these questions from one document:

1. What does the product do?
2. What does it deliberately not do?
3. Which commands are supported?
4. Which packet and ranking path are production?
5. What files can it read or write?
6. Which integrations and versions are supported?
7. How is it removed?

## 6. Must-have segment B: one user journey and one CLI

### Objective

Make pCodex understandable without requiring knowledge of the internal research program.

### Best completion approach

Design the CLI from the first-run journey backward. Default output should answer three questions only: current status, what pCodex did, and the next action. Put diagnostic depth behind `--verbose` and stable automation data behind `--json`.

### Required work

#### Public help

- Show only the supported product commands in normal help.
- Move tuning, raw compile, benchmark, stress, lab, and plugin-development commands into advanced or developer namespaces.
- Give every public command a concise help description and examples.
- Fail closed on unknown commands without launching Codex.

#### Setup

- Make `pcodex setup` idempotent.
- Avoid tuning and MCP registration by default.
- Detect conflicts before writing files.
- Print exactly one recommended next command.
- Emit a versioned JSON receipt.

#### Status and doctor

- Use three primary states: `READY`, `NEEDS_ACTION`, and `BLOCKED`.
- Keep default output short.
- Add `pcodex doctor --strict` for automation.
- Return nonzero for missing required dependencies, invalid state, or unusable integration.
- Distinguish warnings from blockers.

#### Review and uninstall

- Keep review tied to the exact compile receipt and repository state.
- Add `pcodex uninstall --dry-run` and `pcodex uninstall --yes`.
- Preserve user-authored and unrelated plugin/config entries.
- Report exactly what was removed, preserved, or not found.

#### Documentation

Reduce the primary user documentation to:

- `README.md`
- `docs/GETTING_STARTED.md`
- `docs/CODEX_INTEGRATION.md`
- `docs/OPENCLAW_INTEGRATION.md`
- `docs/TROUBLESHOOTING.md`

Move obsolete alpha instructions, implementation reports, and completed plans under `docs/history/` or label them clearly as noncanonical.

### Required tests

#### CLI contract

- Public help contains every supported command.
- Public help excludes research-only terminology.
- Every public command supports a predictable success and failure exit code.
- Every JSON receipt validates against its schema.
- Human output contains no internal selector, experiment, or tuning identifiers by default.

#### Documentation contract

- Extract and parse every shell command in canonical docs.
- Confirm every documented flag exists.
- Confirm every referenced file exists.
- Confirm documented generated paths match implementation.
- Fail CI when a canonical command example becomes stale.

#### First-run usability

- Test setup in a clean fixture repository.
- Test setup in a dirty repository.
- Test setup twice and prove idempotency.
- Test existing user-authored `.agents` and plugin files.
- Test paths containing spaces.
- Test missing Codex and missing plugin strategy behavior.

### Evidence and metrics

- Median time from install to first useful dry run.
- Setup success rate.
- Percentage of testers requiring undocumented help.
- Most common setup failure reasons.

### Completion gate G1

G1 passes when five new testers can use only the Getting Started guide to reach a correct dry run, with a median completion time under ten minutes and no undocumented repair steps.

## 7. Must-have segment C: production core and package boundaries

### Objective

Turn the production compiler into a stable, understandable engine that is isolated from research machinery.

### Best completion approach

Extract contracts before splitting files. Refactor around request, selection, packet, receipt, safety, adapter, and state boundaries. Preserve existing ranking semantics during the structural pass.

### Required contracts

Define and version:

- `ContextRequestV1`
- `ContextSelectionV1`
- `ContextPacketV1`
- `ContextReceiptV1`
- `PacketStrategyPluginV1`
- `AgentAdapterV1`

Each contract needs:

- A Python protocol or typed data model.
- JSON Schema where it crosses a process boundary.
- Compatibility rules.
- Golden fixtures.
- Clear sensitivity classification for every field.

### Target package boundaries

```text
premode-core       inventory, safety, selection, canonical packet
premode-codex      Codex CLI, skills, plugin, optional MCP
premode-openclaw   OpenClaw detection, policy, and integration
premode-observer   research and evaluation only
```

These may remain in one repository initially, but production imports must follow the boundaries.

### Refactoring priorities

- Separate canonical packet rendering from legacy renderers.
- Separate production selection from experimental selectors.
- Separate repository inventory from model-facing packet creation.
- Separate state reads/writes from pure compilation.
- Separate Codex launching from pCodex compilation.
- Separate adapter policy from general repository detection.
- Decompose oversized modules by stable responsibility, not arbitrary line count.

### Performance approach

Optimize the whole production compile path rather than isolated selectors:

1. Measure end-to-end compile time and filesystem reads.
2. Add a safe candidate shortlist or reusable index.
3. Preserve content-aware reranking for ambiguous cases.
4. Retain deterministic fallback when the index is missing or stale.
5. Promote only after held-out quality equivalence.

### Required tests

- Import-isolation tests for all four package boundaries.
- Golden canonical-packet tests.
- Schema compatibility tests.
- Determinism tests across repeated runs and process restarts.
- Tests proving the exact prompt appears once.
- Tests proving diagnostic and experimental fields never enter the canonical packet.
- Tests proving production behavior is unchanged during structural refactoring.
- End-to-end performance benchmarks for small, medium, large, and asset-heavy fixtures.

### Completion gate G2-core

The production path must be explainable as a short pipeline, import no observer code, use one canonical packet, and preserve baseline retrieval quality within the agreed tolerance.

## 8. Must-have segment D: privacy, security, state, and reversibility

### Objective

Make every trust claim mechanically enforceable.

### Best completion approach

Treat filesystem access, persisted state, model-visible output, and integration mutation as separate security boundaries. Build adversarial tests around each boundary before relying on documentation.

### Required work

#### Literal no-write modes

The following operations must perform zero writes:

```bash
pcodex status --advisory
pcodex doctor --advisory
pcodex run --dry-run
pcodex integrate codex --dry-run
pcodex integrate openclaw --dry-run
pcodex uninstall --dry-run
```

They must not:

- Create `.premode` or `.pcodex`.
- Refresh inventory or topology state.
- Record telemetry.
- Create unmanaged packet files.
- Update timestamps or counters.
- Modify repo, user, Codex, MCP, or OpenClaw configuration.
- Launch Codex or OpenClaw.

If a required cache is missing, report the planned refresh rather than writing it.

#### MCP containment

- Bind each MCP server process to one resolved workspace root.
- Remove arbitrary `project_root` from model-callable tool input.
- Reject traversal, absolute-path escape, and symlink escape.
- Return minimal model-visible data.
- Keep diagnostics in local receipts keyed by opaque IDs.
- Do not expose prompt text, packet paths, absolute roots, or internal metadata unless explicitly required by the user-facing tool contract.

#### Data retention

- Do not persist raw prompts or packets by default.
- Store explicitly requested audit data in one managed directory.
- Use restrictive permissions.
- Define retention and maximum size.
- Add cleanup and uninstall coverage.
- Make partial and interrupted writes atomic and recoverable.

#### Integration writes

- Generate a conflict report before modification.
- Track file ownership and hashes in an install receipt.
- Never delete or overwrite a changed user file automatically.
- Provide symmetric preview, apply, status, repair, and uninstall operations.

### Required tests

#### Byte-level no-write tests

- Snapshot file paths, hashes, sizes, and timestamps before each no-write command.
- Run the command in clean, missing-state, stale-state, corrupt-state, and dirty-repo conditions.
- Assert the snapshot is unchanged.
- Inspect temporary directories for leaked packet files.
- Assert no child Codex/OpenClaw process starts.

#### Filesystem adversarial tests

- `../` traversal.
- Absolute paths.
- Symlink chains and loops.
- Nested repositories.
- Case-folding collisions.
- Paths with spaces and Unicode.
- FIFOs, devices, sockets, and unreadable files.
- Very large and binary files.
- Secret-like filenames.
- Generated, historical, state, and proof directories.

#### Prompt adversarial tests

- Requests to inspect outside the repository.
- Prompt injection inside README, docs, logs, or generated artifacts.
- Fake authority declarations.
- Secret-exfiltration requests.
- Shell interpolation and command-substitution text.
- Very long prompts and control characters.

#### State tests

- Atomic writes.
- Interrupted writes.
- Corrupt JSON.
- Unknown future schema.
- Upgrade and downgrade behavior.
- Concurrent readers and writers.
- Cleanup of only owned state.

### Completion gate G2-security

G2-security passes only with zero no-write violations, zero root-containment violations, zero unmanaged prompt/packet files, and a successful rollback/uninstall matrix.

## 9. Must-have segment E: production Codex integration

### Objective

Make pCodex installable and verifiable as one supported Codex plugin rather than a collection of repo-local scaffolds.

### Best completion approach

Adopt the current Codex plugin structure directly. Keep terminal pCodex as the dependable fallback, but make the plugin the distributable Codex experience. Deprecate duplicate plugin paths instead of maintaining two implementations.

### Required work

#### One plugin

- Use `plugins/pcodex` as the canonical source unless the product contract selects otherwise.
- Retire the legacy plugin installer that creates a separate `premode-router` plugin tree.
- Provide a migration preview and cleanup receipt for legacy installations.
- Derive core, plugin, and MCP versions from one source.

#### Complete manifest

The manifest must declare:

- Stable name and version.
- Description and developer identity.
- Skills path.
- `mcpServers` path only when MCP is included.
- Hooks only when supported and required.
- Interface metadata.
- Icons and screenshots.
- Homepage, repository, license, privacy, and terms links.
- Starter prompts that reflect supported behavior.

#### Correct MCP approval behavior

- Without `--with-mcp`, do not write or advertise an MCP configuration.
- With `--with-mcp`, preview the file and permissions first.
- Do not mutate global Codex config by default.
- Print exact activation and removal instructions.
- Continue to treat automatic subagent interception as unsupported until directly proven through a supported hook.

#### Installed skill behavior

- Resolve helpers relative to the installed plugin root or installed executable.
- Do not assume the target repository already contains `.agents/skills/pcodex/bin`.
- Use advisory status before any potentially state-refreshing dry run.
- Keep skill descriptions narrow enough for reliable triggering.

### Required tests

#### Manifest and marketplace

- Validate manifest fields and relative paths.
- Confirm every referenced file is packaged.
- Add the marketplace to each supported Codex version.
- Install the plugin from the marketplace.
- Verify skill discovery in a new task.
- Verify optional MCP is disabled by default.
- Enable, call, disable, and remove MCP.
- Remove the plugin and confirm no owned files or registration remain.

#### MCP conformance

- Initialize and protocol negotiation.
- Tool listing and schema.
- Valid invocation.
- Invalid JSON and unknown methods.
- Missing and oversized task input.
- Root containment and symlink escape.
- Concurrent requests.
- Cancellation and shutdown.
- Error responses without sensitive data.
- No-write dry-run.

#### End-to-end Codex fixture

1. Install pCodex.
2. Install the Codex plugin.
3. Open a clean fixture repository.
4. Run a dry preflight.
5. Confirm expected likely paths.
6. Run one disposable Codex edit task.
7. Confirm changed-file boundaries.
8. Run review and validation.
9. Disable and uninstall the plugin.
10. Confirm clean removal.

### Completion gate G3

G3 passes when a beta tester can install, discover, use, disable, upgrade, and uninstall the Codex plugin without manually editing configuration, and when the MCP boundary passes all containment and no-write tests.

## 10. Must-have segment F: production OpenClaw adapter

### Objective

Turn OpenClaw-specific repository intelligence into a real installable integration.

### Best completion approach

Build a dedicated, minimal OpenClaw adapter. Reuse the general core and OpenClaw authority policy, but do not ship the frozen observer profile or machine-specific validation executor as product code.

### Required commands

```bash
pcodex integrate openclaw --dry-run
pcodex integrate openclaw --write
pcodex integrate openclaw --status
pcodex integrate openclaw --repair
pcodex integrate openclaw --uninstall
```

### Required tool contract

Expose a narrow tool such as `premode_preflight`.

Inputs:

- Exact task.
- Optional supported profile.

Outputs:

- Ordered likely paths.
- Authority classifications.
- Dangerous mutation zones.
- Expected validation surfaces.
- Opaque receipt ID.

The configured OpenClaw workspace is the immutable root. The model must not select an arbitrary root.

### Required behavior

- Detect current authority surfaces.
- Demote generated and historical evidence unless explicitly task-named.
- Recognize dangerous state, bridge, Unreal, Blender, executor, and task-queue mutation zones.
- Preserve the exact task.
- Perform no arbitrary command execution.
- Require no broad filesystem access outside the workspace.
- Support configurable executable locations.
- Work on macOS and Linux.
- Keep validation execution separate from context selection.

### Fixture matrix

- Complete OpenClaw control-plane repository.
- Minimal OpenClaw repository.
- OpenClaw-like false positive.
- Nested Node/Web executor.
- Unreal workspace with control-plane wrappers.
- Blender pipeline.
- Missing authority surfaces.
- Conflicting current and historical state.
- Misleading instructions in generated evidence.
- Repository path containing spaces.

### Required tests

- Correct adapter detection and false-positive rejection.
- Current authority outranks generated evidence.
- Explicitly named files receive appropriate promotion.
- Nested executors do not steal repository-root authority.
- Dangerous zones are identified accurately.
- Historical proof does not become operating guidance.
- No path outside the configured workspace can be read.
- Install, repair, and uninstall preserve unrelated OpenClaw configuration.
- Compatibility tests across every supported OpenClaw version and platform.

### Held-out OpenClaw acceptance set

Run at least 20 frozen tasks spanning:

- Read-only investigation.
- Source modification.
- Validation repair.
- State and authority reconciliation.
- Unreal integration.
- Blender integration.
- Nested executor work.

Measure file selection, forbidden-path compliance, patch quality, validation outcome, and unnecessary exploration.

### Completion gate G4

G4 passes when an OpenClaw user can install the adapter with one command, receive correct authority-aware context, and completely remove it without knowing pCodex internals or machine-specific lab paths.

## 11. Must-have segment G: packaging, CI, upgrades, and supportability

### Objective

Make installation and release behavior independent of the developer's workstation.

### Best completion approach

Build packages in clean environments, test the installed artifacts rather than the source tree, and treat upgrade/uninstall behavior as first-class product functionality.

### Required distribution

Preferred public form:

```bash
pipx install pcodex
```

An equivalent `uv tool install` path may also be supported. Private beta releases may use signed wheels or a signed bundle until registry publication is authorized.

The standard production strategy must be included automatically. Users must not install a second package to obtain the default behavior.

### Required CI matrix

- Python 3.11, 3.12, and 3.13.
- macOS and Linux.
- Unit tests.
- Integration tests.
- Packaging and clean-install tests.
- Codex manifest and marketplace validation.
- MCP conformance tests.
- OpenClaw adapter tests.
- Documentation command tests.
- Type checking.
- Linting and formatting checks.
- Dependency, secret, and security scanning.
- Release artifact verification.

### Required release artifacts

- Wheel and source distribution.
- SHA-256 checksums.
- Signed provenance.
- SBOM.
- Changelog.
- Migration notes.
- Rollback instructions.
- Supported-version matrix.
- Known limitations.

### Required lifecycle commands

- Install.
- Status.
- Upgrade check.
- Upgrade.
- Repair.
- Uninstall preview.
- Uninstall apply.

### Required tests

#### Fresh install

- Clean macOS and Linux environment.
- No existing pCodex state.
- No existing Codex/OpenClaw integration.
- Path containing spaces.
- Offline operation after artifact download.
- Missing optional runtime.

#### Upgrade

- Previous supported beta to current.
- Legacy plugin present.
- Existing generated state.
- Existing verified tuning state.
- Partial installation.
- Interrupted upgrade.
- Corrupt manifest or state.
- Unsupported downgrade attempt.

#### Uninstall

- Remove only owned files and registrations.
- Preserve user-modified files and report them.
- Preserve unrelated marketplace entries and MCP servers.
- Remove managed state only when requested.
- Verify reinstall after uninstall.

### Completion gate G5

G5 passes when the same signed release artifacts install, upgrade, validate, roll back, and uninstall successfully across the supported matrix without relying on the source checkout.

## 12. Must-have segment H: held-out outcome proof and market readiness

### Objective

Demonstrate that pCodex improves real agent work, not only packet structure.

### Best completion approach

Use a frozen, leakage-audited evaluation corpus with a small number of meaningful arms. Compare the untreated agent with the production pCodex path. Do not use the public evaluation as another broad algorithm shootout.

### Minimum corpus

- At least 10 repositories.
- At least 100 frozen tasks.
- Explicit development and held-out partitions.
- Repositories not used to design the production ranking rules.
- Multiple languages, layouts, and repository sizes.

Recommended coverage:

- Small Python package.
- Python web service.
- React or Next.js application.
- TypeScript monorepo.
- Swift/iOS project.
- Go or Rust service.
- Documentation-heavy repository.
- Messy legacy repository.
- Asset-heavy repository.
- OpenClaw control-plane repository.

### Evaluation arms

1. Standard agent without pCodex.
2. Production pCodex general mode.
3. Production pCodex OpenClaw mode where applicable.

### Primary metrics

#### Retrieval

- Top-1 precision.
- Top-3 and top-5 relevant-file recall.
- Relevant-test recall.
- Forbidden/generated-path selection rate.
- Empty and fallback rates.

#### Agent outcome

- Task success.
- Patch correctness.
- Validation success.
- Scope violations.
- Unrelated file changes.
- Repair turns.
- Time to completion.
- Unnecessary file reads.

#### Efficiency

- End-to-end wall time.
- Actual provider input/output tokens where available.
- Cache usage.
- Tool calls.
- Repeated reads.
- Compiler overhead.

#### Trust

- Secret exposure.
- No-write violations.
- Root-containment failures.
- Stale/generated evidence treated as authority.
- Cleanup and uninstall failures.

### Initial promotion thresholds

These thresholds should be frozen before the held-out run:

| Metric | Required threshold |
|---|---:|
| Top-5 relevant-file recall | at least 90% |
| Relevant-test recall | at least 85% |
| Forbidden/generated-path selection | below 1% |
| Dry-run write violations | 0 |
| Root-containment violations | 0 |
| Patch-quality regression | no more than 2 percentage points |
| Scope violations | at least 25% lower than baseline |
| Unnecessary file reads | at least 20% lower than baseline |
| Compiler p95, normal repository | below 1 second |
| Compiler p95, large repository | below 3 seconds |
| Supported-system install success | at least 95% |
| Tested rollback/uninstall success | 100% |

If token usage improves but patch quality fails the threshold, promotion is blocked.

### Required public evidence

Publish at least three reproducible case studies:

1. Conventional application repository.
2. Large or messy monorepo.
3. OpenClaw proof-governed repository.

Each case study must include:

- Repository and commit.
- Frozen tasks.
- Exact commands.
- Baseline configuration.
- pCodex configuration.
- Selected paths.
- Patch and validation outcomes.
- Token and latency measurements when available.
- Failures and negative results.
- Reproduction instructions.

### Marketing rules

- Lead with deterministic local context and reviewability.
- Do not lead with token-savings percentages until the methodology is public and reproducible.
- Label compile-only measurements as structural or proxy results.
- Use held-out live results for task-quality and provider-usage claims.
- State supported repositories and known weak cases explicitly.

### Completion gate G6

G6 passes when an external reviewer can reproduce the major product claims and the held-out release candidate clears every frozen quality, safety, installation, and performance threshold.

## 13. Cross-segment test suites

The following named suites should become durable release surfaces.

### Suite 1: core contract

- Request, selection, packet, and receipt schemas.
- Exact-task preservation.
- Canonical packet fields.
- Determinism.
- Plugin compatibility.

### Suite 2: no-write and privacy

- Advisory commands.
- Dry-run commands.
- Temp-file inspection.
- Telemetry and timestamp checks.
- Model-visible output leakage checks.

### Suite 3: repository safety

- Root containment.
- Traversal and symlinks.
- Secret and sensitive paths.
- Generated/history/state paths.
- Nested repositories.

### Suite 4: Codex product

- Plugin manifest.
- Marketplace discovery.
- Skill resolution.
- Optional MCP.
- End-to-end fixture task.
- Removal and migration.

### Suite 5: OpenClaw product

- Detection and false positives.
- Authority ranking.
- Dangerous mutation zones.
- Integration lifecycle.
- Version/platform compatibility.

### Suite 6: packaging and lifecycle

- Clean install.
- Upgrade.
- Interrupted operation.
- Repair.
- Rollback.
- Uninstall and reinstall.

### Suite 7: held-out outcome evaluation

- Frozen task corpus.
- Leakage receipts.
- Standard versus production pCodex.
- Patch-quality review.
- Live usage when authorized.

## 14. Project management structure

### Recommended workstreams

| Workstream | Owns | Must not own |
|---|---|---|
| Product contract | scope, commands, docs, claims | ranking experiments |
| Core | contracts, selection, packet, safety | Codex/OpenClaw UI |
| Codex adapter | plugin, skills, MCP, lifecycle | general ranking policy |
| OpenClaw adapter | authority policy and integration | observer experiments |
| Release engineering | packages, CI, upgrade, uninstall | product scope decisions |
| Evaluation | corpus, baselines, metrics, reports | production implementation |

Keep evaluation review independent from the implementation workstream whenever practical.

### Milestone record

Every milestone should track:

- Owner.
- Start date.
- Target date.
- Baseline commit.
- Allowed files or package boundary.
- Required test suites.
- Evidence directory.
- Risks.
- Decision: pass, revise, or block.

### Weekly operating rhythm

1. Monday: select one gate-level outcome and freeze its acceptance criteria.
2. Midweek: run focused tests and update risks.
3. Friday: validate from a clean install or worktree.
4. End of week: publish a short receipt with completed, failed, and deferred work.

Do not report a percentage complete based only on tasks checked off. Report which release gates have passed.

## 15. Recommended first six implementation tickets

These tickets provide the highest-leverage start.

### T90-001: freeze the product contract

Deliver `PRODUCT_CONTRACT.md`, `premode.product.json`, the public command inventory, and the surface classification.

### T90-002: create the canonical documentation set

Create the five primary user documents, redirect current entrypoints to them, and move stale plans out of the canonical path.

### T90-003: make dry-run byte-identically no-write

Cover CLI dry-run, MCP dry-run, Codex integration preview, OpenClaw integration preview, and uninstall preview.

### T90-004: consolidate the two Codex plugin systems

Select one plugin root, provide migration, unify versions, correct the manifest, and test marketplace installation.

### T90-005: bind MCP to one workspace

Remove caller-selected roots, minimize model-visible output, eliminate unmanaged packet files, and add adversarial containment tests.

### T90-006: establish installed-artifact CI

Build wheels, install them in clean macOS/Linux environments, run the public workflow, and uninstall them.

## 16. Final 90/100 release checklist

### Product

- [ ] One public name.
- [ ] One production branch.
- [ ] One canonical packet.
- [ ] One production ranking path.
- [ ] One Codex plugin.
- [ ] One OpenClaw adapter.
- [ ] One first-run path.

### Installation and lifecycle

- [ ] One-command installation.
- [ ] Under-five-minute median activation.
- [ ] Upgrade and repair commands.
- [ ] Complete uninstall and rollback.
- [ ] Signed artifacts and checksums.
- [ ] Supported platform/runtime matrix.

### Safety and privacy

- [ ] Dry-run proven zero-write.
- [ ] Advisory proven zero-write.
- [ ] MCP permanently bounded to one workspace.
- [ ] Symlink and traversal tests pass.
- [ ] No unmanaged prompt or packet files.
- [ ] No internal diagnostics in model-facing output.
- [ ] Integration conflicts are previewed.
- [ ] Every owned write is reversible.

### Quality

- [ ] CI passes on every supported platform and Python version.
- [ ] Core contract suite passes.
- [ ] Codex discovery and lifecycle suite passes.
- [ ] MCP conformance suite passes.
- [ ] OpenClaw compatibility suite passes.
- [ ] Packaging, upgrade, and uninstall suite passes.
- [ ] Documentation command suite passes.
- [ ] State migration suite passes.

### Evidence and market readiness

- [ ] Frozen, leakage-audited corpus.
- [ ] At least 100 representative held-out tasks.
- [ ] Untreated baseline comparison.
- [ ] Retrieval thresholds pass.
- [ ] Patch-quality threshold passes.
- [ ] Safety thresholds pass.
- [ ] Live usage measured where authorized.
- [ ] Three reproducible public case studies.
- [ ] Marketing statements match the published evidence.

## 17. Release decision

The 90/100 release is approved only when G0 through G6 pass and every unchecked item in the final checklist is either completed or explicitly removed from the declared product contract.

The release must be blocked when any of the following is true:

- Dry-run or advisory mode writes unexpectedly.
- MCP can inspect outside its configured repository.
- Installation or uninstall can overwrite or remove unrelated user state.
- The canonical documentation does not match the current CLI.
- Codex or OpenClaw integration depends on machine-specific lab paths.
- Held-out patch quality materially regresses.
- Public savings or quality claims cannot be reproduced.

The fastest route to completion is therefore:

1. Consolidate the product and documentation.
2. Make the privacy and no-write contracts literal.
3. Finish one supported Codex plugin.
4. Ship one real OpenClaw adapter.
5. Package and test installed artifacts.
6. Prove outcomes on a frozen held-out corpus.
