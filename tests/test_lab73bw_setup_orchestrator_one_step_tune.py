from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from premode import cli
from premode import pcodex_bootstrap as pcodex
from premode import tuning
from premode.compiler import compile_prompt


LITERAL_SYMBOL_KWARGS = {
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
    "record_artifacts": False,
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "synthetic_repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    _write(repo / "src" / "auth" / "login.py", "def login_user(name):\n    return name.strip()\n")
    _write(repo / "src" / "client.py", "def client_entrypoint():\n    return 'client'\n")
    _write(repo / "tests" / "test_login.py", "def test_login_user():\n    assert True\n")
    return repo


def _state(repo: Path) -> dict[str, Any]:
    return json.loads((repo / ".premode" / "pcodex_state.json").read_text(encoding="utf-8"))


def _minimal_verify(verdict: str) -> dict[str, Any]:
    return {
        "schema_version": "pcodex.tuning_verify.v1",
        "status": "verified",
        "verdict": verdict,
        "profile_validation_status": "PASS" if verdict != "FAIL" else "FAIL",
        "evaluation_prompt_count": 1,
        "notes": [] if verdict == "PASS" else ["synthetic_verdict"],
        "general": {"packet_token_estimate": 10},
        "tuned": {"packet_token_estimate": 8},
        "delta": {"packet_token_estimate_change": -2},
        "artifacts": {
            "VERIFY_REPORT": ".premode/tuning/VERIFY_REPORT.md",
            "VERIFY_RESULTS": ".premode/tuning/VERIFY_RESULTS.json",
        },
    }


def _fake_tune_result(repo: Path, verdict: str) -> dict[str, Any]:
    return {
        "status": "tuning_ready" if verdict == "PASS" else "needs_adjustment" if verdict == "NEEDS_ADJUSTMENT" else "failed",
        "repo_root": str(repo),
        "out_dir": str(repo / ".premode" / "tuning"),
        "generation_status": "generated",
        "validation_status": "PASS" if verdict != "FAIL" else "FAIL",
        "verdict": verdict,
        "notes": [] if verdict == "PASS" else ["synthetic_verdict"],
    }


def _generate_valid_profile(repo: Path) -> None:
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"


def test_pcodex_tune_one_step_runs_static_validate_and_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    calls: list[str] = []

    def fake_write(project_root: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
        calls.append("static")
        return {"status": "generated", "validation_status": "pass"}

    def fake_validate(project_root: Path, *, out_dir: Path | None = None, write_report: bool = True) -> dict[str, Any]:
        calls.append("validate")
        return {"status": "pass", "failures": []}

    def fake_verify(project_root: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
        calls.append("verify")
        return _minimal_verify("PASS")

    monkeypatch.setattr(tuning, "write_tuning_artifacts", fake_write)
    monkeypatch.setattr(tuning, "validate_tuning_artifacts", fake_validate)
    monkeypatch.setattr(tuning, "verify_tuning_profile", fake_verify)

    assert pcodex.main(["tune", "--repo-root", str(repo)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls == ["static", "validate", "verify"]
    assert payload["status"] == "tuning_ready"
    assert payload["verdict"] == "PASS"
    assert payload["safety_summary"]["live_codex_tasks"] is False


def test_pcodex_tune_preserves_explicit_static_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(tuning, "write_tuning_artifacts", lambda *_args, **_kwargs: calls.append("static") or {"validation_status": "pass"})
    monkeypatch.setattr(tuning, "validate_tuning_artifacts", lambda *_args, **_kwargs: pytest.fail("validate not expected"))
    monkeypatch.setattr(tuning, "verify_tuning_profile", lambda *_args, **_kwargs: pytest.fail("verify not expected"))

    assert pcodex.main(["tune", "--repo-root", str(repo), "--static-only"]) == 0
    json.loads(capsys.readouterr().out)
    assert calls == ["static"]


def test_pcodex_tune_preserves_explicit_validate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(tuning, "validate_tuning_artifacts", lambda *_args, **_kwargs: {"status": "pass", "failures": []})
    monkeypatch.setattr(tuning, "write_tuning_artifacts", lambda *_args, **_kwargs: pytest.fail("static not expected"))
    monkeypatch.setattr(tuning, "verify_tuning_profile", lambda *_args, **_kwargs: pytest.fail("verify not expected"))

    assert pcodex.main(["tune", "--repo-root", str(repo), "--validate"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_pcodex_tune_preserves_explicit_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(tuning, "verify_tuning_profile", lambda *_args, **_kwargs: _minimal_verify("PASS"))
    monkeypatch.setattr(tuning, "write_tuning_artifacts", lambda *_args, **_kwargs: pytest.fail("static not expected"))
    monkeypatch.setattr(tuning, "validate_tuning_artifacts", lambda *_args, **_kwargs: pytest.fail("validate not expected"))

    assert pcodex.main(["tune", "--repo-root", str(repo), "--verify"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "PASS"


def test_pcodex_tune_needs_adjustment_is_nonfatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(tuning, "write_tuning_artifacts", lambda *_args, **_kwargs: {"status": "generated", "validation_status": "pass"})
    monkeypatch.setattr(tuning, "validate_tuning_artifacts", lambda *_args, **_kwargs: {"status": "pass", "failures": []})
    monkeypatch.setattr(tuning, "verify_tuning_profile", lambda *_args, **_kwargs: _minimal_verify("NEEDS_ADJUSTMENT"))

    assert pcodex.main(["tune", "--repo-root", str(repo)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "NEEDS_ADJUSTMENT"
    assert payload["status"] == "needs_adjustment"


def test_pcodex_tune_fail_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(tuning, "write_tuning_artifacts", lambda *_args, **_kwargs: {"status": "generated_with_validation_failures", "validation_status": "fail"})
    monkeypatch.setattr(tuning, "validate_tuning_artifacts", lambda *_args, **_kwargs: {"status": "fail", "failures": ["synthetic_failure"]})
    monkeypatch.setattr(tuning, "verify_tuning_profile", lambda *_args, **_kwargs: _minimal_verify("FAIL"))

    assert pcodex.main(["tune", "--repo-root", str(repo)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "FAIL"
    assert payload["status"] == "failed"


def test_one_step_tune_writes_only_under_tuning_dir(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = {path.relative_to(repo).as_posix() for path in repo.rglob("*") if path.is_file()}

    result = pcodex.run_one_step_tune(repo)

    after = {path.relative_to(repo).as_posix() for path in repo.rglob("*") if path.is_file()}
    added = after - before
    assert result["verdict"] in {"PASS", "NEEDS_ADJUSTMENT", "FAIL"}
    assert added
    assert all(path.startswith(".premode/tuning/") for path in added)


def test_pcodex_setup_skip_tune_writes_on_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    result = pcodex.setup(repo, skip_tune=True, no_mcp=True)

    assert result["setup_status"] == "complete"
    assert result["mode"] == "on"
    assert result["tuning_verdict"] == "SKIPPED"
    assert result["mcp_status"] == "skipped (no_mcp)"
    assert _state(repo)["mode"] == "on"


def test_pcodex_setup_pass_tuning_writes_tuned_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _generate_valid_profile(repo)

    result = pcodex.setup(repo, no_mcp=True, tune_runner=lambda root: _fake_tune_result(root, "PASS"))

    assert result["mode"] == "tuned"
    assert result["tuning_verdict"] == "PASS"
    assert _state(repo)["mode"] == "tuned"


def test_pcodex_setup_needs_adjustment_writes_on_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    result = pcodex.setup(repo, no_mcp=True, tune_runner=lambda root: _fake_tune_result(root, "NEEDS_ADJUSTMENT"))

    assert result["mode"] == "on"
    assert result["tuning_verdict"] == "NEEDS_ADJUSTMENT"
    assert result["fallback"] == "using general literal_symbol"
    assert _state(repo)["mode"] == "on"


def test_pcodex_setup_fail_writes_on_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    result = pcodex.setup(repo, no_mcp=True, tune_runner=lambda root: _fake_tune_result(root, "FAIL"))

    assert result["setup_status"] == "complete"
    assert result["mode"] == "on"
    assert result["tuning_verdict"] == "FAIL"
    assert _state(repo)["mode"] == "on"


def test_pcodex_setup_json_is_parseable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)

    assert pcodex.main(["setup", "--repo-root", str(repo), "--skip-tune", "--no-mcp", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["setup_status"] == "complete"
    assert payload["mode"] == "on"
    assert payload["codex_launch"] == "not_executed"


def test_pcodex_setup_no_mcp_does_not_attempt_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(pcodex, "_run_codex_mcp_command", lambda *_args, **_kwargs: pytest.fail("MCP command not expected"))

    result = pcodex.setup(repo, skip_tune=True, no_mcp=True)

    assert result["mcp"]["status"] == "skipped"
    assert result["mcp"]["reason"] == "no_mcp"


def test_pcodex_setup_codex_cli_missing_is_nonblocking_when_no_mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)

    def fake_available(name: str) -> bool:
        if name == "codex":
            return False
        return True

    monkeypatch.setattr(pcodex, "_command_available", fake_available)

    result = pcodex.setup(repo, skip_tune=True, no_mcp=True)

    assert result["setup_status"] == "complete"
    assert result["checks"]["codex_available"] is False
    assert result["mcp"]["status"] == "skipped"


def test_pcodex_setup_does_not_mutate_real_codex_config_by_default(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    calls: list[dict[str, Any]] = []

    def registrar(project_root: Path, *, no_mcp: bool, isolated: bool, real_codex_registration: bool) -> dict[str, Any]:
        calls.append({"no_mcp": no_mcp, "isolated": isolated, "real": real_codex_registration})
        return {"status": "registered", "registered": True, "config_scope": "isolated"}

    result = pcodex.setup(repo, skip_tune=True, mcp_registrar=registrar)

    assert result["mcp_status"] == "registered in isolated config"
    assert calls == [{"no_mcp": False, "isolated": True, "real": False}]


def test_pcodex_setup_real_codex_registration_is_explicit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    calls: list[bool] = []

    def registrar(project_root: Path, *, no_mcp: bool, isolated: bool, real_codex_registration: bool) -> dict[str, Any]:
        calls.append(real_codex_registration)
        return {"status": "registered", "registered": True, "config_scope": "real", "warning": "real config"}

    pcodex.setup(repo, skip_tune=True, real_codex_registration=True, mcp_registrar=registrar)

    assert calls == [True]


def test_pcodex_setup_never_runs_codex_exec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(pcodex, "run_codex", lambda *_args, **_kwargs: pytest.fail("run_codex not expected"))
    monkeypatch.setattr(pcodex, "run_disabled", lambda *_args, **_kwargs: pytest.fail("codex exec path not expected"))

    result = pcodex.setup(repo, skip_tune=True, no_mcp=True)

    assert result["codex_launch"] == "not_executed"


def test_setup_dashboard_includes_mode_tuning_mcp_and_fallback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)

    assert pcodex.main(["setup", "--repo-root", str(repo), "--skip-tune", "--no-mcp"]) == 0
    out = capsys.readouterr().out

    assert "Mode: on" in out
    assert "Tuning: SKIPPED" in out
    assert "MCP: skipped (no_mcp)" in out
    assert "Fallback: using general literal_symbol" in out


def test_pcodex_setup_routes_to_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("pcodex setup must not route to Codex wrapper"))

    assert cli.pcodex_main(["setup", "--help"]) == 0
    assert calls == [["setup", "--help"]]


def test_premode_compile_literal_symbol_default_unchanged_by_setup(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = compile_prompt(repo, "Update login behavior.", "lite", **LITERAL_SYMBOL_KWARGS)
    pcodex.setup(repo, skip_tune=True, no_mcp=True)
    after = compile_prompt(repo, "Update login behavior.", "lite", **LITERAL_SYMBOL_KWARGS)

    assert after["packet"] == before["packet"]
    assert "<TASK_CLASS>" not in after["packet"]
    assert "<SUPPORT_RELATIONS>" not in after["packet"]


def test_premode_compile_literal_symbol_tuning_unchanged_by_setup(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _generate_valid_profile(repo)
    before = compile_prompt(repo, "Update login behavior.", "lite", tuning_profile=".premode/tuning/repo_profile.json", **LITERAL_SYMBOL_KWARGS)
    pcodex.setup(repo, skip_tune=True, no_mcp=True)
    after = compile_prompt(repo, "Update login behavior.", "lite", tuning_profile=".premode/tuning/repo_profile.json", **LITERAL_SYMBOL_KWARGS)

    assert after["packet"] == before["packet"]
    assert "tuning_profile" not in after["packet"]
