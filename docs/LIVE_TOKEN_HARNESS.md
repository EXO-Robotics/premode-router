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

Runs a task-matrix suite from `--task-matrix`. It is never default and requires
both:

```bash
PREMODE_ENABLE_LIVE_CODEX_SPEND_TEST=1
PREMODE_ENABLE_LIVE_CODEX_MATRIX=1
```

Without `--task-matrix`, `live_matrix` still runs the legacy single disposable
pair. With `--task-matrix`, the harness creates one standard and one enhanced
lane for each task, records randomized per-task lane order, and emits
`premode.live_token_harness.matrix_result.v1`.

## Task Matrix

Matrix mode accepts:

```bash
premode lab live-token-harness \
  --mode dry_run_mock \
  --task-matrix /path/to/tasks.json \
  --fixture-root /path/to/fixtures \
  --json
```

Each task object must include:

- `task_id`
- `prompt_text`
- either `fixture_path` or `fixture` with `--fixture-root`
- optional `expected_files`
- optional `expected_tests`
- optional `forbidden_files`
- optional `validation_command`

Aggregate matrix results include `prompt_sha256`, not `prompt_text`.

## Auth Bootstrap

Live Codex lanes use isolated `HOME`, `TMPDIR`, `CODEX_HOME`, and
`PCODEX_ALPHA_HOME`. Isolated homes do not automatically inherit the normal
user Codex login. Live modes therefore perform an auth preflight before
spending tokens.

Supported auth bootstrap modes are selected with `PREMODE_CODEX_AUTH_MODE`:

- `none`: default. No auth is copied or created; live execution is blocked.
- `inherit_auth_cache`: copies the normal user's `.codex/auth.json` into each
  isolated lane home only when `PREMODE_ALLOW_CODEX_AUTH_CACHE_COPY=1` is also
  set.
- `device_auth`: runs `codex login --device-auth` inside the lane home.
- `api_key`: runs `codex login --with-api-key` from stdin using the process
  environment.
- `access_token`: runs `codex login --with-access-token` from stdin using the
  process environment.

`PREMODE_CODEX_AUTH_SOURCE_HOME` can override the source home for
`inherit_auth_cache`. Auth file contents, token values, and environment values
are never serialized into aggregate JSON or Markdown reports. Copied auth files
are local lane secrets under the artifact tree.

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
