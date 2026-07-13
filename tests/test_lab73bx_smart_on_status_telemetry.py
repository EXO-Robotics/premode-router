from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from premode import pcodex_bootstrap as pcodex
from premode import pcodex_mcp
from premode import pcodex_state
from premode import tuning
from premode.compiler import compile_prompt


RAW_PROMPT = "Hypothetical dummy task: inspect login flow. Do not modify files."
SECRET_PROMPT = "Hypothetical dummy task SECRET_PROMPT_NEVER_STORE. Do not modify files."

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


def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PCODEX_ENABLED", raising=False)
    monkeypatch.delenv("PCODEX_ALGORITHM", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG_PATH", raising=False)


def _generate_tuning(repo: Path, verdict: str = "PASS") -> Path:
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"
    profile = repo / ".premode" / "tuning" / "repo_profile.json"
    _write_json(
        repo / ".premode" / "tuning" / "VERIFY_RESULTS.json",
        {
            "schema_version": "pcodex.tuning_verify.v1",
            "status": "verified",
            "verdict": verdict,
            "profile_validation_status": "PASS" if verdict != "FAIL" else "FAIL",
            "evaluation_prompt_count": 2,
            "general": {"packet_token_estimate": 100},
            "tuned": {"packet_token_estimate": 80},
            "delta": {"packet_token_estimate_change": -20},
            "packet_boundary_safe": True,
            "profile_validation_failures": [] if verdict != "FAIL" else ["synthetic_failure"],
            "notes": [] if verdict == "PASS" else ["synthetic_verdict"],
            "rows": [],
            "artifacts": {
                "VERIFY_REPORT": ".premode/tuning/VERIFY_REPORT.md",
                "VERIFY_RESULTS": ".premode/tuning/VERIFY_RESULTS.json",
            },
        },
    )
    return profile


def _corrupt_profile(profile: Path) -> None:
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["schema_version"] = "wrong"
    _write_json(profile, payload)


def _packet(task: str, marker: str) -> str:
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
        calls.append({"prompt": prompt, "profile": profile, "tuning_profile": tuning_profile, "write_policy": write_policy})
        command = ["premode", "compile", prompt, "--repo", str(project_root), "--plugin", "literal_symbol"]
        if tuning_profile:
            command.extend(["--tuning", tuning_profile])
        return {
            "status": "compiled",
            "route": "plugin_alias",
            "premode_command": command,
            "packet": _packet(prompt, "tuned" if tuning_profile else "generalized"),
            "packet_sha256": "sha-tuned" if tuning_profile else "sha-generalized",
            "model_facing_sections": ["TASK", "PRIMARY_FILES", "RELATED_TESTS", "END_PREMODE_CONTEXT_PACKET_V5"],
            "tuning_profile": tuning_profile,
            "routing_decision": _decision(),
        }

    return compile_runner


def test_smart_on_pass_resolves_effective_tuned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo, "PASS")
    pcodex.set_enabled(repo, True)

    result = pcodex.resolve_mode_state(repo)

    assert result["configured_mode"] == "on"
    assert result["effective_mode"] == "tuned"
    assert result["effective_tuning_profile"] == ".premode/tuning/repo_profile.json"
    assert result["tuning"]["verify"] == "PASS"


def test_smart_on_missing_profile_resolves_general_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex.resolve_mode_state(repo)

    assert result["configured_mode"] == "on"
    assert result["effective_mode"] == "on"
    assert result["effective_tuning_profile"] is None
    assert result["tuning"]["verify"] == "missing"


@pytest.mark.parametrize("verdict", ["NEEDS_ADJUSTMENT", "FAIL"])
def test_smart_on_non_pass_verify_resolves_general_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verdict: str,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo, verdict)
    pcodex.set_enabled(repo, True)

    result = pcodex.resolve_mode_state(repo)

    assert result["effective_mode"] == "on"
    assert result["fallback"]["active"] is True
    assert result["fallback"]["last_reason"] == f"verify_{verdict.lower()}"


def test_smart_on_invalid_profile_resolves_general_and_records_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    profile = _generate_tuning(repo, "PASS")
    _corrupt_profile(profile)
    pcodex.set_enabled(repo, True)
    calls: list[dict[str, Any]] = []

    result = pcodex.run_dry_run(repo, SECRET_PROMPT, compile_runner=_runner(calls))
    state_text = (repo / ".premode" / "pcodex_state.json").read_text(encoding="utf-8")

    assert result["configured_mode"] == "on"
    assert result["effective_mode"] == "on"
    assert result["fallback"]["active"] is True
    assert calls[0]["tuning_profile"] is None
    assert "SECRET_PROMPT_NEVER_STORE" not in state_text
    assert "login_user" not in state_text
    state = json.loads(state_text)
    # Literal dry-run authority does not record runtime telemetry, even when
    # read-only mode resolution observes an existing fallback.
    assert "telemetry" not in state
    assert "fallback" not in state
    assert result["fallback"]["last_reason"] == "tuning_profile_invalid"


def test_mode_tuned_remains_strict_for_invalid_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    profile = _generate_tuning(repo, "PASS")
    pcodex.set_tuned(repo)
    _corrupt_profile(profile)

    with pytest.raises(pcodex_state.PcodexStateError):
        pcodex.run_dry_run(repo, RAW_PROMPT, compile_runner=_runner([]))


def test_mode_off_remains_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex.run_dry_run(repo, RAW_PROMPT, compile_runner=lambda *_args, **_kwargs: pytest.fail("compile not expected"))

    assert result["configured_mode"] == "off"
    assert result["effective_mode"] == "off"
    assert result["transform_applied"] is False


def test_run_dry_run_shows_configured_and_effective_mode_and_uses_tuned_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo, "PASS")
    pcodex.set_enabled(repo, True)
    calls: list[dict[str, Any]] = []

    result = pcodex.run_dry_run(repo, RAW_PROMPT, compile_runner=_runner(calls))

    assert result["configured_mode"] == "on"
    assert result["effective_mode"] == "tuned"
    assert calls[0]["tuning_profile"] == ".premode/tuning/repo_profile.json"
    assert result["premode_command"][-2:] == ["--tuning", ".premode/tuning/repo_profile.json"]


def test_run_enabled_on_pass_and_invalid_profile_respect_effective_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    profile = _generate_tuning(repo, "PASS")
    pcodex.set_enabled(repo, True)
    options: list[Any] = []

    def fake_run_codex(project_root: Path, prompt: str, profile_name: str | None, opts: Any) -> dict[str, Any]:
        options.append(opts)
        return {"returncode": 0, "tuning_profile": opts.tuning_profile, "codex_launch": "mocked"}

    monkeypatch.setattr(pcodex, "run_codex", fake_run_codex)

    assert pcodex.run_enabled(repo, RAW_PROMPT)["tuning_profile"] == ".premode/tuning/repo_profile.json"
    _corrupt_profile(profile)
    assert pcodex.run_enabled(repo, RAW_PROMPT)["tuning_profile"] is None
    assert options[0].tuning_profile == ".premode/tuning/repo_profile.json"
    assert options[1].tuning_profile is None


def test_mcp_transform_on_pass_uses_tuned_packet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo, "PASS")
    pcodex.set_enabled(repo, True)
    calls: list[dict[str, Any]] = []

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_runner(calls),
    )

    assert result.mode == "on"
    assert result.effective_mode == "tuned"
    assert result.tuning_profile == ".premode/tuning/repo_profile.json"
    assert "* src/auth/login.py" in result.transformed_prompt
    assert calls[0]["tuning_profile"] == ".premode/tuning/repo_profile.json"


def test_mcp_transform_on_invalid_tuning_falls_back_to_generalized_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    profile = _generate_tuning(repo, "PASS")
    _corrupt_profile(profile)
    pcodex.set_enabled(repo, True)
    calls: list[dict[str, Any]] = []

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_runner(calls),
    )

    assert result.mode == "on"
    assert result.effective_mode == "on"
    assert result.transform_applied is True
    assert result.metadata["fallback"]["active"] is True
    assert calls[0]["tuning_profile"] is None
    assert "* src/auth/login.py" in result.transformed_prompt


def test_mcp_transform_tuned_invalid_returns_raw_prompt_with_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    profile = _generate_tuning(repo, "PASS")
    pcodex.set_tuned(repo)
    _corrupt_profile(profile)

    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=lambda *_args, **_kwargs: pytest.fail("compile not expected"),
    )

    assert result.transformed_prompt == RAW_PROMPT
    assert result.mode == "tuned"
    assert result.transform_applied is False
    assert "Invalid tuning profile" in str(result.error)
    assert "Invalid tuning profile" not in result.transformed_prompt


def test_status_human_and_json_include_dashboard_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _generate_tuning(repo, "PASS")
    pcodex.set_enabled(repo, True)

    assert pcodex.main(["status", "--repo-root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "Configured mode: on" in out
    assert "Effective mode: tuned" in out
    assert "Tuning: PASS" in out
    assert "Fallback: none" in out
    assert "Telemetry: compile_count=0 fallback_count=0" in out

    assert pcodex.main(["status", "--repo-root", str(repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "pcodex.status.v1"
    assert payload["configured_mode"] == "on"
    assert payload["effective_mode"] == "tuned"
    assert payload["tuning"]["verify"] == "PASS"
    assert payload["mcp"]["status"] == "unknown"
    assert payload["fallback"]["active"] is False
    assert payload["savings"] == {"available": False, "reason": "not_enough_data"}


def test_status_codex_cli_missing_reports_unavailable_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    monkeypatch.setattr(pcodex, "_command_available", lambda name: False if name == "codex" else True)

    payload = pcodex.status(repo)

    assert payload["mcp"]["codex_cli_available"] is False
    assert payload["mcp"]["status"] == "unknown"


def test_old_state_files_without_extension_fields_remain_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    _write_json(
        repo / ".premode" / "pcodex_state.json",
        {
            "schema_version": "pcodex.state.v1",
            "enabled": True,
            "mode": "on",
            "algorithm": "literal_symbol",
            "tuning_profile": None,
        },
    )

    payload = pcodex.status(repo)

    assert payload["configured_mode"] == "on"
    assert payload["effective_mode"] == "on"
    assert payload["telemetry"] == {"compile_count": 0, "mode_counts": {"off": 0, "on": 0, "tuned": 0}, "fallback_count": 0}


def test_model_facing_packet_and_compile_invariants_remain_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    profile = _generate_tuning(repo, "PASS")
    pcodex.set_enabled(repo, True)

    generalized = compile_prompt(repo, RAW_PROMPT, "lite", **LITERAL_SYMBOL_KWARGS)
    tuned = compile_prompt(repo, RAW_PROMPT, "lite", tuning_profile=profile, **LITERAL_SYMBOL_KWARGS)
    result = pcodex_mcp.pcodex_transform_subagent_prompt_tool(
        RAW_PROMPT,
        project_root=repo,
        dry_run=True,
        compile_runner=_runner([]),
    )

    assert "PREMODE_CONTEXT_PACKET_V5" in generalized["packet"]
    assert "PREMODE_CONTEXT_PACKET_V5" in tuned["packet"]
    assert "tuning_profile_diagnostics" not in tuned["packet"]
    assert result.transformed_prompt.startswith("TASK\n")
    for forbidden in ("TASK_CLASS", "SUPPORT_RELATIONS", "diagnostics", "CONFIDENCE", "VALIDATION", "COMMANDS", "DO_NOT_EDIT"):
        assert forbidden not in result.transformed_prompt
