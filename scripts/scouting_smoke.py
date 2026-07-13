#!/usr/bin/env python3
"""Run the bounded four-task STANDARD/B0 Qwen scouting smoke privately."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "observer" / "src"))

from premode_observer.harness import ControlledHarness, HarnessLimits, SamplerSettings  # noqa: E402
from premode_observer.measurement import build_observer_receipt, validate_receipt_schema  # noqa: E402
from premode_observer.validation import TaskFixture, validate_task as validate_observer_task  # noqa: E402


CORPUS_SCRIPT = REPO_ROOT / "scripts" / "scouting_corpus.py"
MODULE_SPEC = importlib.util.spec_from_file_location("scouting_corpus", CORPUS_SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
scouting_corpus = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(scouting_corpus)

SMOKE_TASK_IDS = ("repo-001-g2-t01", "repo-002-g2-t02", "repo-003-g2-t03", "repo-004-g2-t04")
ARMS = ("STANDARD", "B0")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr[-4000:]}")
    return completed


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fixture_state_hash(fixture: Path, spec: dict[str, Any]) -> str:
    state = {
        "base_commit": spec["base_commit"],
        "files": {relative: sha256_bytes((fixture / relative).read_bytes()) for relative in spec["allowed_mutation_paths"]},
    }
    return sha256_bytes(json.dumps(state, sort_keys=True, separators=(",", ":")).encode())


def apfs_clone(source: Path, destination: Path) -> str:
    if destination.exists():
        shutil.rmtree(destination)
    completed = subprocess.run(["cp", "-cR", str(source), str(destination)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode == 0:
        return "apfs_clonefile"
    run(["git", "clone", "--no-local", "--no-hardlinks", str(source), str(destination)], timeout=300)
    return "contained_git_clone_fallback"


def compile_b0_packet(
    python: Path,
    b0_source: Path,
    fixture: Path,
    prompt: str,
    private_run_root: Path,
    timeout_seconds: int = 180,
) -> tuple[str, dict[str, Any], list[str]]:
    packet_path = private_run_root / "b0_packet.txt"
    metadata_path = private_run_root / "b0_compile.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(b0_source / "src")
    run([
        str(python), "-m", "premode.cli", "compile", prompt,
        "--repo", str(fixture), "--profile", "lite", "--plugin", "literal_symbol",
        "--out", str(packet_path), "--json-out", str(metadata_path), "--no-record",
    ], cwd=b0_source, env=environment, timeout=timeout_seconds)
    metadata = load_json(metadata_path)
    packet = packet_path.read_text(encoding="utf-8")
    selected: list[str] = []
    for key in ("selected_paths", "packet_files", "candidate_edit_files", "likely_files"):
        value = metadata.get(key)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            selected = list(value)
            break
    if not selected and isinstance(metadata.get("selected"), list):
        selected = [
            item["path"] for item in metadata["selected"]
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]
    if not selected and isinstance(metadata.get("contract"), dict):
        for key in ("packet_files", "candidate_edit_files"):
            value = metadata["contract"].get(key)
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                selected = list(value)
                break
    return packet, metadata, selected


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def token_usage(run_receipt: dict[str, Any]) -> dict[str, int]:
    prompt_tokens = 0
    completion_tokens = 0
    for turn in run_receipt.get("turns", []):
        response = turn.get("response") if isinstance(turn, dict) else None
        usage = response.get("usage") if isinstance(response, dict) else None
        if isinstance(usage, dict):
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
    return {
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def execute(arguments: argparse.Namespace) -> int:
    corpus_root = Path(arguments.corpus_root).resolve()
    run_root = Path(arguments.run_root).resolve() / arguments.run_id
    private_results = corpus_root / "private-results" / arguments.run_id
    tasks = {item["task_id"]: item for item in load_json(corpus_root / "tasks" / "PRIVATE_TASK_DEFINITIONS.json")}
    specs = load_json(corpus_root / "validators" / "PRIVATE_VALIDATOR_SPECS.json")
    mutations = {item["task_id"]: item for item in load_json(corpus_root / "mutations" / "PRIVATE_MUTATION_INDEX.json")}
    manifest = load_json(corpus_root / "manifests" / "PRIVATE_CORPUS_MANIFEST.json")
    repositories = {item["repository_id"]: item for item in manifest["repositories"]}
    python = Path(arguments.python).resolve()
    b0_source = Path(arguments.b0_source).resolve()
    harness = ControlledHarness(
        arguments.endpoint,
        arguments.model,
        limits=HarnessLimits(max_turns=12, max_tool_calls=32, max_output_tokens=1024, max_tool_result_bytes=32_768, task_timeout_seconds=300, command_timeout_seconds=30),
        sampler=SamplerSettings(seed=42, temperature=0.0, top_p=1.0, reasoning_effort="none"),
    )
    results: list[dict[str, Any]] = []
    start_hashes: dict[str, dict[str, str]] = {}
    peak_temp_bytes = 0
    run_root.mkdir(parents=True, exist_ok=True)
    private_results.mkdir(parents=True, exist_ok=True)
    schedule = [(task_id, ARMS[(task_index + arm_index) % 2]) for task_index, task_id in enumerate(SMOKE_TASK_IDS) for arm_index in range(2)]
    for sequence, (task_id, arm) in enumerate(schedule, 1):
        task = tasks[task_id]
        spec = specs[task_id]
        repository = repositories[task["repository_id"]]
        source = corpus_root / "repos" / "immutable" / repository["directory"]
        fixture = run_root / f"{sequence:02d}-{task_id}-{arm.casefold()}"
        private_run_root = private_results / f"{sequence:02d}-{task_id}-{arm.casefold()}"
        private_run_root.mkdir(parents=True, exist_ok=True)
        clone_method = apfs_clone(source, fixture)
        try:
            patch_path = Path(mutations[task_id]["mutation_patch_path"])
            run(["git", "-C", str(fixture), "apply", "--whitespace=nowarn", str(patch_path)])
            start_hash = fixture_state_hash(fixture, spec)
            start_hashes.setdefault(task_id, {})[arm] = start_hash
            mutated_validation = {"_private_validator_spec": spec}
            mutated_pass, mutated_errors = scouting_corpus.validate_task(mutated_validation, fixture)
            if mutated_pass:
                raise RuntimeError(f"mutated precondition unexpectedly passed for {task_id}")
            mutated_snapshot = {
                relative: (fixture / relative).read_bytes()
                for relative in spec["allowed_mutation_paths"]
            }
            packet = None
            packet_metadata: dict[str, Any] = {}
            selected_paths: list[str] = []
            if arm == "B0":
                packet, packet_metadata, selected_paths = compile_b0_packet(python, b0_source, fixture, task["prompt"], private_run_root)
            started = time.monotonic()
            raw_run = harness.run(task["prompt"], fixture, packet=packet, selected_paths=selected_paths)
            wall_time_seconds = time.monotonic() - started
            hidden_pass, hidden_errors = scouting_corpus.validate_task(mutated_validation, fixture)
            observer_fixture = TaskFixture(
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
            observer_validation = validate_observer_task(observer_fixture, fixture, raw_run).to_dict()
            if not hidden_pass:
                observer_validation["all_task_validators_pass"] = False
                observer_validation["tests_passed"] = False
                observer_validation["outcome_class"] = "partial" if raw_run.get("status") == "finished" else "runtime_failure"
            tool_misuse = any(event.get("safety_event_codes") for event in raw_run.get("tool_events", []))
            observer_validation["scope_adherence"] = not observer_validation.get("unrelated_files_changed") and not tool_misuse
            model_visible_input = packet if packet is not None else task["prompt"]
            packet_paths = selected_paths if arm == "B0" else []
            packet_projection_hash = canonical_hash(packet_paths)
            routing = packet_metadata.get("routing_decision") if isinstance(packet_metadata.get("routing_decision"), dict) else None
            candidate_evidence = routing.get("candidate_provenance") if isinstance(routing, dict) else None
            native_receipt = build_observer_receipt(
                fixture,
                packet_paths=packet_paths,
                packet_hash=sha256_bytes(model_visible_input.encode()),
                packet_projection_hash=packet_projection_hash,
                run=raw_run,
                validation=observer_validation,
                required_paths=spec["allowed_mutation_paths"] if arm == "B0" else (),
                wrong_ordinary_paths=(),
                routing_decision_hash=canonical_hash(routing) if routing is not None else None,
                candidate_evidence_hash=canonical_hash(candidate_evidence) if candidate_evidence is not None else None,
                packet_hash_verified=True,
                packet_bytes=model_visible_input,
                packet_changed=arm == "B0",
                action_order_complete=True,
                legacy_unsafe=observer_validation.get("unsafe"),
                source_receipt_hashes=(canonical_hash(raw_run), canonical_hash({"hidden_validator_passed": hidden_pass, "hidden_validator_errors": hidden_errors})),
            ).to_dict()
            validate_receipt_schema(native_receipt)
            observer_validation["observer_receipt"] = native_receipt
            observer_validation["measurement_valid"] = native_receipt["measurement_status"]["status"] == "COMPLETE"
            model_patch = scouting_corpus.patch_for_files(fixture, [
                (relative, mutated_snapshot[relative], (fixture / relative).read_bytes())
                for relative in spec["allowed_mutation_paths"]
                if mutated_snapshot[relative] != (fixture / relative).read_bytes()
            ])
            (private_run_root / "model_patch.diff").write_bytes(model_patch)
            write_json(private_run_root / "raw_harness_run.json", raw_run)
            write_json(private_run_root / "observer_validation.json", observer_validation)
            events = raw_run.get("tool_events", [])
            usage = token_usage(raw_run)
            result = {
                "sequence": sequence,
                "task_id": task_id,
                "repository_id": task["repository_id"],
                "task_class": task["task_class"],
                "arm": arm,
                "clone_method": clone_method,
                "starting_state_hash": start_hash,
                "mutated_precondition_failed": not mutated_pass,
                "mutated_precondition_errors": mutated_errors,
                "harness_status": raw_run.get("status"),
                "hidden_validator_passed": hidden_pass,
                "hidden_validator_errors": hidden_errors,
                "observer_outcome": observer_validation.get("outcome_class"),
                "observer_measurement_valid": observer_validation.get("measurement_valid"),
                "receipt_present": isinstance(observer_validation.get("observer_receipt"), dict),
                "requests": len(raw_run.get("turns", [])),
                "reads": sum(event.get("name") == "read_file" for event in events),
                "searches": sum(event.get("name") == "search_text" for event in events),
                "tool_calls": len(events),
                "files_edited": sorted({path for event in events if event.get("name") in {"apply_patch", "write_file"} for path in event.get("accessed_paths", [])}),
                "selected_path_count": len(selected_paths),
                "packet_sha256": sha256_bytes(packet.encode()) if packet is not None else None,
                "compile_provider": "canonical_core_v1" if arm == "B0" and packet_metadata.get("canonical_core_packet") is True else None,
                "compile_packet_version": packet_metadata.get("packet_version"),
                "wall_time_seconds": round(wall_time_seconds, 3),
                **usage,
            }
            results.append(result)
            write_json(private_run_root / "run_summary.json", result)
            peak_temp_bytes = max(peak_temp_bytes, scouting_corpus.directory_size(fixture))
        finally:
            shutil.rmtree(fixture, ignore_errors=True)
            if fixture.exists():
                raise RuntimeError(f"cleanup failed for {fixture}")
    parity = {task_id: hashes.get("STANDARD") == hashes.get("B0") for task_id, hashes in start_hashes.items()}
    summary = {
        "schema_version": "pcodex-qwen-smoke/1.0.0",
        "run_id": arguments.run_id,
        "model": arguments.model,
        "endpoint": arguments.endpoint,
        "worker_count": 1,
        "planned_runs": 8,
        "completed_runs": len(results),
        "tasks": len(SMOKE_TASK_IDS),
        "repositories": len({result["repository_id"] for result in results}),
        "task_classes": len({result["task_class"] for result in results}),
        "identical_arm_start_states": parity,
        "all_identical_arm_start_states": all(parity.values()),
        "all_mutated_preconditions_failed": all(result["mutated_precondition_failed"] for result in results),
        "all_hidden_validators_passed": all(result["hidden_validator_passed"] for result in results),
        "all_receipts_present": all(result["receipt_present"] for result in results),
        "all_cleanup_succeeded": not any(run_root.iterdir()),
        "temporary_peak_bytes_single_run": peak_temp_bytes,
        "results": results,
        "full_panel_started": False,
    }
    write_json(corpus_root / "private-results" / "PRIVATE_SMOKE_RESULTS.json", summary)
    write_json(corpus_root / "private-results" / "PRIVATE_RUN_MANIFEST.json", {
        "schema_version": summary["schema_version"],
        "run_id": arguments.run_id,
        "schedule": schedule,
        "raw_result_root": str(private_results),
        "results": results,
    })
    print(json.dumps({
        "completed_runs": len(results),
        "all_identical_arm_start_states": summary["all_identical_arm_start_states"],
        "all_hidden_validators_passed": summary["all_hidden_validators_passed"],
        "all_receipts_present": summary["all_receipts_present"],
        "all_cleanup_succeeded": summary["all_cleanup_succeeded"],
    }, sort_keys=True))
    return 0 if len(results) == 8 else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--corpus-root", required=True)
    result.add_argument(
        "--run-root",
        default=str(Path(tempfile.gettempdir()) / "pcodex-scouting-runs"),
    )
    result.add_argument("--run-id", required=True)
    result.add_argument("--python", required=True)
    result.add_argument("--b0-source", required=True)
    result.add_argument(
        "--endpoint",
        default=os.environ.get("PCODEX_SCOUTING_ENDPOINT", "http://" + "127.0.0.1:11434/v1"),
    )
    result.add_argument("--model", default="qwen3.6:latest")
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
