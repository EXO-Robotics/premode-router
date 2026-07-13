"""Experiment-only controls for the B0 STANDARD-versus-guidance scouting study.

This module deliberately contains no task prompts, validator internals, model
outputs, or repository identities.  It validates private records and produces
content-free scheduling and comparison facts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import random
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "b0-scouting-study.v1"
ARMS = ("STANDARD", "B0")
TASK_CLASSIFICATIONS = frozenset({
    "b0_quality_win", "b0_efficiency_win", "b0_quality_and_efficiency_win",
    "equivalent", "standard_quality_win", "standard_efficiency_win",
    "b0_regression", "agent_only_failure", "validator_or_fixture_failure",
    "attribution_inconclusive", "invalid",
})
DEFECT_CLASSES = frozenset({
    "missing_required_source", "missing_required_test", "wrong_package_selected",
    "wrong_duplicate_authority", "irrelevant_path_distracted_agent",
    "generated_or_historical_mispromotion", "cross_module_omission",
    "support_file_omission", "over_narrow_packet", "over_broad_packet",
    "incorrect_abstention", "incorrect_fallback", "path_ordering_defect",
    "ignored_supplied_path", "misread_correct_file",
    "incorrect_edit_after_correct_retrieval", "validation_misinterpretation",
    "premature_completion", "excessive_exploration_despite_good_packet",
    "model_tool_use_failure", "validator_defect", "task_ambiguity",
    "fixture_defect", "runtime_failure", "tool_failure", "measurement_invalid",
    "infrastructure_failure", "attribution_inconclusive",
})
CAUSAL_CONFIDENCE = frozenset({"high", "medium", "low", "inconclusive"})
MATERIALITY = {
    "token_fraction": 0.10,
    "token_absolute": 512,
    "requests": 1,
    "reads": 2,
    "searches": 1,
    "wall_fraction": 0.15,
}


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cell_id(task_id: str, arm: str, repetition: int, configuration_hash: str) -> str:
    return canonical_sha256({"task_id": task_id, "arm": arm, "repetition": repetition, "configuration_hash": configuration_hash})


def build_blocked_schedule(
    tasks: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    configuration_hash: str,
    repetitions: int = 1,
    workers: int = 3,
) -> list[dict[str, Any]]:
    if workers != 3:
        raise ValueError("the frozen scouting design requires exactly three workers")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    task_ids = [str(task.get("task_id") or "") for task in tasks]
    if any(not task_id for task_id in task_ids) or len(set(task_ids)) != len(task_ids):
        raise ValueError("task IDs must be non-empty and unique")
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    order = 0
    for repetition in range(1, repetitions + 1):
        shuffled = list(tasks)
        rng.shuffle(shuffled)
        for block_index, start in enumerate(range(0, len(shuffled), workers)):
            block = shuffled[start : start + workers]
            for position, task in enumerate(block):
                task_id = str(task["task_id"])
                first_arm = ARMS[(block_index + position + repetition) % 2]
                arm_order = (first_arm, ARMS[1 - ARMS.index(first_arm)])
                worker_rotation = (position + block_index + repetition - 1) % workers
                workers_by_arm = {
                    "STANDARD": worker_rotation,
                    "B0": (worker_rotation + 1) % workers,
                }
                for within_task_order, arm in enumerate(arm_order):
                    rows.append({
                        "schema_version": SCHEMA_VERSION,
                        "cell_id": _cell_id(task_id, arm, repetition, configuration_hash),
                        "task_id": task_id,
                        "repository_id": str(task.get("repository_id") or ""),
                        "task_class": str(task.get("task_class") or ""),
                        "arm": arm,
                        "repetition": repetition,
                        "block": f"r{repetition}-b{block_index:03d}",
                        "order": order,
                        "within_task_order": within_task_order,
                        "planned_worker": workers_by_arm[arm],
                        "configuration_hash": configuration_hash,
                    })
                    order += 1
    validate_schedule(rows, workers=workers)
    return rows


def validate_schedule(rows: Sequence[Mapping[str, Any]], *, workers: int = 3) -> None:
    if not rows:
        raise ValueError("schedule is empty")
    cell_ids = [row.get("cell_id") for row in rows]
    if any(not isinstance(value, str) or len(value) != 64 for value in cell_ids) or len(set(cell_ids)) != len(cell_ids):
        raise ValueError("cell IDs must be unique SHA-256 values")
    by_task_rep: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("arm") not in ARMS:
            raise ValueError("unknown arm")
        worker = row.get("planned_worker")
        if not isinstance(worker, int) or not 0 <= worker < workers:
            raise ValueError("invalid worker")
        by_task_rep[(str(row.get("task_id")), int(row.get("repetition") or 0))].append(row)
    for pair in by_task_rep.values():
        if {str(row.get("arm")) for row in pair} != set(ARMS) or len(pair) != 2:
            raise ValueError("every task repetition requires exactly one run per arm")
        if len({int(row["planned_worker"]) for row in pair}) != 2:
            raise ValueError("paired arms must use different workers")
        if {int(row.get("within_task_order") or 0) for row in pair} != {0, 1}:
            raise ValueError("paired arm order is invalid")
    counts = Counter((str(row["arm"]), int(row["planned_worker"])) for row in rows)
    for arm in ARMS:
        values = [counts[(arm, worker)] for worker in range(workers)]
        if max(values) - min(values) > 1:
            raise ValueError("arm-to-worker allocation is imbalanced")


def trajectory_metrics(run: Mapping[str, Any], *, required_paths: Sequence[str] = (), supplied_paths: Sequence[str] = ()) -> dict[str, Any]:
    events = run.get("tool_events") if isinstance(run.get("tool_events"), list) else []
    visible_reads: list[str] = []
    scanned_file_count = 0
    searches = 0
    mutations: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        name = event.get("name")
        paths = [str(path) for path in event.get("accessed_paths") or [] if isinstance(path, str)]
        if name in {"read_file", "list_directory", "inspect_path_metadata", "search_text"}:
            visible_reads.extend(paths)
        if name == "search_text":
            searches += 1
            scanned_file_count += int(event.get("scanned_file_count") or 0)
        if name in {"apply_patch", "write_file"}:
            mutations.extend(paths)
    counts = Counter(visible_reads)
    unique_reads = list(dict.fromkeys(visible_reads))
    first_relevant_index = next((index for index, path in enumerate(visible_reads) if path in set(required_paths)), None)
    supplied = set(supplied_paths)
    required = set(required_paths)
    return {
        "files_read": visible_reads,
        "unique_files_read": unique_reads,
        "repeated_file_reads": sum(max(0, count - 1) for count in counts.values()),
        "searches": searches,
        "search_scanned_file_count": scanned_file_count,
        "tool_calls": len(events),
        "requests": len(run.get("turns") or []),
        "mutations": list(dict.fromkeys(mutations)),
        "first_relevant_file_index": first_relevant_index,
        "supplied_paths_used": sorted(supplied & set(unique_reads)),
        "supplied_paths_unused": sorted(supplied - set(unique_reads)),
        "unsupplied_required_paths": sorted(required - supplied),
    }


def usage_metrics(run: Mapping[str, Any]) -> dict[str, int]:
    prompt_tokens = 0
    completion_tokens = 0
    missing = 0
    for turn in run.get("turns") or []:
        response = turn.get("response") if isinstance(turn, Mapping) and isinstance(turn.get("response"), Mapping) else {}
        usage = response.get("usage") if isinstance(response.get("usage"), Mapping) else None
        if usage is None:
            missing += 1
            continue
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
    return {
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "usage_missing_requests": missing,
    }


def validate_accepted_attempts(records: Sequence[Mapping[str, Any]]) -> None:
    accepted = [record for record in records if record.get("accepted") is True]
    cells = [record.get("cell_id") for record in accepted]
    fixtures = [record.get("fixture_instance_id") for record in accepted]
    runs = [record.get("run_id") for record in records]
    if len(cells) != len(set(cells)):
        raise ValueError("duplicate accepted experimental cell")
    if any(not value for value in fixtures) or len(fixtures) != len(set(fixtures)):
        raise ValueError("fixture instance reused")
    if any(not value for value in runs) or len(runs) != len(set(runs)):
        raise ValueError("duplicate run ID")
    controls: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for record in accepted:
        task_id = str(record.get("task_id"))
        for key in ("task_hash", "validator_hash", "start_tree_hash", "system_prompt_hash", "tool_schema_hash", "model_runtime_hash", "sampler_hash"):
            controls[task_id][key].add(str(record.get(key)))
    for task_id, values in controls.items():
        drift = [key for key, hashes in values.items() if len(hashes) != 1 or "None" in hashes or "" in hashes]
        if drift:
            raise ValueError(f"frozen control drift for {task_id}: {','.join(drift)}")


def _materially_lower(candidate: Mapping[str, Any], control: Mapping[str, Any]) -> bool:
    c_tokens, s_tokens = int(candidate.get("total_tokens") or 0), int(control.get("total_tokens") or 0)
    token_win = s_tokens - c_tokens >= MATERIALITY["token_absolute"] and c_tokens <= s_tokens * (1 - MATERIALITY["token_fraction"])
    request_win = int(control.get("requests") or 0) - int(candidate.get("requests") or 0) >= MATERIALITY["requests"]
    read_win = int(control.get("unique_read_count") or 0) - int(candidate.get("unique_read_count") or 0) >= MATERIALITY["reads"]
    search_win = int(control.get("searches") or 0) - int(candidate.get("searches") or 0) >= MATERIALITY["searches"]
    return token_win or request_win or read_win or search_win


def classify_pair(
    standard: Mapping[str, Any],
    b0: Mapping[str, Any],
    *,
    causal_confidence: str = "inconclusive",
    reproducible: bool = False,
) -> str:
    if causal_confidence not in CAUSAL_CONFIDENCE:
        raise ValueError("invalid causal confidence")
    if standard.get("valid") is not True or b0.get("valid") is not True:
        return "invalid"
    if standard.get("validator_or_fixture_failure") or b0.get("validator_or_fixture_failure"):
        return "validator_or_fixture_failure"
    s_success, b_success = bool(standard.get("task_success")), bool(b0.get("task_success"))
    if not s_success and not b_success:
        if standard.get("primary_defect") in {"model_tool_use_failure", "premature_completion", "incorrect_edit_after_correct_retrieval"} and standard.get("primary_defect") == b0.get("primary_defect"):
            return "agent_only_failure"
        return "attribution_inconclusive"
    b_eff = _materially_lower(b0, standard)
    s_eff = _materially_lower(standard, b0)
    if b_success and not s_success:
        return "b0_quality_and_efficiency_win" if b_eff else "b0_quality_win"
    if s_success and not b_success:
        if reproducible and causal_confidence in {"medium", "high"}:
            return "b0_regression"
        return "attribution_inconclusive"
    if standard.get("quality_rank") is not None and b0.get("quality_rank") is not None:
        if int(b0["quality_rank"]) > int(standard["quality_rank"]):
            return "b0_quality_and_efficiency_win" if b_eff else "b0_quality_win"
        if int(standard["quality_rank"]) > int(b0["quality_rank"]):
            return "standard_quality_win"
    if b_eff and not s_eff:
        return "b0_efficiency_win"
    if s_eff and not b_eff:
        return "standard_efficiency_win"
    return "equivalent"


_PRIVATE_PATTERNS = (
    re.compile(r"/(?:Users|private|home)/", re.I),
    re.compile(r"\\Users\\", re.I),
    re.compile(r"\b(?:prompt|transcript|validator_internal|model_output|tool_payload)\b", re.I),
    re.compile(r"(?:api[_-]?key|authorization|bearer|credential|secret)\s*[:=]", re.I),
)


def assert_public_safe(value: str) -> None:
    matches = [pattern.pattern for pattern in _PRIVATE_PATTERNS if pattern.search(value)]
    if matches:
        raise ValueError("public artifact contains a private-data pattern")


def validate_comparison_record(record: Mapping[str, Any]) -> None:
    classification = record.get("classification")
    if classification not in TASK_CLASSIFICATIONS:
        raise ValueError("invalid task classification")
    confidence = record.get("causal_confidence")
    if confidence not in CAUSAL_CONFIDENCE:
        raise ValueError("invalid causal confidence")
    defect = record.get("primary_defect")
    if defect is not None and defect not in DEFECT_CLASSES:
        raise ValueError("invalid defect class")
    if record.get("packet_caused") is True:
        if confidence not in {"medium", "high"} or record.get("causal_chain_complete") is not True:
            raise ValueError("packet causality requires a complete medium/high-confidence chain")
