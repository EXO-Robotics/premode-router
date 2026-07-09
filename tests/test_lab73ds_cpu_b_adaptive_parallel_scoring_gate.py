from __future__ import annotations

import hashlib
import json

import pytest

from premode import role_model
from premode.role_model import (
    ADAPTIVE_PARALLEL_POLICY_VERSION,
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    RepoWarmIndex,
    dry_run_selector_candidate,
)


PROMPT = "Fix the runtime cache bug and verify the cache regression test."


def _paths(count: int) -> list[str]:
    paths: list[str] = []
    templates = (
        "src/cache/module_{i:05d}.py",
        "tests/test_cache_{i:05d}.py",
        "docs/cache_{i:05d}.md",
        "config/cache_{i:05d}.yml",
        "assets/cache_{i:05d}.png",
    )
    for i in range(count):
        paths.append(templates[i % len(templates)].format(i=i))
    return paths


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


def _parallel(paths: list[str], *, mode: str = "threads", workers: int = 2):
    return dry_run_selector_candidate(
        paths,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache/module_00000.py"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(paths),
        parallel_scoring_enabled=True,
        parallel_scoring_mode=mode,
        parallel_score_workers=workers,
    )


def _score_order_hash(result) -> str:
    payload = {
        "selected_paths": list(result.selected_paths),
        "role_buckets": dict(result.role_bucket_summary),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _assert_equivalent(serial, adaptive) -> None:
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


def test_adaptive_mode_remains_opt_in_and_default_behavior_unchanged() -> None:
    default = dry_run_selector_candidate(_paths(50), PROMPT, default_selected_paths=["README.md"])

    assert default.candidate_selector_used is False
    assert default.selected_paths == ("README.md",)
    assert default.parallel_scoring_enabled is False
    assert default.parallel_scoring_mode == "serial"
    assert default.adaptive_parallel_enabled is False


def test_adaptive_mode_does_not_run_unless_explicitly_enabled() -> None:
    result = dry_run_selector_candidate(
        _paths(300),
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache/module_00000.py"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(_paths(300)),
        parallel_scoring_mode="adaptive",
    )

    assert result.candidate_selector_used is True
    assert result.parallel_scoring_enabled is False
    assert result.adaptive_parallel_enabled is False
    assert result.adaptive_policy_version is None


def test_adaptive_mode_requires_warm_index_and_does_not_make_warm_or_candidate_default() -> None:
    paths = _paths(300)
    warm_only = dry_run_selector_candidate(
        paths,
        PROMPT,
        default_selected_paths=["README.md"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(paths),
    )
    no_warm = dry_run_selector_candidate(
        paths,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/cache/module_00000.py"],
        parallel_scoring_enabled=True,
        parallel_scoring_mode="adaptive",
    )

    assert warm_only.candidate_selector_used is False
    assert warm_only.candidate_selector_fallback_reason == "candidate_not_requested"
    assert warm_only.adaptive_parallel_enabled is False
    assert no_warm.warm_index_enabled is False
    assert no_warm.parallel_score_fallback_reason == "parallel_requires_valid_warm_index"
    assert no_warm.adaptive_parallel_enabled is False


@pytest.mark.parametrize(
    "count,mode,workers,small_guard",
    [
        (50, "serial", 0, True),
        (300, "serial", 0, True),
        (600, "serial", 0, True),
        (1200, "serial", 0, False),
        (5000, "serial", 0, False),
        (8000, "serial", 0, False),
    ],
)
def test_adaptive_threshold_policy_selects_expected_thread_first_modes(
    count: int,
    mode: str,
    workers: int,
    small_guard: bool,
) -> None:
    result = _adaptive(_paths(count))

    assert result.adaptive_parallel_enabled is True
    assert result.adaptive_policy_version == ADAPTIVE_PARALLEL_POLICY_VERSION
    assert result.adaptive_candidate_count == count
    assert result.adaptive_selected_mode == mode
    assert result.adaptive_selected_workers == workers
    assert result.adaptive_reason == "measured_warm_serial_near_best"
    assert (result.adaptive_selected_workers or 0) <= count
    assert result.adaptive_small_repo_guard_triggered is small_guard
    assert result.parallel_scoring_mode == "adaptive"
    assert result.parallel_score_fallback_reason is None


@pytest.mark.parametrize("count", [50, 300, 600, 1200, 5000, 8000])
def test_adaptive_output_matches_serial_for_every_candidate_bucket(count: int) -> None:
    paths = _paths(count)
    serial = _serial(paths)
    adaptive = _adaptive(paths)

    _assert_equivalent(serial, adaptive)
    assert adaptive.candidate_enumeration_count == serial.candidate_enumeration_count == count


def test_repeated_adaptive_runs_are_deterministic() -> None:
    paths = _paths(1200)
    first = _adaptive(paths)
    second = _adaptive(paths)

    assert second.selected_paths == first.selected_paths
    assert second.role_bucket_summary == first.role_bucket_summary
    assert second.selection_lock_hash == first.selection_lock_hash
    assert _score_order_hash(second) == _score_order_hash(first)


def test_adaptive_worker_choice_and_diagnostics_do_not_affect_lock_or_packet_hash() -> None:
    paths = _paths(1200)
    serial = _serial(paths)
    adaptive = _adaptive(paths)
    threads_four = _parallel(paths, workers=4)
    payload = adaptive.to_dict()

    assert adaptive.adaptive_selected_workers == 0
    assert adaptive.adaptive_selected_mode == "serial"
    assert threads_four.parallel_score_workers == 4
    assert adaptive.selection_lock_hash == threads_four.selection_lock_hash == serial.selection_lock_hash
    assert _score_order_hash(adaptive) == _score_order_hash(threads_four) == _score_order_hash(serial)
    assert "packet" not in payload
    assert "packet_hash" not in payload
    assert "model_facing_output" not in payload


def test_worker_exception_falls_back_to_serial_with_structured_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(1200)
    serial = _serial(paths)

    def fail_score(_args):  # pragma: no cover - exercised through worker fallback
        raise RuntimeError("forced worker failure")

    monkeypatch.setattr(role_model, "_score_warm_candidate", fail_score)
    fallback = _adaptive(paths)

    assert fallback.parallel_score_fallback_reason == "worker_exception:RuntimeError"
    assert fallback.adaptive_fallback_reason == "worker_exception:RuntimeError"
    _assert_equivalent(serial, fallback)


def test_process_mode_remains_explicit_and_not_selected_by_adaptive_policy() -> None:
    paths = _paths(1200)
    adaptive = _adaptive(paths)
    process = _parallel(_paths(50), mode="processes", workers=2)

    assert adaptive.adaptive_selected_mode != "processes"
    assert adaptive.parallel_scoring_mode == "adaptive"
    assert process.parallel_scoring_mode == "processes"


def test_setup_install_package_live_routing_surfaces_untouched() -> None:
    payload = _adaptive(_paths(300)).to_dict()

    assert "setup" not in payload
    assert "install" not in payload
    assert "package" not in payload
    assert "live_routing" not in payload
