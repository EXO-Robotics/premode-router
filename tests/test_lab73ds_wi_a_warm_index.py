from __future__ import annotations

from dataclasses import replace
import json

from premode.role_model import (
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    SELECTOR_MATRIX_CLAIM_LEVEL,
    WARM_INDEX_INVENTORY_VERSION,
    RepoWarmIndex,
    dry_run_selector_candidate,
)


PROMPT = "Fix the runtime cache bug and verify the regression test."
PATHS = [
    "README.md",
    "src/cache.py",
    "tests/test_cache.py",
    "assets/logo.png",
]


def _cold():
    return dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache.py"],
    )


def _warm(index: RepoWarmIndex):
    return dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache.py"],
        warm_index_enabled=True,
        warm_index=index,
    )


def test_warm_index_builds_without_content_reads() -> None:
    index = RepoWarmIndex.build(PATHS)

    assert index.content_reads == 0
    assert index.path_metadata
    assert all(metadata.path for metadata in index.path_metadata)
    payload = json.dumps(index.to_dict(), sort_keys=True).lower()
    assert "file_content" not in payload
    assert "source_text" not in payload
    assert "source_snippet" not in payload


def test_cold_and_warm_selected_paths_candidate_counts_and_buckets_match() -> None:
    cold = _cold()
    warm = _warm(RepoWarmIndex.build(PATHS))

    assert warm.warm_index_enabled is True
    assert warm.warm_index_hit is True
    assert warm.selected_paths == cold.selected_paths
    assert len(warm.candidate_paths) == len(cold.candidate_paths)
    assert warm.role_bucket_summary == cold.role_bucket_summary
    assert warm.selection_lock_hash == cold.selection_lock_hash
    assert warm.content_reads == cold.content_reads == 0


def test_warm_index_hit_and_miss_metadata_is_recorded() -> None:
    built = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        warm_index_enabled=True,
    )
    hit = _warm(RepoWarmIndex.build(PATHS))

    assert built.warm_index_miss is True
    assert built.warm_index_build_ms >= 0
    assert hit.warm_index_hit is True
    assert hit.warm_index_cache_key


def test_missing_index_falls_back_to_cold_path() -> None:
    cold = _cold()
    result = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        warm_index_enabled=True,
        warm_index=None,
        build_warm_index=False,
    )

    assert result.warm_index_fallback_reason == "missing_index"
    assert result.selected_paths == cold.selected_paths
    assert result.selection_lock_hash == cold.selection_lock_hash


def test_corrupt_and_stale_index_fall_back_to_cold_path() -> None:
    cold = _cold()
    corrupt = replace(RepoWarmIndex.build(PATHS), path_metadata=())
    stale = RepoWarmIndex.build(PATHS[:-1])

    corrupt_result = _warm(corrupt)
    stale_result = _warm(stale)

    assert corrupt_result.warm_index_fallback_reason == "corrupt_index_metadata"
    assert stale_result.warm_index_fallback_reason == "file_set_changed"
    assert corrupt_result.selected_paths == cold.selected_paths
    assert stale_result.selected_paths == cold.selected_paths


def test_file_set_and_inventory_version_change_invalidate_index() -> None:
    index = RepoWarmIndex.build(PATHS)
    changed_paths = PATHS + ["src/new_cache.py"]

    assert index.validate_for_paths(changed_paths)[1] == "file_set_changed"
    assert index.validate_for_paths(PATHS, inventory_version="future-version")[1] == "selector_inventory_version_changed"
    assert WARM_INDEX_INVENTORY_VERSION == "warm-index-v1"


def test_no_file_contents_prompts_or_packets_are_cached() -> None:
    index = RepoWarmIndex.build(PATHS)
    payload = json.dumps(index.to_dict(include_paths=True), sort_keys=True)

    assert PROMPT not in payload
    assert "raw_prompt" not in payload
    assert "packet" not in payload
    assert "source_snippet" not in payload


def test_deterministic_ordering_is_preserved() -> None:
    cold = dry_run_selector_candidate(
        list(reversed(PATHS)),
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
    )
    warm = dry_run_selector_candidate(
        list(reversed(PATHS)),
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(list(reversed(PATHS))),
    )

    assert warm.selected_paths == cold.selected_paths
    assert warm.selection_lock_hash == cold.selection_lock_hash


def test_candidate_selector_remains_opt_in_and_default_behavior_unchanged() -> None:
    result = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        default_selected_paths=["README.md"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(PATHS),
    )

    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback_reason == "candidate_not_requested"
    assert result.selected_paths == ("README.md",)


def test_level_0_claim_label_remains_enforced() -> None:
    result = _warm(RepoWarmIndex.build(PATHS))

    assert SELECTOR_MATRIX_CLAIM_LEVEL == "Level 0 internal metric only"
    assert result.claim_level == SELECTOR_MATRIX_CLAIM_LEVEL
