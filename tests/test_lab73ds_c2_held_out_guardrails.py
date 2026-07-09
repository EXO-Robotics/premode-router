from __future__ import annotations

import json

from premode.role_model import (
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    SELECTOR_MATRIX_CLAIM_LEVEL,
    infer_prompt_intent,
    infer_prompt_intent_v2,
    rank_intent_v2_paths,
    role_bucket_for_path,
    selection_lock_hash_for_paths,
)


def _ranked(paths: list[str], prompt: str) -> list[str]:
    return [decision.path for decision in rank_intent_v2_paths(paths, prompt)]


def test_media_asset_lookup_maps_media_files_to_primary_lookup() -> None:
    decision = role_bucket_for_path("assets/materials/catalog.json", "media_asset_lookup")

    assert decision.role_bucket == "primary_lookup"


def test_media_asset_lookup_prevents_source_outranking_asset_matches() -> None:
    prompt = "Locate the material catalog media asset without using runtime source files."
    paths = [
        "src/main.py",
        "runtime/material_loader.py",
        "assets/materials/catalog.json",
        "assets/materials/legacy_catalog.json",
    ]

    selected = _ranked(paths, prompt)

    assert selected[0] == "assets/materials/catalog.json"
    assert selected.index("assets/materials/catalog.json") < selected.index("runtime/material_loader.py")
    assert "assets/materials/legacy_catalog.json" not in selected


def test_large_repo_media_lookup_stays_metadata_only() -> None:
    prompt = "In a large repo media library, locate the texture index metadata path."
    paths = [
        "mega_assets/library/texture_index.json",
        "src/main.py",
        "archive/old_texture_index.json",
    ]

    intent = infer_prompt_intent_v2(prompt)
    selected = _ranked(paths, prompt)

    assert intent.intent == "large_repo_media_lookup"
    assert selected[0] == "mega_assets/library/texture_index.json"
    assert role_bucket_for_path("mega_assets/library/texture_index.json", intent).role_bucket == "primary_lookup"


def test_code_entrypoint_lookup_maps_source_entrypoints_to_primary_lookup() -> None:
    decision = role_bucket_for_path("bridge/runtime/bridge_entry.py", "code_entrypoint_lookup")

    assert decision.role_bucket == "primary_lookup"


def test_code_entrypoint_lookup_keeps_media_assets_out_of_primary() -> None:
    prompt = "Find the bridge command entrypoint and bootstrap file, not the material catalog."
    paths = [
        "bridge/runtime/bridge_entry.py",
        "bridge/assets/material_catalog.json",
        "src/main.py",
    ]

    ranked = rank_intent_v2_paths(paths, prompt)
    buckets = {decision.path: decision.role_bucket for decision in ranked}

    assert buckets["bridge/runtime/bridge_entry.py"] == "primary_lookup"
    assert buckets.get("bridge/assets/material_catalog.json") != "primary_lookup"


def test_bugfix_runtime_maps_source_and_tests_to_expected_roles() -> None:
    assert role_bucket_for_path("src/runtime_cache.py", "bugfix_runtime").role_bucket == "primary_edit"
    assert role_bucket_for_path("tests/test_runtime_cache.py", "bugfix_runtime").role_bucket == "verification"


def test_docs_config_and_workflow_primary_roles() -> None:
    assert role_bucket_for_path("docs/install_guide.md", "docs_only").role_bucket == "primary_edit"
    assert role_bucket_for_path("README.md", "docs_only").role_bucket == "support_context"
    assert role_bucket_for_path("pyproject.toml", "config_change").role_bucket == "primary_edit"
    assert role_bucket_for_path("docs/release.md", "config_change", linked=True).role_bucket == "docs_support"
    assert role_bucket_for_path(".github/workflows/ci.yml", "workflow_change").role_bucket == "primary_edit"
    assert role_bucket_for_path("scripts/ci_smoke.py", "workflow_change").role_bucket == "primary_edit"
    assert role_bucket_for_path("docs/release.md", "workflow_change", linked=True).role_bucket == "docs_support"


def test_support_role_caps_prevent_support_crowd_out() -> None:
    prompt = "Fix the runtime cache key bug and verify with the cache regression test."
    paths = [
        "README.md",
        "docs/runtime.md",
        "config/settings.yaml",
        "services/cache/runtime_cache.py",
        "tests/test_runtime_cache.py",
    ]

    ranked = rank_intent_v2_paths(paths, prompt)
    buckets = [decision.role_bucket for decision in ranked]

    assert "services/cache/runtime_cache.py" in [decision.path for decision in ranked]
    assert "tests/test_runtime_cache.py" in [decision.path for decision in ranked]
    assert buckets.count("support_context") <= 1
    assert buckets.count("config_support") <= 1


def test_unknown_remains_bounded() -> None:
    prompt = "Please handle this unclear thing."
    paths = ["src/random.py", "README.md", "pyproject.toml"]

    intent = infer_prompt_intent_v2(prompt)
    ranked = rank_intent_v2_paths(paths, prompt)

    assert intent.intent == "unknown"
    assert intent.bounded_selection is True
    assert len(ranked) <= 3


def test_selector_remains_opt_in_and_default_intent_unchanged() -> None:
    assert INTENT_V2_ROLE_BUCKETS_VARIANT == "intent_v2_role_buckets"
    assert infer_prompt_intent("Fix the runtime cache bug.").intent == "runtime"


def test_claim_label_raw_prompt_safety_and_selection_lock_stability() -> None:
    raw_prompt = "Locate the private material catalog."
    payload = infer_prompt_intent_v2(raw_prompt).to_dict()

    assert SELECTOR_MATRIX_CLAIM_LEVEL == "Level 0 internal metric only"
    assert raw_prompt not in json.dumps(payload, sort_keys=True)
    assert selection_lock_hash_for_paths(["b.py", "a.py"], intent="bugfix_runtime") == selection_lock_hash_for_paths(
        ["a.py", "b.py"],
        intent="bugfix_runtime",
    )
