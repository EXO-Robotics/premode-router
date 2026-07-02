# Changelog

## v0.2.6.24

- Reframed compiled packets as data packets around the exact canonical user prompt.
- Removed model-facing planner layers from rendered packets while keeping compatibility JSON fields stable.
- Preserved safety boundaries, candidate context, discovered command evidence, and review-contract drift checks.
- Bumped package version to `0.2.6.24`.

## v0.2.6.23

- Tightened the product boundary: Pre-mode is documented as a context compiler/routing formatter, not a local reasoning engine or implementation planner.
- Added `premode compile --context-only` to compile candidate context, suggested tests/commands, cache metrics, and safety boundaries without strong allowed-edit narrowing.
- Added user-facing `candidate_edit_files`, `read_only_support_files`, `prompt_forbidden_files`, `safety_blocked_files`, `suggested_tests`, and `suggested_commands` aliases while preserving legacy `likely_edit_files` and `allowed_edit_files`.
- Cleaned review-patch wording so reports say patches stayed inside or touched files outside the saved context contract, including prompt-forbidden and safety-blocked buckets.
- Documented the adapter expansion freeze: prefer `.premode/profile.yml` or generic structural profiles unless a major safety false-positive requires core support.
- Marked `premode plugin`, `premode hook`, `premode mcp-server`, and `premode lab` as experimental/deferred surfaces outside the primary MVP workflow.
- Added release manifest exclusions for git, virtualenv, pycache, pytest cache, `.DS_Store`, and generated `.premode` runtime outputs.
- Removed Goldpine-specific root-affinity logic from universal adapter detection while preserving generalized Swift/iOS routing and profile-scoped OpenClaw/control-plane behavior.
- Bumped package version to `0.2.6.23`.

## v0.2.6.22

- Added .NET/C#, Zig, and Haskell Stack/Cabal adapter detection, source routing, related-test mapping, command discovery, and review-contract allowed-edit bridging.
- Kept .NET project files, Zig build metadata, and Stack/Cabal package metadata read-only unless explicitly requested as build/package/project configuration changes.
- Added packet-bound review-patch pass coverage for a .NET allowed-source edit.
- Preserved v0.2.6.21 adapter review-contract behavior and existing routing safety invariants.
- Bumped package version to `0.2.6.22`.

## v0.2.6.21

- Bridged safe Elixir/Phoenix, PHP/Composer, Ruby/Rails, and Terraform adapter `likely_edit_files` into `patch_boundary.allowed_edit_files` and saved `review_contract.allowed_edit_files`.
- Kept central routing safety filtering in front of the bridge so manifests, generated/build outputs, state/proof/runtime files, secrets, and prompt-forbidden paths remain non-editable.
- Added review-patch fixtures for clean allowed-source passes and forbidden adapter paths.
- Added process diagnostics and process-group termination for timeout-wrapped smoke child processes.
- Bumped package version to `0.2.6.21`.

## v0.2.6.20

- Added Elixir/Phoenix, PHP/Composer, Ruby/Rails, and Terraform adapter detection, source routing, related-test mapping, and command discovery.
- Hardened Unity detection so lowercase web `assets/` no longer triggers Unity without real Unity markers.
- Improved Android/Kotlin Gradle wrapper commands and app-module test/build suggestions.
- Extended review-patch coverage for untracked generated/proof/state/secret files and directory-level negative prompt patterns.
- Preserved central v0.2.6.19 routing safety invariants while extending manifest/generated classifications.
- Bumped package version to `0.2.6.20`.

## v0.2.6.19

- Added central routing safety invariants for generated/build/output/state/proof/runtime paths and read-only manifests before packet and review-contract output.
- Filtered `_output`, generated suffixes, dist/build/cache/target/out/tmp, Bazel, Terraform, Dart, and similar output paths from edit/test/verification buckets unless explicitly authorized.
- Tightened Node/web source prompts so `package.json` and workspace manifests stay command evidence/read-only support unless dependency, script, package, or config edits are requested.
- Added Maven/Gradle command discovery with wrapper preference.
- Added pytest subprocess/hang diagnostics and split smoke phases with per-step timeout controls.
- Bumped package version to `0.2.6.19`.

## v0.2.6.18

- Surfaced semantic routing buckets at top level in compile JSON so consumers can read likely edit files, support files, related tests, verification order, and diagnostics without unpacking `impact_map`.
- Tightened SwiftUI tutorial/UI-shell prompts to keep only strongly matched Swift UI/ViewModel/state files in allowed edits and downrank broad Swift candidates.
- Preserved animal/art manifest suppression while adding diagnostics for Swift scope tightening.
- Bumped package version to `0.2.6.18`.

## v0.2.6.17

- Reconciled safe Swift full-text source recovery back into `likely_edit_files` and `likely_files` even when the final selected context is the recovery proof.
- Suppressed animal/art/source manifest JSON files from SwiftUI/source full-text context unless explicitly prompt-mentioned.
- Populated routing diagnostics for source recovery attempts, recovered Swift candidates, docs downranking, filtered reasons, and asset manifest filtering.
- Bumped package version to `0.2.6.17`.

## v0.2.6.16

- Reconciled Swift/iOS source recovery with semantic edit buckets so recovered safe Swift full-text files also appear in `likely_edit_files`.
- Downranked prompt-excluded `Docs/*.md` files, including campaign-bible docs, for SwiftUI/source prompts that explicitly avoid Docs.
- Added recovered source candidates and docs downrank counts to routing diagnostics.
- Bumped package version to `0.2.6.16`.

## v0.2.6.15

- Downranked dirty in-repo planning/art-source files for Swift/iOS source prompts, especially when the prompt excludes Docs, Planning_Bundles, ArtSource, assets, or related folders.
- Added Swift/iOS source recovery hints so safe Swift UI/view/model/source files can be surfaced when dirty planning context would otherwise dominate routing.
- Added routing diagnostics for source recovery attempts, safe candidate counts, and filtered planning/art boundaries.
- Bumped package version to `0.2.6.15`.

## v0.2.6.14

- Changed `premode compile --out ... --json-out ...` to print a compact receipt by default instead of the full packet; `--show-raw` still prints the packet.
- Split impact routing into semantic buckets: `likely_edit_files`, `read_only_support_files`, `prompt_forbidden_files`, `related_tests`, and `verification_order`.
- Tightened OpenClaw/control-plane allowed edits for prompts naming one explicit source file.
- Added smoke phase/duration diagnostics for core, plugin, and benchmark phases.
- Bumped package version to `0.2.6.14`.

## v0.2.6.13

- Enforced ignored/reference/generated path boundaries in repo-map impact routing.
- Filtered `_external_references`, dependency folders, generated/proof/state/runtime outputs, build outputs, binaries, and caches from `likely_files`, `related_tests`, and `verification_order` unless explicitly prompt-mentioned.
- Added compact routing diagnostics when boundary filtering removes candidate paths.
- Mirrored the boundary in selected-context routing so ignored/reference paths are excluded from packet context unless explicitly named.
- Bumped package version to `0.2.6.13`.

## v0.2.6.12

- Added a child-repo context boundary when detection selects a child `task_root` from a messy parent.
- Downgraded dirty parent guidance/persona files outside the selected child root to compact inherited-authority context unless explicitly prompt-mentioned.
- Prefer child-root context and nearest child `AGENTS.md` over parent workspace guidance for lite source/gameplay prompts.
- Added compile evidence for inherited parent authority counts and samples.
- Bumped package version to `0.2.6.12`.

## v0.2.6.11

- Added prompt-affinity scoring for direct child Git roots so OpenClaw/Unreal prompts select `openclaw_repo` and Goldpine/iOS/Swift prompts select the matching iOS repo.
- Expanded `active_root_candidates` diagnostics with markers, marker bonuses, prompt-affinity bonuses, and ignored/reference penalties.
- Added ambiguity diagnostics when multiple direct child Git roots remain close-scoring without prompt affinity.
- Compacted dirty authority/runbook/history/memory docs under lite source/gameplay prompts so they remain visible without dominating full-text context.
- Bumped package version to `0.2.6.11`.

## v0.2.6.10

- Added direct child `.git` root discovery for messy parent launches.
- Promotes direct child Git roots over deeply nested ignored/reference package markers.
- Added `active_root_candidates` diagnostics with scores, penalties, and reasons.
- Prevented `_external_references` and `node_modules` package roots from outranking visible child repos.
- Bumped package version to `0.2.6.10`.

## v0.2.6.9

- Compacted lite Packet V3 metadata for dirty files, diff summaries, redaction summaries, and trust-boundary warnings.
- Summarized dirty paths by category and noisy prefix instead of dumping large dirty-file lists into packets.
- Hardened nested root selection so deeply nested external/generated/reference project markers do not win over direct child repo markers.
- Added focused OpenClaw-style metadata budget and messy-parent nested-root tests.
- Bumped package version to `0.2.6.9`.

## v0.2.6.7

- Codex CLI adapter compatibility patch for local CLIs that reject `--ask-for-approval`.
- Detects supported `codex exec --help` flags before building the subprocess command.
- Prefers `--approval-mode on-request`, falls back to `--ask-for-approval on-request`, or omits approval flags with JSON warnings.
- Falls back from `-C` to `--cd`, then subprocess `cwd`, while keeping the compiled packet on stdin with the final `-` sentinel.
- Adds dry-run `codex_capabilities` and `codex_warnings` fields.
- Bumped package version to `0.2.6.7`.

## v0.2.6.6

- Local validation and macOS portability cleanup for the v2.6 release-candidate line.
- Bumped package version to `0.2.6.6`.
- Replaced the smoke test's GNU `timeout` dependency with `scripts/run_with_timeout.py`.
- Documented no-install `PYTHONPATH=src python -m premode.cli ...` validation commands.
- Clarified Python >=3.11, macOS system Python, `tomllib`, virtualenv, and pytest setup requirements.
- Added end-to-end CLI validation for `review-patch --since-compile` in a temporary Git worktree.
- Clarified benchmark language for total repo-token savings, cacheable-prefix percent, and dynamic-suffix percent.
- Did not implement `premode lint-agents`; v2.7 remains planning-only.

## v0.2.6.5

- Release-candidate cleanup for external Codex testing.
- Bumped package version to `0.2.6.5`.
- Simplified `README.md` into a user-facing quickstart and command reference.
- Simplified `IMPLEMENTATION_REPORT.md` and `FINAL_PACKAGE_INDEX.md` for current-version clarity.
- Standardized validation commands across public docs.
- Documented `premode review-patch --since-compile` as the default local workflow.
- Kept benchmark budget-exceeded cases visible as diagnostic output and compacted Packet V3 self-metadata so the built-in lite benchmark fits under budget.
- Added `CODEX_ONE_SHOT_PROMPT_v2.7.0.md` for the next Agent Config Linter slice without implementing the command yet.

## v0.2.6.4

- Release-candidate polish for benchmark output and docs.
- Added top-level `prompt_count` for quick JSON parsing.
- Added benchmark cache split percentages at per-prompt and summary levels.
- Surfaced budget-exceeded prompt details with over-budget amount and likely reason.
- Documented `premode review-patch --since-compile` as the default local workflow.

## v0.2.6.3

- Added `premode benchmark` for prompt-suite token and routing reports.
- Added optional benchmark review-loop metrics via `--include-review` and `--since-compile`.
- Added example benchmark prompt suite.
- Added release-candidate docs for benchmark usage.

## v0.2.6.2

- Added compile-time worktree baseline snapshots.
- Added `premode review-patch --since-compile`.
- Split preexisting, post-compile, and agent-candidate changes.
- Added base-ref fallback metadata.
- Split findings into blocking, warning, and info.

## v0.2.6.1

- Hardened review evidence parsing.
- Bound auto-discovered logs to `packet_sha256`.
- Added `evidence_present_but_unbound`.
- Fixed `0 failed` false failure handling.
- Classified rename/copy old paths.
- Ignored Pre-mode runtime index metadata during review.

## v0.2.6.0

- Added `premode review-patch`.
- Added structured saved `review_contract`.
- Added scope/risk classification and merge-readiness output.

## v0.2.5.7

- Added cache-aware Packet V3.
- Added `--cache-optimized`, `--packet-version`, and saved packet artifacts.
- Made `pcodex` use lite profile, repo map, Packet V3, and save-by-default behavior.

## v0.2.5.6

- Added universal stress harness covering Python, Rust, Go, TypeScript/pnpm, Swift/iOS, native C++/SCons, mixed monorepos, control-plane repos, adversarial fixtures, and tiny repos.
