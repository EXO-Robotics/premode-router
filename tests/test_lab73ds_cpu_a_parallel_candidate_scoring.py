from __future__ import annotations

import builtins

import pytest

from premode.role_model import (
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    RepoWarmIndex,
    RoleBucketDecision,
    ScoreRecord,
    _reduce_score_records,
    dry_run_selector_candidate,
)


PROMPT = "Fix the runtime cache bug and verify the regression test."
PATHS = [
    "docs/cache.md",
    "src/cache.py",
    "tests/test_cache.py",
    "config/cache.yml",
    "assets/cache_icon.png",
]

PROMPT_MATRIX = [
    (
        "media_asset_lookup",
        "Locate the texture asset catalog without opening runtime source files.",
        [
            "assets/materials/catalog.json",
            "assets/materials/legacy_catalog.json",
            "src/material_loader.py",
            "docs/materials.md",
        ],
    ),
    (
        "code_entrypoint_lookup",
        "Find the startup entrypoint and bootstrap config.",
        [
            "src/main.py",
            "src/runtime/cache.py",
            "config/settings.yaml",
            "tests/test_main.py",
            "assets/icon.png",
        ],
    ),
    (
        "symbol_lookup",
        "Locate the function definition for cache invalidation.",
        [
            "src/cache_invalidation.py",
            "tests/test_cache_invalidation.py",
            "README.md",
            "pyproject.toml",
        ],
    ),
    (
        "specific_bugfix",
        "Fix the runtime cache bug and verify the regression test.",
        PATHS,
    ),
    (
        "docs_only",
        "Update the installation documentation guide without changing runtime code.",
        [
            "README.md",
            "docs/installation.md",
            "src/install.py",
            "tests/test_install.py",
        ],
    ),
    (
        "config_change",
        "Change package metadata in pyproject configuration.",
        [
            "pyproject.toml",
            "src/package_info.py",
            "docs/package.md",
            "tests/test_package.py",
        ],
    ),
    (
        "workflow_change",
        "Tighten the CI workflow script before release.",
        [
            ".github/workflows/ci.yml",
            "scripts/ci_smoke.py",
            "src/main.py",
            "tests/test_main.py",
            "docs/release.md",
        ],
    ),
    (
        "broad_repo_inspection",
        "Give me an overview map of this repo.",
        [
            "AI_START_HERE.md",
            "AGENTS.md",
            "premode.ai.json",
            "README.md",
            "src/premode/compiler.py",
        ],
    ),
    (
        "large_repo_media_safe_prompt",
        "In a large repo media library, locate the texture index metadata path.",
        [
            "mega_assets/library/texture_index.json",
            "archive/old_texture_index.json",
            "src/main.py",
            "docs/assets.md",
        ],
    ),
]


def _serial(paths: list[str], prompt: str):
    return dry_run_selector_candidate(
        paths,
        prompt,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache.py"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(paths),
    )


def _parallel(paths: list[str], prompt: str, *, mode: str = "threads", workers: int = 2):
    return dry_run_selector_candidate(
        paths,
        prompt,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache.py"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(paths),
        parallel_scoring_enabled=True,
        parallel_scoring_mode=mode,
        parallel_score_workers=workers,
    )


def _assert_parallel_equivalent(serial, parallel) -> None:
    assert parallel.selected_paths == serial.selected_paths
    assert len(parallel.candidate_paths) == len(serial.candidate_paths)
    assert parallel.role_bucket_summary == serial.role_bucket_summary
    assert parallel.selection_lock_hash == serial.selection_lock_hash
    assert parallel.content_reads == serial.content_reads == 0


def test_parallel_scoring_remains_opt_in_and_default_behavior_unchanged() -> None:
    result = dry_run_selector_candidate(PATHS, PROMPT, default_selected_paths=["README.md"])

    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback_reason == "candidate_not_requested"
    assert result.selected_paths == ("README.md",)
    assert result.parallel_scoring_enabled is False
    assert result.parallel_scoring_mode == "serial"


def test_serial_warm_index_output_is_unchanged() -> None:
    cold = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache.py"],
    )
    warm = _serial(PATHS, PROMPT)

    assert warm.warm_index_hit is True
    assert warm.warm_index_metadata_only_verified is True
    assert warm.selected_paths == cold.selected_paths
    assert len(warm.candidate_paths) == len(cold.candidate_paths)
    assert warm.role_bucket_summary == cold.role_bucket_summary
    assert warm.selection_lock_hash == cold.selection_lock_hash
    assert warm.content_reads == cold.content_reads == 0


@pytest.mark.parametrize("task_id,prompt,paths", PROMPT_MATRIX)
def test_thread_mode_matches_serial_for_selector_fixture_matrix(task_id: str, prompt: str, paths: list[str]) -> None:
    serial = _serial(paths, prompt)
    parallel = _parallel(paths, prompt, mode="threads", workers=4)

    assert task_id
    assert parallel.parallel_scoring_enabled is True
    assert parallel.parallel_scoring_mode == "threads"
    assert parallel.parallel_score_fallback_reason is None
    assert parallel.score_record_count == len(RepoWarmIndex.build(paths).paths)
    _assert_parallel_equivalent(serial, parallel)


def test_repeated_parallel_runs_are_deterministic() -> None:
    first = _parallel(PATHS, PROMPT, mode="threads", workers=2)
    second = _parallel(PATHS, PROMPT, mode="threads", workers=4)
    third = _parallel(list(reversed(PATHS)), PROMPT, mode="threads", workers=2)
    serial_reversed = _serial(list(reversed(PATHS)), PROMPT)

    assert second.selected_paths == first.selected_paths
    assert second.selection_lock_hash == first.selection_lock_hash
    assert second.role_bucket_summary == first.role_bucket_summary
    assert third.selected_paths == serial_reversed.selected_paths
    assert third.selection_lock_hash == serial_reversed.selection_lock_hash


def test_worker_completion_order_does_not_affect_serial_reducer() -> None:
    records = [
        ScoreRecord(ordinal=2, path="tests/test_cache.py", score=650, role_bucket="verification", sort_key=(-650, "tests/test_cache.py"), matched_signal_ids=(), role_bucket_reason="runtime_test_verification"),
        ScoreRecord(ordinal=0, path="README.md", score=350, role_bucket="support_context", sort_key=(-350, "README.md"), matched_signal_ids=(), role_bucket_reason="docs_support"),
        ScoreRecord(ordinal=1, path="src/cache.py", score=900, role_bucket="primary_edit", sort_key=(-900, "src/cache.py"), matched_signal_ids=(), role_bucket_reason="runtime_source_primary"),
    ]

    selected, fallback = _reduce_score_records(records, intent_name="bugfix_runtime", limit=3, candidate_count=3)

    assert fallback is None
    assert [decision.path for decision in selected] == ["src/cache.py", "tests/test_cache.py", "README.md"]


def test_tie_scores_reduce_identically_to_serial_sort_key() -> None:
    records = [
        ScoreRecord(ordinal=1, path="b.py", score=900, role_bucket="primary_edit", sort_key=(-900, "b.py"), matched_signal_ids=(), role_bucket_reason="runtime_source_primary"),
        ScoreRecord(ordinal=0, path="a.py", score=900, role_bucket="primary_edit", sort_key=(-900, "a.py"), matched_signal_ids=(), role_bucket_reason="runtime_source_primary"),
    ]

    selected, fallback = _reduce_score_records(records, intent_name="bugfix_runtime", limit=2, candidate_count=2)

    assert fallback is None
    assert [decision.path for decision in selected] == ["a.py"]


def test_worker_metadata_path_performs_no_file_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_open(*_args, **_kwargs):  # pragma: no cover - failure path only
        raise AssertionError("worker path must not open files")

    monkeypatch.setattr(builtins, "open", fail_open)
    result = _parallel(PATHS, PROMPT, mode="threads", workers=2)

    assert result.parallel_score_fallback_reason is None
    assert result.worker_content_reads == 0
    assert result.worker_file_open_count == 0
    assert result.worker_stat_count == 0
    assert result.worker_walk_count == 0
    assert result.content_reads == 0


def test_worker_exception_fails_closed_to_serial() -> None:
    serial = _serial(PATHS, PROMPT)
    fallback = _parallel(PATHS, PROMPT, mode="unsupported", workers=2)

    assert fallback.parallel_score_fallback_reason == "unsupported_parallel_mode:unsupported"
    _assert_parallel_equivalent(serial, fallback)


def test_process_mode_is_serial_equivalent_or_structured_fallback() -> None:
    serial = _serial(PATHS, PROMPT)
    process = _parallel(PATHS, PROMPT, mode="processes", workers=2)

    _assert_parallel_equivalent(serial, process)
    if process.parallel_score_fallback_reason is None:
        assert process.parallel_scoring_mode == "processes"
        assert process.score_record_count == len(PATHS)
    else:
        assert process.parallel_score_fallback_reason.startswith(("worker_exception:", "unsupported_parallel_mode:"))


def test_lock_hash_excludes_timing_and_worker_details() -> None:
    serial = _serial(PATHS, PROMPT)
    two_workers = _parallel(PATHS, PROMPT, mode="threads", workers=2)
    four_workers = _parallel(PATHS, PROMPT, mode="threads", workers=4)

    assert two_workers.total_selector_ms >= 0
    assert four_workers.total_selector_ms >= 0
    assert two_workers.parallel_score_workers != four_workers.parallel_score_workers
    assert two_workers.selection_lock_hash == four_workers.selection_lock_hash == serial.selection_lock_hash


def test_candidate_and_warm_index_selectors_remain_opt_in() -> None:
    warm_only = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        default_selected_paths=["README.md"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(PATHS),
    )
    candidate_only = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache.py"],
    )

    assert warm_only.candidate_selector_used is False
    assert warm_only.candidate_selector_fallback_reason == "candidate_not_requested"
    assert warm_only.selected_paths == ("README.md",)
    assert candidate_only.warm_index_enabled is False
    assert candidate_only.parallel_scoring_enabled is False


def test_setup_install_package_live_routing_and_packet_surfaces_untouched() -> None:
    payload = _parallel(PATHS, PROMPT, mode="threads", workers=2).to_dict()

    assert "setup" not in payload
    assert "install" not in payload
    assert "package" not in payload
    assert "live_routing" not in payload
    assert "packet" not in payload
