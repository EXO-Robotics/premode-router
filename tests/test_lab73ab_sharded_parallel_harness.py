from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode.sharded_runner import (
    ShardedRunnerConfig,
    aggregate_shard_ledgers,
    build_run_plan,
    execute_shards,
    interruption_summary,
    paired_completed_records,
    resume_report,
    shard_assignment_summary,
    validate_plan_safety,
    write_dry_run_plan,
)


def _units(count: int = 6) -> list[dict[str, object]]:
    return [
        {
            "run_id": f"prompt_{index:02d}_v5_ranked_paths_r1",
            "prompt_id": f"prompt_{index:02d}",
            "lane": "v5_ranked_paths" if index % 2 else "standard",
            "packet_version": "v5" if index % 2 else None,
            "packet_variant": "ranked_paths" if index % 2 else None,
            "repeat": 1,
            "raw_task_hash": f"hash-{index}",
            "fixture_source": f"/private/tmp/public_fixtures/repo_{index}",
        }
        for index in range(count)
    ]


def _config(tmp_path: Path, shard_count: int = 2) -> ShardedRunnerConfig:
    return ShardedRunnerConfig(artifact_root=tmp_path / "lab", shard_count=shard_count, per_shard_max_workers=4)


def _write_result(path: Path, status: str = "pass") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "normalized_tokens": {
                    "input_tokens": 100,
                    "cached_input_tokens": 80,
                    "uncached_input_tokens": None,
                    "derived_uncached_input_tokens": 20,
                    "cache_adjusted_input_tokens": 28.0,
                    "token_derivation_status": "derived",
                    "token_schema_source": "turn.completed",
                    "token_derivation_notes": [],
                    "raw_token_fields": {"input_tokens": 100, "cached_input_tokens": 80},
                },
                "token_derivation_status": "derived",
                "raw_usage_events": [],
                "command_ledger_path": str(path.parent / "command_ledger.json"),
                "explicit_repo_file_reads": ["src/app.py"],
                "memory_file_reads": [],
                "search_hits": [],
                "validation_targets": [],
                "import_or_stacktrace_references": [],
                "file_reference_only_paths": [],
                "first_repo_file_read": "src/app.py",
                "first_repo_file_read_inside_likely": True,
                "first_file_edited": "src/app.py",
                "first_file_edited_inside_packet": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_deterministic_shard_assignment_and_dry_run_outputs(tmp_path: Path) -> None:
    config = _config(tmp_path, shard_count=4)
    plan1 = build_run_plan(_units(10), config)
    plan2 = build_run_plan(list(reversed(_units(10))), config)

    assert [unit["run_id"] for unit in plan1["run_units"]] == [unit["run_id"] for unit in plan2["run_units"]]
    assert [unit["assigned_shard"] for unit in plan1["run_units"]] == [unit["assigned_shard"] for unit in plan2["run_units"]]
    assert sorted(unit["run_id"] for unit in plan1["run_units"]) == sorted({unit["run_id"] for unit in plan1["run_units"]})

    summary = write_dry_run_plan(plan1, config.artifact_root)

    assert (config.artifact_root / "PARALLEL_RUN_PLAN.json").exists()
    assert (config.artifact_root / "SHARD_ASSIGNMENT_SUMMARY.json").exists()
    assert summary["effective_max_concurrent_runs"] == 16
    assert sum(summary["runs_per_shard"].values()) == 10


def test_paths_are_unique_and_inside_shard_directories(tmp_path: Path) -> None:
    config = _config(tmp_path, shard_count=3)
    plan = build_run_plan(_units(9), config)
    worktrees = [unit["worktree_path"] for unit in plan["run_units"]]
    logs = [unit["log_dir"] for unit in plan["run_units"]]
    results = [unit["run_result_path"] for unit in plan["run_units"]]

    assert len(worktrees) == len(set(worktrees))
    assert len(logs) == len(set(logs))
    assert len(results) == len(set(results))
    assert {Path(unit["shard_dir"]).name for unit in plan["run_units"]} == {"shard_00", "shard_01", "shard_02"}


def test_duplicate_run_ids_and_private_fixture_paths_are_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    duplicate = [_units(1)[0], _units(1)[0]]
    with pytest.raises(ValueError, match="duplicate run_id"):
        build_run_plan(duplicate, config)

    private_unit = _units(1)[0]
    private_unit["fixture_source"] = "/Users/example/Documents/New project/GoldpineValley-iOS"
    with pytest.raises(ValueError, match="private fixture"):
        build_run_plan([private_unit], config)


def test_resume_skips_valid_and_marks_missing_or_invalid(tmp_path: Path) -> None:
    config = _config(tmp_path)
    plan = build_run_plan(_units(3), config)
    _write_result(Path(plan["run_units"][0]["run_result_path"]))
    Path(plan["run_units"][1]["run_result_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(plan["run_units"][1]["run_result_path"]).write_text('{"status": "pass"}\n', encoding="utf-8")

    report = resume_report(plan, config.artifact_root)

    assert report["already_complete"] == 1
    assert report["skipped_valid"] == 1
    assert report["rerun_needed"] == 2
    assert {entry["run_id"] for entry in report["invalid_results"]} == {
        plan["run_units"][1]["run_id"],
        plan["run_units"][2]["run_id"],
    }


def test_aggregation_catches_missing_results_and_duplicate_terminal_records(tmp_path: Path) -> None:
    config = _config(tmp_path)
    plan = build_run_plan(_units(2), config)
    write_dry_run_plan(plan, config.artifact_root)
    first = plan["run_units"][0]
    _write_result(Path(first["run_result_path"]))
    ledger = Path(first["shard_dir"]) / "SHARD_LEDGER.jsonl"
    ledger.write_text(
        json.dumps({"run_id": first["run_id"], "status": "pass", "run_result_path": first["run_result_path"]}) + "\n"
        + json.dumps({"run_id": first["run_id"], "status": "pass", "run_result_path": first["run_result_path"]}) + "\n",
        encoding="utf-8",
    )

    aggregate = aggregate_shard_ledgers(plan, config.artifact_root)

    assert aggregate["complete"] is False
    assert aggregate["duplicate_terminal_records"] == [first["run_id"]]
    assert plan["run_units"][1]["run_id"] in aggregate["missing_terminal_records"]
    assert aggregate["missing_run_results"][0]["run_id"] == plan["run_units"][1]["run_id"]


def test_aggregation_preserves_token_and_command_measurement_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    plan = build_run_plan(_units(2), config)
    write_dry_run_plan(plan, config.artifact_root)
    for unit in plan["run_units"]:
        _write_result(Path(unit["run_result_path"]))
        ledger = Path(unit["shard_dir"]) / "SHARD_LEDGER.jsonl"
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"run_id": unit["run_id"], "status": "pass", "run_result_path": unit["run_result_path"]}) + "\n")

    aggregate = aggregate_shard_ledgers(plan, config.artifact_root)

    assert aggregate["complete"] is True
    assert aggregate["token_derivation_status_counts"] == {"derived": 2}
    assert json.loads((config.artifact_root / "TOKEN_TELEMETRY_SUMMARY.json").read_text(encoding="utf-8"))["token_derivation_status_counts"] == {"derived": 2}
    assert json.loads((config.artifact_root / "COMMAND_LEDGER_SUMMARY.json").read_text(encoding="utf-8"))["command_ledger_missing"] == []


def test_usage_limit_status_stops_new_launches_and_records_interruption(tmp_path: Path) -> None:
    config = _config(tmp_path)
    plan = build_run_plan(_units(3), config)

    def run_unit(unit: dict[str, object]) -> dict[str, object]:
        status = "usage_limit" if unit["run_id"] == plan["run_units"][0]["run_id"] else "pass"
        return {"run_id": unit["run_id"], "status": status, "run_result_path": unit["run_result_path"]}

    execution = execute_shards(plan, config.artifact_root, run_unit)
    summary = json.loads((config.artifact_root / "INTERRUPTION_SUMMARY.json").read_text(encoding="utf-8"))

    assert execution["stopped"] is True
    assert execution["launched"] == 1
    assert summary["status"] == "usage_limit"
    assert summary["stop_launching_new_run_units"] is True


def test_interruption_summary_can_record_policy_block(tmp_path: Path) -> None:
    summary = interruption_summary("policy_block", "policy controls blocked launch", tmp_path, launched=1, completed=0)

    assert summary["status"] == "policy_block"
    assert summary["stop_launching_new_run_units"] is False
    assert (tmp_path / "INTERRUPTION_SUMMARY.json").exists()


def test_paired_comparison_uses_only_completed_pass_pairs() -> None:
    records = [
        {"prompt_id": "p1", "repeat": 1, "lane": "standard", "status": "pass"},
        {"prompt_id": "p1", "repeat": 1, "lane": "v5_ranked_paths", "status": "pass"},
        {"prompt_id": "p2", "repeat": 1, "lane": "standard", "status": "fail"},
        {"prompt_id": "p2", "repeat": 1, "lane": "v5_ranked_paths", "status": "pass"},
    ]

    pairs = paired_completed_records(records, "standard", "v5_ranked_paths")

    assert len(pairs) == 1
    assert pairs[0][0]["prompt_id"] == "p1"


def test_validate_plan_safety_catches_duplicate_branch_names(tmp_path: Path) -> None:
    config = _config(tmp_path)
    plan = build_run_plan(_units(2), config)
    units = plan["run_units"]
    units[1]["branch_name"] = units[0]["branch_name"]

    with pytest.raises(ValueError, match="duplicate branch_name"):
        validate_plan_safety(units, config)
