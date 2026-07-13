#!/usr/bin/env python3
"""Run the frozen initial 35-task x 2-arm Qwen scouting panel privately."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import random
import shutil
import sys
import threading
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scouting_smoke as common


def build_schedule(tasks: dict[str, dict[str, Any]], seed: int, workers: int) -> list[dict[str, Any]]:
    generator = random.Random(seed)
    classes = sorted({task["task_class"] for task in tasks.values()})
    generator.shuffle(classes)
    schedule: list[dict[str, Any]] = []
    for block, task_class in enumerate(classes, 1):
        cells = [
            (task_id, arm)
            for task_id, task in tasks.items() if task["task_class"] == task_class
            for arm in common.ARMS
        ]
        generator.shuffle(cells)
        for task_id, arm in cells:
            schedule.append({
                "sequence": len(schedule) + 1,
                "block": block,
                "task_class": task_class,
                "task_id": task_id,
                "arm": arm,
                "planned_worker_slot": len(schedule) % workers,
            })
    return schedule


def execute(arguments: argparse.Namespace) -> int:
    if not 1 <= arguments.workers <= 3:
        raise ValueError("workers must be between 1 and 3")
    corpus_root = Path(arguments.corpus_root).resolve()
    run_root = Path(arguments.run_root).resolve() / arguments.run_id
    private_results = corpus_root / "private-results" / arguments.run_id
    tasks = {item["task_id"]: item for item in common.load_json(corpus_root / "tasks" / "PRIVATE_TASK_DEFINITIONS.json")}
    specs = common.load_json(corpus_root / "validators" / "PRIVATE_VALIDATOR_SPECS.json")
    mutations = {item["task_id"]: item for item in common.load_json(corpus_root / "mutations" / "PRIVATE_MUTATION_INDEX.json")}
    manifest = common.load_json(corpus_root / "manifests" / "PRIVATE_CORPUS_MANIFEST.json")
    repositories = {item["repository_id"]: item for item in manifest["repositories"]}
    python = Path(arguments.python).resolve()
    b0_source = Path(arguments.b0_source).resolve()
    full_schedule = build_schedule(tasks, arguments.seed, arguments.workers)
    if len(full_schedule) != len(tasks) * 2 or len(tasks) not in range(30, 41):
        raise RuntimeError("frozen full schedule must contain 30-40 paired tasks")
    selected_task_ids = set(tasks)
    if arguments.task_ids:
        selected_task_ids = set(arguments.task_ids)
        unknown = selected_task_ids - set(tasks)
        if unknown:
            raise ValueError(f"unknown task ids: {sorted(unknown)}")
        full_schedule = [cell for cell in full_schedule if cell["task_id"] in selected_task_ids]
    full_schedule = [{**cell, "repetition": arguments.repetition} for cell in full_schedule]
    prior_summary: dict[str, Any] | None = None
    prior_results: list[dict[str, Any]] = []
    schedule = full_schedule
    if arguments.resume_from:
        prior_summary = common.load_json(Path(arguments.resume_from).resolve())
        prior_results = list(prior_summary.get("results") or [])
        full_schedule = build_schedule(tasks, arguments.seed, int(prior_summary.get("worker_count") or arguments.workers))
        missing_keys = {
            (int(item["sequence"]), item["task_id"], item["arm"])
            for item in prior_summary.get("errors") or []
        }
        schedule = [
            cell for cell in full_schedule
            if (cell["sequence"], cell["task_id"], cell["arm"]) in missing_keys
        ]
        if not schedule:
            raise RuntimeError("resume source contains no missing cells")
    run_root.mkdir(parents=True, exist_ok=True)
    private_results.mkdir(parents=True, exist_ok=True)
    common.write_json(corpus_root / "schedules" / "PRIVATE_FULL_SCOUTING_SCHEDULE.json", {
        "schema_version": "pcodex-qwen-full-schedule/1.0.0",
        "seed": arguments.seed,
        "workers": arguments.workers,
        "schedule": full_schedule,
        "active_retry_schedule": schedule if arguments.resume_from else [],
    })
    output_lock = threading.Lock()

    def run_cell(cell: dict[str, Any]) -> dict[str, Any]:
        sequence = cell["sequence"]
        task_id = cell["task_id"]
        arm = cell["arm"]
        task = tasks[task_id]
        spec = specs[task_id]
        repository = repositories[task["repository_id"]]
        source = corpus_root / "repos" / "immutable" / repository["directory"]
        fixture = run_root / f"{sequence:03d}-{task_id}-{arm.casefold()}"
        private_run_root = private_results / f"{sequence:03d}-{task_id}-{arm.casefold()}"
        private_run_root.mkdir(parents=True, exist_ok=True)
        clone_method = common.apfs_clone(source, fixture)
        try:
            patch_path = Path(mutations[task_id]["mutation_patch_path"])
            common.run(["git", "-C", str(fixture), "apply", "--whitespace=nowarn", str(patch_path)])
            start_hash = common.fixture_state_hash(fixture, spec)
            validation_task = {"_private_validator_spec": spec}
            mutated_pass, mutated_errors = common.scouting_corpus.validate_task(validation_task, fixture)
            if mutated_pass:
                raise RuntimeError(f"mutated precondition unexpectedly passed for {task_id}")
            mutated_snapshot = {relative: (fixture / relative).read_bytes() for relative in spec["allowed_mutation_paths"]}
            packet = None
            packet_metadata: dict[str, Any] = {}
            selected_paths: list[str] = []
            if arm == "B0":
                packet, packet_metadata, selected_paths = common.compile_b0_packet(
                    python, b0_source, fixture, task["prompt"], private_run_root,
                    timeout_seconds=arguments.compile_timeout,
                )
            harness = common.ControlledHarness(
                arguments.endpoint,
                arguments.model,
                limits=common.HarnessLimits(max_turns=12, max_tool_calls=32, max_output_tokens=1024, max_tool_result_bytes=32_768, task_timeout_seconds=300, command_timeout_seconds=30),
                sampler=common.SamplerSettings(seed=42, temperature=0.0, top_p=1.0, reasoning_effort="none"),
            )
            raw_run = harness.run(task["prompt"], fixture, packet=packet, selected_paths=selected_paths)
            hidden_pass, hidden_errors = common.scouting_corpus.validate_task(validation_task, fixture)
            observer_fixture = common.TaskFixture(
                task_id=task_id,
                task_text=task["prompt"],
                repository_fixture=task["repository_id"],
                required_paths=tuple(spec["allowed_mutation_paths"]),
                allowed_paths=tuple(spec["allowed_mutation_paths"]),
                expected_changed_paths=(),
                prohibited_changed_paths=(),
                validation_command=None,
                timeout_seconds=300,
                maximum_turns=12,
                maximum_tool_calls=32,
            )
            observer_validation = common.validate_observer_task(observer_fixture, fixture, raw_run).to_dict()
            if not hidden_pass:
                observer_validation["all_task_validators_pass"] = False
                observer_validation["tests_passed"] = False
                observer_validation["outcome_class"] = "partial" if raw_run.get("status") == "finished" else "runtime_failure"
            tool_misuse = any(event.get("safety_event_codes") for event in raw_run.get("tool_events", []))
            observer_validation["scope_adherence"] = not observer_validation.get("unrelated_files_changed") and not tool_misuse
            model_visible_input = packet if packet is not None else task["prompt"]
            packet_paths = selected_paths if arm == "B0" else []
            routing = packet_metadata.get("routing_decision") if isinstance(packet_metadata.get("routing_decision"), dict) else None
            candidate_evidence = routing.get("candidate_provenance") if isinstance(routing, dict) else None
            native_receipt = common.build_observer_receipt(
                fixture,
                packet_paths=packet_paths,
                packet_hash=common.sha256_bytes(model_visible_input.encode()),
                packet_projection_hash=common.canonical_hash(packet_paths),
                run=raw_run,
                validation=observer_validation,
                required_paths=spec["allowed_mutation_paths"] if arm == "B0" else (),
                wrong_ordinary_paths=(),
                routing_decision_hash=common.canonical_hash(routing) if routing is not None else None,
                candidate_evidence_hash=common.canonical_hash(candidate_evidence) if candidate_evidence is not None else None,
                packet_hash_verified=True,
                packet_bytes=model_visible_input,
                packet_changed=arm == "B0",
                action_order_complete=True,
                legacy_unsafe=observer_validation.get("unsafe"),
                source_receipt_hashes=(common.canonical_hash(raw_run), common.canonical_hash({"hidden_validator_passed": hidden_pass, "hidden_validator_errors": hidden_errors})),
            ).to_dict()
            common.validate_receipt_schema(native_receipt)
            observer_validation["observer_receipt"] = native_receipt
            observer_validation["measurement_valid"] = native_receipt["measurement_status"]["status"] == "COMPLETE"
            model_patch = common.scouting_corpus.patch_for_files(fixture, [
                (relative, mutated_snapshot[relative], (fixture / relative).read_bytes())
                for relative in spec["allowed_mutation_paths"]
                if mutated_snapshot[relative] != (fixture / relative).read_bytes()
            ])
            (private_run_root / "model_patch.diff").write_bytes(model_patch)
            common.write_json(private_run_root / "raw_harness_run.json", raw_run)
            common.write_json(private_run_root / "observer_validation.json", observer_validation)
            events = raw_run.get("tool_events", [])
            usage = common.token_usage(raw_run)
            read_paths = [path for event in events if event.get("name") == "read_file" for path in event.get("accessed_paths", [])]
            action_paths = set(read_paths) | {path for event in events if event.get("name") in {"apply_patch", "write_file"} for path in event.get("accessed_paths", [])}
            packet_quality = native_receipt["packet_quality"]
            run_outcome = native_receipt["run_outcome"]
            result = {
                **cell,
                "repository_id": task["repository_id"],
                "clone_method": clone_method,
                "starting_state_hash": start_hash,
                "mutated_precondition_failed": not mutated_pass,
                "mutated_precondition_errors": mutated_errors,
                "harness_status": raw_run.get("status"),
                "hidden_validator_passed": hidden_pass,
                "hidden_validator_errors": hidden_errors,
                "observer_outcome": observer_validation.get("outcome_class"),
                "observer_measurement_status": native_receipt["measurement_status"]["status"],
                "recommendation_status": native_receipt["recommendation_safety"]["status"],
                "packet_quality_status": packet_quality["status"],
                "attribution_status": native_receipt["safety_attribution"]["status"],
                "execution_safety": run_outcome["execution_safety"],
                "scope_status": run_outcome["run_scope_status"],
                "receipt_schema_valid": True,
                "requests": len(raw_run.get("turns", [])),
                "read_paths": sorted(set(read_paths)),
                "repeated_reads": len(read_paths) - len(set(read_paths)),
                "searches": sum(event.get("name") == "search_text" for event in events),
                "tool_calls": len(events),
                "files_edited": sorted({path for event in events if event.get("name") in {"apply_patch", "write_file"} for path in event.get("accessed_paths", [])}),
                "selected_paths": selected_paths,
                "supplied_used_paths": sorted(set(selected_paths) & action_paths),
                "supplied_unused_paths": sorted(set(selected_paths) - action_paths),
                "unsupplied_required_paths": sorted(set(spec["allowed_mutation_paths"]) - set(selected_paths)) if arm == "B0" else [],
                "packet_sha256": common.sha256_bytes(packet.encode()) if packet is not None else None,
                "compile_provider": "canonical_core_v1" if arm == "B0" and packet_metadata.get("canonical_core_packet") is True else None,
                "compile_packet_version": packet_metadata.get("packet_version"),
                "wall_time_seconds": round(raw_run.get("end_to_end_ms", 0) / 1000, 3),
                "fixture_size_bytes": common.scouting_corpus.directory_size(fixture),
                **usage,
            }
            common.write_json(private_run_root / "run_summary.json", result)
            with output_lock:
                print(json.dumps({"sequence": sequence, "task_id": task_id, "arm": arm, "success": hidden_pass, "measurement": result["observer_measurement_status"]}, sort_keys=True), flush=True)
            return result
        finally:
            shutil.rmtree(fixture, ignore_errors=True)
            if fixture.exists():
                raise RuntimeError(f"cleanup failed for {fixture}")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=arguments.workers, thread_name_prefix="pcodex-scout") as executor:
        futures = {executor.submit(run_cell, cell): cell for cell in schedule}
        for future in as_completed(futures):
            cell = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append({"sequence": cell["sequence"], "task_id": cell["task_id"], "arm": cell["arm"], "error_type": type(exc).__name__, "error": str(exc)[:2000]})
    results = prior_results + results
    results.sort(key=lambda item: item["sequence"])
    start_hashes: dict[str, dict[str, str]] = {}
    for result in results:
        start_hashes.setdefault(result["task_id"], {})[result["arm"]] = result["starting_state_hash"]
    parity = {task_id: arms.get("STANDARD") == arms.get("B0") for task_id, arms in start_hashes.items()}
    summary = {
        "schema_version": "pcodex-qwen-full-panel/1.0.0",
        "run_id": arguments.run_id,
        "seed": arguments.seed,
        "model": arguments.model,
        "worker_count": int(prior_summary.get("worker_count") or arguments.workers) if prior_summary else arguments.workers,
        "retry_worker_count": arguments.workers if prior_summary else 0,
        "planned_runs": len(full_schedule),
        "completed_runs": len(results),
        "errors": errors,
        "resumed_from_run_id": prior_summary.get("run_id") if prior_summary else None,
        "retry_cell_count": len(schedule) if prior_summary else 0,
        "task_count": len(selected_task_ids),
        "repository_count": len({tasks[task_id]["repository_id"] for task_id in selected_task_ids}),
        "all_identical_arm_start_states": len(parity) == len(selected_task_ids) and all(parity.values()),
        "all_mutated_preconditions_failed": all(result["mutated_precondition_failed"] for result in results),
        "all_receipts_complete": all(result["observer_measurement_status"] == "COMPLETE" and result["receipt_schema_valid"] for result in results),
        "all_cleanup_succeeded": not any(run_root.iterdir()),
        "temporary_peak_estimate_bytes": arguments.workers * max((result["fixture_size_bytes"] for result in results), default=0),
        "results": results,
    }
    result_path = corpus_root / "private-results" / f"{arguments.output_stem}.json"
    manifest_path = corpus_root / "private-results" / ("PRIVATE_RUN_MANIFEST.json" if arguments.output_stem == "PRIVATE_FULL_SCOUTING_RESULTS" else f"{arguments.output_stem}_RUN_MANIFEST.json")
    common.write_json(result_path, summary)
    common.write_json(manifest_path, {
        "schema_version": summary["schema_version"],
        "run_id": arguments.run_id,
        "schedule_hash": common.canonical_hash(full_schedule),
        "schedule": full_schedule,
        "raw_result_roots": [
            *([str(corpus_root / "private-results" / str(prior_summary.get("run_id")))] if prior_summary else []),
            str(private_results),
        ],
        "completed_runs": len(results),
        "errors": errors,
    })
    defects: dict[str, list[dict[str, Any]]] = {
        "validator_failure": [], "runtime_failure": [], "unsafe_execution": [], "b0_packet_incomplete": []
    }
    for result in results:
        cell = {key: result[key] for key in ("task_id", "repository_id", "task_class", "arm")}
        if not result["hidden_validator_passed"]:
            defects["validator_failure"].append(cell)
        if result["harness_status"] != "finished":
            defects["runtime_failure"].append(cell)
        if result["execution_safety"] != "SAFE":
            defects["unsafe_execution"].append(cell)
        if result["arm"] == "B0" and result["packet_quality_status"] != "CORRECT":
            defects["b0_packet_incomplete"].append(cell)
    strengths = {
        "exact_or_expansion_success": [
            {key: result[key] for key in ("task_id", "repository_id", "task_class", "arm", "observer_outcome")}
            for result in results if result["hidden_validator_passed"] and result["execution_safety"] == "SAFE"
        ],
        "complete_measurement_count": sum(result["observer_measurement_status"] == "COMPLETE" for result in results),
        "identical_start_pair_count": sum(parity.values()),
    }
    defect_path = corpus_root / "private-results" / ("PRIVATE_DEFECT_DATABASE.json" if arguments.output_stem == "PRIVATE_FULL_SCOUTING_RESULTS" else f"{arguments.output_stem}_DEFECTS.json")
    strength_path = corpus_root / "private-results" / ("PRIVATE_STRENGTH_DATABASE.json" if arguments.output_stem == "PRIVATE_FULL_SCOUTING_RESULTS" else f"{arguments.output_stem}_STRENGTHS.json")
    common.write_json(defect_path, defects)
    common.write_json(strength_path, strengths)
    print(json.dumps({
        "planned_runs": len(full_schedule),
        "completed_runs": len(results),
        "errors": len(errors),
        "all_identical_arm_start_states": summary["all_identical_arm_start_states"],
        "all_receipts_complete": summary["all_receipts_complete"],
        "all_cleanup_succeeded": summary["all_cleanup_succeeded"],
        "validator_successes": sum(result["hidden_validator_passed"] for result in results),
    }, sort_keys=True))
    return 0 if len(results) == len(full_schedule) and not errors and summary["all_receipts_complete"] and summary["all_cleanup_succeeded"] else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--corpus-root", required=True)
    result.add_argument(
        "--run-root",
        default=str(Path(common.tempfile.gettempdir()) / "pcodex-scouting-runs"),
    )
    result.add_argument("--run-id", required=True)
    result.add_argument("--python", required=True)
    result.add_argument("--b0-source", required=True)
    result.add_argument(
        "--endpoint",
        default=os.environ.get("PCODEX_SCOUTING_ENDPOINT", "http://" + "127.0.0.1:11434/v1"),
    )
    result.add_argument("--model", default="qwen3.6:latest")
    result.add_argument("--workers", type=int, default=3)
    result.add_argument("--seed", type=int, default=20260713)
    result.add_argument("--compile-timeout", type=int, default=180)
    result.add_argument("--resume-from")
    result.add_argument("--task-ids", nargs="+")
    result.add_argument("--repetition", type=int, default=1)
    result.add_argument("--output-stem", default="PRIVATE_FULL_SCOUTING_RESULTS")
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
