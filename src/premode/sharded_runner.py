from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


TERMINAL_STATUSES = {
    "pass",
    "fail",
    "timeout",
    "setup_failure",
    "usage_limit",
    "policy_block",
    "interrupted",
    "parse_failure",
    "measurement_incomplete",
}


@dataclass(frozen=True)
class ShardedRunnerConfig:
    artifact_root: Path
    shard_count: int = 2
    per_shard_max_workers: int = 4
    assignment_strategy: str = "round_robin_sorted"
    public_live_matrix: bool = True

    @property
    def effective_max_concurrent_runs(self) -> int:
        return self.shard_count * self.per_shard_max_workers


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_run_plan(
    run_units: list[dict[str, Any]],
    config: ShardedRunnerConfig,
) -> dict[str, Any]:
    if config.shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    if config.per_shard_max_workers < 1:
        raise ValueError("per_shard_max_workers must be >= 1")
    sorted_units = sorted(run_units, key=lambda unit: str(unit["run_id"]))
    seen: set[str] = set()
    planned: list[dict[str, Any]] = []
    for index, unit in enumerate(sorted_units):
        run_id = str(unit["run_id"])
        if run_id in seen:
            raise ValueError(f"duplicate run_id: {run_id}")
        seen.add(run_id)
        shard = _assign_shard(run_id, index, config)
        planned_unit = {
            "run_id": run_id,
            "prompt_id": unit.get("prompt_id") or "",
            "lane": unit.get("lane") or "",
            "packet_version": unit.get("packet_version"),
            "packet_variant": unit.get("packet_variant"),
            "repeat": int(unit.get("repeat") or 1),
            "raw_task_hash": unit.get("raw_task_hash") or "",
            "fixture_source": str(unit.get("fixture_source") or ""),
            "assigned_shard": shard,
            "status": "planned",
            "branch_name": unit.get("branch_name") or f"lab73ab/{run_id}",
            "shard_dir": str(shard_dir(config.artifact_root, shard)),
            "worktree_path": str(run_worktree_path(config.artifact_root, shard, run_id)),
            "log_dir": str(run_log_dir(config.artifact_root, shard, run_id)),
            "run_result_path": str(run_result_path(config.artifact_root, shard, run_id)),
            "codex_jsonl_path": str(run_codex_jsonl_path(config.artifact_root, shard, run_id)),
        }
        planned.append(planned_unit)
    validate_plan_safety(planned, config)
    return {
        "created_at": now_iso(),
        "parallel_mode": "sharded",
        "shard_count": config.shard_count,
        "per_shard_max_workers": config.per_shard_max_workers,
        "effective_max_concurrent_runs": config.effective_max_concurrent_runs,
        "assignment_strategy": config.assignment_strategy,
        "public_live_matrix": config.public_live_matrix,
        "total_runs": len(planned),
        "run_units": planned,
    }


def write_dry_run_plan(plan: dict[str, Any], artifact_root: Path) -> dict[str, Any]:
    artifact_root.mkdir(parents=True, exist_ok=True)
    _write_json(artifact_root / "PARALLEL_RUN_PLAN.json", plan)
    for shard, units in _units_by_shard(plan["run_units"]).items():
        directory = shard_dir(artifact_root, shard)
        directory.mkdir(parents=True, exist_ok=True)
        _write_json(directory / "SHARD_RUN_PLAN.json", {
            "shard": shard,
            "per_shard_max_workers": plan["per_shard_max_workers"],
            "run_units": units,
        })
    summary = shard_assignment_summary(plan)
    _write_json(artifact_root / "SHARD_ASSIGNMENT_SUMMARY.json", summary)
    return summary


def shard_assignment_summary(plan: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(str(unit["assigned_shard"]) for unit in plan.get("run_units", []))
    return {
        "total_runs": len(plan.get("run_units", [])),
        "shard_count": int(plan.get("shard_count") or 0),
        "per_shard_max_workers": int(plan.get("per_shard_max_workers") or 0),
        "effective_max_concurrent_runs": int(plan.get("effective_max_concurrent_runs") or 0),
        "assignment_strategy": plan.get("assignment_strategy"),
        "runs_per_shard": {str(index): counts.get(str(index), 0) for index in range(int(plan.get("shard_count") or 0))},
    }


def plan_from_path(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resume_report(plan: dict[str, Any], artifact_root: Path) -> dict[str, Any]:
    started = now_iso()
    invalid_results: list[dict[str, Any]] = []
    already_complete = 0
    rerun_needed = 0
    duplicates = _duplicate_run_ids(plan.get("run_units", []))
    for unit in plan.get("run_units", []):
        result_path = Path(unit["run_result_path"])
        valid, reason = valid_terminal_result(result_path)
        if valid:
            already_complete += 1
        else:
            rerun_needed += 1
            invalid_results.append({"run_id": unit["run_id"], "path": str(result_path), "reason": reason})
    report = {
        "planned_runs": len(plan.get("run_units", [])),
        "already_complete": already_complete,
        "rerun_needed": rerun_needed,
        "skipped_valid": already_complete,
        "invalid_results": invalid_results,
        "duplicate_run_ids": duplicates,
        "resume_started_at": started,
        "resume_finished_at": now_iso(),
    }
    _write_json(artifact_root / "RESUME_REPORT.json", report)
    return report


def valid_terminal_result(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, "missing RUN_RESULT.json"
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"invalid JSON: {exc}"
    status = result.get("status")
    if status not in TERMINAL_STATUSES:
        return False, f"non-terminal status: {status}"
    if "normalized_tokens" not in result:
        return False, "missing normalized token schema"
    if "command_ledger_path" not in result and "command_ledger_parse_warnings" not in result:
        return False, "missing command ledger path or parse warning"
    return True, None


def aggregate_shard_ledgers(
    plan: dict[str, Any],
    artifact_root: Path,
) -> dict[str, Any]:
    units = plan.get("run_units", [])
    planned_by_id = {unit["run_id"]: unit for unit in units}
    records: list[dict[str, Any]] = []
    missing_shard_ledgers: list[str] = []
    for shard in range(int(plan.get("shard_count") or 0)):
        ledger_path = shard_dir(artifact_root, shard) / "SHARD_LEDGER.jsonl"
        if not ledger_path.exists():
            missing_shard_ledgers.append(str(ledger_path))
            continue
        for line in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({"run_id": None, "status": "parse_failure", "parse_error": "invalid shard ledger JSON"})
    terminal = [record for record in records if record.get("status") in TERMINAL_STATUSES]
    counts = Counter(str(record.get("run_id")) for record in terminal)
    duplicate_terminal_records = sorted(run_id for run_id, count in counts.items() if run_id != "None" and count > 1)
    missing_run_results: list[dict[str, Any]] = []
    missing_terminal_records = sorted(run_id for run_id in planned_by_id if counts.get(run_id, 0) == 0)
    unexpected_run_ids = sorted(str(record.get("run_id")) for record in terminal if record.get("run_id") not in planned_by_id)
    normalized_token_missing: list[str] = []
    command_ledger_missing: list[str] = []
    for unit in units:
        result_path = Path(unit["run_result_path"])
        if not result_path.exists():
            missing_run_results.append({"run_id": unit["run_id"], "path": str(result_path)})
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            missing_run_results.append({"run_id": unit["run_id"], "path": str(result_path), "reason": "invalid JSON"})
            continue
        if "normalized_tokens" not in result:
            normalized_token_missing.append(unit["run_id"])
        if "command_ledger_path" not in result and "command_ledger_parse_warnings" not in result:
            command_ledger_missing.append(unit["run_id"])
    complete = (
        not missing_shard_ledgers
        and not duplicate_terminal_records
        and not missing_terminal_records
        and not unexpected_run_ids
        and not missing_run_results
        and not normalized_token_missing
        and not command_ledger_missing
    )
    aggregate = {
        "planned_run_count": len(units),
        "ledger_record_count": len(records),
        "terminal_record_count": len(terminal),
        "complete": complete,
        "missing_shard_ledgers": missing_shard_ledgers,
        "missing_terminal_records": missing_terminal_records,
        "duplicate_terminal_records": duplicate_terminal_records,
        "unexpected_run_ids": unexpected_run_ids,
        "missing_run_results": missing_run_results,
        "normalized_token_missing": normalized_token_missing,
        "command_ledger_missing": command_ledger_missing,
        "status_counts": dict(Counter(str(record.get("status")) for record in terminal)),
        "token_derivation_status_counts": dict(Counter(str(_load_result_field(record, "token_derivation_status", artifact_root)) for record in terminal)),
    }
    _write_jsonl(artifact_root / "LIVE_RUN_LEDGER.jsonl", terminal)
    _write_json(artifact_root / "TOKEN_TELEMETRY_SUMMARY.json", {
        "token_derivation_status_counts": aggregate["token_derivation_status_counts"],
        "normalized_token_missing": normalized_token_missing,
    })
    _write_json(artifact_root / "COMMAND_LEDGER_SUMMARY.json", {
        "command_ledger_missing": command_ledger_missing,
    })
    _write_json(artifact_root / "CANARY_DIAGNOSTICS.json", {"source": "sharded_aggregation", "complete": complete})
    _write_json(artifact_root / "SCOPE_REVIEW_SUMMARY.json", {"source": "sharded_aggregation", "complete": complete})
    _write_json(artifact_root / "OUTLIER_TAXONOMY.json", {"source": "sharded_aggregation", "outliers": []})
    _write_json(artifact_root / "LIVE_PAIRED_COMPARISON.json", {"source": "sharded_aggregation", "pairs": []})
    return aggregate


def paired_completed_records(records: list[dict[str, Any]], left_lane: str, right_lane: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_key: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for record in records:
        if record.get("status") != "pass":
            continue
        key = (str(record.get("prompt_id") or ""), int(record.get("repeat") or 1))
        by_key.setdefault(key, {})[str(record.get("lane") or "")] = record
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for lanes in by_key.values():
        if left_lane in lanes and right_lane in lanes:
            pairs.append((lanes[left_lane], lanes[right_lane]))
    return pairs


def interruption_summary(status: str, message: str, artifact_root: Path, *, launched: int = 0, completed: int = 0) -> dict[str, Any]:
    summary = {
        "status": status,
        "message": message,
        "stop_launching_new_run_units": status == "usage_limit",
        "already_launched_runs": launched,
        "completed_runs": completed,
        "written_at": now_iso(),
    }
    _write_json(artifact_root / "INTERRUPTION_SUMMARY.json", summary)
    return summary


def execute_shards(
    plan: dict[str, Any],
    artifact_root: Path,
    run_unit: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    resume: bool = False,
) -> dict[str, Any]:
    """Sequential shard controller used by lab-local runners.

    The callable may implement its own per-shard worker pool; this wrapper keeps
    plan/resume/ledger semantics deterministic and testable without launching
    Codex from product code.
    """
    if resume:
        resume_report(plan, artifact_root)
    launched = 0
    completed = 0
    stopped = False
    for shard, units in _units_by_shard(plan.get("run_units", [])).items():
        directory = shard_dir(artifact_root, shard)
        directory.mkdir(parents=True, exist_ok=True)
        shard_records: list[dict[str, Any]] = []
        for unit in units:
            if stopped:
                break
            if resume and valid_terminal_result(Path(unit["run_result_path"]))[0]:
                continue
            launched += 1
            result = run_unit(unit)
            status = result.get("status")
            shard_records.append(result)
            completed += 1
            if status == "usage_limit":
                interruption_summary("usage_limit", "usage limit reported by run unit", artifact_root, launched=launched, completed=completed)
                stopped = True
        _write_jsonl(directory / "SHARD_LEDGER.jsonl", shard_records, append=True)
        _write_json(directory / "SHARD_STATUS.json", {
            "shard": shard,
            "planned": len(units),
            "records_written": len(shard_records),
            "stopped": stopped,
        })
    return {"launched": launched, "completed": completed, "stopped": stopped}


def validate_plan_safety(units: list[dict[str, Any]], config: ShardedRunnerConfig) -> None:
    _ensure_unique(units, "run_id")
    _ensure_unique(units, "worktree_path")
    _ensure_unique(units, "branch_name")
    _ensure_unique(units, "run_result_path")
    for unit in units:
        _ensure_inside(Path(unit["shard_dir"]), config.artifact_root)
        _ensure_inside(Path(unit["worktree_path"]), config.artifact_root)
        _ensure_inside(Path(unit["log_dir"]), config.artifact_root)
        _ensure_inside(Path(unit["run_result_path"]), config.artifact_root)
        if config.public_live_matrix and _is_private_fixture(str(unit.get("fixture_source") or "")):
            raise ValueError(f"private fixture path is not allowed: {unit['fixture_source']}")


def shard_dir(artifact_root: Path, shard: int) -> Path:
    return artifact_root / "shards" / f"shard_{shard:02d}"


def run_log_dir(artifact_root: Path, shard: int, run_id: str) -> Path:
    return shard_dir(artifact_root, shard) / "logs" / run_id


def run_worktree_path(artifact_root: Path, shard: int, run_id: str) -> Path:
    return shard_dir(artifact_root, shard) / "worktrees" / run_id


def run_result_path(artifact_root: Path, shard: int, run_id: str) -> Path:
    return run_log_dir(artifact_root, shard, run_id) / "RUN_RESULT.json"


def run_codex_jsonl_path(artifact_root: Path, shard: int, run_id: str) -> Path:
    return run_log_dir(artifact_root, shard, run_id) / "codex.jsonl"


def _assign_shard(run_id: str, index: int, config: ShardedRunnerConfig) -> int:
    if config.assignment_strategy == "round_robin_sorted":
        return index % config.shard_count
    if config.assignment_strategy == "hash_mod":
        value = sum((idx + 1) * ord(ch) for idx, ch in enumerate(run_id))
        return value % config.shard_count
    raise ValueError(f"unsupported assignment strategy: {config.assignment_strategy}")


def _units_by_shard(units: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for unit in units:
        out.setdefault(int(unit["assigned_shard"]), []).append(unit)
    return dict(sorted(out.items()))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]], *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _ensure_unique(units: list[dict[str, Any]], key: str) -> None:
    values = [str(unit.get(key) or "") for unit in units]
    dupes = sorted(value for value, count in Counter(values).items() if count > 1)
    if dupes:
        raise ValueError(f"duplicate {key}: {dupes}")


def _ensure_inside(path: Path, root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path outside artifact root: {path}") from exc


def _is_private_fixture(path: str) -> bool:
    lowered = path.lower()
    private_markers = (
        "goldpine",
        "robotriage",
        "rich-cli",
        "rich_cli",
        "/users/example/documents/new project/",
        "/users/example/documents/protfolio projects/",
    )
    return any(marker in lowered for marker in private_markers)


def _duplicate_run_ids(units: list[dict[str, Any]]) -> list[str]:
    counts = Counter(str(unit.get("run_id") or "") for unit in units)
    return sorted(run_id for run_id, count in counts.items() if count > 1)


def _load_result_field(record: dict[str, Any], field: str, artifact_root: Path) -> Any:
    result_path = record.get("run_result_path")
    if not result_path:
        run_id = str(record.get("run_id") or "")
        matches = list(artifact_root.glob(f"shards/*/logs/{run_id}/RUN_RESULT.json"))
        result_path = str(matches[0]) if matches else None
    if not result_path:
        return None
    try:
        result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if field in result:
        return result[field]
    if isinstance(result.get("normalized_tokens"), dict):
        return result["normalized_tokens"].get(field)
    return None
