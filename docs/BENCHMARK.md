# Benchmark Guide

`premode benchmark` compiles a prompt suite and reports compile-only context and packet metrics.

It does not run live Codex, does not measure live provider usage, and must not be cited as live token or cost savings.

It reports three related but separate KPIs:

- full repo reduction percent: how much smaller the compiled packet is than the eligible readable repo surface
- derived cache-adjusted input: a benchmark-derived cache-shape estimate, not live provider usage
- cacheable-prefix percent: how much of the remaining packet is positioned before task-specific data for provider prefix caching
- dynamic-suffix percent: how much of the remaining packet is prompt-specific and expected to change per run

The legacy "total repo-token savings" and `estimated_savings_vs_eligible_repo_percent` wording is retained only as a deprecated compatibility alias for `full_repo_reduction_percent`. It is not live Codex token savings.

## Basic command

```bash
premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
```

## Prompt suites

A suite can be a simple list:

```json
[
  "Fix the failing test with the smallest safe patch."
]
```

or a richer object:

```json
{
  "prompts": [
    {
      "name": "cli_validation",
      "prompt": "Fix src/app.py and run the related tests.",
      "expected_files": ["src/app.py"],
      "expected_tests": ["tests/test_app.py"]
    }
  ]
}
```

Run it with:

```bash
premode benchmark --prompts examples/benchmark_prompts.json --profile lite --json
```

## Report fields

The JSON report includes:

```text
benchmark_kind
compile_only
live_codex_run
cache_mode
shared_cache_measured
live_input_tokens
live_cached_tokens
live_cost_savings
metric_semantics
lane_metadata
prompt_count
summary.prompt_count
average_packet_tokens
average_savings_percent
average_cacheable_prefix_tokens
average_dynamic_suffix_tokens
average_cacheable_prefix_percent
average_dynamic_suffix_percent
budget_exceeded_count
budget_exceeded_prompts
cases[]
```

Each case includes packet token counts, cache split percentages, likely files, related tests, expectation hit/miss results, and budget status.

Each case also includes normalized compile-only fields:

```text
schema_version
benchmark_kind
compile_only
live_codex_run
strategy
packet_version
packet_variant
packet_strategy
cache_mode
run_temperature
repo_shape
prompt_id
prompt_preserved
packet_total_tokens
selected_context_tokens
eligible_repo_surface_tokens
full_repo_reduction_percent
estimated_savings_vs_eligible_repo_percent
estimated_savings_alias_status
derived_cache_adjusted_input
live_input_tokens
live_cached_tokens
live_cost_savings
primary_files
related_tests
anchors_count
expected_file_hit_at_1
expected_file_hit_at_3
expected_file_hit_at_5
expected_test_hit_at_5
expected_primary_node_hit
inventory_cache_hit
topology_cache_hit
full_walk_performed
files_walked
files_listed
files_content_read
bytes_read
compile_ms
packet_hash
static_prefix_hash
first_1024_hash
model_facing_leak_check
fallback_used
errors
warnings_out_of_band
```

For compile-only benchmark rows, `compile_only=true`, `live_codex_run=false`, and `live_input_tokens`, `live_cached_tokens`, and `live_cost_savings` are `null`.

## Cache Mode

Every row carries `cache_mode`.

- `strategy_isolated` is the default label. Use it for rows intended to compare strategies without intentionally sharing warmed state across strategies.
- `shared_cache` is available only when a run intentionally shares warmed inventory/topology state and the report keeps those rows separate.

Top-level `shared_cache_measured=false` means no shared-cache lane was measured in that report.

## Public/Private Lane Metadata

Benchmark reports include `lane_metadata` with branch, HEAD, package version, Python version, source path, source dirty status, prompt suite hash, and benchmark harness hash. Public/private comparison fields are explicit:

```text
public_private_comparison_valid
comparison_invalid_reason
```

If no public clone comparison was run, `public_private_comparison_valid=false` and `comparison_invalid_reason=public_unavailable`.

## Budget diagnostics

Benchmark does not hide over-budget prompts. If a lite prompt exceeds the packet budget, the report surfaces:

```json
{
  "name": "scope_guarded_patch",
  "packet_tokens": 12969,
  "budget": 12000,
  "over_by": 969,
  "likely_reason": "policy_metadata_or_packet_overhead"
}
```

Use this to decide whether to reduce selected context, compact policy metadata, or document that the prompt requires a larger profile.

## Optional review-loop metric

```bash
premode benchmark --include-review --since-compile --profile lite --json
```

This compiles each prompt, saves the packet, runs `review-patch`, and reports pass/warning/blocked counts. It does not run tests or mutate source files.

## Validation

```bash
premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
```
