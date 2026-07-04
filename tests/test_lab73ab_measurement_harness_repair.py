from __future__ import annotations

from premode.live_ledger import (
    aggregate_measurement_rows,
    command_ledger_from_events,
    normalize_token_usage,
    paired_cache_adjusted_delta,
    parse_jsonl_usage,
)


def _command_event(command: str, output: str = "", *, event_index_type: str = "item.completed") -> dict:
    return {
        "type": event_index_type,
        "timestamp": "2026-07-02T00:00:00Z",
        "item": {
            "type": "command_execution",
            "command": command,
            "exit_code": 0,
            "status": "completed",
            "stdout": output,
        },
    }


def _edit_event(path: str) -> dict:
    return {
        "type": "item.completed",
        "item": {
            "type": "file_change",
            "status": "completed",
            "changes": [{"path": path}],
        },
    }


def test_token_normalizer_explicit_uncached_fields_produce_explicit_cache_adjusted_cost() -> None:
    token = normalize_token_usage({"input_tokens": 1000, "cached_input_tokens": 600, "uncached_input_tokens": 400, "output_tokens": 70})

    assert token["token_derivation_status"] == "explicit"
    assert token["uncached_input_tokens"] == 400
    assert token["derived_uncached_input_tokens"] is None
    assert token["cache_adjusted_input_tokens"] == 460
    assert token["raw_token_fields"]["input_tokens"] == 1000


def test_token_normalizer_derives_only_when_schema_semantics_confirmed() -> None:
    unavailable = normalize_token_usage({"input_tokens": 1000, "cached_input_tokens": 600})
    derived = normalize_token_usage(
        {"input_tokens": 1000, "cached_input_tokens": 600},
        input_tokens_are_total=True,
        cached_input_tokens_are_subset=True,
    )

    assert unavailable["token_derivation_status"] == "unavailable"
    assert unavailable["cache_adjusted_input_tokens"] is None
    assert derived["token_derivation_status"] == "derived"
    assert derived["derived_uncached_input_tokens"] == 400
    assert derived["cache_adjusted_input_tokens"] == 460


def test_token_normalizer_missing_or_invalid_fields() -> None:
    missing = normalize_token_usage({"input_tokens": 1000})
    invalid = normalize_token_usage(
        {"input_tokens": 100, "cached_input_tokens": 200},
        input_tokens_are_total=True,
        cached_input_tokens_are_subset=True,
    )

    assert missing["token_derivation_status"] == "unavailable"
    assert invalid["token_derivation_status"] == "invalid"
    assert invalid["cache_adjusted_input_tokens"] is None


def test_parse_jsonl_usage_preserves_raw_usage_events_and_derives_for_confirmed_turn_completed(tmp_path) -> None:
    path = tmp_path / "stdout.jsonl"
    path.write_text(
        '{"type":"turn.completed","usage":{"input_tokens":1000,"cached_input_tokens":600,"output_tokens":70,"reasoning_output_tokens":5}}\n',
        encoding="utf-8",
    )

    usage = parse_jsonl_usage(path)

    assert usage["usage_event_count"] == 1
    assert usage["token_derivation_status"] == "derived"
    assert usage["derived_uncached_input_tokens"] == 400
    assert usage["cache_adjusted_input_tokens"] == 460
    assert usage["raw_usage_events_sample"]
    assert usage["raw_jsonl_path"] == str(path)


def test_cat_and_sed_count_as_repo_file_reads() -> None:
    ledger = command_ledger_from_events([
        _command_event("cat src/foo.py"),
        _command_event("sed -n '1,80p' src/bar.py"),
    ])

    assert ledger["explicit_repo_file_reads"] == ["src/foo.py", "src/bar.py"]
    assert ledger["explicit_file_read_count"] == 2
    assert ledger["first_repo_file_read"] == "src/foo.py"


def test_rg_is_search_not_explicit_file_read_and_search_hits_are_preserved() -> None:
    ledger = command_ledger_from_events([
        _command_event("rg foo src/", "src/foo.py:12:def foo():\n"),
    ])

    assert ledger["search_commands"] == 1
    assert ledger["explicit_repo_file_reads"] == []
    assert ledger["search_hits"] == ["src/foo.py"]


def test_stacktrace_and_import_error_are_references_not_reads() -> None:
    output = 'Traceback (most recent call last):\n  File "src/foo.py", line 2, in <module>\nModuleNotFoundError: No module named "bar"\n'
    ledger = command_ledger_from_events([
        _command_event("pytest tests/test_foo.py", output),
    ])

    assert ledger["validation_commands"] == 1
    assert ledger["explicit_repo_file_reads"] == []
    assert "src/foo.py" in ledger["import_or_stacktrace_references"]
    assert "tests/test_foo.py" in ledger["validation_targets"]


def test_memory_file_reads_are_separated_from_repo_file_reads() -> None:
    ledger = command_ledger_from_events([
        _command_event("cat /Users/example/.codex/memories/MEMORY.md"),
        _command_event("cat src/foo.py"),
    ])

    assert ledger["memory_file_reads"] == ["Users/example/.codex/memories/MEMORY.md"]
    assert ledger["explicit_repo_file_reads"] == ["src/foo.py"]


def test_validation_commands_include_common_test_tools() -> None:
    ledger = command_ledger_from_events([
        _command_event("pytest tests/test_foo.py"),
        _command_event("npm test"),
        _command_event("cargo test"),
        _command_event("go test ./..."),
        _command_event("xcodebuild test -scheme App"),
    ])

    assert ledger["validation_commands"] == 5
    assert ledger["build_or_parse_commands"] == 0


def test_first_repo_file_read_and_first_edit_canaries() -> None:
    ledger = command_ledger_from_events([
        _command_event("rg foo src/", "src/foo.py:12:def foo():\n"),
        _command_event("cat src/foo.py"),
        _edit_event("src/foo.py"),
    ])

    assert ledger["first_repo_file_read"] == "src/foo.py"
    assert ledger["first_file_edited"] == "src/foo.py"


def test_aggregate_pair_comparison_refuses_unavailable_cache_adjusted_tokens() -> None:
    left = {"lane": "a", "input_tokens": 1000, "cached_input_tokens": 600, "cache_adjusted_input_tokens": None, "token_derivation_status": "unavailable"}
    right = {"lane": "b", "input_tokens": 900, "cached_input_tokens": 500, "cache_adjusted_input_tokens": None, "token_derivation_status": "unavailable"}

    pair = paired_cache_adjusted_delta(left, right)
    aggregate = aggregate_measurement_rows([left, right])

    assert pair["token_pair_valid"] is False
    assert pair["cache_adjusted_delta_right_minus_left"] is None
    assert pair["left_raw_input_tokens_not_cache_adjusted_cost"] == 1000
    assert aggregate["cache_adjusted_available_count"] == 0
    assert aggregate["unavailable_token_rows"] == 2
