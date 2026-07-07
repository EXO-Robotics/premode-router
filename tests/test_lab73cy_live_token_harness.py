from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import cli
from premode.compiler import compile_prompt
from premode.live_token_harness import (
    DEFAULT_PROMPT,
    LIVE_MATRIX_ENV,
    LIVE_SPEND_ENV,
    _usage_fields,
    parse_usage_file,
    run_live_token_harness,
)


FORBIDDEN_AGGREGATE_TERMS = (
    "pcodex smoke ok",
    "def message",
    "<TASK_CLASS>",
    "<SUPPORT_RELATIONS>",
    "confidence",
    "validation guidance",
)


def test_harness_entrypoint_is_discoverable() -> None:
    parser = cli.build_parser()

    help_text = parser.format_help()

    assert "lab" in help_text
    lab_action = next(action for action in parser._actions if getattr(action, "dest", None) == "command")
    assert "lab" in lab_action.choices
    lab_parser = lab_action.choices["lab"]
    lab_sub = next(action for action in lab_parser._actions if getattr(action, "dest", None) == "lab_command")
    assert "live-token-harness" in lab_sub.choices


def test_dry_run_mock_does_not_run_live_codex_and_isolates_lanes(tmp_path: Path, repo: Path) -> None:
    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path, mode="dry_run_mock", prompt=DEFAULT_PROMPT)

    standard = result["standard"]
    enhanced = result["enhanced"]

    assert result["live_codex_run"] is False
    assert result["mode"] == "dry_run_mock"
    assert standard["command"] == ["codex", "exec", "-"]
    assert "pcodex run --dry-run <prompt>" in enhanced["command"]
    assert result["repo_fixture"]["standard_repo"] != result["repo_fixture"]["enhanced_repo"]
    assert result["safety"]["repo_isolation_verified"] is True
    assert result["safety"]["home_isolation_verified"] is True
    assert result["safety"]["tmpdir_isolation_verified"] is True
    assert result["safety"]["codex_home_isolation_verified"] is True
    assert standard["usage_available"] is False
    assert enhanced["usage_available"] is False
    assert standard["usage_unavailable_reason"] == "dry_run_mock_no_live_codex"
    assert enhanced["usage_unavailable_reason"] == "dry_run_mock_no_live_codex"
    assert standard["tests_passed"] is True
    assert enhanced["tests_passed"] is True


def test_live_mode_refuses_without_explicit_env_flag(tmp_path: Path, repo: Path) -> None:
    result = run_live_token_harness(
        source_repo=repo,
        artifact_root=tmp_path,
        mode="live_minimal",
        env={},
    )

    assert result["live_codex_run"] is False
    assert result["quality"]["task_outcome"] == "blocked_before_live_spend"
    assert result["standard"]["usage_unavailable_reason"] == f"{LIVE_SPEND_ENV}_not_enabled"


def test_live_matrix_requires_second_env_flag(tmp_path: Path, repo: Path) -> None:
    result = run_live_token_harness(
        source_repo=repo,
        artifact_root=tmp_path,
        mode="live_matrix",
        env={LIVE_SPEND_ENV: "1"},
    )

    assert result["live_codex_run"] is False
    assert result["delta"]["conclusion"] == f"{LIVE_MATRIX_ENV}_not_enabled"


def test_standard_and_enhanced_lanes_use_same_prompt_hash(tmp_path: Path, repo: Path) -> None:
    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path, mode="dry_run_mock", prompt=DEFAULT_PROMPT)

    assert result["prompt_sha256"] == result["standard"]["prompt_sha256"]
    assert result["prompt_sha256"] == result["enhanced"]["prompt_sha256"]


def test_enhanced_lane_uses_current_pcodex_setup_path(tmp_path: Path, repo: Path) -> None:
    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path, mode="dry_run_mock")
    commands = result["enhanced"]["command"]

    assert commands[:4] == [
        "pcodex setup --skip-tune --no-mcp",
        "pcodex on",
        "pcodex first-run --json",
        "pcodex run --dry-run <prompt>",
    ]
    assert result["enhanced"]["pcodex_first_run_schema"] == "pcodex.first_run_receipt.v1"
    assert result["enhanced"]["pcodex_dry_run_status"] == "dry_run"
    assert result["enhanced"]["transform_applied"] is True


def test_usage_fields_parse_synthetic_codex_jsonl(tmp_path: Path) -> None:
    jsonl = tmp_path / "codex.jsonl"
    jsonl.write_text(
        '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":80,"output_tokens":10,"total_tokens":110}}\n',
        encoding="utf-8",
    )

    usage = parse_usage_file(jsonl)

    assert usage["usage_available"] is True
    assert usage["input_tokens"] == 100
    assert usage["cached_input_tokens"] == 80
    assert usage["output_tokens"] == 10
    assert usage["total_tokens"] == 110


def test_usage_fields_accept_pcodex_actual_usage_normalized_tokens() -> None:
    usage = _usage_fields(
        {
            "normalized_tokens": {
                "input_tokens": 140,
                "cached_input_tokens": 30,
                "output_tokens": 12,
                "total_tokens": 152,
            },
            "input_tokens_total": 140,
            "input_tokens_cached": 30,
        },
        source="pcodex_run_actual_usage",
    )

    assert usage["usage_available"] is True
    assert usage["usage_source"] == "pcodex_run_actual_usage"
    assert usage["input_tokens"] == 140
    assert usage["cached_input_tokens"] == 30
    assert usage["output_tokens"] == 12
    assert usage["total_tokens"] == 152
    assert usage["usage_unavailable_reason"] is None


def test_usage_fields_are_null_when_no_usage_source_exists(tmp_path: Path) -> None:
    jsonl = tmp_path / "codex.jsonl"
    jsonl.write_text('{"type":"message","text":"done"}\n', encoding="utf-8")

    usage = parse_usage_file(jsonl)

    assert usage["usage_available"] is False
    assert usage["input_tokens"] is None
    assert usage["cached_input_tokens"] is None
    assert usage["output_tokens"] is None
    assert usage["total_tokens"] is None
    assert usage["usage_unavailable_reason"] == "no_parseable_usage_fields"


def test_aggregate_result_omits_raw_prompt_and_source_snippets(tmp_path: Path, repo: Path) -> None:
    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path, mode="dry_run_mock", prompt=DEFAULT_PROMPT)
    aggregate = json.dumps(result, sort_keys=True)

    assert result["safety"]["raw_prompt_in_aggregate"] is False
    assert result["safety"]["raw_source_snippets_in_aggregate"] is False
    for forbidden in FORBIDDEN_AGGREGATE_TERMS:
        assert forbidden not in aggregate


def test_results_include_quality_and_safety_fields(tmp_path: Path, repo: Path) -> None:
    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path, mode="dry_run_mock")

    assert "quality" in result
    assert "safety" in result
    assert "scope_drift" in result["standard"]
    assert "review_patch_status" in result["enhanced"]
    assert result["delta"]["conclusion"] == "usage_unavailable"


def test_cleanup_removes_generated_state_from_enhanced_lane(tmp_path: Path, repo: Path) -> None:
    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path, mode="dry_run_mock")
    enhanced_repo = Path(result["repo_fixture"]["enhanced_repo"])

    assert result["enhanced"]["generated_state_written"] is True
    assert result["enhanced"]["cleanup_status"] == "cleaned"
    assert not (enhanced_repo / ".premode" / "out").exists()


def test_developer_source_repo_is_rejected_as_fixture(tmp_path: Path, repo: Path) -> None:
    with pytest.raises(ValueError):
        run_live_token_harness(source_repo=repo, artifact_root=tmp_path, fixture_repo=repo)


def test_literal_symbol_packet_contract_remains_model_facing_clean(repo: Path) -> None:
    (repo / "src" / "app.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    result = compile_prompt(
        repo,
        "Fix the failing test",
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
        record_artifacts=False,
    )

    packet = result["packet"]

    assert "PREMODE_CONTEXT_PACKET_V5" in packet
    for forbidden in ("TASK_CLASS", "SUPPORT_RELATIONS", "validation guidance", "do-not-edit", "confidence"):
        assert forbidden not in packet


def test_cli_live_token_harness_json_dry_run(tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(repo)

    rc = cli.main([
        "lab",
        "live-token-harness",
        "--mode",
        "dry_run_mock",
        "--artifact-root",
        str(tmp_path),
        "--json",
    ])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert rc == 0
    assert payload["schema_version"] == "premode.live_token_harness.result.v1"
    assert payload["live_codex_run"] is False
