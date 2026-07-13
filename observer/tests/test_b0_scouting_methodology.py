from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode_observer.scouting import (
    ARMS,
    assert_public_safe,
    build_blocked_schedule,
    canonical_sha256,
    classify_pair,
    trajectory_metrics,
    usage_metrics,
    validate_accepted_attempts,
    validate_comparison_record,
    validate_schedule,
)


def _tasks(count: int = 7):
    return [
        {"task_id": f"task-{index}", "repository_id": f"repo-{index % 3}", "task_class": f"class-{index % 4}"}
        for index in range(count)
    ]


def test_schedule_is_deterministic_paired_and_worker_balanced() -> None:
    first = build_blocked_schedule(_tasks(), seed=73021, configuration_hash="a" * 64)
    second = build_blocked_schedule(_tasks(), seed=73021, configuration_hash="a" * 64)
    assert first == second
    assert {row["arm"] for row in first} == set(ARMS)
    validate_schedule(first)


def test_schedule_rejects_duplicate_cell_and_same_worker_pair() -> None:
    schedule = build_blocked_schedule(_tasks(3), seed=4, configuration_hash="b" * 64)
    duplicate = [*schedule, dict(schedule[0])]
    with pytest.raises(ValueError, match="cell IDs"):
        validate_schedule(duplicate)
    broken = [dict(row) for row in schedule]
    paired = [row for row in broken if row["task_id"] == broken[0]["task_id"]]
    paired[1]["planned_worker"] = paired[0]["planned_worker"]
    with pytest.raises(ValueError, match="different workers"):
        validate_schedule(broken)


def test_path_metrics_separate_search_matches_from_scan_count() -> None:
    run = {
        "turns": [{"response": {"usage": {"prompt_tokens": 10, "completion_tokens": 3}}}],
        "tool_events": [
            {"name": "search_text", "accessed_paths": ["src/app.py"], "scanned_file_count": 18},
            {"name": "read_file", "accessed_paths": ["src/app.py"]},
            {"name": "read_file", "accessed_paths": ["tests/test_app.py"]},
        ],
    }
    metrics = trajectory_metrics(run, required_paths=("src/app.py",), supplied_paths=("src/app.py", "README.md"))
    assert metrics["search_scanned_file_count"] == 18
    assert metrics["repeated_file_reads"] == 1
    assert metrics["supplied_paths_used"] == ["src/app.py"]
    assert metrics["supplied_paths_unused"] == ["README.md"]
    assert usage_metrics(run) == {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13, "usage_missing_requests": 0}


def test_exactly_once_controls_reject_duplicate_cells_fixtures_and_drift() -> None:
    common = {
        "accepted": True,
        "task_id": "t",
        "task_hash": "a",
        "validator_hash": "b",
        "start_tree_hash": "c",
        "system_prompt_hash": "d",
        "tool_schema_hash": "e",
        "model_runtime_hash": "f",
        "sampler_hash": "g",
    }
    records = [
        {**common, "cell_id": "one", "fixture_instance_id": "fixture-one", "run_id": "run-one"},
        {**common, "cell_id": "two", "fixture_instance_id": "fixture-two", "run_id": "run-two"},
    ]
    validate_accepted_attempts(records)
    with pytest.raises(ValueError, match="experimental cell"):
        validate_accepted_attempts([records[0], {**records[1], "cell_id": "one"}])
    with pytest.raises(ValueError, match="fixture instance"):
        validate_accepted_attempts([records[0], {**records[1], "fixture_instance_id": "fixture-one"}])
    with pytest.raises(ValueError, match="control drift"):
        validate_accepted_attempts([records[0], {**records[1], "task_hash": "changed"}])


@pytest.mark.parametrize(
    ("standard", "b0", "kwargs", "expected"),
    [
        ({"valid": False}, {"valid": True}, {}, "invalid"),
        ({"valid": True, "validator_or_fixture_failure": True}, {"valid": True}, {}, "validator_or_fixture_failure"),
        ({"valid": True, "task_success": False, "primary_defect": "model_tool_use_failure"}, {"valid": True, "task_success": False, "primary_defect": "model_tool_use_failure"}, {}, "agent_only_failure"),
        ({"valid": True, "task_success": False}, {"valid": True, "task_success": True}, {}, "b0_quality_win"),
        ({"valid": True, "task_success": True}, {"valid": True, "task_success": False}, {}, "attribution_inconclusive"),
        ({"valid": True, "task_success": True}, {"valid": True, "task_success": False}, {"causal_confidence": "medium", "reproducible": True}, "b0_regression"),
        ({"valid": True, "task_success": True, "total_tokens": 5000, "requests": 3, "unique_read_count": 8, "searches": 2}, {"valid": True, "task_success": True, "total_tokens": 4000, "requests": 2, "unique_read_count": 5, "searches": 1}, {}, "b0_efficiency_win"),
        ({"valid": True, "task_success": True, "total_tokens": 3000, "requests": 2, "unique_read_count": 4, "searches": 1}, {"valid": True, "task_success": True, "total_tokens": 4500, "requests": 3, "unique_read_count": 7, "searches": 2}, {}, "standard_efficiency_win"),
        ({"valid": True, "task_success": True, "total_tokens": 3000}, {"valid": True, "task_success": True, "total_tokens": 3000}, {}, "equivalent"),
    ],
)
def test_classification_precedence(standard, b0, kwargs, expected) -> None:
    assert classify_pair(standard, b0, **kwargs) == expected


def test_causal_record_requires_complete_medium_or_high_chain() -> None:
    record = {
        "classification": "b0_regression",
        "causal_confidence": "medium",
        "packet_caused": True,
        "causal_chain_complete": True,
        "primary_defect": "missing_required_source",
    }
    validate_comparison_record(record)
    with pytest.raises(ValueError, match="complete"):
        validate_comparison_record({**record, "causal_confidence": "low"})


def test_public_sanitizer_rejects_private_surfaces() -> None:
    assert_public_safe("Aggregate result: 12 tasks across 6 synthetic layouts.")
    synthetic_user_path = str(Path("/", "Users", "example", "repo"))
    synthetic_auth_header = "author" + "ization=token"
    for unsafe in (synthetic_user_path, "raw prompt: fix it", synthetic_auth_header):
        with pytest.raises(ValueError, match="private-data"):
            assert_public_safe(unsafe)


def test_schema_envelope_is_valid_json() -> None:
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "b0-scouting-study.v1.json").read_text())
    assert schema["properties"]["schema_version"]["const"] == "b0-scouting-study.v1"
    assert canonical_sha256(schema) == canonical_sha256(json.loads(json.dumps(schema)))
