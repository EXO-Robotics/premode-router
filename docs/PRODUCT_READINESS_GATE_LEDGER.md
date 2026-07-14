# Product-Readiness Gate Ledger

Status date: 2026-07-14
Campaign branch: `product/codex-beta-v1`
Accepted campaign baseline: `88b459ca79ebd04149bb0719405656df2c904292`
Current integrated milestone implementation: `a96d5055be6a8593a007487c8a4f30ce7fadfeb5`

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
| G2-core | canonical packet, `ProductionRankingProviderV1`, frozen incumbent handoff, managed state, repair/uninstall | complete | full repository suite, clean artifact lifecycle, and nine-case production behavior freeze pass | none | later algorithm promotion must use the immutable handoff contract | passed |
| G2-security | no-write receipts, containment, ownership, scanners | complete | macOS/Linux and Python 3.11-3.13 CI and Stage 2 clean-artifact proof pass | none | broader adversarial review continues | passed |
| G3 — production Codex integration | canonical plugin lifecycle, bounded optional MCP, and Codex 0.143 discovery | complete | macOS/Linux wheel/sdist lifecycle, live discovery, workspace binding, protocol, containment, cancellation, shutdown, and sensitive-error checks pass | none | broader Codex versions are unsupported | passed |
| G4 — production OpenClaw adapter | experimental detection/policy only | not started | not started | product lifecycle, containment, compatibility, and 20-task acceptance set absent | full G4 scope | not_started |
| G5 — distribution and release engineering | workflows `29301111990`, `29302610473`, and `29311089717`; reproducible wheel/sdist, SBOM, provenance, rollback | substantially complete | macOS/Linux × Python 3.11-3.13 and frozen-algorithm artifact authorities pass | product-level upgrade check/apply commands and final RC evidence remain | Windows not supported | substantially_complete |
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
- Qualification repair SHA: `d86b7f6cbf1d30b4afbb40202ae489fd568bc998`.
- Canonical set: the ten documents declared by `documentation_contract` in `premode.product.json`.
- Automated evidence: 1,273 passed and 5 skipped in the complete repository suite; 192 passed and 4 skipped in the focused suite; static executable, command, flag, semantic-combination, containment, link, referenced-file, generated-path, version-role, and JSON-schema validation; blind tester-bundle isolation; CI wiring; first-run fixture qualification.
- Study kit: deterministic five-fixture archives, restoration commands, receipt schema/templates, content-free aggregate validator, and separate blind/coordinator payloads.
- Independent review: three read-only lanes ended at P0=0/P1=0 after fixes.
- Corrective qualification: the first committed builder run exposed repeated missing-Codex installation writes. The repair made valid receipt-owned missing-Codex installs idempotent while preserving fail-closed damaged, interrupted, unknown, and unsupported-version states; corrective re-review ended at P0=0/P1=0.
- Artifacts: wheel SHA-256 `cff10c0443cc421e9207c39abde0d90d7ca8b3f995f9ae194bd59c691b123bb2`; sdist SHA-256 `353a21604c014b138b186c75ec9586af85e87d07d8264e537310046cca1c988b`.
- Installed-artifact evidence: wheel and sdist lifecycle, live Codex `0.143.0`, missing-Codex lifecycle, no-write, package allowlist, upgrade/rollback, and parity passed from the clean corrective commit.
- Study-kit evidence: two independent materializations were byte-identical; the kit is bound to the qualified wheel and qualification receipt hashes.
- Remote evidence: workflow `29305106614`; six test jobs, six artifact jobs, reproducibility, release evidence, static quality, and history scanning passed. Dependency review was correctly skipped for manual dispatch.
- External evidence: `docs/FIRST_RUN_STUDY_PROTOCOL.md` freezes the five-person study and reconciled activation thresholds. No tester result is inferred from automation.
- Current blocker: five eligible human tester receipts have not been collected.

### G3 — Canonical Codex Plugin and Optional MCP Closure

- Classification: passed.
- Canonical plugin implementation SHA: `a2095ab28bb0f3b9b563c6d6357f18f09cc57275`.
- Diagnostic evidence preservation SHA: `72cd619`.
- Linux process-observation repair SHA: `8167f0e`.
- Qualification: canonical plugin preview/install/status/repair/disable/uninstall/reinstall; legacy migration; exact registration ownership; optional MCP disabled by default; immutable workspace binding; initialization, tool schema, invocation, invalid input, traversal, symlink, concurrency, cancellation, shutdown, and sensitive-error checks.
- Installed-artifact evidence: wheel and sdist lifecycle and literal no-write probes passed on macOS and Linux with Codex `0.143.x`.
- Independent review: three read-only lanes ended at P0=0/P1=0 after fixes.
- Remote evidence: workflow `29309004411`; six test jobs, six artifact jobs, reproducibility, release evidence, static quality, and history scanning passed. Dependency review was correctly skipped for manual dispatch while pinned `pip-audit` passed.
- Supported claim: production Codex integration is qualified for the declared Codex `0.143.x`, macOS/Linux, and Python 3.11-3.13 matrix.
- Unsupported claim: broader Codex-version compatibility or marketplace publication.

### Stage 4 — Production Algorithm Handoff and Integration

- Classification: passed with the incumbent retained; no algorithm behavior changed.
- Starting SHA: `8167f0e`.
- Implementation SHA: `688697e6b6303d03b644e960a4cad4b06b3deaeb`.
- CI security corrective SHA: `a96d5055be6a8593a007487c8a4f30ce7fadfeb5`.
- Promotion decision: `no_candidate_promoted`; the incumbent baseline remains `b9aede455c8d49217ef0a67e8dec0c8cf2c565a6` with tree `8120490deb23457d19299b09d5291783753f2066`.
- Production freeze: nine real compile/provider cases covering narrow, broad, five representative abstention shapes, and explicit provider-returned fallback; exact task appears once; SHA-256 `f4499af2b068a8802d3abaadbd360e804facebf4afc5dc6f461ee3fd12e2714c`.
- Native evidence accounting: 36 complete receipts and 6 preserved exclusions. All 11 aggregate evidence authorities, disclosure classes, qualification scopes/dimensions, supported/prohibited claims, and known limitations are exact-bound without opening private evidence.
- Tests: 1,335 passed and 5 intentional skips in the final local full suite; focused algorithm/productization suites, Ruff, mypy, compilation, schema validation, documentation validation, product-manifest validation, public hygiene, Bandit, Detect Secrets, Semgrep, pip-audit, Gitleaks, and TruffleHog passed locally or in the remote matrix.
- Independent review: three read-only lanes ended at P0=0/P1=0. The CI secret-exclusion correction received a separate P0=0/P1=0 re-review and credential-shaped negative regression probes.
- Artifacts: wheel SHA-256 `f337ecc1ccff0328ac4edb66d313b72f143f85ac71f63560a7ad831e38f7ff4f`; sdist SHA-256 `d118f8fe445bfd7b1e3533544477ad6ebc1aa1884a79e84f85786820bcdac18b`; handoff SHA-256 `9aec0dc9b800cc7869b2ab61b0eb7b6eb4de3f7a578acbe617272f9ae8e8553a`; handoff-schema SHA-256 `06ed2871b4e898a374d3853c6235422e48c856fdc6c4be84b03e81fc6e7cde5d`.
- Installed-artifact evidence: wheel/sdist no-write, lifecycle, Codex discovery, upgrade/rollback, archive safety, package allowlist, parity, SBOM, provenance, standalone handoff authorities, and package removal passed from the clean corrective commit.
- Remote evidence: workflow `29311089717`; six test jobs, six artifact jobs, reproducibility, release evidence, static quality/security, and full-history scanning passed. Dependency review was correctly skipped for manual dispatch while pinned `pip-audit` passed.
- Supported claim: one frozen, qualified incumbent production path exists behind `ProductionRankingProviderV1`, with explicit abstention/fallback contract compatibility and no experiment identifiers in public artifacts.
- Unsupported claim: a newly promoted algorithm, universal savings, or final held-out release qualification.
