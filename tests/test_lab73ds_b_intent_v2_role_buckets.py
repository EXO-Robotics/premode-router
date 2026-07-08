from __future__ import annotations

import json

from premode.role_model import (
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    SELECTOR_MATRIX_CLAIM_LEVEL,
    infer_prompt_intent_v2,
    intent_v2_path_score,
    role_bucket_for_path,
    selection_lock_hash_for_paths,
)


def test_media_asset_lookup_classifies_and_prioritizes_media_manifest() -> None:
    intent = infer_prompt_intent_v2("Locate the asset manifest for a material without opening source files.")
    bounded = infer_prompt_intent_v2("Locate the media asset catalog index and avoid unrelated runtime code.")

    assert intent.intent == "media_asset_lookup"
    assert bounded.intent == "media_asset_lookup"
    assert intent.confidence >= 0.8
    assert role_bucket_for_path("assets/asset_manifest.json", intent).role_bucket == "primary_lookup"
    assert role_bucket_for_path("src/bridge_entry.py", intent).role_bucket == "ignore_or_noise"
    assert intent_v2_path_score("assets/asset_manifest.json", intent) > intent_v2_path_score("src/bridge_entry.py", intent)


def test_code_entrypoint_lookup_classifies_and_maps_entrypoint_source() -> None:
    intent = infer_prompt_intent_v2("Find the startup entrypoint and bootstrap config.")

    assert intent.intent == "code_entrypoint_lookup"
    assert role_bucket_for_path("src/main.py", intent).role_bucket == "primary_lookup"
    assert role_bucket_for_path("assets/icon.png", intent).role_bucket == "asset_support"
    assert role_bucket_for_path("tests/test_main.py", intent).role_bucket == "ignore_or_noise"


def test_bugfix_runtime_classifies_tests_as_verification() -> None:
    intent = infer_prompt_intent_v2("Fix the runtime regression in the bridge behavior.")

    assert intent.intent == "bugfix_runtime"
    runtime_intent = "bugfix_runtime"
    assert role_bucket_for_path("src/runtime.py", runtime_intent).role_bucket == "primary_edit"
    assert role_bucket_for_path("tests/test_runtime.py", runtime_intent).role_bucket == "verification"
    assert role_bucket_for_path("docs/runtime.md", runtime_intent).role_bucket == "ignore_or_noise"


def test_docs_config_workflow_and_broad_repo_intents() -> None:
    assert infer_prompt_intent_v2("Update the README usage guide.").intent == "docs_only"
    assert role_bucket_for_path("docs/usage.md", "docs_only").role_bucket == "primary_edit"

    assert infer_prompt_intent_v2("Change package metadata in pyproject configuration.").intent == "config_change"
    assert role_bucket_for_path("pyproject.toml", "config_change").role_bucket == "primary_edit"

    assert infer_prompt_intent_v2("Tighten the CI workflow script before release.").intent == "workflow_change"
    assert role_bucket_for_path(".github/workflows/ci.yml", "workflow_change").role_bucket == "primary_edit"

    assert infer_prompt_intent_v2("Give me an overview map of this repo.").intent == "broad_repo_inspection"
    assert role_bucket_for_path("AI_START_HERE.md", "broad_repo_inspection").role_bucket == "primary_lookup"


def test_unknown_intent_remains_bounded() -> None:
    intent = infer_prompt_intent_v2("Please handle this unclear thing.")

    assert intent.intent == "unknown"
    assert intent.bounded_selection is True
    assert role_bucket_for_path("src/random.py", intent).role_bucket == "ignore_or_noise"


def test_paste_safe_intent_output_does_not_include_raw_prompt() -> None:
    raw_prompt = "Locate the private asset manifest for the bridge fixture."
    payload = infer_prompt_intent_v2(raw_prompt).to_dict()

    assert raw_prompt not in json.dumps(payload, sort_keys=True)
    assert "media_asset_lookup" in json.dumps(payload, sort_keys=True)


def test_selector_matrix_claim_label_is_level_zero() -> None:
    assert SELECTOR_MATRIX_CLAIM_LEVEL == "Level 0 internal metric only"
    assert INTENT_V2_ROLE_BUCKETS_VARIANT == "intent_v2_role_buckets"


def test_selection_lock_hash_is_stable_for_same_inputs() -> None:
    first = selection_lock_hash_for_paths(["src/main.py", "tests/test_main.py"], intent="bugfix_runtime")
    second = selection_lock_hash_for_paths(["tests/test_main.py", "src/main.py"], intent="bugfix_runtime")
    changed = selection_lock_hash_for_paths(["src/main.py"], intent="bugfix_runtime")

    assert first == second
    assert first != changed
