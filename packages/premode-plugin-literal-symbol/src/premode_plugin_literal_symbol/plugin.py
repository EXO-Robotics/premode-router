from __future__ import annotations

from copy import deepcopy
from typing import Any

PLUGIN_METADATA: dict[str, Any] = {
    "schema_version": "pcodex.packet-strategy-plugin.v1",
    "name": "premode-plugin-literal-symbol",
    "version": "0.1.0",
    "strategy_id": "literal_symbol",
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
    "fallback": "ranked_paths_plus_anchors",
    "fallback_variant": "ranked_paths_plus_anchors",
    "fallback_strategy": None,
    "model_facing_sections": [
        "TASK",
        "PRIMARY_FILES",
        "RELATED_TESTS",
        "END_PREMODE_CONTEXT_PACKET_V5",
    ],
    "diagnostics_out_of_band": True,
    "license": "Proprietary / All Rights Reserved",
    "private": True,
    "private_package": True,
    "sensitivity_classification": "public_safe",
    "deferred_policy_branches": [
        {
            "strategy": "literal_symbol_config_gated",
            "status": "deferred_policy_branch",
            "default": False,
        },
    ],
    "non_default_strategies": [
        {
            "strategy": "literal_symbol_collision_filter",
            "status": "rejected_as_default_challenger",
            "default": False,
        },
        {
            "strategy": "literal_symbol_import_rank_json_only",
            "status": "dropped",
            "default": False,
        },
    ],
    "measured_public_matrix": {
        "lab": "7.3AH",
        "prompt_count": 6,
        "repeat_count": 2,
        "derived_cache_adjusted_reduction_vs_standard_percent": 17.02,
        "derived_cache_adjusted_reduction_vs_ranked_paths_plus_anchors_percent": 11.68,
        "scope_issues": 0,
        "model_facing_leakage": 0,
        "claim_scope": "six-prompt public same-run matrix",
    },
}


def get_plugin() -> dict[str, Any]:
    """Return registry metadata for the private literal-symbol plugin."""
    return deepcopy(PLUGIN_METADATA)


def compile_kwargs() -> dict[str, str]:
    """Return the core Pre-mode compile options used by this plugin."""
    return {
        "packet_version": str(PLUGIN_METADATA["packet_version"]),
        "packet_variant": str(PLUGIN_METADATA["packet_variant"]),
        "packet_strategy": str(PLUGIN_METADATA["packet_strategy"]),
    }


def fallback_kwargs() -> dict[str, str | None]:
    """Return the safe compile options for the package fallback."""
    return {
        "packet_version": str(PLUGIN_METADATA["packet_version"]),
        "packet_variant": str(PLUGIN_METADATA["fallback_variant"]),
        "packet_strategy": PLUGIN_METADATA["fallback_strategy"],
    }


def fallback_diagnostics(reason: str) -> dict[str, Any]:
    """Return JSON-only fallback diagnostics for registry or caller use."""
    return {
        "fallback_used": True,
        "fallback_reason": str(reason or "unspecified"),
        "fallback_variant": str(PLUGIN_METADATA["fallback_variant"]),
        "fallback_strategy": PLUGIN_METADATA["fallback_strategy"],
        "diagnostics_out_of_band": True,
    }


def command_args() -> list[str]:
    """Return CLI arguments for invoking the core literal-symbol strategy."""
    kwargs = compile_kwargs()
    return [
        "--packet-version",
        kwargs["packet_version"],
        "--packet-variant",
        kwargs["packet_variant"],
        "--packet-strategy",
        kwargs["packet_strategy"],
    ]
