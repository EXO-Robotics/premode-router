from __future__ import annotations

from dataclasses import replace
import json

from premode.role_model import (
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    WARM_INDEX_PATH_NORMALIZATION_VERSION,
    RepoWarmIndex,
    dry_run_selector_candidate,
    infer_prompt_intent,
)


PROMPT = "Fix the runtime cache bug and verify the regression test."
PATHS = [
    "docs/cache.md",
    "src/cache.py",
    "tests/test_cache.py",
    "config/cache.yml",
    "assets/cache_icon.png",
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
        repo_root="/repo",
        git_head="head-a",
        dirty_state_hash="clean",
        include_exclude_hash="include-a",
        ignore_file_hash="ignore-a",
    )


def _index() -> RepoWarmIndex:
    return RepoWarmIndex.build(
        PATHS,
        repo_root="/repo",
        git_head="head-a",
        dirty_state_hash="clean",
        include_exclude_hash="include-a",
        ignore_file_hash="ignore-a",
    )


def test_warm_index_remains_opt_in_and_default_selector_unchanged() -> None:
    result = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        default_selected_paths=["README.md"],
        warm_index_enabled=True,
        warm_index=_index(),
    )

    assert infer_prompt_intent(PROMPT).intent == "runtime"
    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback_reason == "candidate_not_requested"
    assert result.selected_paths == ("README.md",)


def test_warm_and_cold_outputs_are_equivalent() -> None:
    cold = _cold()
    warm = _warm(_index())

    assert warm.warm_index_hit is True
    assert warm.warm_index_metadata_only_verified is True
    assert warm.selected_paths == cold.selected_paths
    assert len(warm.candidate_paths) == len(cold.candidate_paths)
    assert warm.role_bucket_summary == cold.role_bucket_summary
    assert warm.selection_lock_hash == cold.selection_lock_hash
    assert warm.content_reads == cold.content_reads == 0


def test_repeated_warm_hit_runs_are_deterministic() -> None:
    index = _index()
    first = _warm(index)
    second = _warm(index)

    assert second.warm_index_hit is True
    assert second.selected_paths == first.selected_paths
    assert second.role_bucket_summary == first.role_bucket_summary
    assert second.selection_lock_hash == first.selection_lock_hash


def test_warm_index_build_caches_metadata_only() -> None:
    index = _index()
    payload = json.dumps(index.to_dict(include_paths=True), sort_keys=True)

    assert index.content_reads == 0
    assert index.to_dict()["metadata_only_verified"] is True
    assert PROMPT not in payload
    assert "raw_prompt" not in payload
    assert "packet" not in payload
    assert "source_snippet" not in payload
    assert "file_content" not in payload


def test_missing_corrupt_and_stale_index_fall_back_with_equivalent_output() -> None:
    cold = _cold()
    missing = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        warm_index_enabled=True,
        warm_index=None,
        build_warm_index=False,
    )
    corrupt = _warm(replace(_index(), path_metadata=()))
    stale = _warm(
        RepoWarmIndex.build(
            PATHS[:-1],
            repo_root="/repo",
            git_head="head-a",
            dirty_state_hash="clean",
            include_exclude_hash="include-a",
            ignore_file_hash="ignore-a",
        )
    )

    assert missing.warm_index_fallback_reason == "missing_index"
    assert corrupt.warm_index_fallback_reason == "corrupt_index_metadata"
    assert stale.warm_index_fallback_reason == "file_set_changed"
    assert missing.selected_paths == cold.selected_paths
    assert corrupt.selected_paths == cold.selected_paths
    assert stale.selected_paths == cold.selected_paths


def test_invalidation_checks_cover_repo_and_config_changes() -> None:
    index = _index()

    assert index.validate_for_paths(PATHS, repo_root="/other")[1] == "repo_root_mismatch"
    assert index.validate_for_paths(PATHS, git_head="head-b")[1] == "git_head_changed"
    assert index.validate_for_paths(PATHS, dirty_state_hash="dirty")[1] == "dirty_state_changed"
    assert index.validate_for_paths(PATHS, include_exclude_hash="include-b")[1] == "include_exclude_config_changed"
    assert index.validate_for_paths(PATHS, ignore_file_hash="ignore-b")[1] == "ignore_config_changed"
    assert index.validate_for_paths(PATHS, inventory_version="future")[1] == "selector_inventory_version_changed"
    assert index.validate_for_paths(PATHS, path_normalization_version="windows-v1")[1] == "path_normalization_version_changed"
    assert index.validate_for_paths(PATHS + ["src/new_cache.py"])[1] == "file_set_changed"
    assert WARM_INDEX_PATH_NORMALIZATION_VERSION == "posix-slash-v1"


def test_deterministic_ordering_is_preserved() -> None:
    reversed_paths = list(reversed(PATHS))
    cold = dry_run_selector_candidate(
        reversed_paths,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
    )
    warm = dry_run_selector_candidate(
        reversed_paths,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(reversed_paths),
    )

    assert warm.selected_paths == cold.selected_paths
    assert warm.selection_lock_hash == cold.selection_lock_hash


def test_candidate_selector_stays_opt_in_with_warm_index_enabled() -> None:
    result = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate="unsupported",
        warm_index_enabled=True,
        warm_index=_index(),
    )

    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback_reason == "unsupported_selector_candidate"


def test_setup_install_package_live_routing_surfaces_are_not_present() -> None:
    payload = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        warm_index_enabled=True,
        warm_index=_index(),
    ).to_dict()

    assert "setup" not in payload
    assert "install" not in payload
    assert "package" not in payload
    assert "live_routing" not in payload
