from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from premode import pcodex_bootstrap as pcodex
from premode import pcodex_mcp
from premode import pcodex_mcp_server
from premode import pcodex_state
from premode import tuning
from premode.compiler import compile_prompt


RAW_PROMPT = "Hypothetical dummy task: inspect login flow. Do not modify files."
MODEL_FACING_SECTIONS = ["TASK", "LIKELY FILES", "PRIMARY", "VERIFY"]


LITERAL_SYMBOL_KWARGS = {
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
    "record_artifacts": False,
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "synthetic_repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    _write(repo / "src" / "auth" / "login.py", "def login_user(name):\n    return name.strip()\n")
    _write(repo / "src" / "client.py", "def client_entrypoint():\n    return 'client'\n")
    _write(repo / "tests" / "test_login.py", "def test_login_user():\n    assert True\n")
    return repo


def _generate_tuning(repo: Path) -> Path:
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"
    _write_json(
        repo / ".premode" / "tuning" / "VERIFY_RESULTS.json",
        {
            "schema_version": "pcodex.tuning_verify.v1",
            "status": "verified",
            "verdict": "PASS",
            "profile_validation_status": "PASS",
            "evaluation_prompt_count": 1,
            "general": {"packet_token_estimate": 100},
            "tuned": {"packet_token_estimate": 80},
            "delta": {"packet_token_estimate_change": -20},
            "packet_boundary_safe": True,
            "profile_validation_failures": [],
            "notes": [],
            "rows": [],
            "artifacts": {
                "VERIFY_REPORT": ".premode/tuning/VERIFY_REPORT.md",
                "VERIFY_RESULTS": ".premode/tuning/VERIFY_RESULTS.json",
            },
        },
    )
    return repo / ".premode" / "tuning" / "repo_profile.json"


def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PCODEX_ENABLED", raising=False)
    monkeypatch.delenv("PCODEX_ALGORITHM", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG_PATH", raising=False)


def _packet(task: str, marker: str = "generalized") -> str:
    return (
        "TASK\n"
        f"{task}\n"
        "LIKELY FILES\n\nPRIMARY\n\n* src/auth/login.py\n\n"
        "VERIFY\n\n* tests/test_login.py\n\n"
        "Start with these files. Expand only when required by the task.\n"
    )


def _decision() -> dict[str, Any]:
    return {
        "schema_version": "routing-decision.v1", "mode": "narrow", "confidence": "high",
        "primary_paths": ["src/auth/login.py"], "verification_paths": ["tests/test_login.py"], "support_paths": [],
        "ambiguity_indicators": [], "decision_reasons": ["fixture"],
        "candidate_provenance": [
            {"schema_version": "candidate-evidence.v1", "path": "src/auth/login.py", "role": "primary", "rank": 0, "score": 10, "confidence": "high", "matched_signals": ["explicit_path:src/auth/login.py"], "provenance": ["fixture"]},
            {"schema_version": "candidate-evidence.v1", "path": "tests/test_login.py", "role": "verification", "rank": 1, "score": 8, "confidence": "high", "matched_signals": ["source_test_relation:src/auth/login.py"], "provenance": ["fixture"]},
        ],
    }


def _runner(calls: list[dict[str, Any]]):
    def compile_runner(
        project_root: Path,
        prompt: str,
        profile: str | None,
        *,
        tuning_profile: str | None = None,
        write_policy: Any | None = None,
    ) -> dict[str, Any]:
        calls.append(
            {
                "project_root": project_root,
                "prompt": prompt,
                "profile": profile,
                "tuning_profile": tuning_profile,
                "write_policy": write_policy,
            }
        )
        command = ["premode", "compile", prompt, "--repo", str(project_root), "--plugin", "literal_symbol"]
        if tuning_profile:
            command.extend(["--tuning", tuning_profile])
        return {
            "status": "compiled",
            "route": "plugin_alias",
            "premode_command": command,
            "packet": _packet(prompt, marker="tuned" if tuning_profile else "generalized"),
            "packet_sha256": "sha-tuned" if tuning_profile else "sha-generalized",
            "model_facing_sections": MODEL_FACING_SECTIONS,
            "tuning_profile": tuning_profile,
            "routing_decision": _decision(),
        }

    return compile_runner


def _set_tuned_state_without_profile(repo: Path) -> None:
    pcodex_state.write_pcodex_state(
        repo,
        {
            "schema_version": "pcodex.state.v1",
            "enabled": True,
            "mode": "tuned",
            "algorithm": "literal_symbol",
            "tuning_profile": ".premode/tuning/repo_profile.json",
        },
    )


def test_run_dry_run_off_reports_raw_mode_and_skips_compile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex.run_dry_run(repo, RAW_PROMPT, compile_runner=lambda *_args, **_kwargs: pytest.fail("compile not expected"))

    assert result["mode"] == "off"
    assert result["enabled"] is False
    assert result["transform_applied"] is False
    assert result["premode_command"] is None
    assert result["packet_path"] is None
    assert result["final_prompt_preview"] == RAW_PROMPT
    assert result["codex_launch"] == "not_executed"


def test_run_dry_run_on_uses_generalized_literal_symbol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    calls: list[dict[str, Any]] = []
    pcodex.set_enabled(repo, True)

    result = pcodex.run_dry_run(repo, RAW_PROMPT, compile_runner=_runner(calls))

    assert result["mode"] == "on"
    assert result["transform_applied"] is True
    assert result["tuning_profile"] is None
    assert calls[0]["tuning_profile"] is None
    assert "--plugin" in result["premode_command"]
    assert "--tuning" not in result["premode_command"]


def test_run_dry_run_tuned_uses_state_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo)
    pcodex.set_tuned(repo)
    calls: list[dict[str, Any]] = []

    result = pcodex.run_dry_run(repo, RAW_PROMPT, compile_runner=_runner(calls))

    assert result["mode"] == "tuned"
    assert result["transform_applied"] is True
    assert result["tuning_profile"] == ".premode/tuning/repo_profile.json"
    assert calls[0]["tuning_profile"] == ".premode/tuning/repo_profile.json"
    assert result["premode_command"][-2:] == ["--tuning", ".premode/tuning/repo_profile.json"]


def test_run_tuned_missing_profile_fails_before_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _set_tuned_state_without_profile(repo)
    monkeypatch.setattr(pcodex, "run_codex", lambda *_args, **_kwargs: pytest.fail("live Codex must not run"))

    code = pcodex.main(["run", RAW_PROMPT, "--repo", str(repo)])

    assert code == 2
    payload = json.loads(capsys.readouterr().err)
    assert "Tuning profile not found" in payload["error"]
    assert payload["codex_launch"] == "not_executed"
    assert payload["transform_applied"] is False


def test_run_tuned_invalid_profile_fails_before_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    profile = _generate_tuning(repo)
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["schema_version"] = "wrong"
    _write_json(profile, payload)
    pcodex_state.write_pcodex_state(
        repo,
        {
            "schema_version": "pcodex.state.v1",
            "enabled": True,
            "mode": "tuned",
            "algorithm": "literal_symbol",
            "tuning_profile": ".premode/tuning/repo_profile.json",
        },
    )
    monkeypatch.setattr(pcodex, "run_codex", lambda *_args, **_kwargs: pytest.fail("live Codex must not run"))

    code = pcodex.main(["run", RAW_PROMPT, "--repo", str(repo)])

    assert code == 2
    assert "Invalid tuning profile" in json.loads(capsys.readouterr().err)["error"]


def test_live_run_tuned_passes_tuning_profile_to_codex_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo)
    pcodex.set_tuned(repo)
    calls: list[Any] = []

    def fake_run_codex(project_root: Path, prompt: str, profile: str | None, options: Any) -> dict[str, Any]:
        calls.append((project_root, prompt, profile, options))
        return {"returncode": 0, "tuning_profile": options.tuning_profile, "child_env": options.child_env}

    monkeypatch.setattr(pcodex, "run_codex", fake_run_codex)

    result = pcodex.run_enabled(repo, RAW_PROMPT)

    assert result["tuning_profile"] == ".premode/tuning/repo_profile.json"
    assert result["child_env"]["PCODEX_ENABLED"] == "1"
    assert calls[0][3].packet_strategy == "literal_symbol"


def test_transform_off_returns_raw_prompt_and_out_of_band_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=lambda *_args, **_kwargs: pytest.fail("compile not expected"),
    )

    assert result.transformed_prompt == RAW_PROMPT
    assert result.mode == "off"
    assert result.transform_applied is False
    assert result.metadata["mode"] == "off"
    assert result.metadata["transform_applied"] is False


def test_transform_on_preserves_raw_prompt_and_appends_generalized_packet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    calls: list[dict[str, Any]] = []

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_runner(calls),
    )

    assert result.mode == "on"
    assert result.transform_applied is True
    assert result.transformed_prompt.startswith("TASK\n")
    assert RAW_PROMPT in result.transformed_prompt
    assert result.transformed_prompt.startswith("TASK\n")
    assert "* src/auth/login.py" in result.transformed_prompt
    assert calls[0]["tuning_profile"] is None


def test_transform_tuned_preserves_raw_prompt_and_uses_tuning_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo)
    pcodex.set_tuned(repo)
    calls: list[dict[str, Any]] = []

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_runner(calls),
    )

    assert result.mode == "tuned"
    assert result.transform_applied is True
    assert result.tuning_profile == ".premode/tuning/repo_profile.json"
    assert result.transformed_prompt.startswith("TASK\n")
    assert RAW_PROMPT in result.transformed_prompt
    assert "* src/auth/login.py" in result.transformed_prompt
    assert calls[0]["tuning_profile"] == ".premode/tuning/repo_profile.json"


def test_transform_tuned_missing_profile_returns_raw_prompt_with_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _set_tuned_state_without_profile(repo)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=lambda *_args, **_kwargs: pytest.fail("compile not expected"),
    )

    assert result.transformed_prompt == RAW_PROMPT
    assert result.mode == "tuned"
    assert result.transform_applied is False
    assert "Tuning profile not found" in str(result.error)
    assert "Tuning profile not found" not in result.transformed_prompt
    assert result.metadata["status"] == "tuned_profile_invalid_raw_prompt"


def test_transform_tuned_invalid_profile_returns_raw_prompt_with_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    profile = _generate_tuning(repo)
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["schema_version"] = "wrong"
    _write_json(profile, payload)
    pcodex_state.write_pcodex_state(
        repo,
        {
            "schema_version": "pcodex.state.v1",
            "enabled": True,
            "mode": "tuned",
            "algorithm": "literal_symbol",
            "tuning_profile": ".premode/tuning/repo_profile.json",
        },
    )

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=lambda *_args, **_kwargs: pytest.fail("compile not expected"),
    )

    assert result.transformed_prompt == RAW_PROMPT
    assert result.transform_applied is False
    assert "Invalid tuning profile" in str(result.error)
    assert "Invalid tuning profile" not in result.transformed_prompt


def test_mcp_server_call_mirrors_mode_aware_transform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo)
    pcodex.set_tuned(repo)
    calls: list[dict[str, Any]] = []

    result = pcodex_mcp_server.call_tool(
        "pcodex_transform_subagent_prompt",
        {"subagent_prompt": RAW_PROMPT, "dry_run": True},
        cwd=repo,
        compile_runner=_runner(calls),
    )["structuredContent"]

    assert result["mode"] == "tuned"
    assert result["transform_applied"] is True
    assert result["tuning_profile"] == ".premode/tuning/repo_profile.json"
    assert result["metadata"]["mode"] == "tuned"
    assert calls[0]["tuning_profile"] == ".premode/tuning/repo_profile.json"


def test_invalid_state_fails_safely_for_transform_but_not_model_facing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _write_json(repo / ".premode" / "pcodex_state.json", {"schema_version": "wrong"})

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=lambda *_args, **_kwargs: pytest.fail("compile not expected"),
    )

    assert result.transformed_prompt == RAW_PROMPT
    assert result.transform_applied is False
    assert result.metadata["status"] == "invalid_state_raw_prompt"
    assert str(result.error) not in result.transformed_prompt


def test_model_facing_packet_boundary_and_forbidden_terms_remain_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_runner([]),
    )

    assert result.transformed_prompt.startswith("TASK\n")
    for required in ("TASK\n", "LIKELY FILES", "PRIMARY", "VERIFY"):
        assert required in result.transformed_prompt
    for forbidden in (
        "TASK_CLASS",
        "SUPPORT_RELATIONS",
        "diagnostics",
        "CONFIDENCE",
        "VALIDATION",
        "COMMANDS",
        "DO_NOT_EDIT",
    ):
        assert forbidden not in result.transformed_prompt


def test_generalized_and_explicit_tuning_compile_behavior_remain_available(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile = _generate_tuning(repo)

    generalized = compile_prompt(repo, RAW_PROMPT, "lite", **LITERAL_SYMBOL_KWARGS)
    tuned = compile_prompt(repo, RAW_PROMPT, "lite", tuning_profile=profile, **LITERAL_SYMBOL_KWARGS)

    assert "PREMODE_CONTEXT_PACKET_V5" in generalized["packet"]
    assert "PREMODE_CONTEXT_PACKET_V5" in tuned["packet"]
    assert "tuning_profile_diagnostics" not in tuned["packet"]
    assert tuned["tuning_profile_diagnostics"]["applied"] is True
