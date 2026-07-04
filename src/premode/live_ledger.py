from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any


DEFAULT_CACHE_ADJUSTMENT_FACTOR = 0.10
MAX_RAW_USAGE_EVENTS = 20


def cache_adjusted_input_tokens(
    input_tokens_uncached: int | None,
    input_tokens_cached: int | None,
    *,
    cache_adjustment_factor: float = DEFAULT_CACHE_ADJUSTMENT_FACTOR,
) -> float | None:
    if input_tokens_uncached is None or input_tokens_cached is None:
        return None
    return float(input_tokens_uncached) + float(cache_adjustment_factor) * float(input_tokens_cached)


def normalize_token_usage(
    raw: dict[str, Any] | None = None,
    *,
    cache_adjustment_factor: float = DEFAULT_CACHE_ADJUSTMENT_FACTOR,
    input_tokens_are_total: bool = False,
    cached_input_tokens_are_subset: bool = False,
    token_schema_source: str | None = None,
) -> dict[str, Any]:
    raw = raw or {}
    raw_fields = _raw_token_fields(raw)
    total = _int_or_none(
        raw.get("input_tokens")
        or raw.get("input_tokens_total")
        or raw.get("prompt_tokens")
    )
    cached = _int_or_none(
        raw.get("cached_input_tokens")
        or raw.get("input_tokens_cached")
        or raw.get("cached_tokens")
        or ((raw.get("input_token_details") or {}).get("cached_tokens") if isinstance(raw.get("input_token_details"), dict) else None)
        or ((raw.get("prompt_tokens_details") or {}).get("cached_tokens") if isinstance(raw.get("prompt_tokens_details"), dict) else None)
    )
    explicit_uncached = _int_or_none(
        raw.get("uncached_input_tokens")
        or raw.get("input_tokens_uncached")
        or raw.get("uncached_tokens")
    )
    output = _int_or_none(raw.get("output_tokens") or raw.get("completion_tokens"))
    reasoning = _int_or_none(
        raw.get("reasoning_tokens")
        or raw.get("reasoning_output_tokens")
        or ((raw.get("completion_tokens_details") or {}).get("reasoning_tokens") if isinstance(raw.get("completion_tokens_details"), dict) else None)
    )
    total_tokens = _int_or_none(raw.get("total_tokens"))
    notes: list[str] = []
    status = "unavailable"
    derived_uncached: int | None = None
    uncached: int | None = None
    adjusted: float | None = None
    if cached is not None and cached < 0:
        status = "invalid"
        notes.append("cached_input_tokens is negative")
    elif total is not None and total < 0:
        status = "invalid"
        notes.append("input_tokens is negative")
    elif explicit_uncached is not None:
        uncached = explicit_uncached
        if cached is None:
            status = "unavailable"
            notes.append("explicit uncached input is present but cached input is missing")
        elif uncached < 0:
            status = "invalid"
            notes.append("explicit uncached input is negative")
        else:
            status = "explicit"
            adjusted = cache_adjusted_input_tokens(uncached, cached, cache_adjustment_factor=cache_adjustment_factor)
    elif total is not None and cached is not None:
        if not input_tokens_are_total or not cached_input_tokens_are_subset:
            status = "unavailable"
            notes.append("input/cached fields present but schema semantics were not confirmed for derivation")
        elif cached > total:
            status = "invalid"
            notes.append("cached_input_tokens exceeds input_tokens")
        else:
            derived_uncached = total - cached
            status = "derived"
            adjusted = cache_adjusted_input_tokens(derived_uncached, cached, cache_adjustment_factor=cache_adjustment_factor)
    else:
        missing = []
        if total is None:
            missing.append("input_tokens")
        if cached is None:
            missing.append("cached_input_tokens")
        notes.append("missing fields: " + ", ".join(missing))
    return {
        "input_tokens": total,
        "cached_input_tokens": cached,
        "uncached_input_tokens": uncached,
        "derived_uncached_input_tokens": derived_uncached,
        "cache_adjusted_input_tokens": adjusted,
        "output_tokens": output,
        "reasoning_tokens": reasoning,
        "total_tokens": total_tokens,
        "token_derivation_status": status,
        "token_schema_source": token_schema_source,
        "token_derivation_notes": notes,
        "raw_token_fields": raw_fields,
        "cache_adjustment_factor": cache_adjustment_factor,
    }


def normalize_token_ledger(
    raw: dict[str, Any] | None = None,
    *,
    cache_adjustment_factor: float = DEFAULT_CACHE_ADJUSTMENT_FACTOR,
    input_tokens_are_total: bool = False,
    cached_input_tokens_are_subset: bool = False,
    token_schema_source: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_token_usage(
        raw,
        cache_adjustment_factor=cache_adjustment_factor,
        input_tokens_are_total=input_tokens_are_total,
        cached_input_tokens_are_subset=cached_input_tokens_are_subset,
        token_schema_source=token_schema_source,
    )
    return {
        "input_tokens_total": normalized["input_tokens"],
        "input_tokens_uncached": normalized["uncached_input_tokens"],
        "input_tokens_cached": normalized["cached_input_tokens"],
        "derived_uncached_input_tokens": normalized["derived_uncached_input_tokens"],
        "output_tokens": normalized["output_tokens"],
        "reasoning_output_tokens": normalized["reasoning_tokens"],
        "total_tokens": normalized["total_tokens"],
        "cache_adjusted_input_tokens": normalized["cache_adjusted_input_tokens"],
        "token_derivation_status": normalized["token_derivation_status"],
        "token_schema_source": normalized["token_schema_source"],
        "token_derivation_notes": normalized["token_derivation_notes"],
        "raw_token_fields": normalized["raw_token_fields"],
        "cache_adjustment_factor": cache_adjustment_factor,
    }


def empty_exploration_ledger(reason: str | None = None) -> dict[str, Any]:
    ledger = {
        "command_count": None,
        "repo_wide_search_count": 0,
        "explicit_file_reads": [],
        "explicit_file_read_count": 0,
        "search_result_file_mentions": [],
        "command_output_file_mentions": [],
        "validation_output_file_mentions": [],
        "generated_output_file_mentions": [],
        "all_referenced_files": [],
        "all_referenced_file_count": 0,
        "unique_files_read": [],
        "unique_files_read_count": 0,
        "unique_files_read_semantics": "deprecated_heuristic_all_referenced_files",
        "unique_file_read_bytes": None,
        "first_file_read": None,
        "first_edit_file": None,
        "changed_files": [],
        "changed_files_inside_candidates": None,
        "changed_files_inside_packet": None,
        "memory_file_reads": [],
        "explicit_repo_file_reads": [],
        "import_or_stacktrace_references": [],
        "module_references": [],
        "test_failure_file_references": [],
        "file_reference_only_paths": [],
        "first_repo_file_read": None,
    }
    if reason:
        ledger["missing_reason"] = reason
    return ledger


def empty_command_ledger() -> dict[str, Any]:
    return {
        "total": 0,
        "file_read_commands": 0,
        "search_commands": 0,
        "edit_commands": 0,
        "validation_commands": 0,
        "status_diff_commands": 0,
        "environment_probe_commands": 0,
        "build_or_parse_commands": 0,
        "other_commands": 0,
        "repeated_commands": [],
        "failed_or_blocked_commands": [],
        "validation_commands_after_last_edit": 0,
        "status_diff_commands_after_last_edit": 0,
        "commands_after_last_edit": 0,
        "commands_after_patch_complete_signal": 0,
        "raw_commands": [],
        "records": [],
        "explicit_file_reads": [],
        "explicit_repo_file_reads": [],
        "explicit_file_read_count": 0,
        "memory_file_reads": [],
        "search_hits": [],
        "validation_targets": [],
        "edit_targets": [],
        "import_or_stacktrace_references": [],
        "module_references": [],
        "test_failure_file_references": [],
        "file_reference_only_paths": [],
        "first_file_read": None,
        "first_repo_file_read": None,
        "first_file_edited": None,
        "memory_search_commands": [],
        "memory_read_commands": [],
        "memory_query_terms": [],
        "memory_command_count": 0,
        "memory_search_before_repo_search": None,
        "memory_output_bytes": 0,
        "memory_output_lines": 0,
        "memory_tokens_if_estimated": None,
        "actual_xcode_command_count": 0,
        "xcode_string_mention_count": 0,
        "xcode_memory_mention_count": 0,
        "xcode_search_mention_count": 0,
        "xcode_xcodebuild_commands": [],
        "xcode_command_violation_detected": False,
    }


def normalize_live_metrics(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw or {}
    return {
        "token_ledger": normalize_token_ledger(raw.get("token_ledger") or raw),
        "exploration_ledger": raw.get("exploration_ledger") or empty_exploration_ledger("raw exploration log not provided"),
    }


def parse_jsonl_token_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return normalize_token_ledger({})
    token_data: dict[str, Any] = {}
    raw_usage_events: list[dict[str, Any]] = []
    warnings: list[str] = []
    schema_sources: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = event.get("usage") if isinstance(event, dict) else None
        if isinstance(usage, dict):
            if len(raw_usage_events) < MAX_RAW_USAGE_EVENTS:
                raw_usage_events.append(event)
            elif len(raw_usage_events) == MAX_RAW_USAGE_EVENTS:
                warnings.append("raw usage events truncated")
            token_data.update(usage)
            schema_sources.add(str(event.get("type") or "usage"))
    semantics_confirmed = _usage_schema_semantics_confirmed(raw_usage_events)
    ledger = normalize_token_ledger(
        token_data,
        input_tokens_are_total=semantics_confirmed,
        cached_input_tokens_are_subset=semantics_confirmed,
        token_schema_source=",".join(sorted(schema_sources)) if schema_sources else None,
    )
    ledger["raw_usage_events"] = raw_usage_events
    ledger["raw_usage_events_sample"] = raw_usage_events
    ledger["raw_usage_events_truncated"] = len(raw_usage_events) >= MAX_RAW_USAGE_EVENTS and "raw usage events truncated" in warnings
    ledger["raw_jsonl_path"] = str(path)
    ledger["raw_token_fields"] = _raw_token_fields(token_data)
    ledger["usage_event_count"] = len(raw_usage_events)
    ledger["usage_parse_warnings"] = warnings
    return ledger


def parse_jsonl_usage(path: Path) -> dict[str, Any]:
    ledger = parse_jsonl_token_ledger(path)
    return {
        "input_tokens": ledger.get("input_tokens_total"),
        "cached_input_tokens": ledger.get("input_tokens_cached"),
        "uncached_input_tokens": ledger.get("input_tokens_uncached"),
        "derived_uncached_input_tokens": ledger.get("derived_uncached_input_tokens"),
        "cache_adjusted_input_tokens": ledger.get("cache_adjusted_input_tokens"),
        "output_tokens": ledger.get("output_tokens"),
        "reasoning_tokens": ledger.get("reasoning_output_tokens"),
        "total_tokens": ledger.get("total_tokens"),
        "token_derivation_status": ledger.get("token_derivation_status"),
        "token_schema_source": ledger.get("token_schema_source"),
        "token_derivation_notes": ledger.get("token_derivation_notes") or [],
        "raw_token_fields": ledger.get("raw_token_fields") or {},
        "raw_usage_events": ledger.get("raw_usage_events") or [],
        "raw_jsonl_path": ledger.get("raw_jsonl_path"),
        "raw_usage_events_sample": ledger.get("raw_usage_events_sample") or [],
        "raw_usage_events_truncated": bool(ledger.get("raw_usage_events_truncated")),
        "usage_event_count": int(ledger.get("usage_event_count") or 0),
        "usage_parse_warnings": ledger.get("usage_parse_warnings") or [],
    }


def parse_command_ledger_from_jsonl(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_command_ledger()
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return command_ledger_from_events(events)


def command_ledger_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    patch_complete_index: int | None = None
    for event_index, event in enumerate(events):
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        event_type = str(event.get("type") or "")
        item_type = str(item.get("type") or "")
        if item_type == "command_execution" and event_type.endswith(".completed"):
            command = str(item.get("command") or "").strip()
            if command:
                records.append({
                    "event_index": event_index,
                    "kind": "command",
                    "command": command,
                    "category": classify_command(command),
                    "exit_code": item.get("exit_code"),
                    "status": item.get("status"),
                    "output_text": _event_output_text(item),
                    "cwd": item.get("cwd"),
                    "timestamp": event.get("timestamp"),
                })
        elif item_type == "file_change" and event_type.endswith(".completed"):
            changes = item.get("changes") if isinstance(item.get("changes"), list) else []
            label = ", ".join(str(change.get("path") or "") for change in changes if isinstance(change, dict) and change.get("path"))
            records.append({
                "event_index": event_index,
                "kind": "edit",
                "command": f"file_change: {label}" if label else "file_change",
                "category": "edit_commands",
                "exit_code": 0,
                "status": item.get("status"),
                "output_text": "",
                "edit_targets": [str(change.get("path") or "") for change in changes if isinstance(change, dict) and change.get("path")],
                "timestamp": event.get("timestamp"),
            })
        elif item_type == "agent_message" and event_type.endswith(".completed"):
            text = str(item.get("text") or "").lower()
            if patch_complete_index is None and any(
                phrase in text
                for phrase in (
                    "final hygiene",
                    "final quick validation",
                    "final status",
                    "wrap up",
                    "implemented",
                    "summary",
                )
            ):
                patch_complete_index = len(records)

    ledger = empty_command_ledger()
    ledger["total"] = len(records)
    raw_commands: list[str] = []
    counts: dict[str, int] = {}
    last_edit_index: int | None = None
    first_repo_search_index: int | None = None
    first_memory_search_index: int | None = None
    explicit_reads: list[str] = []
    explicit_repo_reads: list[str] = []
    memory_file_reads: list[str] = []
    search_hits: list[str] = []
    validation_targets: list[str] = []
    edit_targets: list[str] = []
    import_refs: list[str] = []
    module_refs: list[str] = []
    test_failure_refs: list[str] = []
    file_reference_only: list[str] = []
    memory_query_terms: list[str] = []
    normalized_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        command = str(record.get("command") or "")
        category = str(record.get("category") or "other_commands")
        output_text = str(record.get("output_text") or "")
        normalized = normalize_command_record(record)
        normalized_records.append(normalized)
        raw_commands.append(command)
        ledger[category] = int(ledger.get(category) or 0) + 1
        counts[command] = counts.get(command, 0) + 1
        memory_info = memory_command_info(command, output_text)
        if memory_info["is_memory_command"]:
            ledger["memory_command_count"] = int(ledger["memory_command_count"]) + 1
            if memory_info["is_search"]:
                ledger["memory_search_commands"].append(command)
                if first_memory_search_index is None:
                    first_memory_search_index = index
            if memory_info["is_read"]:
                ledger["memory_read_commands"].append(command)
            memory_query_terms.extend(memory_info["query_terms"])
            ledger["memory_output_bytes"] = int(ledger["memory_output_bytes"]) + int(memory_info["output_bytes"])
            ledger["memory_output_lines"] = int(ledger["memory_output_lines"]) + int(memory_info["output_lines"])
        elif category == "search_commands" and first_repo_search_index is None:
            first_repo_search_index = index
        if not memory_info["is_memory_command"]:
            explicit_reads.extend(normalized["repo_file_reads"])
            explicit_repo_reads.extend(normalized["repo_file_reads"])
        memory_file_reads.extend(normalized["memory_file_reads"])
        search_hits.extend(normalized["search_hits"])
        validation_targets.extend(normalized["validation_targets"])
        edit_targets.extend(normalized["edit_targets"])
        import_refs.extend(normalized["import_or_stacktrace_references"])
        module_refs.extend(normalized["module_references"])
        test_failure_refs.extend(normalized["test_failure_file_references"])
        file_reference_only.extend(normalized["file_reference_only_paths"])
        xcode_info = classify_xcode_command(command)
        ledger["actual_xcode_command_count"] = int(ledger["actual_xcode_command_count"]) + int(xcode_info["actual_count"])
        ledger["xcode_string_mention_count"] = int(ledger["xcode_string_mention_count"]) + int(xcode_info["string_mention_count"])
        ledger["xcode_memory_mention_count"] = int(ledger["xcode_memory_mention_count"]) + int(xcode_info["memory_mention_count"])
        ledger["xcode_search_mention_count"] = int(ledger["xcode_search_mention_count"]) + int(xcode_info["search_mention_count"])
        if xcode_info["actual_commands"]:
            ledger["xcode_xcodebuild_commands"].extend(xcode_info["actual_commands"])
        if category == "edit_commands":
            last_edit_index = index
        if _command_failed_or_blocked(record):
            ledger["failed_or_blocked_commands"].append({
                "command": command,
                "exit_code": record.get("exit_code"),
                "status": record.get("status"),
            })

    repeated = [
        {"command": command, "count": count}
        for command, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count > 1
    ]
    ledger["raw_commands"] = raw_commands
    ledger["records"] = normalized_records
    ledger["explicit_file_reads"] = _dedupe(explicit_reads)
    ledger["explicit_repo_file_reads"] = _dedupe(explicit_repo_reads)
    ledger["explicit_file_read_count"] = len(ledger["explicit_file_reads"])
    ledger["memory_file_reads"] = _dedupe(memory_file_reads)
    ledger["search_hits"] = _dedupe(search_hits)
    ledger["validation_targets"] = _dedupe(validation_targets)
    ledger["edit_targets"] = _dedupe(edit_targets)
    ledger["import_or_stacktrace_references"] = _dedupe(import_refs)
    ledger["module_references"] = _dedupe(module_refs)
    ledger["test_failure_file_references"] = _dedupe(test_failure_refs)
    ledger["file_reference_only_paths"] = _dedupe(file_reference_only)
    ledger["first_file_read"] = ledger["explicit_file_reads"][0] if ledger["explicit_file_reads"] else None
    ledger["first_repo_file_read"] = ledger["explicit_repo_file_reads"][0] if ledger["explicit_repo_file_reads"] else None
    ledger["first_file_edited"] = ledger["edit_targets"][0] if ledger["edit_targets"] else None
    ledger["memory_query_terms"] = _dedupe(memory_query_terms)
    ledger["memory_search_before_repo_search"] = (
        first_memory_search_index is not None
        and (first_repo_search_index is None or first_memory_search_index < first_repo_search_index)
    )
    if int(ledger["memory_output_bytes"]) > 0:
        ledger["memory_tokens_if_estimated"] = max(1, int(ledger["memory_output_bytes"]) // 4)
    ledger["xcode_command_violation_detected"] = int(ledger["actual_xcode_command_count"]) > 0
    ledger["repeated_commands"] = repeated
    if last_edit_index is not None:
        after_last_edit = records[last_edit_index + 1 :]
        ledger["commands_after_last_edit"] = len(after_last_edit)
        ledger["validation_commands_after_last_edit"] = sum(1 for item in after_last_edit if item.get("category") == "validation_commands")
        ledger["status_diff_commands_after_last_edit"] = sum(1 for item in after_last_edit if item.get("category") == "status_diff_commands")
    if patch_complete_index is not None:
        ledger["commands_after_patch_complete_signal"] = max(0, len(records) - patch_complete_index)
    return ledger


def classify_command(command: str) -> str:
    text = _strip_shell_wrapper(command)
    lower = text.lower()
    name = _command_name(text)
    if memory_command_info(text)["is_memory_command"]:
        return "other_commands"
    if "apply_patch" in lower or name in {"apply_patch"}:
        return "edit_commands"
    if name in {"rg", "grep", "find", "fd", "ag"}:
        return "search_commands"
    if name in {"cat", "sed", "nl", "head", "tail", "less"}:
        return "file_read_commands"
    if name == "git":
        if "diff --check" in lower:
            return "validation_commands"
        if any(lower.startswith(prefix) for prefix in ("git status", "git diff", "git diff --cached", "git branch", "git log", "git show")):
            return "status_diff_commands"
        if any(lower.startswith(prefix) for prefix in ("git rev-parse", "git worktree list")):
            return "environment_probe_commands"
    if name in {"pwd", "ls", "which", "whoami", "uname", "date", "lsof", "ps", "pgrep"}:
        return "environment_probe_commands"
    if _is_validation_command(lower):
        return "validation_commands"
    if _is_build_or_parse_command(lower, name):
        return "build_or_parse_commands"
    if name in {"python", "python3"} and _looks_like_file_reading_python(lower):
        return "file_read_commands"
    return "other_commands"


def normalize_command_record(record: dict[str, Any]) -> dict[str, Any]:
    command = str(record.get("command") or "")
    output_text = str(record.get("output_text") or "")
    argv = _argv(command)
    category = str(record.get("category") or classify_command(command))
    memory_info = memory_command_info(command, output_text)
    repo_reads: list[str] = []
    memory_reads: list[str] = []
    if memory_info["is_memory_command"]:
        memory_reads.extend(extract_explicit_file_reads_from_command(command, include_search_args=False))
    elif category == "file_read_commands":
        repo_reads.extend(extract_explicit_file_reads_from_command(command, include_search_args=False))
    search_hits = _extract_search_hits(output_text) if category == "search_commands" else []
    validation_targets = _validation_targets_from_command(command) if category == "validation_commands" else []
    edit_targets = list(record.get("edit_targets") or [])
    if not edit_targets and category == "edit_commands":
        edit_targets.extend(_extract_paths(command))
    references = classify_output_references(output_text)
    classification: list[str] = []
    if repo_reads:
        classification.append("repo_file_read")
    if memory_reads:
        classification.append("memory_file_read")
    if category == "search_commands":
        classification.append("search_command")
    if category == "validation_commands":
        classification.append("validation_command")
    if category == "edit_commands":
        classification.append("edit_command")
    if category == "status_diff_commands":
        classification.append("status_diff_command")
    if len(output_text.encode("utf-8", errors="replace")) > 12000:
        classification.append("large_output_command")
    if references["import_or_stacktrace_references"]:
        classification.append("import_or_stacktrace_reference")
    file_reference_only = [
        path for path in references["file_reference_only_paths"]
        if path not in repo_reads and path not in memory_reads and path not in search_hits
    ]
    if file_reference_only:
        classification.append("file_reference_only")
    if any(path.startswith(("/", "private/", "tmp/")) for path in repo_reads + file_reference_only):
        classification.append("non_repo_path")
    if not classification:
        classification.append("unknown")
    return {
        "event_index": record.get("event_index"),
        "timestamp": record.get("timestamp"),
        "kind": record.get("kind") or "command",
        "argv": argv,
        "command_text": command,
        "cwd": str(record.get("cwd") or ""),
        "exit_code": record.get("exit_code"),
        "stdout_excerpt": _excerpt(output_text),
        "stderr_excerpt": "",
        "referenced_paths": _dedupe(repo_reads + memory_reads + search_hits + validation_targets + edit_targets + references["all_references"]),
        "repo_file_reads": _dedupe(repo_reads),
        "memory_file_reads": _dedupe(memory_reads),
        "search_hits": _dedupe(search_hits),
        "validation_targets": _dedupe(validation_targets),
        "edit_targets": _dedupe(edit_targets),
        "import_or_stacktrace_references": references["import_or_stacktrace_references"],
        "module_references": references["module_references"],
        "test_failure_file_references": references["test_failure_file_references"],
        "file_reference_only_paths": _dedupe(file_reference_only),
        "classification": _dedupe(classification),
    }


def _event_output_text(item: dict[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("output", "stdout", "stderr", "text"):
        value = item.get(key)
        if isinstance(value, str):
            chunks.append(value)
    return "\n".join(chunks)


def _argv(command: str) -> list[str]:
    text = _strip_shell_wrapper(command)
    try:
        return shlex.split(text)
    except ValueError:
        return re.split(r"\s+", text.strip())


def extract_explicit_file_reads_from_command(command: str, *, include_search_args: bool = False) -> list[str]:
    argv = _argv(command)
    if not argv:
        return []
    name = Path(argv[0]).name
    if name in {"cat", "nl", "less"}:
        return _dedupe([arg for arg in argv[1:] if _looks_like_file_arg(arg)])
    if name in {"head", "tail"}:
        return _dedupe([arg for arg in argv[1:] if _looks_like_file_arg(arg)])
    if name == "sed":
        return _dedupe([arg for arg in argv[1:] if _looks_like_file_arg(arg)])
    if include_search_args and name in {"rg", "grep"}:
        return _dedupe([arg for arg in argv[2:] if _looks_like_file_arg(arg)])
    if name == "git" and len(argv) >= 2:
        sub = argv[1]
        if sub == "diff" and "--" in argv:
            return _dedupe([arg for arg in argv[argv.index("--") + 1 :] if _looks_like_file_arg(arg)])
        if sub == "show":
            out: list[str] = []
            for arg in argv[2:]:
                if ":" in arg:
                    maybe = arg.rsplit(":", 1)[-1]
                    if _looks_like_file_arg(maybe):
                        out.append(maybe)
                elif _looks_like_file_arg(arg):
                    out.append(arg)
            return _dedupe(out)
    lower = _strip_shell_wrapper(command).lower()
    if name in {"python", "python3"} and _looks_like_file_reading_python(lower):
        return _dedupe(_extract_paths(command))
    return []


def classify_output_references(text: str) -> dict[str, list[str]]:
    import_refs: list[str] = []
    module_refs: list[str] = []
    test_failure_refs: list[str] = []
    file_only: list[str] = []
    for line in (text or "").splitlines():
        paths = _extract_paths(line)
        if not paths:
            continue
        lower = line.lower()
        if "traceback" in lower or re.search(r'file ".*", line \d+', line, flags=re.I):
            import_refs.extend(paths)
        elif "importerror" in lower or "modulenotfounderror" in lower or "cannot find module" in lower:
            import_refs.extend(paths)
            module_refs.extend(paths)
        elif re.search(r"\b(failed|error|assertionerror)\b", lower) or "::" in line:
            test_failure_refs.extend(paths)
        elif _looks_like_search_result(line):
            # Search hits are handled separately by command classification.
            pass
        else:
            file_only.extend(paths)
    all_refs = _dedupe(import_refs + module_refs + test_failure_refs + file_only)
    return {
        "import_or_stacktrace_references": _dedupe(import_refs),
        "module_references": _dedupe(module_refs),
        "test_failure_file_references": _dedupe(test_failure_refs),
        "file_reference_only_paths": _dedupe(file_only),
        "all_references": all_refs,
    }


def _extract_search_hits(text: str) -> list[str]:
    hits: list[str] = []
    for line in (text or "").splitlines():
        if _looks_like_search_result(line):
            hits.extend(_extract_paths(line))
    return _dedupe(hits)


def _validation_targets_from_command(command: str) -> list[str]:
    argv = _argv(command)
    out: list[str] = []
    for arg in argv[1:]:
        if _looks_like_file_arg(arg):
            out.append(arg)
    return _dedupe(out)


def _excerpt(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def _looks_like_file_arg(arg: str) -> bool:
    text = str(arg or "").strip()
    if not text or text == "--" or text.startswith("-"):
        return False
    if text.startswith(("http://", "https://")):
        return False
    return bool(re.search(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+$", text))


def memory_command_info(command: str, output_text: str = "") -> dict[str, Any]:
    text = _strip_shell_wrapper(command)
    lower = text.lower()
    is_memory = "/.codex/memories/" in lower or "/memory.md" in lower or ".codex/memories" in lower
    argv = _argv(text)
    name = Path(argv[0]).name if argv else ""
    is_search = is_memory and name in {"rg", "grep", "find", "fd", "ag"}
    is_read = is_memory and name in {"cat", "sed", "nl", "head", "tail", "less"}
    query_terms: list[str] = []
    if is_search and len(argv) > 1:
        for arg in argv[1:]:
            if arg.startswith("-") or "/" in arg or arg.endswith((".md", ".txt", ".json")):
                continue
            query_terms.append(arg)
            break
    return {
        "is_memory_command": is_memory,
        "is_search": is_search,
        "is_read": is_read,
        "query_terms": query_terms,
        "output_bytes": len((output_text or "").encode("utf-8", errors="replace")) if is_memory else 0,
        "output_lines": len((output_text or "").splitlines()) if is_memory and output_text else 0,
    }


def classify_xcode_command(command: str) -> dict[str, Any]:
    text = _strip_shell_wrapper(command)
    lower = text.lower()
    argv = _argv(text)
    name = Path(argv[0]).name if argv else ""
    is_search = name in {"rg", "grep", "find", "fd", "ag"}
    is_memory = memory_command_info(text)["is_memory_command"]
    mentions_xcode = "xcode" in lower or "xcodebuild" in lower
    actual = False
    if name in {"xcodebuild", "xed"}:
        actual = True
    elif name == "open" and len(argv) >= 3 and argv[1] == "-a" and argv[2].lower() == "xcode":
        actual = True
    elif argv and "/applications/xcode.app/" in argv[0].lower():
        actual = True
    return {
        "actual_count": 1 if actual else 0,
        "actual_commands": [text] if actual else [],
        "string_mention_count": 1 if mentions_xcode and not actual else 0,
        "memory_mention_count": 1 if mentions_xcode and is_memory and not actual else 0,
        "search_mention_count": 1 if mentions_xcode and is_search and not actual else 0,
    }


def _strip_shell_wrapper(command: str) -> str:
    text = (command or "").strip()
    match = re.match(r"^/(?:bin/)?(?:zsh|bash|sh)\s+-lc\s+(['\"])(?P<body>.*)\1$", text)
    if match:
        return match.group("body").strip()
    return text


def _is_validation_command(lower: str) -> bool:
    return any(
        token in lower
        for token in (
            "pytest",
            "python -m pytest",
            "python3 -m pytest",
            "python -m py_compile",
            "python3 -m py_compile",
            "python tests/",
            "python3 tests/",
            "npm test",
            "pnpm test",
            "yarn test",
            "bun test",
            "cargo test",
            "go test",
            "swift test",
            "xcodebuild test",
            "git diff --check",
        )
    )


def _is_build_or_parse_command(lower: str, name: str) -> bool:
    if name in {"cmake", "make", "ninja"}:
        return True
    if name == "swiftc" and "-parse" in lower:
        return True
    if name == "xcodebuild":
        return True
    if "swiftc -parse" in lower:
        return True
    return False


def _looks_like_file_reading_python(lower: str) -> bool:
    return any(token in lower for token in ("read_text", "read_bytes", "open(", ".read(", "json.load", "tomllib.load"))


def _usage_schema_semantics_confirmed(events: list[dict[str, Any]]) -> bool:
    if not events:
        return False
    saw_total_and_cached = False
    for event in events:
        usage = event.get("usage") if isinstance(event, dict) else None
        if not isinstance(usage, dict):
            continue
        total = _int_or_none(usage.get("input_tokens") or usage.get("input_tokens_total"))
        cached = _int_or_none(usage.get("cached_input_tokens") or usage.get("input_tokens_cached"))
        if total is None or cached is None:
            continue
        if cached > total:
            return False
        saw_total_and_cached = True
        event_type = str(event.get("type") or "")
        if event_type and not event_type.endswith("completed") and event_type not in {"turn.completed", "response.completed"}:
            # Unknown event types can still be normalized, but do not prove the derivation contract.
            return False
    return saw_total_and_cached


def _raw_token_fields(raw: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "usage",
        "input_tokens",
        "input_tokens_total",
        "cached_input_tokens",
        "input_tokens_cached",
        "uncached_input_tokens",
        "input_tokens_uncached",
        "output_tokens",
        "reasoning_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        "input_token_details",
        "prompt_tokens",
        "prompt_tokens_details",
        "cached_tokens",
        "completion_tokens",
        "completion_tokens_details",
    }
    return {key: raw[key] for key in sorted(keys) if key in raw}


def _command_failed_or_blocked(record: dict[str, Any]) -> bool:
    status = str(record.get("status") or "").lower()
    exit_code = record.get("exit_code")
    if status in {"failed", "blocked"}:
        return True
    try:
        return exit_code is not None and int(exit_code) != 0
    except (TypeError, ValueError):
        return False


def parse_exploration_ledger_from_text(text: str, *, candidate_files: list[str] | None = None, packet_files: list[str] | None = None) -> dict[str, Any]:
    candidate_set = {p for p in candidate_files or []}
    packet_set = {p for p in packet_files or []}
    lines = (text or "").splitlines()
    command_lines = [line for line in lines if re.match(r"^\s*(?:\$|cmd:|command:)\s+", line)]
    commands = len(command_lines)
    explicit_reads: list[str] = []
    repo_wide_search_count = 0
    search_mentions: list[str] = []
    command_output_mentions: list[str] = []
    validation_mentions: list[str] = []
    generated_mentions: list[str] = []
    memory_file_reads: list[str] = []
    for line in lines:
        lowered = line.lower()
        command_text = re.sub(r"^\s*(?:\$|cmd:|command:)\s+", "", line).strip()
        if command_text:
            command_name = _command_name(command_text)
            is_memory_command = memory_command_info(command_text)["is_memory_command"]
            if command_name in {"rg", "grep"} and not is_memory_command:
                repo_wide_search_count += 1
            reads = extract_explicit_file_reads_from_command(command_text)
            if is_memory_command:
                memory_file_reads.extend(reads)
            else:
                explicit_reads.extend(reads)
        paths = _extract_paths(line)
        if not paths:
            continue
        if _looks_like_search_result(line):
            search_mentions.extend(paths)
        elif "validation" in lowered or lowered.startswith(("test:", "tests:", "pytest:", "build:", "lint:")):
            validation_mentions.extend(paths)
        elif "generated" in lowered or "report" in lowered or lowered.startswith(("wrote ", "created ")):
            generated_mentions.extend(paths)
        elif "output" in lowered or "stdout" in lowered or "stderr" in lowered:
            command_output_mentions.extend(paths)
        elif line not in command_lines:
            command_output_mentions.extend(paths)
    changed = _dedupe(re.findall(r"(?m)(?:modified|changed|edited)\s+([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)", text or ""))
    explicit_reads = _dedupe(explicit_reads)
    search_mentions = _dedupe(search_mentions)
    command_output_mentions = _dedupe(command_output_mentions)
    validation_mentions = _dedupe(validation_mentions)
    generated_mentions = _dedupe(generated_mentions)
    all_referenced = _dedupe(explicit_reads + search_mentions + command_output_mentions + validation_mentions + generated_mentions + changed)
    return {
        "command_count": commands or None,
        "repo_wide_search_count": repo_wide_search_count,
        "explicit_file_reads": explicit_reads,
        "explicit_file_read_count": len(explicit_reads),
        "search_result_file_mentions": search_mentions,
        "command_output_file_mentions": command_output_mentions,
        "validation_output_file_mentions": validation_mentions,
        "generated_output_file_mentions": generated_mentions,
        "memory_file_reads": _dedupe(memory_file_reads),
        "all_referenced_files": all_referenced,
        "all_referenced_file_count": len(all_referenced),
        "unique_files_read": all_referenced,
        "unique_files_read_count": len(all_referenced),
        "unique_files_read_semantics": "deprecated_heuristic_all_referenced_files",
        "unique_file_read_bytes": None,
        "first_file_read": explicit_reads[0] if explicit_reads else None,
        "first_edit_file": changed[0] if changed else None,
        "changed_files": changed,
        "changed_files_inside_candidates": all(path in candidate_set for path in changed) if changed and candidate_set else None,
        "changed_files_inside_packet": all(path in packet_set for path in changed) if changed and packet_set else None,
    }


def normalized_run_measurements(
    *,
    token_usage: dict[str, Any] | None = None,
    command_ledger: dict[str, Any] | None = None,
    likely_files: list[str] | None = None,
    packet_files: list[str] | None = None,
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    token = token_usage or normalize_token_usage({})
    ledger = command_ledger or empty_command_ledger()
    likely_set = set(likely_files or [])
    packet_set = set(packet_files or [])
    changed = changed_files or []
    first_repo = ledger.get("first_repo_file_read")
    first_read = ledger.get("first_file_read") or first_repo
    first_edit = ledger.get("first_file_edited") or (changed[0] if changed else None)
    out = {
        "normalized_tokens": token,
        "input_tokens": token.get("input_tokens"),
        "cached_input_tokens": token.get("cached_input_tokens"),
        "uncached_input_tokens": token.get("uncached_input_tokens"),
        "derived_uncached_input_tokens": token.get("derived_uncached_input_tokens"),
        "cache_adjusted_input_tokens": token.get("cache_adjusted_input_tokens"),
        "output_tokens": token.get("output_tokens"),
        "reasoning_tokens": token.get("reasoning_tokens"),
        "total_tokens": token.get("total_tokens"),
        "token_derivation_status": token.get("token_derivation_status"),
        "token_schema_source": token.get("token_schema_source"),
        "token_derivation_notes": token.get("token_derivation_notes") or [],
        "raw_token_fields": token.get("raw_token_fields") or {},
        "explicit_file_reads": int(ledger.get("explicit_file_read_count") or 0),
        "explicit_repo_file_reads": ledger.get("explicit_repo_file_reads") or [],
        "memory_file_reads": ledger.get("memory_file_reads") or [],
        "search_command_count": int(ledger.get("search_commands") or 0),
        "validation_command_count": int(ledger.get("validation_commands") or 0),
        "import_or_stacktrace_references": ledger.get("import_or_stacktrace_references") or [],
        "file_reference_only_paths": ledger.get("file_reference_only_paths") or [],
        "first_file_read": first_read,
        "first_file_read_inside_likely": first_read in likely_set if first_read else None,
        "first_file_read_inside_packet": first_read in packet_set if first_read else None,
        "first_repo_file_read": first_repo,
        "first_repo_file_read_inside_likely": first_repo in likely_set if first_repo else None,
        "first_repo_file_read_inside_packet": first_repo in packet_set if first_repo else None,
        "first_file_edited": first_edit,
        "first_file_edited_inside_likely": first_edit in likely_set if first_edit else None,
        "first_file_edited_inside_packet": first_edit in packet_set if first_edit else None,
    }
    return out


def aggregate_measurement_rows(rows: list[dict[str, Any]], *, lane_key: str = "lane") -> dict[str, Any]:
    by_lane: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_lane.setdefault(str(row.get(lane_key) or "unknown"), []).append(row)
    status_counts = _counter(row.get("token_derivation_status") for row in rows)
    out = {
        "row_count": len(rows),
        "token_derivation_status_counts": status_counts,
        "cache_adjusted_available_count": sum(1 for row in rows if row.get("cache_adjusted_input_tokens") is not None),
        "cache_adjusted_unavailable_count": status_counts.get("unavailable", 0),
        "cache_adjusted_invalid_count": status_counts.get("invalid", 0),
        "explicit_token_rows": status_counts.get("explicit", 0),
        "derived_token_rows": status_counts.get("derived", 0),
        "unavailable_token_rows": status_counts.get("unavailable", 0),
        "invalid_token_rows": status_counts.get("invalid", 0),
        "lanes": {},
    }
    for lane, lane_rows in sorted(by_lane.items()):
        out["lanes"][lane] = {
            "run_count": len(lane_rows),
            "input_tokens_sum": _sum_field(lane_rows, "input_tokens"),
            "raw_input_tokens_not_cache_adjusted_cost": _sum_field(lane_rows, "input_tokens"),
            "cached_input_tokens_sum": _sum_field(lane_rows, "cached_input_tokens"),
            "uncached_input_tokens_sum": _sum_field(lane_rows, "uncached_input_tokens"),
            "derived_uncached_input_tokens_sum": _sum_field(lane_rows, "derived_uncached_input_tokens"),
            "cache_adjusted_input_sum": _sum_field(lane_rows, "cache_adjusted_input_tokens"),
            "cache_adjusted_input_median": _median_field(lane_rows, "cache_adjusted_input_tokens"),
            "output_tokens_sum": _sum_field(lane_rows, "output_tokens"),
            "reasoning_tokens_sum": _sum_field(lane_rows, "reasoning_tokens"),
            "total_tokens_sum": _sum_field(lane_rows, "total_tokens"),
            "explicit_file_reads_sum": _sum_field(lane_rows, "explicit_file_reads"),
            "first_repo_file_read_likely_rate": _bool_rate(lane_rows, "first_repo_file_read_inside_likely"),
            "first_edit_packet_rate": _bool_rate(lane_rows, "first_file_edited_inside_packet"),
            "token_derivation_status_counts": _counter(row.get("token_derivation_status") for row in lane_rows),
        }
    return out


def paired_cache_adjusted_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_value = left.get("cache_adjusted_input_tokens")
    right_value = right.get("cache_adjusted_input_tokens")
    available = isinstance(left_value, (int, float)) and isinstance(right_value, (int, float))
    return {
        "token_pair_valid": available,
        "left_cache_adjusted_input_tokens": left_value,
        "right_cache_adjusted_input_tokens": right_value,
        "cache_adjusted_delta_right_minus_left": (right_value - left_value) if available else None,
        "refusal_reason": None if available else "cache_adjusted_input_tokens unavailable for one or both rows",
        "left_raw_input_tokens_not_cache_adjusted_cost": left.get("input_tokens"),
        "right_raw_input_tokens_not_cache_adjusted_cost": right.get("input_tokens"),
    }


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _sum_field(rows: list[dict[str, Any]], key: str) -> int | float | None:
    values = [row.get(key) for row in rows if isinstance(row.get(key), (int, float))]
    return sum(values) if values else None


def _median_field(rows: list[dict[str, Any]], key: str) -> int | float | None:
    values = sorted(row.get(key) for row in rows if isinstance(row.get(key), (int, float)))
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def _bool_rate(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)


def _counter(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        out[key] = out.get(key, 0) + 1
    return out


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip().lstrip("./")
        if text and text not in seen:
            out.append(text)
            seen.add(text)
    return out


def _command_name(command_text: str) -> str:
    text = command_text.strip()
    if not text:
        return ""
    if text.startswith("/bin/") or text.startswith("/usr/bin/"):
        text = Path(text.split()[0]).name + text[len(text.split()[0]):]
    parts = re.split(r"\s+", text, maxsplit=1)
    name = parts[0].strip("'\"")
    if name in {"python", "python3", "env", "xcrun"} and len(parts) > 1:
        return name
    return Path(name).name


def _extract_paths(text: str) -> list[str]:
    return _dedupe(re.findall(r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)(?::\d+)?", text or ""))


def _looks_like_search_result(line: str) -> bool:
    return bool(re.match(r"^\s*[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+:\d+:", line or ""))
