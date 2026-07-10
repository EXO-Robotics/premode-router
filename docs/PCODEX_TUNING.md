# pCodex Tuning

pCodex tuning is a local, static profile layer for the private `literal_symbol` path. It generates repo-specific artifacts under `.premode/tuning/`, validates them, and can run an offline compile-only verifier before tuned mode is enabled.

It does not run Codex, dispatch subagents, call external services, edit source files, or add model-facing diagnostics.

## Commands

Run the recommended one-step local tuning pipeline:

```bash
pcodex tune
```

This runs static artifact generation, validation, and offline verification in order. It does not run Codex or contact external services.

Generate static tuning artifacts only:

```bash
pcodex tune --static-only
```

Validate existing artifacts:

```bash
pcodex tune --validate
```

Run the offline mini verifier:

```bash
pcodex tune --verify
```

The generated profile can be used directly by Pre-mode:

```bash
premode compile --plugin literal_symbol --tuning .premode/tuning/repo_profile.json "Fix the failing test"
```

## Generated Files

Default output lives under `.premode/tuning/`.

Key files:

- `.premode/tuning/repo_profile.json`
- `.premode/tuning/path_taxonomy.json`
- `.premode/tuning/repo_vocabulary.json`
- `.premode/tuning/source_test_map.json`
- `.premode/tuning/prompt_phrase_routes.json`
- `.premode/tuning/hotspots_and_suppressions.json`
- `.premode/tuning/literal_symbol_weights.json`
- `.premode/tuning/evaluation_prompts.jsonl`
- `.premode/tuning/TUNING_REPORT.md`
- `.premode/tuning/VALIDATION_REPORT.md`
- `.premode/tuning/VERIFY_REPORT.md`
- `.premode/tuning/VERIFY_RESULTS.json`

`repo_profile.json` is the compile-time profile consumed by `--tuning` and by `pcodex tuned`.

## Verification Meanings

`pcodex tune --verify` compares generalized and tuned local selection against generated evaluation prompts. It is compile-only and local-selection only.

- `PASS`: profile validates, packet boundary is safe, evaluation prompts exist, and tuned selection is not worse by the verifier's local metrics.
- `NEEDS_ADJUSTMENT`: profile validates but local selection evidence suggests review or refinement before relying on tuned mode.
- `FAIL`: profile validation, packet-boundary safety, or local selection checks failed.

These verdicts do not guarantee live Codex task success or token savings. Tuned improvements are repo-specific and must be verified locally.

## Mode Interaction

`on` mode uses tuned behavior only when `.premode/tuning/repo_profile.json` is valid and `.premode/tuning/VERIFY_RESULTS.json` has verdict `PASS`. If the profile is missing, invalid, not verified, `NEEDS_ADJUSTMENT`, or `FAIL`, `on` safely falls back to generalized `literal_symbol`.

`tuned` mode remains strict. It requires a valid tuning profile and `.premode/tuning/VERIFY_RESULTS.json` verdict `PASS`; it fails clearly when the profile is missing, invalid, or unverified.

`pcodex status` reports configured mode, effective mode, explicit effective state, tuning status, fallback state, local telemetry counters, lockfile/cache-manifest status, and savings-estimate availability. Fallback telemetry stores counters and reasons only; it must not store prompts, source snippets, secrets, or file contents.

Effective states:

- `OFF_RAW`: no Pre-mode transform.
- `ON_GENERALIZED`: generalized `literal_symbol` packet.
- `ON_TUNED_VERIFIED`: `on` mode using verified repo-local tuning.
- `TUNED_STRICT`: strict tuned mode.
- `SAFE_PASSTHROUGH`: raw prompt passthrough when LCC cannot safely compile.

Generated control-plane files include `.premode/lcc.lock.json` and `.premode/out/cache_manifest.json`. They are local, ignored runtime state and contain hashes/status only.

## Safety Boundary

Tuning artifacts are local repo artifacts. They should not contain secrets, absolute local paths, source snippets, or expanded model-facing diagnostics. Normal pCodex model-facing rendering uses the canonical `TASK` and `LIKELY FILES` packet. The older V5 marker renderer remains available only through developer/compatibility compile surfaces.

Plain `pcodex setup` is the narrow setup path. Automatic verified-profile use in `on`, explicit tuning commands, and the hidden legacy `pcodex setup --isolated` workflow remain compatibility/developer behavior pending CONFIG-A.
