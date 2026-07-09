# V5 Literal Symbol

`literal_symbol` is the lead private Pre-mode V5 context-selection strategy. It keeps the model-facing packet compact by selecting ranked paths and literal anchors that point the coding agent at likely primary files and related tests without adding planner-style ceremony.

## Supported Command

Use the plugin alias:

```bash
premode compile --plugin literal_symbol "Fix the failing test"
```

Use explicit tuning only with a validated repo-local profile:

```bash
premode compile --plugin literal_symbol --tuning .premode/tuning/repo_profile.json "Fix the failing test"
```

Tuning does not become the default compile path. The default remains the generalized `literal_symbol` strategy unless `--tuning` is supplied or pCodex mode state is set to `tuned`.

The explicit equivalent flags are:

```bash
premode compile "Fix the failing test" \
  --packet-version v5 \
  --packet-variant tool_assisted_anchors_internal \
  --packet-strategy literal_symbol
```

## Why Compact Anchors

The V5 packet is designed to preserve the exact task prompt and add only compact repo context. Literal anchors are intended to help the agent find relevant code quickly while avoiding bulky snippets, validation instructions, or confidence prose in the model-facing prompt.

This keeps Pre-mode in its proper role: local context compiler and routing formatter, not a local reasoning engine.

## Model-Facing Packet Boundary

Allowed model-facing sections:

```text
TASK
PRIMARY_FILES
RELATED_TESTS
END
```

In the current renderer, the end marker is `END_PREMODE_CONTEXT_PACKET_V5`.

Excluded from model-facing content:

- `TASK_CLASS`
- `SUPPORT_RELATIONS`
- snippets
- diagnostics
- confidence
- validation guidance
- commands
- do-not-edit language
- review metadata
- scope contracts

## Diagnostics Policy

Strategy diagnostics, rejected anchors, fallback metadata, plugin metadata, and benchmark notes stay out of band in JSON results, tests, or lab reports. They should not be rendered into the model-facing packet unless explicitly requested by a non-default debug flag.

The pCodex control plane may write local out-of-band files such as `.premode/lcc.lock.json` and `.premode/out/cache_manifest.json`. These files are not model-facing packet content and must remain content-free: hashes, status fields, counters, timestamps, and reasons are allowed; prompt text, source snippets, secrets, validation guidance, commands, or planner metadata are not.

## Fallback And Comparison Baseline

`ranked_paths_plus_anchors` remains the fallback and comparison baseline. It is not replaced as a historical comparison point.

The following branches are not defaults:

- `literal_symbol_config_gated`
- `literal_symbol_collision_filter`
- `literal_symbol_import_rank_json_only`

## Safe Measured Claim

In a bounded local same-run matrix of six prompts, `literal_symbol` reduced derived cache-adjusted input by 17.02% versus standard and 11.68% versus `ranked_paths_plus_anchors`, with zero scope issues and zero model-facing leakage.

This is bounded local evidence, not a public benchmark claim or universal guarantee.

## Known Limitations

- The measured reduction evidence is limited to the six-prompt local same-run matrix.
- The strategy does not prove savings on all Codex tasks.
- Tuned behavior is repo-specific and must be verified locally before relying on it.
- The strategy does not own Codex dispatch or subagent routing.
- The plugin package is private and not published.
