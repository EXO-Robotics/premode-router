from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import pcodex_bootstrap as pcodex
from premode import pcodex_mcp
from premode import pcodex_mcp_server


RAW_PROMPT = "Investigate failing import in src/example.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DOC = REPO_ROOT / "docs" / "pcodex" / "CODEX_TOOL_CONFIGURATION.md"
CONTRACT_DOC = REPO_ROOT / "docs" / "pcodex" / "SUBAGENT_ROUTING_CONTRACT.md"


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


def _alias_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
    return {
        "status": "compiled",
        "route": "plugin_alias",
        "premode_command": ["premode", "compile", prompt, "--plugin", "literal_symbol"],
        "packet": _packet(prompt),
        "packet_sha256": "abc123",
        "model_facing_sections": ["TASK", "PRIMARY_FILES", "RELATED_TESTS", "END_PREMODE_CONTEXT_PACKET_V5"],
        "routing_decision": {"schema_version": "routing-decision.v1", "mode": "narrow", "confidence": "high", "primary_paths": ["src/example.py"], "verification_paths": ["tests/test_example.py"], "support_paths": [], "ambiguity_indicators": [], "decision_reasons": ["fixture"], "candidate_provenance": [{"schema_version": "candidate-evidence.v1", "path": "src/example.py", "role": "primary", "rank": 0, "score": 10, "confidence": "high", "matched_signals": ["explicit_path:src/example.py"], "provenance": ["fixture"]}, {"schema_version": "candidate-evidence.v1", "path": "tests/test_example.py", "role": "verification", "rank": 1, "score": 8, "confidence": "high", "matched_signals": ["source_test_relation:src/example.py"], "provenance": ["fixture"]}]},
    }


def test_pcodex_mcp_server_command_is_registered() -> None:
    help_text = pcodex._parser().format_help()

    assert "mcp-server" not in help_text
    assert pcodex.main(["mcp-server", "--help"]) == 0


def test_server_lists_pcodex_transform_tool() -> None:
    response = pcodex_mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response["result"]["tools"][0]["name"] == "pcodex_transform_subagent_prompt"
    assert response["result"]["tools"][0]["inputSchema"]["required"] == ["subagent_prompt"]


def test_server_handles_valid_transform_call(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    response = pcodex_mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "pcodex_transform_subagent_prompt",
                "arguments": {"subagent_prompt": RAW_PROMPT, "dry_run": True},
            },
        },
        cwd=repo,
        compile_runner=_alias_runner,
    )

    result = response["result"]["structuredContent"]
    assert result["enabled"] is True
    assert result["transformed_prompt"] != RAW_PROMPT
    assert RAW_PROMPT in result["transformed_prompt"]


def test_server_preserves_raw_prompt(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex_mcp_server.call_tool(
        "pcodex_transform_subagent_prompt",
        {"subagent_prompt": RAW_PROMPT, "dry_run": True},
        cwd=repo,
        compile_runner=_alias_runner,
    )["structuredContent"]

    assert result["metadata"]["input_prompt_preserved"] is True
    assert RAW_PROMPT in result["transformed_prompt"]


def test_server_returns_raw_prompt_when_disabled(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex_mcp_server.call_tool(
        "pcodex_transform_subagent_prompt",
        {"subagent_prompt": RAW_PROMPT, "dry_run": True},
        cwd=repo,
        compile_runner=_alias_runner,
    )["structuredContent"]

    assert result["enabled"] is False
    assert result["transformed_prompt"] == RAW_PROMPT


def test_server_returns_raw_prompt_plus_error_on_compile_failure(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    def failing_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
        raise RuntimeError("compile unavailable")

    result = pcodex_mcp_server.call_tool(
        "pcodex_transform_subagent_prompt",
        {"subagent_prompt": RAW_PROMPT, "dry_run": True},
        cwd=repo,
        compile_runner=failing_runner,
    )["structuredContent"]

    assert result["transformed_prompt"] == RAW_PROMPT
    assert result["error"] == "compile_failed"
    assert result["metadata"]["error_status"] == "compile_failed_raw_prompt"


def test_server_rejects_unsupported_tool_names_safely() -> None:
    response = pcodex_mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "unknown_tool", "arguments": {}},
        }
    )

    assert response["error"]["code"] == -32000
    assert "unsupported tool" in response["error"]["message"]


def test_server_never_returns_raw_internal_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sensitive-runtime-detail"

    def fail_tool(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(pcodex_mcp_server, "pcodex_transform_subagent_prompt_tool", fail_tool)
    response = pcodex_mcp_server.handle_request(
        {
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "pcodex_transform_subagent_prompt", "arguments": {"subagent_prompt": RAW_PROMPT}},
        }
    )

    assert response["error"] == {"code": -32603, "message": "internal tool error"}
    assert secret not in json.dumps(response)


def test_server_rejects_invalid_json_safely() -> None:
    response = pcodex_mcp_server.handle_line("{not json")

    assert response["error"]["code"] == -32700
    assert "invalid JSON" in response["error"]["message"]


def test_server_emits_json_only_and_no_secret_env_dump(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-appear")
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-appear")
    pcodex.set_enabled(repo, True)

    response = pcodex_mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "pcodex_transform_subagent_prompt",
                "arguments": {"subagent_prompt": RAW_PROMPT, "dry_run": True},
            },
        },
        cwd=repo,
        compile_runner=_alias_runner,
    )
    encoded = json.dumps(response, sort_keys=True)
    captured = capsys.readouterr()

    assert json.loads(encoded)
    assert captured.out == ""
    assert captured.err == ""
    assert "should-not-appear" not in encoded
    assert "OPENAI_API_KEY" not in encoded
    assert "GITHUB_TOKEN" not in encoded


def test_server_does_not_launch_live_codex(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    calls: list[str] = []

    def runner(project_root: Path, prompt: str, profile: str | None) -> dict:
        calls.append(prompt)
        return _alias_runner(project_root, prompt, profile)

    pcodex_mcp_server.call_tool(
        "pcodex_transform_subagent_prompt",
        {"subagent_prompt": RAW_PROMPT, "dry_run": True},
        cwd=repo,
        compile_runner=runner,
    )

    assert calls == [RAW_PROMPT]


def test_server_rejects_model_selected_project_root(repo: Path) -> None:
    with pytest.raises(ValueError, match="server-bound"):
        pcodex_mcp_server.call_tool(
            "pcodex_transform_subagent_prompt",
            {"subagent_prompt": RAW_PROMPT, "project_root": "/"},
            cwd=repo,
            compile_runner=_alias_runner,
        )


def test_tool_schema_does_not_expose_project_root() -> None:
    assert "project_root" not in pcodex_mcp.TOOL_INPUT_SCHEMA["properties"]


def test_server_uses_pcodex_mcp_tool_function(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_tool(subagent_prompt: str, **kwargs: object) -> pcodex_mcp.PcodexToolResult:
        calls.append(subagent_prompt)
        return pcodex_mcp.PcodexToolResult(
            transformed_prompt=subagent_prompt,
            enabled=False,
            algorithm="literal_symbol",
            used_fallback=False,
            error=None,
            metadata={"input_prompt_preserved": True, "model_facing_sections": pcodex_mcp.MODEL_FACING_SECTIONS},
        )

    monkeypatch.setattr(pcodex_mcp_server, "pcodex_transform_subagent_prompt_tool", fake_tool)

    response = pcodex_mcp_server.call_tool(
        "pcodex_transform_subagent_prompt",
        {"subagent_prompt": RAW_PROMPT, "dry_run": True},
    )

    assert calls == [RAW_PROMPT]
    assert response["structuredContent"]["algorithm"] == "literal_symbol"


def test_config_docs_mention_pcodex_mcp_server() -> None:
    text = CONFIG_DOC.read_text(encoding="utf-8")

    assert "pcodex mcp-server" in text
    assert "pcodex_transform_subagent_prompt" in text
    assert "codex mcp add" in text


def test_config_docs_label_unverified_enforcement_as_candidate() -> None:
    text = CONFIG_DOC.read_text(encoding="utf-8")

    assert "configuration candidate" in text
    assert "does not prove installed Codex calls the tool before subagent dispatch" in text
    assert "Do not claim pCodex automatically controls hosted/internal Codex subagents" in text


def test_config_docs_avoid_hosted_ui_patch_claims() -> None:
    combined = CONFIG_DOC.read_text(encoding="utf-8") + "\n" + CONTRACT_DOC.read_text(encoding="utf-8")

    assert "Do not patch hosted Codex/Web UI" in combined
    assert "hosted Codex/Web UI is supported" not in combined
    assert "controls all hosted/internal subagents" not in combined


def test_config_docs_do_not_include_lab_source_paths() -> None:
    combined = CONFIG_DOC.read_text(encoding="utf-8") + "\n" + CONTRACT_DOC.read_text(encoding="utf-8")

    assert "premode" + "_labs/" not in combined
    assert "/private" + "/tmp/" not in combined


def test_server_source_has_no_network_listener_or_user_paths() -> None:
    source = Path(pcodex_mcp_server.__file__).read_text(encoding="utf-8")

    assert "socket" not in source
    assert "http.server" not in source
    assert "/" + "Users/" not in source
    assert "/private/tmp" not in source
