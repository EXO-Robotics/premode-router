from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from premode import cli
from premode import pcodex_bootstrap as pcodex
from premode import tuning
from premode.cache_manifest import read_cache_manifest
from premode.lockfile import read_lockfile
from premode.pcodex_state import (
    EFFECTIVE_OFF_RAW,
    EFFECTIVE_ON_GENERALIZED,
    EFFECTIVE_ON_TUNED_VERIFIED,
    EFFECTIVE_SAFE_PASSTHROUGH,
    EFFECTIVE_TUNED_STRICT,
    PcodexStateError,
)
from premode.compiler import compile_prompt


RAW_PROMPT = "Hypothetical dummy task: inspect login flow. Do not modify files."
SECRET_PROMPT = "Hypothetical SECRET_LCC_PROMPT_NEVER_STORE. Do not modify files."


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
    repo = tmp_path / "repo"
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


def _generate_verified_tuning(repo: Path) -> Path:
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"
    _write_json(
        repo / ".premode" / "tuning" / "VERIFY_RESULTS.json",
        {
            "schema_version": "pcodex.tuning_verify.v1",
            "status": "verified",
            "verdict": "PASS",
            "profile_validation_status": "PASS",
            "evaluation_prompt_count": 2,
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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_effective_mode_state_machine_and_status_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)

    assert pcodex.status(repo)["effective_state"] == EFFECTIVE_ON_GENERALIZED
    assert read_lockfile(repo)["valid"] is True

    pcodex.set_enabled(repo, False)
    assert pcodex.status(repo)["effective_state"] == EFFECTIVE_OFF_RAW

    _generate_verified_tuning(repo)
    pcodex.set_enabled(repo, True)
    smart_on = pcodex.status(repo)
    assert smart_on["configured_mode"] == "on"
    assert smart_on["effective_mode"] == "tuned"
    assert smart_on["effective_state"] == EFFECTIVE_ON_TUNED_VERIFIED

    pcodex.set_tuned(repo)
    strict = pcodex.status(repo)
    assert strict["configured_mode"] == "tuned"
    assert strict["effective_state"] == EFFECTIVE_TUNED_STRICT
    assert read_lockfile(repo)["payload"]["effective_state"] == EFFECTIVE_TUNED_STRICT


def test_invalid_state_uses_safe_passthrough_without_compile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    path = repo / ".premode" / "pcodex_state.json"
    path.parent.mkdir()
    path.write_text("{not-json", encoding="utf-8")

    result = pcodex.run_dry_run(
        repo,
        SECRET_PROMPT,
        compile_runner=lambda *_args, **_kwargs: pytest.fail("compile must not run for invalid state"),
    )

    assert result["effective_state"] == EFFECTIVE_SAFE_PASSTHROUGH
    assert result["transform_applied"] is False
    assert result["final_prompt_preview"].startswith("Hypothetical <redacted>")
    lock_text = (repo / ".premode" / "lcc.lock.json").read_text(encoding="utf-8")
    assert "SECRET_LCC_PROMPT_NEVER_STORE" not in lock_text
    assert read_lockfile(repo)["payload"]["effective_state"] == EFFECTIVE_SAFE_PASSTHROUGH


def test_general_on_compile_failure_degrades_to_safe_passthrough_but_tuned_is_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    def broken_compile(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic compile failure")

    general = pcodex.run_dry_run(repo, RAW_PROMPT, compile_runner=broken_compile)
    assert general["effective_state"] == EFFECTIVE_SAFE_PASSTHROUGH
    assert general["transform_applied"] is False
    assert general["safe_passthrough_reason"] == "compile_failed:RuntimeError"

    _generate_verified_tuning(repo)
    pcodex.set_tuned(repo)
    with pytest.raises(RuntimeError):
        pcodex.run_dry_run(repo, RAW_PROMPT, compile_runner=broken_compile)


def test_lockfile_and_cache_manifest_are_content_free_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex.run_dry_run(repo, SECRET_PROMPT)

    assert result["cache_manifest"]["valid"] is True
    assert result["lockfile"]["valid"] is True
    for relative in [".premode/lcc.lock.json", ".premode/out/cache_manifest.json"]:
        text = (repo / relative).read_text(encoding="utf-8")
        json.loads(text)
        assert "SECRET_LCC_PROMPT_NEVER_STORE" not in text
        assert "def login_user" not in text


def test_cache_manifest_prefix_stability_and_profile_cache_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    first = pcodex.compile_pcodex_packet(repo, "Update login behavior.", "lite")
    first_manifest = read_cache_manifest(repo)["payload"]
    second = pcodex.compile_pcodex_packet(repo, "Update client behavior.", "lite")
    second_manifest = read_cache_manifest(repo)["payload"]

    assert first["packet_sha256"] != second["packet_sha256"]
    assert first_manifest["static_prefix_hash"] == second_manifest["static_prefix_hash"]
    assert first_manifest["provider_hint"]["prompt_cache_key"] == second_manifest["provider_hint"]["prompt_cache_key"]

    _generate_verified_tuning(repo)
    pcodex.set_enabled(repo, True)
    pcodex.compile_pcodex_packet(
        repo,
        "Update login behavior.",
        "lite",
        tuning_profile=".premode/tuning/repo_profile.json",
    )
    tuned_manifest = read_cache_manifest(repo)["payload"]
    assert tuned_manifest["provider_hint"]["prompt_cache_key"] != first_manifest["provider_hint"]["prompt_cache_key"]


def test_doctor_and_status_expose_trust_screen_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    status = pcodex.status(repo)
    doctor = pcodex.doctor(repo)
    human = pcodex.format_doctor(doctor)

    assert status["effective_state"] == EFFECTIVE_ON_GENERALIZED
    assert status["packet"]["plugin_alias"] == "literal_symbol"
    assert status["lockfile"]["valid"] is True
    assert doctor["effective_state"] == EFFECTIVE_ON_GENERALIZED
    assert doctor["native_codex_integration"]["slash_commands"] == "not_native"
    assert "automatic MCP invocation are not assumed" in human


def test_model_facing_v5_packet_contract_stays_minimal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    before = compile_prompt(repo, RAW_PROMPT, "lite", **LITERAL_SYMBOL_KWARGS)
    pcodex.set_enabled(repo, True)
    after = compile_prompt(repo, RAW_PROMPT, "lite", **LITERAL_SYMBOL_KWARGS)

    assert after["packet"] == before["packet"]
    packet = after["packet"]
    assert RAW_PROMPT in packet
    assert "<TASK>" in packet
    assert "<PRIMARY_FILES>" in packet
    assert "<RELATED_TESTS>" in packet
    assert "<TASK_CLASS>" not in packet
    assert "<SUPPORT_RELATIONS>" not in packet
    assert "do-not-edit" not in packet.lower()


def test_explicit_flags_and_plugin_conflict_cli_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)

    explicit_code = cli.main(
        [
            "compile",
            RAW_PROMPT,
            "--repo",
            str(repo),
            "--packet-version",
            "v5",
            "--packet-variant",
            "tool_assisted_anchors_internal",
            "--packet-strategy",
            "literal_symbol",
            "--profile",
            "lite",
            "--json",
            "--no-record",
        ]
    )
    explicit_payload = json.loads(capsys.readouterr().out)
    assert explicit_code == 0
    assert explicit_payload["packet_version"] == "v5"
    assert explicit_payload["packet_variant"] == "tool_assisted_anchors_internal"

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "compile",
                RAW_PROMPT,
                "--repo",
                str(repo),
                "--plugin",
                "literal_symbol",
                "--packet-version",
                "v4",
                "--json",
                "--no-record",
            ]
        )
    assert exc.value.code == 2
    assert "premode: error:" in capsys.readouterr().err


def test_tuned_mode_requires_verify_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"

    with pytest.raises(PcodexStateError, match="Verified tuning is required"):
        pcodex.set_tuned(repo)

    assert not (repo / ".premode" / "pcodex_state.json").exists()
