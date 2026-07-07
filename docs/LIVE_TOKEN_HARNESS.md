# Live Token Harness

## Purpose

The live token harness measures actual available Codex usage for paired standard
and enhanced runs. It exists to recover the standard-vs-enhanced token-spend
surface without turning compile-only packet estimates into live savings claims.

## What It Can Prove

- Live input, output, cached-input, and total token usage when Codex exposes
  those fields in parseable output or receipts.
- Relative standard-vs-enhanced usage on fixed disposable tasks.
- Patch and diff scope differences.
- Task success or failure on the recorded validation commands.
- Whether LCC preflight changes token usage and quality for that exact task pair.

## What It Cannot Prove Unless Measured

- Universal savings.
- Guaranteed provider cache hits.
- Production Codex UI interception.
- All-repo generality.
- Monetary savings when prices are not captured.
- Provider-side cache behavior when `cached_input_tokens` is unavailable.

## Required Lane Isolation

Each run pair must isolate:

- Repo checkout.
- `HOME`.
- `TMPDIR`.
- Codex home/config when configurable.
- pCodex install root when configurable.
- `.premode` state.
- Output logs.
- Artifact paths.

The harness must not run directly inside the developer source worktree. Standard
and enhanced lanes use separate disposable repo copies from the same fixture
state.

## Run Modes

### dry_run_mock

Default. Does not launch live Codex. It validates harness mechanics, lane
isolation, prompt hashing, pCodex setup/on/first-run/dry-run dispatch, test
capture, cleanup, and content-safe aggregate reporting.

### live_minimal

Runs the smallest useful disposable standard/enhanced pair. It requires:

```bash
PREMODE_ENABLE_LIVE_CODEX_SPEND_TEST=1
```

### live_matrix

Runs a larger task suite. It is never default and requires both:

```bash
PREMODE_ENABLE_LIVE_CODEX_SPEND_TEST=1
PREMODE_ENABLE_LIVE_CODEX_MATRIX=1
```

## Usage Fields

Every aggregate result includes:

- `usage_available`
- `usage_source`
- `input_tokens`
- `cached_input_tokens`
- `output_tokens`
- `total_tokens`
- `model`
- `model_provider`
- `effort`
- `duration_ms`
- `cost_estimate`
- `cost_estimate_available`
- `standard_vs_enhanced_delta`

When usage is unavailable, numeric usage fields remain `null`, the lane records
an explicit `usage_unavailable_reason`, and the result must not fabricate token
numbers.

## Content Safety

Aggregate reports record `prompt_sha256`, not the raw prompt. Raw source
snippets and raw prompts are not included in aggregate results. If live mode
stores raw stdout/stderr logs, they stay under the local artifact path in a
`raw_logs_non_paste_safe` directory and are not intended for public reports.

## Current Entry Point

```bash
premode lab live-token-harness --mode dry_run_mock --json
```

Live modes are blocked unless the required environment flags are set.
