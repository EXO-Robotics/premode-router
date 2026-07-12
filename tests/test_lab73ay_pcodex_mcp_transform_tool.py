from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import pcodex_bootstrap as pcodex
from premode import pcodex_mcp


RAW_PROMPT = "Investigate failing import in src/example.py"


def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PCODEX_ENABLED", raising=False)
    monkeypatch.delenv("PCODEX_ALGORITHM", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG_PATH", raising=False)


def _packet(task: str) -> str:
    return (
        "TASK\n"
        f"{task}\n"
        "LIKELY FILES\n\nPRIMARY\n\n* src/example.py\n\n"
        "VERIFY\n\n* tests/test_example.py\n\n"
        "Start with these files. Expand only when required by the task.\n"
    )


def _decision(*, abstain: bool = False) -> dict:
    primary = [] if abstain else ["src/example.py"]
    return {
        "schema_version": "routing-decision.v1", "mode": "abstain" if abstain else "narrow", "confidence": "low" if abstain else "high",
        "primary_paths": primary, "verification_paths": [] if abstain else ["tests/test_example.py"], "support_paths": [],
        "ambiguity_indicators": ["fixture_abstain"] if abstain else [], "decision_reasons": ["fixture"],
        "candidate_provenance": [] if abstain else [
            {"schema_version": "candidate-evidence.v1", "path": "src/example.py", "role": "primary", "rank": 0, "score": 10, "confidence": "high", "matched_signals": ["explicit_path:src/example.py"], "provenance": ["fixture"]},
            {"schema_version": "candidate-evidence.v1", "path": "tests/test_example.py", "role": "verification", "rank": 1, "score": 8, "confidence": "high", "matched_signals": ["source_test_relation:src/example.py"], "provenance": ["fixture"]},
        ],
    }


def _alias_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
    return {
        "status": "compiled",
        "route": "plugin_alias",
        "premode_command": ["premode", "compile", prompt, "--repo", str(project_root), "--plugin", "literal_symbol"],
        "packet": _packet(prompt),
        "packet_sha256": "abc123",
        "model_facing_sections": ["TASK", "LIKELY FILES", "PRIMARY", "VERIFY"],
        "routing_decision": _decision(),
    }


def _fallback_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
    return {
        "status": "compiled",
        "route": "explicit_fallback",
        "premode_command": [
            "premode",
            "compile",
            prompt,
            "--packet-version",
            "v5",
            "--packet-variant",
            "tool_assisted_anchors_internal",
            "--packet-strategy",
            "literal_symbol",
        ],
        "packet": _packet(prompt),
        "packet_sha256": "fallback123",
        "model_facing_sections": ["TASK", "LIKELY FILES", "PRIMARY", "VERIFY"],
        "routing_decision": _decision(),
    }


def _abstain_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
    return {
        "status": "compiled",
        "route": "plugin_alias",
        "packet": prompt,
        "packet_sha256": "abstain123",
        "routing_decision": _decision(abstain=True),
    }


def test_tool_function_accepts_subagent_prompt(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    assert result.enabled is True
    assert result.algorithm == "literal_symbol"
    assert result.transformed_prompt != RAW_PROMPT


def test_tool_function_preserves_raw_prompt(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    assert RAW_PROMPT in result.transformed_prompt
    assert result.metadata["input_prompt_preserved"] is True


def test_tool_function_returns_raw_prompt_when_disabled(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    assert result.enabled is False
    assert result.transformed_prompt == RAW_PROMPT


def test_mcp_abstention_is_exact_raw_prompt_with_no_selected_paths(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_abstain_runner,
    )

    assert result.transformed_prompt == RAW_PROMPT
    assert result.transform_applied is False
    assert result.metadata["routing_mode"] == "abstain"
    assert result.metadata["selected_paths"] == []
    assert result.metadata["packet_path"] is None


def test_tool_function_returns_raw_prompt_with_error_on_compile_failure(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    def failing_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
        raise RuntimeError("compile unavailable")

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=failing_runner,
    )

    assert result.transformed_prompt == RAW_PROMPT
    assert result.error == "compile_failed"
    assert result.metadata["error_status"] == "compile_failed_raw_prompt"


def test_tool_result_reports_allowed_model_facing_sections_only(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    assert result.metadata["model_facing_sections"] == [
        "TASK",
        "LIKELY FILES",
        "PRIMARY",
        "VERIFY",
    ]


def test_tool_result_does_not_expose_diagnostics_or_forbidden_sections(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    for required in ("TASK\n", "LIKELY FILES", "PRIMARY", "VERIFY"):
        assert required in result.transformed_prompt
    for forbidden in (
        "TASK_CLASS",
        "SUPPORT_RELATIONS",
        "<FILE ",
        "snippets",
        "diagnostics",
        "CONFIDENCE",
        "VALIDATION",
        "COMMANDS",
        "DO_NOT_EDIT",
    ):
        assert forbidden not in result.transformed_prompt


def test_tool_result_does_not_print_secrets(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-appear")
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-appear")
    pcodex.set_enabled(repo, True)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )
    captured = capsys.readouterr()
    text = captured.out + captured.err + json.dumps(result.as_dict())

    assert "should-not-appear" not in text
    assert "OPENAI_API_KEY" not in text
    assert "GITHUB_TOKEN" not in text


def test_tool_supports_fake_compile_runner_injection(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    calls: list[str] = []

    def runner(project_root: Path, prompt: str, profile: str | None) -> dict:
        calls.append(prompt)
        return _fallback_runner(project_root, prompt, profile)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=runner,
    )

    assert calls == [RAW_PROMPT]
    assert result.used_fallback is True


def test_spawn_agent_payload_adapter_extracts_prompt_and_transforms(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    payload = {"type": "spawnAgent", "prompt": RAW_PROMPT, "metadata": {"agent_kind": "analysis"}}

    transformed = pcodex_mcp.transform_spawn_agent_payload(
        payload,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    assert transformed["prompt"] != RAW_PROMPT
    assert RAW_PROMPT in str(transformed["prompt"])
    assert transformed["pcodex"]["status"] == "transformed"


def test_spawn_agent_adapter_preserves_unknown_fields(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    payload = {"type": "spawnAgent", "prompt": RAW_PROMPT, "priority": "low", "unknown": {"x": 1}}

    transformed = pcodex_mcp.transform_spawn_agent_payload(
        payload,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    assert transformed["priority"] == "low"
    assert transformed["unknown"] == {"x": 1}
    assert payload["prompt"] == RAW_PROMPT


def test_collab_agent_tool_call_adapter_transforms_nested_prompt(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    payload = {"type": "collabAgentToolCall", "tool": "spawnAgent", "arguments": {"prompt": RAW_PROMPT, "model": "mock"}}

    transformed = pcodex_mcp.transform_collab_agent_tool_call_payload(
        payload,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    arguments = transformed["arguments"]
    assert isinstance(arguments, dict)
    assert arguments["prompt"] != RAW_PROMPT
    assert RAW_PROMPT in arguments["prompt"]
    assert arguments["model"] == "mock"


def test_collab_agent_tool_call_adapter_preserves_top_level_prompt_shape(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    payload = {"type": "collabAgentToolCall", "tool": "spawnAgent", "prompt": RAW_PROMPT, "id": "call-1"}

    transformed = pcodex_mcp.transform_collab_agent_tool_call_payload(
        payload,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    assert transformed["id"] == "call-1"
    assert transformed["prompt"] != RAW_PROMPT
    assert RAW_PROMPT in str(transformed["prompt"])


def test_unsupported_payloads_fail_safely() -> None:
    payload = {"type": "collabAgentToolCall", "tool": "sendInput", "arguments": {"prompt": RAW_PROMPT}}

    transformed = pcodex_mcp.transform_collab_agent_tool_call_payload(payload, dry_run=True)

    assert transformed["arguments"] == payload["arguments"]
    assert transformed["pcodex"]["status"] == "unsupported_payload"
    assert transformed["pcodex"]["enabled"] is False


def test_payload_adapter_adds_pcodex_metadata_out_of_band(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    payload = {"type": "spawnAgent", "prompt": RAW_PROMPT}

    transformed = pcodex_mcp.transform_spawn_agent_payload(
        payload,
        project_root=repo,
        dry_run=True,
        compile_runner=_alias_runner,
    )

    assert "pcodex" in transformed
    assert "pcodex" not in str(transformed["prompt"])
    assert transformed["pcodex"]["algorithm"] == "literal_symbol"


def test_tool_schema_is_safe_and_minimal() -> None:
    assert pcodex_mcp.TOOL_NAME == "pcodex_transform_subagent_prompt"
    assert pcodex_mcp.TOOL_INPUT_SCHEMA["required"] == ["subagent_prompt"]
    assert pcodex_mcp.TOOL_INPUT_SCHEMA["additionalProperties"] is False
    assert "environment" not in pcodex_mcp.TOOL_INPUT_SCHEMA["properties"]
    assert "secrets" not in json.dumps(pcodex_mcp.TOOL_INPUT_SCHEMA).lower()


def test_no_lab_or_user_paths_are_baked_into_product_code() -> None:
    source = Path(pcodex_mcp.__file__).read_text(encoding="utf-8")

    assert "/private/tmp" not in source
    assert "/" + "Users/" not in source
    assert "premode_labs" not in source


def test_tests_do_not_depend_on_lab_artifacts() -> None:
    source = Path(__file__).read_text(encoding="utf-8")

    assert "premode" + "_labs/" not in source
    assert "/private" + "/tmp/" not in source
