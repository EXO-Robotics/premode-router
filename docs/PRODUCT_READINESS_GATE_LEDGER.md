# Product-Readiness Gate Ledger

Status date: 2026-07-13
Campaign branch: `product/codex-beta-v1`
Accepted campaign baseline: `88b459ca79ebd04149bb0719405656df2c904292`
Current integrated milestone implementation: `9131d680c1542c1cb54fc29f09f35c832290eb95`

The gate authority is `docs/ROADMAP_TO_90.md`. Later evidence cannot compensate for an earlier failed gate.

## Threshold reconciliation

- Activation: the product target is a useful dry run in under five minutes. G1 minimum acceptance is a five-person median under ten minutes with no undocumented repair. The 90/100 aspiration remains a median under five minutes.
- G2 reporting: G2 is one ordered gate with separately reported `G2-core` and `G2-security` decisions. Both must pass.
- Public CLI: the seven-command target describes the primary journey. `repair` is a supported lifecycle command. The roadmap's product-level upgrade check/apply commands are not yet implemented; artifact-level upgrade/rollback proof does not waive that remaining G5 requirement.
- Installation: the automated supported platform/Python lifecycle matrix requires 100% success. Human invited-beta activation requires at least 95%, with every failure preserved and explained.
- Release phases: Phase A is the Codex-first invited technical beta. Phase B is the literal 90/100 release and includes production OpenClaw, G5 distribution, and G6 proof. Passing Phase A never waives Phase B.
- Publication: release-candidate evidence can pass without publishing. Tags, package upload, marketplace publication, public release, or promotion require separate authorization.

## Ledger

| Gate | Baseline/evidence | Implementation | Qualification | Current blocker | Debt | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| G0 — product contract and scope | `premode.product.json`, `docs/PRODUCT_CONTRACT.md`, `docs/ROADMAP_TO_90.md` | complete | contract/schema tests pass | none | none | passed |
| G1 — product and CLI consolidation | public parser tests, strict doctor, lifecycle tests, first-run fixtures | complete | automated journeys pass | five-person external study not executed | median activation evidence | substantially_complete |
| G2-core | canonical packet, `ProductionRankingProviderV1`, managed state, repair/uninstall | complete | full repository suite and clean artifact lifecycle pass | none | algorithm lane may retain incumbent | passed |
| G2-security | no-write receipts, containment, ownership, scanners | complete | macOS/Linux and Python 3.11-3.13 CI and Stage 2 clean-artifact proof pass | none | broader adversarial review continues | passed |
| G3 — production Codex integration | canonical plugin lifecycle and Codex 0.143 discovery | substantially complete | wheel/sdist lifecycle, live discovery, and optional MCP registration lifecycle pass | full optional-MCP protocol, containment, cancellation, shutdown, and sensitive-error conformance remain | broader Codex versions are unsupported | substantially_complete |
| G4 — production OpenClaw adapter | experimental detection/policy only | not started | not started | product lifecycle, containment, compatibility, and 20-task acceptance set absent | full G4 scope | not_started |
| G5 — distribution and release engineering | workflows `29301111990` and `29302610473`, reproducible wheel/sdist, SBOM, provenance, rollback | substantially complete | macOS/Linux × Python 3.11-3.13 passed twice, including the Stage 2 contract boundary | product-level upgrade check/apply commands and final RC evidence remain | Windows not supported | substantially_complete |
| G6 — held-out product proof | protocol foundations only | not started | not started | frozen 10-repository/100-task corpus and case studies absent | external/model execution | not_started |

## Milestone receipts

### Stage 1 — Packaging and CI Matrix

- Classification: passed.
- Starting SHA: `88b459ca79ebd04149bb0719405656df2c904292`.
- Final SHA: `87e68a90e7b51ccb8e33af355f13026bd23fd4e6`.
- Remote evidence: workflow `29301111990`; all six test jobs, all six artifact jobs, reproducibility, release evidence, static quality, and history scanning passed. The dependency-review action was skipped because the run was manually dispatched; the pinned `pip-audit` job passed in static quality.
- Supported claim: reproducible, qualified wheel and sdist on declared macOS/Linux and Python 3.11-3.13 matrix.
- Unsupported claim: publication or Windows support.

### Stage 2 — Contract and Import-Boundary Stabilization

- Classification: passed.
- Starting SHA: `87e68a90e7b51ccb8e33af355f13026bd23fd4e6`.
- Final SHA: `904d5762f37a3dcff057a919c5d34ee6ce007b74`.
- Tests: complete repository suite passed; focused contract/import/artifact suites passed; mypy, Ruff, compilation, schema validation, product-manifest validation, public hygiene, Bandit, Detect Secrets, Semgrep, and `pip-audit` passed.
- Artifacts: wheel SHA-256 `2f040a7004eac12ac97155cec67b324a7c74c517a7cfee064ef209ac4bb7d612`; sdist SHA-256 `ae4b868fd0b035a56611a0f9855bbed1134b7e29a1722142a0457b9956812ec4`.
- Artifact evidence: preserved in the controller's private qualification output; it is not a publication surface.
- Independent review: three read-only lanes ended at P0=0/P1=0 after fixes.
- Supported claim: six strict cross-process contracts, exact installed golden parity, transitive research-import isolation, and byte-equivalent typed packet boundaries.
- Unsupported claim: a new algorithm or broader task-quality result.
- Remote evidence: workflow `29302610473`; all six test jobs, six artifact jobs, reproducibility, release evidence, static quality, and history scanning passed. Dependency review was correctly skipped for the manual dispatch.

### Stage 3 — Canonical Documentation and First-Run Qualification

- Classification: substantially complete; external human evidence pending.
- Starting SHA: `904d5762f37a3dcff057a919c5d34ee6ce007b74`.
- Implementation SHA: `9131d680c1542c1cb54fc29f09f35c832290eb95`.
- Canonical set: the ten documents declared by `documentation_contract` in `premode.product.json`.
- Automated evidence: 1,273 passed and 5 skipped in the complete repository suite; 192 passed and 4 skipped in the focused suite; static executable, command, flag, semantic-combination, containment, link, referenced-file, generated-path, version-role, and JSON-schema validation; blind tester-bundle isolation; CI wiring; first-run fixture qualification.
- Study kit: deterministic five-fixture archives, restoration commands, receipt schema/templates, content-free aggregate validator, and separate blind/coordinator payloads.
- Independent review: three read-only lanes ended at P0=0/P1=0 after fixes.
- External evidence: `docs/FIRST_RUN_STUDY_PROTOCOL.md` freezes the five-person study and reconciled activation thresholds. No tester result is inferred from automation.
- Current blocker: five eligible human tester receipts have not been collected.
