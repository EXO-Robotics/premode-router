# Benchmark Guide

`premode benchmark` compiles a prompt suite and reports how much context Pre-mode avoids sending to the coding agent.

It reports three related but separate KPIs:

- total repo-token savings: how much smaller the compiled packet is than the eligible repo surface
- cacheable-prefix percent: how much of the remaining packet is positioned before task-specific data for provider prefix caching
- dynamic-suffix percent: how much of the remaining packet is prompt-specific and expected to change per run

Estimated savings compares the compiled packet to the eligible repo surface. Cacheable-prefix percent measures how much of the remaining packet is positioned for provider prefix caching. Dynamic-suffix percent measures the task-specific remainder.

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
