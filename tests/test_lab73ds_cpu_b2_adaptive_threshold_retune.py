from __future__ import annotations

import hashlib
import json

from premode.role_model import (
    ADAPTIVE_PARALLEL_POLICY_VERSION,
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    RepoWarmIndex,
    dry_run_selector_candidate,
)


PROMPT = "Fix the runtime cache bug and verify the cache regression test."


def _paths(count: int) -> list[str]:
    templates = (
        "src/cache/module_{i:05d}.py",
        "tests/test_cache_{i:05d}.py",
        "docs/cache_{i:05d}.md",
        "config/cache_{i:05d}.yml",
        "assets/cache_{i:05d}.png",
    )
    return [templates[i % len(templates)].format(i=i) for i in range(count)]


def _serial(paths: list[str]):
    return dry_run_selector_candidate(
        paths,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache/module_00000.py"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(paths),
    )


def _adaptive(paths: list[str]):
    return dry_run_selector_candidate(
        paths,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache/module_00000.py"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(paths),
        parallel_scoring_enabled=True,
        parallel_scoring_mode="adaptive",
    )


def _score_order_hash(result) -> str:
    payload = {
        "selected_paths": list(result.selected_paths),
        "role_buckets": dict(result.role_bucket_summary),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def test_b2_retuned_policy_selects_warm_serial_for_repeated_sweep_buckets() -> None:
    for count in (50, 150, 300, 600, 1200, 2500, 5000, 12000, 25000):
        result = _adaptive(_paths(count))

        assert result.adaptive_parallel_enabled is True
        assert result.adaptive_policy_version == ADAPTIVE_PARALLEL_POLICY_VERSION
        assert result.adaptive_selected_mode == "serial"
        assert result.adaptive_selected_workers == 0
        assert result.adaptive_reason == "measured_warm_serial_near_best"
        assert result.parallel_score_workers == 0


def test_b2_retuned_policy_preserves_serial_equivalence_and_zero_worker_io() -> None:
    for count in (50, 150, 300, 600, 1200, 2500, 5000, 12000):
        paths = _paths(count)
        serial = _serial(paths)
        adaptive = _adaptive(paths)

        assert adaptive.selected_paths == serial.selected_paths
        assert len(adaptive.candidate_paths) == len(serial.candidate_paths)
        assert adaptive.role_bucket_summary == serial.role_bucket_summary
        assert _score_order_hash(adaptive) == _score_order_hash(serial)
        assert adaptive.selection_lock_hash == serial.selection_lock_hash
        assert adaptive.content_reads == serial.content_reads == 0
        assert adaptive.worker_content_reads == 0
        assert adaptive.worker_file_open_count == 0
        assert adaptive.worker_stat_count == 0
        assert adaptive.worker_walk_count == 0


def test_b2_retuned_policy_is_deterministic_and_does_not_promote_process_mode() -> None:
    paths = _paths(12000)
    first = _adaptive(paths)
    second = _adaptive(paths)

    assert first.adaptive_selected_mode == second.adaptive_selected_mode == "serial"
    assert first.adaptive_selected_workers == second.adaptive_selected_workers == 0
    assert first.selection_lock_hash == second.selection_lock_hash
    assert _score_order_hash(first) == _score_order_hash(second)
    assert first.adaptive_selected_mode != "processes"
