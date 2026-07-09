from __future__ import annotations

import json

from premode.role_model import (
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    SELECTOR_MATRIX_CLAIM_LEVEL,
    dry_run_selector_candidate,
    infer_prompt_intent,
    selection_lock_hash_for_paths,
)


def test_default_selector_remains_unchanged_without_opt_in() -> None:
    paths = ["src/cache.py", "tests/test_cache.py"]
    default_paths = ["src/cache.py"]

    result = dry_run_selector_candidate(paths, "Fix the runtime cache bug.", default_selected_paths=default_paths)

    assert infer_prompt_intent("Fix the runtime cache bug.").intent == "runtime"
    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback is True
    assert result.candidate_selector_fallback_reason == "candidate_not_requested"
    assert result.selected_paths == tuple(default_paths)


def test_candidate_selector_requires_explicit_supported_opt_in() -> None:
    result = dry_run_selector_candidate(
        ["src/cache.py"],
        "Fix the runtime cache bug.",
        selector_candidate="other_selector",
        default_selected_paths=["src/cache.py"],
    )

    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback_reason == "unsupported_selector_candidate"


def test_candidate_selector_uses_intent_v2_role_buckets_as_advisory_only() -> None:
    result = dry_run_selector_candidate(
        ["src/cache.py", "tests/test_cache.py", "README.md"],
        "Fix the runtime cache bug and verify the regression test.",
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache.py"],
    )

    assert result.selector_variant == INTENT_V2_ROLE_BUCKETS_VARIANT
    assert result.candidate_selector_used is True
    assert result.candidate_selector_fallback is False
    assert result.advisory_only is True
    assert result.intent_v2 == "bugfix_runtime"
    assert result.role_bucket_summary["primary_edit"] == 1
    assert result.role_bucket_summary["verification"] == 1


def test_candidate_selector_reports_paste_safe_metadata_fields() -> None:
    raw_prompt = "Locate the texture catalog media asset without runtime code."
    result = dry_run_selector_candidate(
        ["assets/materials/material_catalog.json", "src/main.py"],
        raw_prompt,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/main.py"],
    )
    payload = result.to_dict()

    for key in [
        "selector_variant",
        "candidate_selector_used",
        "candidate_selector_fallback",
        "candidate_selector_fallback_reason",
        "intent_v2",
        "intent_confidence",
        "role_bucket_summary",
        "selection_lock_hash",
    ]:
        assert key in payload
    assert raw_prompt not in json.dumps(payload, sort_keys=True)
    assert "selected_paths" not in payload


def test_low_confidence_unknown_falls_back() -> None:
    result = dry_run_selector_candidate(
        ["src/main.py", "README.md"],
        "Please handle this unclear thing.",
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["README.md"],
    )

    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback is True
    assert result.candidate_selector_fallback_reason == "low_confidence_or_unknown"


def test_empty_primary_selection_falls_back() -> None:
    result = dry_run_selector_candidate(
        ["src/main.py"],
        "Update the documentation guide.",
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/main.py"],
    )

    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback_reason == "empty_primary_selection"


def test_forbidden_risk_fallback_is_represented() -> None:
    result = dry_run_selector_candidate(
        ["src/cache.py", "tests/test_cache.py"],
        "Fix the runtime cache bug.",
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["README.md"],
        forbidden_paths=["src/cache.py"],
    )

    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback_reason == "forbidden_risk_detected"
    assert result.selected_paths == ("README.md",)


def test_content_reads_remain_zero_in_candidate_metadata_path() -> None:
    result = dry_run_selector_candidate(
        ["assets/textures/stone_wall.ktx", "src/main.py"],
        "Locate the texture asset without source files.",
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
    )

    assert result.content_reads == 0


def test_selection_lock_hash_is_stable() -> None:
    result = dry_run_selector_candidate(
        ["tests/test_cache.py", "src/cache.py"],
        "Fix the runtime cache bug and verify the regression test.",
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
    )
    repeated = dry_run_selector_candidate(
        ["src/cache.py", "tests/test_cache.py"],
        "Fix the runtime cache bug and verify the regression test.",
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
    )

    assert result.selection_lock_hash == repeated.selection_lock_hash
    assert result.selection_lock_hash == selection_lock_hash_for_paths(list(result.selected_paths), intent=result.intent_v2)


def test_level_0_claim_label_remains_enforced() -> None:
    result = dry_run_selector_candidate(
        ["src/cache.py"],
        "Fix the runtime cache bug.",
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
    )

    assert SELECTOR_MATRIX_CLAIM_LEVEL == "Level 0 internal metric only"
    assert result.claim_level == SELECTOR_MATRIX_CLAIM_LEVEL
