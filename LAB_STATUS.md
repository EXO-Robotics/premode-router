# Lab Status (Historical Snapshot)

This file records the Lab 7.3T/7.3U state at the time it was written. It is not current product, branch, version, or release authority. Current authority is `origin/Private-Beta` as defined in `docs/PRODUCT_CONTRACT.md` and `docs/RELEASE_AUTHORITY.md`.

## Current validated checkpoint

- Repo: `EXO-Robotics/premode-router`
- Visibility: private
- Branch: `checkpoint/lab-7-3t`
- Commit: `6b39f093831ce019c276c6b8498ed6109a018eb8`
- Short commit: `6b39f09`
- Status at checkpoint: clean, pushed, no staged changes

As of commit `6b39f09` on `checkpoint/lab-7-3t`, Pre-mode Router has a passing local benchmark, improved public remote-manifest simulation generalization, zero broad candidate warnings in the latest remote simulation, and a clean private GitHub checkpoint.

## Lab progression captured by the checkpoint

- Lab 7.3M: policy-safe hardening
- Lab 7.3N: retrieval-quality benchmark
- Lab 7.3O: config/test/workflow aliases
- Lab 7.3P: precision tightening
- Lab 7.3Q: public remote-manifest simulation
- Lab 7.3R: cross-ecosystem role model
- Lab 7.3S: precision and related-test resolver
- Lab 7.3T: docs anchors and related-test cleanup

## Current working branch

- Branch: `lab/7-3u-public-sparse-local-mini`
- Purpose: sparse public-local retrieval validation before returning to live token-savings claims

## 7.3U boundary

Lab 7.3U should answer whether the locator still holds up when run against sparse real public repo contents instead of synthetic remote-manifest fixtures.

Hard boundaries for 7.3U:

- Do not run private live Codex.
- Do not retry private lanes.
- Do not clone or download full public repos.
- Do not download private repos.
- Keep the work public, sparse, local, and retrieval-focused.
- Do not broaden routing to chase raw score.
- Do not tune directly against holdout.

## Branch policy

Keep `checkpoint/lab-7-3t` as the preserved private checkpoint. Use `lab/7-3u-public-sparse-local-mini` for the next research pass. Decide what `main` should represent later, after the stable checkpoint and lab branch workflow are settled.
