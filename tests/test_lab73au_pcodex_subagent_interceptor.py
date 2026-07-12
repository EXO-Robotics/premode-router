from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import pcodex_bootstrap as pcodex
from premode.core_packet import CorePath, render_core_packet
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
        "TASK\n"
        f"{task}\n"
        "LIKELY FILES\n\nPRIMARY\n\n* src/example.py\n\n"
        "VERIFY\n\n* tests/test_example.py\n\n"
        "Start with these files. Expand only when required by the task.\n"
    )


def _decision() -> dict:
    return {
        "schema_version": "routing-decision.v1", "mode": "narrow", "confidence": "high",
        "primary_paths": ["src/example.py"], "verification_paths": ["tests/test_example.py"], "support_paths": [],
        "ambiguity_indicators": [], "decision_reasons": ["fixture"],
        "candidate_provenance": [
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
        "model_facing_sections": ["TASK", "LIKELY FILES", "PRIMARY", "VERIFY"],
        "routing_decision": _decision(),
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
    assert result.prompt.startswith("TASK\n")


def test_transform_uses_literal_symbol_by_default(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_alias_runner, dry_run=True)

    assert result.algorithm == "literal_symbol"


def test_injected_packet_or_shallow_decision_fails_raw_safe(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    def injected(_root: Path, prompt: str, _profile: str | None) -> dict:
        return {
            "packet": f"TASK\n{prompt}\nLIKELY FILES\n\nPRIMARY\n\n* .pcodex/config.toml\n",
            "routing_decision": {"mode": "narrow"},
        }

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=injected, dry_run=True)

    assert result.prompt == RAW_SUBAGENT_PROMPT
    assert result.transform_applied is False
    assert result.error == "invalid_routing_decision"


def test_narrow_decision_rejects_unevidenced_over_budget_support(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    for rel in ("src/app.py", "src/s1.py", "src/s2.py", "src/s3.py"):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n", encoding="utf-8")
    decision = _decision()
    decision["primary_paths"] = ["src/app.py"]
    decision["verification_paths"] = []
    decision["support_paths"] = ["src/s1.py", "src/s2.py", "src/s3.py"]
    decision["candidate_provenance"] = decision["candidate_provenance"][:1]
    decision["candidate_provenance"][0]["path"] = "src/app.py"
    packet = render_core_packet(
        RAW_SUBAGENT_PROMPT,
        [CorePath("src/app.py", "primary"), CorePath("src/s1.py", "support"), CorePath("src/s2.py", "support"), CorePath("src/s3.py", "support")],
    )

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=lambda *_args: {"packet": packet, "routing_decision": decision}, dry_run=True)

    assert result.prompt == RAW_SUBAGENT_PROMPT
    assert result.transform_applied is False


def test_explicit_generated_primary_preserves_generated_intent(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    path = repo / "dist/generated.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("export const value = 1;\n", encoding="utf-8")
    prompt = "Update generated code in dist/generated.js"
    decision = _decision()
    decision["primary_paths"] = ["dist/generated.js"]
    decision["verification_paths"] = []
    decision["candidate_provenance"] = decision["candidate_provenance"][:1]
    decision["candidate_provenance"][0]["path"] = "dist/generated.js"
    packet = render_core_packet(prompt, [CorePath("dist/generated.js", "primary")])

    result = transform_subagent_prompt(prompt, repo, compile_runner=lambda *_args: {"packet": packet, "routing_decision": decision}, dry_run=True)

    assert result.transform_applied is True
    assert "* dist/generated.js" in result.prompt


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
    assert "LIKELY FILES" in dispatcher.spawned_prompt


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
    assert result.error == "compile_failed"
    assert result.metadata["status"] == "compile_failed_raw_prompt"


def test_prompt_format_contains_only_allowed_packet_sections(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = transform_subagent_prompt(RAW_SUBAGENT_PROMPT, repo, compile_runner=_alias_runner, dry_run=True)

    for allowed in ("TASK\n", "LIKELY FILES", "PRIMARY", "VERIFY"):
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
    assert "/" + "Users/" not in source
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
    assert result.prompt.startswith("TASK\n")
    assert "\nLIKELY FILES\n" in result.prompt
    assert result.prompt.count(RAW_SUBAGENT_PROMPT) == 1
    assert "PREMODE_CONTEXT_PACKET" not in result.prompt
