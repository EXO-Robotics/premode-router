# Pre-mode Plugin Literal Symbol

`premode-plugin-literal-symbol` is a private Pre-mode plugin package for the V5 literal-symbol anchor strategy.

It maps to the hardened core Pre-mode strategy:

```text
--packet-version v5 --packet-variant tool_assisted_anchors_internal --packet-strategy literal_symbol
```

The package is a thin registration and metadata layer. It does not fork or duplicate the core compiler strategy.

## Local Install

From the repository root:

```bash
.venv/bin/python -m pip install -e packages/premode-plugin-literal-symbol
```

Or install a locally built wheel:

```bash
.venv/bin/python -m pip wheel --no-deps --no-build-isolation \
  packages/premode-plugin-literal-symbol \
  -w /tmp/premode-plugin-literal-symbol-dist

.venv/bin/python -m pip install --no-index \
  --find-links /tmp/premode-plugin-literal-symbol-dist \
  premode-plugin-literal-symbol
```

This package is private and proprietary. Use requires owner permission.

## Invocation

Use the existing Pre-mode command surface:

```bash
.venv/bin/premode compile "Fix the shell completion behavior" \
  --packet-version v5 \
  --packet-variant tool_assisted_anchors_internal \
  --packet-strategy literal_symbol
```

The plugin metadata exposes the same mapping for a future plugin registry:

```python
from premode_plugin_literal_symbol import get_plugin

plugin = get_plugin()
```

The package also exposes helper metadata for local tooling:

```python
from premode_plugin_literal_symbol import command_args, compile_kwargs, fallback_kwargs
```

## Model-Facing Packet Contract

The model-facing packet remains compact ranked paths plus anchors only:

```text
PREMODE_CONTEXT_PACKET_V5
schema: ranked-paths-plus-anchors
format_version: 1
<TASK>
...
</TASK>
<PRIMARY_FILES>
...
</PRIMARY_FILES>
<RELATED_TESTS>
...
</RELATED_TESTS>
<END_PREMODE_CONTEXT_PACKET_V5>
```

The plugin default does not render `TASK_CLASS`, `SUPPORT_RELATIONS`, snippets, tool traces, diagnostics, confidence prose, warnings, scope contracts, review metadata, validation guidance, command suggestions, or do-not-edit language.

## Diagnostics Policy

Diagnostics remain out-of-band. Strategy identifiers, rejected anchors, discovery statistics, fallback metadata, and deferred policy notes belong in JSON diagnostics or registry metadata, not in the model-facing packet.

## Fallback

The fallback variant is `ranked_paths_plus_anchors`.

Fallback is for compiler-side safety conditions such as probe failure, invalid diagnostics shape, forbidden model-facing section detection before render, empty anchor generation for primary files, packet render validation failure, or unrecognized strategy selection. Fallback is not based on historical token performance.

## Measured Public-Matrix Result

In Lab 7.3AH, on a six-prompt public same-run matrix, `literal_symbol` reduced derived cache-adjusted input by 17.02% versus standard and 11.68% versus `ranked_paths_plus_anchors`, with zero scope issues and zero model-facing leakage.

This is a measured public-matrix result, not a universal guarantee.

## Limitations

Measured on the AH public six-prompt matrix only.

This package does not claim that Pre-mode saves 17% on all tasks, guarantees lower Codex token use, always beats standard, always beats `ranked_paths_plus_anchors`, or is production-proven across all repositories.

`literal_symbol_config_gated` remains a deferred policy branch. It is not the package default.

`literal_symbol_collision_filter` and `literal_symbol_import_rank_json_only` are not package defaults.

## License

Private and proprietary. All rights reserved.

## Publish Status

This package has not been published to PyPI or any external registry.
