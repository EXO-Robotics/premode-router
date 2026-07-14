from __future__ import annotations

from copy import deepcopy
from typing import Any


# The stable default ships with the product. Entry-point plugins remain the
# extension boundary for experimental and third-party strategies.
LITERAL_SYMBOL_METADATA: dict[str, Any] = {
    "schema_version": "pcodex.packet-strategy-plugin.v1",
    "name": "premode-router",
    "version": "builtin",
    "strategy_id": "literal_symbol",
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
    "fallback": "ranked_paths_plus_anchors",
    "diagnostics_out_of_band": True,
    "distribution": "builtin",
    "sensitivity_classification": "public_safe",
}


def get_literal_symbol_plugin() -> dict[str, Any]:
    """Return metadata for the stable strategy included in the core install."""

    return deepcopy(LITERAL_SYMBOL_METADATA)
