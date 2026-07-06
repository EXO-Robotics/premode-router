from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import cli
from premode import pcodex_bootstrap as pcodex
from premode import pcodex_state
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


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    _write(repo / "src" / "auth" / "login.py", "def login_user(name):\n    return name.strip()\n")
    _write(repo / "src" / "client.py", "def client_entrypoint():\n    return 'client'\n")
    _write(repo / "tests" / "test_login.py", "def test_login_user():\n    assert True\n")
    return repo


def _state(repo: Path) -> dict:
    return json.loads((repo / ".premode" / "pcodex_state.json").read_text(encoding="utf-8"))


def _generate_tuning(repo: Path) -> Path:
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"
    return repo / ".premode" / "tuning" / "repo_profile.json"


def test_pcodex_on_writes_on_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = pcodex.set_enabled(repo, True)

    assert result["enabled"] is True
    assert result["mode"] == "on"
    assert result["algorithm"] == "literal_symbol"
    assert result["tuning_profile"] is None
    assert _state(repo) == {
        "schema_version": "pcodex.state.v1",
        "enabled": True,
        "mode": "on",
        "algorithm": "literal_symbol",
        "tuning_profile": None,
    }


def test_pcodex_off_writes_off_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = pcodex.set_enabled(repo, False)

    assert result["enabled"] is False
    assert result["mode"] == "off"
    assert result["algorithm"] == "literal_symbol"
    assert result["tuning_profile"] is None
    assert _state(repo)["mode"] == "off"


def test_missing_state_status_reports_safe_default_without_writing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = pcodex.status(repo)

    assert result["enabled"] is True
    assert result["mode"] == "on"
    assert result["state_exists"] is False
    assert result["state_status"] == "missing_default"
    assert not (repo / ".premode" / "pcodex_state.json").exists()


def test_pcodex_tuned_fails_clearly_when_profile_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _make_repo(tmp_path)

    code = pcodex.main(["tuned", "--profile", ".premode/tuning/repo_profile.json", "--repo-root", str(repo)])

    assert code == 2
    assert "Tuning profile not found" in capsys.readouterr().err
    assert not (repo / ".premode" / "pcodex_state.json").exists()


def test_pcodex_tuned_fails_clearly_when_profile_invalid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _make_repo(tmp_path)
    profile = _generate_tuning(repo)
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["schema_version"] = "wrong"
    profile.write_text(json.dumps(payload), encoding="utf-8")

    code = pcodex.main(["tuned", "--repo-root", str(repo)])

    assert code == 2
    assert "Invalid tuning profile" in capsys.readouterr().err
    assert not (repo / ".premode" / "pcodex_state.json").exists()


def test_pcodex_tuned_writes_state_after_validation(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _generate_tuning(repo)

    result = pcodex.set_tuned(repo)

    assert result["enabled"] is True
    assert result["mode"] == "tuned"
    assert result["algorithm"] == "literal_symbol"
    assert result["tuning_profile"] == ".premode/tuning/repo_profile.json"
    assert result["tuning_profile_valid"] is True
    assert _state(repo)["mode"] == "tuned"


def test_pcodex_tuned_profile_option_accepts_valid_profile(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    profile = _generate_tuning(repo)

    result = pcodex.set_tuned(repo, str(profile))

    assert result["mode"] == "tuned"
    assert result["tuning_profile"] == ".premode/tuning/repo_profile.json"


def test_tuned_failure_does_not_overwrite_existing_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _make_repo(tmp_path)
    pcodex.set_enabled(repo, False)

    code = pcodex.main(["tuned", "--repo-root", str(repo)])

    assert code == 2
    assert "Tuning profile not found" in capsys.readouterr().err
    assert _state(repo)["mode"] == "off"


def test_pcodex_status_human_includes_mode_fields(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _make_repo(tmp_path)
    pcodex.set_enabled(repo, True)

    assert pcodex.main(["status", "--repo-root", str(repo)]) == 0
    out = capsys.readouterr().out

    assert "enabled: true" in out
    assert "mode: on" in out
    assert "algorithm: literal_symbol" in out
    assert "tuning_profile: null" in out


def test_pcodex_status_json_is_parseable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _make_repo(tmp_path)
    pcodex.set_enabled(repo, True)

    assert pcodex.main(["status", "--json", "--repo-root", str(repo)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "pcodex.state.v1"
    assert payload["enabled"] is True
    assert payload["mode"] == "on"
    assert payload["state_path"] == ".premode/pcodex_state.json"


def test_invalid_state_file_reports_safe_default(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo / ".premode" / "pcodex_state.json"
    path.parent.mkdir()
    path.write_text("{not-json", encoding="utf-8")

    result = pcodex.status(repo)

    assert result["enabled"] is True
    assert result["mode"] == "on"
    assert result["state_status"] == "invalid_default"
    assert result["state_error"]


def test_pcodex_tune_commands_still_route_to_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("pcodex tune must stay on bootstrap route"))

    assert cli.pcodex_main(["tune", "--verify"]) == 0
    assert calls == [["tune", "--verify"]]


def test_pcodex_tuned_routes_to_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("pcodex tuned must stay on bootstrap route"))

    assert cli.pcodex_main(["tuned"]) == 0
    assert calls == [["tuned"]]


def test_pcodex_mcp_server_routing_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("pcodex mcp-server must stay on bootstrap route"))

    assert cli.pcodex_main(["mcp-server"]) == 0
    assert calls == [["mcp-server"]]


def test_model_facing_packet_rendering_unchanged_with_mode_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    pcodex.set_enabled(repo, True)

    result = compile_prompt(repo, "Update login behavior.", "lite", **LITERAL_SYMBOL_KWARGS)
    packet = result["packet"]

    assert "<TASK>" in packet
    assert "<PRIMARY_FILES>" in packet
    assert "<RELATED_TESTS>" in packet
    assert "<END_PREMODE_CONTEXT_PACKET_V5>" in packet
    assert "<TASK_CLASS>" not in packet
    assert "<SUPPORT_RELATIONS>" not in packet
    assert "tuning_profile" not in packet


def test_premode_compile_literal_symbol_default_unchanged_by_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    before = compile_prompt(repo, "Update login behavior.", "lite", **LITERAL_SYMBOL_KWARGS)
    pcodex.set_enabled(repo, True)
    after = compile_prompt(repo, "Update login behavior.", "lite", **LITERAL_SYMBOL_KWARGS)

    assert after["packet"] == before["packet"]


def test_premode_compile_literal_symbol_tuning_still_works(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    profile = _generate_tuning(repo)

    result = compile_prompt(repo, "Update login behavior.", "lite", tuning_profile=profile, **LITERAL_SYMBOL_KWARGS)

    assert result["tuning_profile_diagnostics"]["applied"] is True
    assert "tuning_profile_diagnostics" not in result["packet"]


def test_no_lab_or_user_paths_are_baked_into_state_module() -> None:
    source = Path(pcodex_state.__file__).read_text(encoding="utf-8")

    assert "/private/tmp" not in source
    assert "/Users/" not in source
    assert "premode_labs" not in source
