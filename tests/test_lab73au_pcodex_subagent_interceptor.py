from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import pcodex_bootstrap as pcodex
from premode.pcodex_subagent import transform_subagent_prompt


RAW_SUBAGENT_PROMPT = "Investigate failing import in src/example.py and report likely fix."


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
        "PREMODE_CONTEXT_PACKET_V5\n"
        "schema: ranked-paths-plus-anchors\n"
        "format_version: 1\n"
        "<TASK>\n"
        f"{task}\n"
        "</TASK>\n"
        "<PRIMARY_FILES>\n"
        "1. src/example.py\n"
        "   anchors: symbol=load_example\n"
        "</PRIMARY_FILES>\n"
        "<RELATED_TESTS>\n"
        "1. tests/test_example.py\n"
        "   anchors: test_name=test_load_example\n"
        "</RELATED_TESTS>\n"
        "<END_PREMODE_CONTEXT_PACKET_V5>\n"
    )


def _alias_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
    return {
        "status": "compiled",
        "route": "plugin_alias",
        "premode_command": ["premode", "compile", prompt, "--repo", str(project_root), "--plugin", "literal_symbol"],
        "packet": _packet(prompt),
        "packet_sha256": "abc123",
        "model_facing_sections": ["TASK", "PRIMARY_FILES", "RELATED_TESTS", "END_PREMODE_CONTEXT_PACKET_V5"],
    }


def _fallback_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
    return {
        "status": "compiled",
        "route": "explicit_fallback",
        "premode_command": [
            "premode",
            "compile",
            prompt,
            "--repo",
            str(project_root),
            "--packet-version",
            "v5",
            "--packet-variant",
            "tool_assisted_anchors_internal",
            "--packet-strategy",
            "literal_symbol",
        ],
        "packet": _packet(prompt),
        "packet_sha256": "fallback123",
        "model_facing_sections": ["TASK", "PRIMARY_FILES", "RELATED_TESTS", "END_PREMODE_CONTEXT_PACKET_V5"],
    }


def test_disabled_pcodex_returns_raw_subagent_prompt(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_alias_runner)

    assert result.enabled is False
    assert result.prompt == RAW_SUBAGENT_PROMPT
    assert result.packet_path is None


def test_enabled_pcodex_transforms_codex_created_subagent_prompt(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_alias_runner, dry_run=True)

    assert result.enabled is True
    assert result.prompt != RAW_SUBAGENT_PROMPT
    assert RAW_SUBAGENT_PROMPT in result.prompt
    assert "PREMODE_CONTEXT_PACKET_V5" in result.prompt


def test_transform_uses_literal_symbol_by_default(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_alias_runner, dry_run=True)

    assert result.algorithm == "literal_symbol"


def test_transform_calls_preferred_alias_route(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_alias_runner, dry_run=True)

    assert result.route == "plugin_alias"
    assert result.metadata["premode_command"][-2:] == ["--plugin", "literal_symbol"]


def test_transform_can_fallback_to_explicit_literal_symbol_route(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_fallback_runner, dry_run=True)

    assert result.used_fallback is True
    assert "--packet-variant" in result.metadata["premode_command"]
    assert "tool_assisted_anchors_internal" in result.metadata["premode_command"]


class FakeCodexDispatcher:
    def __init__(self) -> None:
        self.spawned_prompt: str | None = None

    def build_subagent_prompt(self) -> str:
        return RAW_SUBAGENT_PROMPT

    def spawn_subagent(self, prompt: str) -> None:
        self.spawned_prompt = prompt


def test_fake_codex_dispatcher_receives_transformed_prompt(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    dispatcher = FakeCodexDispatcher()

    raw_prompt = dispatcher.build_subagent_prompt()
    result = transform_subagent_prompt(raw_prompt, repo, compile_runner=_alias_runner, dry_run=True)
    dispatcher.spawn_subagent(result.prompt)

    assert dispatcher.spawned_prompt is not None
    assert dispatcher.spawned_prompt != raw_prompt
    assert raw_prompt in dispatcher.spawned_prompt
    assert "<PRIMARY_FILES>" in dispatcher.spawned_prompt


def test_fake_dispatcher_never_launches_live_codex(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    dispatcher = FakeCodexDispatcher()

    result = transform_subagent_prompt(dispatcher.build_subagent_prompt(), repo, compile_runner=_alias_runner, dry_run=True)

    assert result.metadata["dry_run"] is True
    assert dispatcher.spawned_prompt is None


def test_compile_failure_returns_raw_prompt_with_error_metadata(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    def failing_runner(project_root: Path, prompt: str, profile: str | None) -> dict:
        raise RuntimeError("compile unavailable")

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=failing_runner, dry_run=True)

    assert result.prompt == RAW_SUBAGENT_PROMPT
    assert result.error == "RuntimeError: compile unavailable"
    assert result.metadata["status"] == "compile_failed_raw_prompt"


def test_prompt_format_contains_only_allowed_packet_sections(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_alias_runner, dry_run=True)

    for allowed in ("<TASK>", "<PRIMARY_FILES>", "<RELATED_TESTS>", "<END_PREMODE_CONTEXT_PACKET_V5>"):
        assert allowed in result.prompt
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
        assert forbidden not in result.prompt


def test_no_secrets_or_full_env_are_printed(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-appear")
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-appear")
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_alias_runner, dry_run=True)
    text = json.dumps(result.__dict__)

    assert "should-not-appear" not in text
    assert "OPENAI_API_KEY" not in text
    assert "GITHUB_TOKEN" not in text


def test_no_lab_or_user_paths_are_baked_into_product_code() -> None:
    source = Path(__import__("premode.pcodex_subagent").pcodex_subagent.__file__).read_text(encoding="utf-8")

    assert "/private/tmp" not in source
    assert "/Users/" not in source
    assert "premode_labs" not in source


def test_real_compile_dry_run_integration_does_not_launch_codex(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "example.py").write_text("def load_example():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_example.py").write_text("from src.example import load_example\n", encoding="utf-8")
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, dry_run=True)

    assert result.enabled is True
    assert result.prompt != RAW_SUBAGENT_PROMPT
    assert RAW_SUBAGENT_PROMPT in result.prompt
    assert "PREMODE_CONTEXT_PACKET_V5" in result.prompt
