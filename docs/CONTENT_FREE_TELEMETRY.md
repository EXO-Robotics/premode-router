# Content-Free Telemetry

This document defines the local telemetry boundary for pCodex and LCC control-plane files.

## Purpose

pCodex needs enough local state to answer operational questions:

- is pCodex on, off, tuned, or safely passing through?
- was tuning verified?
- did fallback happen?
- is there a cacheable prefix candidate?
- what local artifacts were used?

That state must not become hidden prompt capture, source capture, or planner output.

## Generated Files

Current generated control-plane files include:

- `.premode/pcodex_state.json`
- `.premode/lcc.lock.json`
- `.premode/out/cache_manifest.json`
- `.premode/metrics/`
- `.premode/audit/`
- `.premode/tuning/`

These are generated/runtime paths and should stay out of commits unless a user explicitly asks to version a reviewed artifact.

## Allowed Fields

Allowed telemetry and manifest fields:

- predicted files
- actual edited files
- predicted tests
- tests run
- review-patch result
- schema version
- package/LCC version
- public mode
- effective mode or effective state
- plugin alias
- packet version, variant, and strategy names
- status booleans
- status reasons
- fallback reasons
- safe-passthrough reasons
- counters
- token estimates
- cached token counts if available
- timestamps
- git branch
- git HEAD
- hashes of repo root, packets, profiles, verifier results, and static prefixes
- relative generated-file paths
- compile milliseconds
- files walked
- files read
- bytes read
- index cache hit
- repo-map cache hit

## Forbidden Fields

Do not store:

- raw prompt text
- prompt excerpts
- model-facing prompt packets
- source snippets
- file contents
- source bodies
- secrets
- raw logs with private content
- API keys or tokens
- credentials
- environment variable values
- hidden chain-of-thought or planner notes
- validation instructions for the model
- commands to be executed by the model
- do-not-edit lists as model-facing guidance
- confidence prose or diagnostic narratives intended for the model

## Lockfile Boundary

`.premode/lcc.lock.json` is local-only control-plane state. It records the effective state and hashes that help pCodex answer whether the current route is generalized, tuned, strict, or safe passthrough.

It must not store prompt text, source snippets, or packet bodies.

## Cache Manifest Boundary

`.premode/out/cache_manifest.json` is local-only cache observability. It records hashes and estimates for prefix stability and provider-hint experiments.

The provider hint is not a provider guarantee. It must not claim real prompt-cache hits, guaranteed savings, or universal reductions.

## Status And Doctor Boundary

`pcodex status`, `pcodex status --json`, `pcodex doctor`, and `pcodex doctor --json` may report:

- effective state
- lockfile validity
- cache-manifest validity
- Codex CLI availability
- local config status
- tuning status
- fallback status

They should avoid printing secrets, prompt bodies, source contents, or long local config values.

## Future Uses

Future telemetry may support weight tuning, stale-profile detection, noisy-path suppression, source-test mapping confidence, savings estimates, cache stability scores, cache-friendly routing, or local performance receipts. Any future use must preserve the same content-free boundary and must not become a model-facing planning layer.
