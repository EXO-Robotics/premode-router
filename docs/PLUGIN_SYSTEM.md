# Plugin System

Pre-mode resolves private strategy packages through the Python entry point group `premode.plugins`.

## Entry Point Group

The literal-symbol package registers:

```toml
[project.entry-points."premode.plugins"]
literal_symbol = "premode_plugin_literal_symbol.plugin:get_plugin"
```

The entry point returns plugin metadata used by the core CLI to select packet options.

## Literal-Symbol Plugin Package

Package:

```text
packages/premode-plugin-literal-symbol
```

Alias:

```text
literal_symbol
```

The package is a private metadata and registration layer for the core strategy. It does not publish new compiler logic and has not been published to PyPI or any external registry.

## Metadata Shape

The plugin metadata must include a strategy identifier and compile options:

```json
{
  "name": "premode-plugin-literal-symbol",
  "strategy_id": "literal_symbol",
  "packet_version": "v5",
  "packet_variant": "tool_assisted_anchors_internal",
  "packet_strategy": "literal_symbol",
  "fallback": "ranked_paths_plus_anchors"
}
```

The resolver accepts `strategy_id` or `name` as the identity field and requires `packet_version`, `packet_variant`, and `packet_strategy`.

## Compile Usage

```bash
premode compile --plugin literal_symbol "Fix the failing test"
```

If the alias resolves successfully, the CLI applies the plugin packet options. If the caller also passes explicit packet options, they must match the plugin metadata.

Optional compile-time tuning can be applied with a validated repo-local profile:

```bash
premode compile --plugin literal_symbol --tuning .premode/tuning/repo_profile.json "Fix the failing test"
```

The tuning profile adjusts local selection weights and routes for the `literal_symbol` path. It does not change the plugin alias metadata, does not expand the model-facing packet boundary, and is not the default unless a caller explicitly supplies `--tuning` or pCodex mode state selects tuned behavior.

## Benchmark Usage

The benchmark command supports the same plugin alias:

```bash
premode benchmark --profile lite --json --plugin literal_symbol
```

Use this for local comparison only. Benchmark output should be described with the same measured-claim boundary as other Pre-mode results.

## Conflict And Error Behavior

Explicit flag conflicts fail closed. For example, `--plugin literal_symbol` combined with a different `--packet-version`, `--packet-variant`, or `--packet-strategy` raises a CLI error instead of silently choosing one.

Unknown aliases fail closed with a message listing available aliases when possible.

Invalid metadata fails closed when:

- the entry point cannot be loaded
- the returned value is not a dictionary
- required metadata fields are missing or empty
- duplicate aliases are installed

## Private Status

The literal-symbol compatibility plugin source is publicly visible and proprietary. It is intended for local Private-Beta compatibility testing only and is not a public package release.
