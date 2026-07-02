from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any


DEFAULT_CACHE_ADJUSTMENT_FACTOR = 0.10


def cache_adjusted_input_tokens(
    input_tokens_uncached: int | None,
    input_tokens_cached: int | None,
    *,
    cache_adjustment_factor: float = DEFAULT_CACHE_ADJUSTMENT_FACTOR,
) -> float | None:
    if input_tokens_uncached is None or input_tokens_cached is None:
        return None
    return float(input_tokens_uncached) + float(cache_adjustment_factor) * float(input_tokens_cached)


def normalize_token_ledger(raw: dict[str, Any] | None = None, *, cache_adjustment_factor: float = DEFAULT_CACHE_ADJUSTMENT_FACTOR) -> dict[str, Any]:
    raw = raw or {}
    total = _int_or_none(raw.get("input_tokens_total") or raw.get("input_tokens"))
    cached = _int_or_none(raw.get("input_tokens_cached") or raw.get("cached_input_tokens"))
    uncached = _int_or_none(raw.get("input_tokens_uncached") or raw.get("uncached_input_tokens"))
    if uncached is None and total is not None and cached is not None:
        uncached = max(0, total - cached)
    return {
        "input_tokens_total": total,
        "input_tokens_uncached": uncached,
        "input_tokens_cached": cached,
        "output_tokens": _int_or_none(raw.get("output_tokens")),
        "reasoning_output_tokens": _int_or_none(raw.get("reasoning_output_tokens")),
        "cache_adjusted_input_tokens": cache_adjusted_input_tokens(uncached, cached, cache_adjustment_factor=cache_adjustment_factor),
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
        "explicit_file_reads": [],
        "explicit_file_read_count": 0,
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
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = event.get("usage") if isinstance(event, dict) else None
        if isinstance(usage, dict):
            token_data.update(usage)
    return normalize_token_ledger(token_data)


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
    for event in events:
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        event_type = str(event.get("type") or "")
        item_type = str(item.get("type") or "")
        if item_type == "command_execution" and event_type.endswith(".completed"):
            command = str(item.get("command") or "").strip()
            if command:
                records.append({
                    "kind": "command",
                    "command": command,
                    "category": classify_command(command),
                    "exit_code": item.get("exit_code"),
                    "status": item.get("status"),
                    "output_text": _event_output_text(item),
                })
        elif item_type == "file_change" and event_type.endswith(".completed"):
            changes = item.get("changes") if isinstance(item.get("changes"), list) else []
            label = ", ".join(str(change.get("path") or "") for change in changes if isinstance(change, dict) and change.get("path"))
            records.append({
                "kind": "edit",
                "command": f"file_change: {label}" if label else "file_change",
                "category": "edit_commands",
                "exit_code": 0,
                "status": item.get("status"),
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
    memory_query_terms: list[str] = []
    for index, record in enumerate(records):
        command = str(record.get("command") or "")
        category = str(record.get("category") or "other_commands")
        raw_commands.append(command)
        ledger[category] = int(ledger.get(category) or 0) + 1
        counts[command] = counts.get(command, 0) + 1
        memory_info = memory_command_info(command, str(record.get("output_text") or ""))
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
            explicit_reads.extend(extract_explicit_file_reads_from_command(command))
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
    ledger["explicit_file_reads"] = _dedupe(explicit_reads)
    ledger["explicit_file_read_count"] = len(ledger["explicit_file_reads"])
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


def extract_explicit_file_reads_from_command(command: str) -> list[str]:
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
    if name in {"rg", "grep"}:
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
    if " - << " in lower or " - <<" in lower:
        return any(token in lower for token in ("read_text", "open(", ".read(", "json.load", "tomllib.load"))
    return False


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


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


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
