from __future__ import annotations

import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from premode_plugin_literal_symbol import (
    command_args,
    compile_kwargs,
    fallback_diagnostics,
    fallback_kwargs,
    get_plugin,
)


def test_package_imports_and_metadata_loads() -> None:
    plugin = get_plugin()

    assert plugin["name"] == "premode-plugin-literal-symbol"
    assert plugin["strategy_id"] == "literal_symbol"
    assert plugin["version"] == "0.1.0"


def test_strategy_maps_to_core_literal_symbol() -> None:
    plugin = get_plugin()
    kwargs = compile_kwargs()

    assert plugin["packet_version"] == "v5"
    assert plugin["packet_variant"] == "tool_assisted_anchors_internal"
    assert plugin["packet_strategy"] == "literal_symbol"
    assert kwargs == {
        "packet_version": "v5",
        "packet_variant": "tool_assisted_anchors_internal",
        "packet_strategy": "literal_symbol",
    }


def test_fallback_and_allowed_sections() -> None:
    plugin = get_plugin()

    assert plugin["fallback"] == "ranked_paths_plus_anchors"
    assert plugin["fallback_variant"] == "ranked_paths_plus_anchors"
    assert plugin["fallback_strategy"] is None
    assert plugin["model_facing_sections"] == [
        "TASK",
        "PRIMARY_FILES",
        "RELATED_TESTS",
        "END_PREMODE_CONTEXT_PACKET_V5",
    ]


def test_forbidden_model_facing_sections_are_absent() -> None:
    plugin = get_plugin()
    sections = set(plugin["model_facing_sections"])

    assert "TASK_CLASS" not in sections
    assert "SUPPORT_RELATIONS" not in sections
    assert "FILE" not in sections
    assert "SNIPPETS" not in sections
    assert "DIAGNOSTICS" not in sections
    assert plugin["diagnostics_out_of_band"] is True


def test_metadata_has_no_lab_artifact_or_local_path_dependency() -> None:
    plugin = get_plugin()
    metadata_text = repr(plugin)
    plugin_source = (PACKAGE_ROOT / "src" / "premode_plugin_literal_symbol" / "plugin.py").read_text(encoding="utf-8")

    for text in (metadata_text, plugin_source):
        assert "/private/tmp" not in text
        assert "premode_labs" not in text
        assert "/Users/" not in text
        assert "Local Context Compiler" not in text


def test_non_default_strategy_posture() -> None:
    plugin = get_plugin()
    deferred = {item["strategy"]: item for item in plugin["deferred_policy_branches"]}
    non_default = {item["strategy"]: item for item in plugin["non_default_strategies"]}

    assert deferred["literal_symbol_config_gated"]["status"] == "deferred_policy_branch"
    assert deferred["literal_symbol_config_gated"]["default"] is False
    assert non_default["literal_symbol_collision_filter"]["status"] == "rejected_as_default_challenger"
    assert non_default["literal_symbol_collision_filter"]["default"] is False
    assert non_default["literal_symbol_import_rank_json_only"]["status"] == "dropped"
    assert non_default["literal_symbol_import_rank_json_only"]["default"] is False
    assert plugin["packet_strategy"] not in deferred
    assert plugin["packet_strategy"] not in non_default


def test_command_args_match_core_invocation() -> None:
    assert command_args() == [
        "--packet-version",
        "v5",
        "--packet-variant",
        "tool_assisted_anchors_internal",
        "--packet-strategy",
        "literal_symbol",
    ]


def test_fallback_helpers_are_json_only_metadata() -> None:
    assert fallback_kwargs() == {
        "packet_version": "v5",
        "packet_variant": "ranked_paths_plus_anchors",
        "packet_strategy": None,
    }
    diagnostics = fallback_diagnostics("probe failure")

    assert diagnostics == {
        "fallback_used": True,
        "fallback_reason": "probe failure",
        "fallback_variant": "ranked_paths_plus_anchors",
        "fallback_strategy": None,
        "diagnostics_out_of_band": True,
    }


def test_pyproject_entry_point_and_private_metadata() -> None:
    pyproject = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "premode-plugin-literal-symbol"' in pyproject
    assert 'version = "0.1.0"' in pyproject
    assert 'license = {text = "Proprietary / All Rights Reserved"}' in pyproject
    assert '[project.entry-points."premode.plugins"]' in pyproject
    assert 'literal_symbol = "premode_plugin_literal_symbol.plugin:get_plugin"' in pyproject
    assert "License :: OSI Approved" not in pyproject


def test_readme_claim_language_is_measured_and_limited() -> None:
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "17.02% versus standard" in readme
    assert "11.68% versus `ranked_paths_plus_anchors`" in readme
    assert "measured public-matrix result, not a universal guarantee" in readme
    assert "Measured on the AH public six-prompt matrix only." in readme
    assert "Use requires owner permission." in readme
    assert "has not been published" in readme
    assert re.search(r"guarantees lower Codex token use", readme)


def test_license_is_private_and_not_permissive() -> None:
    license_text = (PACKAGE_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert "Proprietary / All Rights Reserved" in license_text
    assert "No permission is granted" in license_text
    for forbidden in ("MIT License", "Apache License", "BSD License", "GNU General Public License", "ISC License"):
        assert forbidden not in license_text
