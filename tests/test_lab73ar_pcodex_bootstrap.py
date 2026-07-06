from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from premode import pcodex_bootstrap as pcodex
from premode import plugins as plugin_module


PLUGIN_METADATA = {
    "name": "premode-plugin-literal-symbol",
    "strategy_id": "literal_symbol",
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
    "fallback_variant": "ranked_paths_plus_anchors",
    "fallback_strategy": None,
    "model_facing_sections": [
        "TASK",
        "PRIMARY_FILES",
        "RELATED_TESTS",
        "END_PREMODE_CONTEXT_PACKET_V5",
    ],
    "diagnostics_out_of_band": True,
    "private_package": True,
}


class FakeEntryPoint:
    group = "premode.plugins"
    value = "fake:get_plugin"

    def __init__(self, name: str, metadata: Any) -> None:
        self.name = name
        self._metadata = metadata

    def load(self):
        return lambda: self._metadata


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, *entry_points: FakeEntryPoint) -> None:
    monkeypatch.setattr(plugin_module.metadata, "entry_points", lambda: list(entry_points))


def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PCODEX_ENABLED", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)


def _make_repo(repo: Path) -> None:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "src" / "helpers.py").write_text("def normalize_shell(value):\n    return value.strip()\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text(
        "from src.helpers import normalize_shell\n\n"
        "def build_config(completion=False):\n"
        "    return {\"completion\": completion}\n\n"
        "def shell_completion(value):\n"
        "    return normalize_shell(value)\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_app.py").write_text(
        "from src.app import build_config\n\n"
        "def test_completion_config():\n"
        "    assert build_config(completion=True)[\"completion\"] is True\n",
        encoding="utf-8",
    )


def test_pcodex_doctor_detects_missing_codex_safely(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setattr(pcodex, "_command_available", lambda name: name != "codex")

    result = pcodex.doctor(repo)

    assert result["codex_executable_available"] is False
    assert result["premode_executable_available"] is True
    assert result["secrets_printed"] is False


def test_pcodex_doctor_detects_missing_premode_safely(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setattr(pcodex, "_command_available", lambda name: name != "premode")

    result = pcodex.doctor(repo)

    assert result["premode_executable_available"] is False
    assert result["codex_executable_available"] is True


def test_pcodex_status_reads_default_on_mode_without_state(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)

    result = pcodex.status(repo)

    assert result["enabled"] is True
    assert result["mode"] == "on"
    assert result["state_status"] == "missing_default"
    assert result["config_source"] == "default"
    assert result["algorithm"] == "literal_symbol"


def test_pcodex_on_enables_routing(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)

    result = pcodex.set_enabled(repo, True)

    assert result["enabled"] is True
    assert pcodex.resolve_config(repo).enabled is True


def test_pcodex_off_disables_routing(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex.set_enabled(repo, False)

    assert result["enabled"] is False
    assert pcodex.resolve_config(repo).enabled is False


def test_pcodex_compile_dry_run_uses_plugin_alias_when_available(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))

    assert pcodex.main(["compile", "Fix completion", "--repo", str(repo), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["route"] == "plugin_alias"
    assert "--plugin" in payload["premode_command"]
    assert "literal_symbol" in payload["premode_command"]


def test_pcodex_compile_dry_run_falls_back_to_explicit_flags(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    _patch_entry_points(monkeypatch)

    assert pcodex.main(["compile", "Fix completion", "--repo", str(repo), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["route"] == "explicit_fallback"
    assert "--packet-variant" in payload["premode_command"]
    assert "tool_assisted_anchors_internal" in payload["premode_command"]


def test_pcodex_run_dry_run_does_not_launch_live_codex(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex.run_dry_run(repo, "Fix completion")

    assert result["codex_launch"] == "not_executed"
    assert result["packet_path"] is None


def test_enabled_dry_run_includes_premode_packet_path(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    _make_repo(repo)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))
    pcodex.set_enabled(repo, True)

    result = pcodex.run_dry_run(repo, "Update build_config completion behavior in src/app.py.")

    assert result["packet_path"]
    assert Path(result["packet_path"]).exists()
    assert result["route"] == "plugin_alias"


def test_disabled_dry_run_does_not_include_premode_packet_path(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex.run_dry_run(repo, "Fix completion")

    assert result["enabled"] is False
    assert result["packet_path"] is None
    assert result["premode_command"] is None


def test_no_secrets_are_printed(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex.run_dry_run(repo, "Fix SECRET_TOKEN_123 without leaking PASSWORD_abc.")
    text = json.dumps(result)

    assert "SECRET_TOKEN_123" not in text
    assert "PASSWORD_abc" not in text
    assert "<redacted>" in text


def test_no_lab_or_user_paths_are_baked_into_product_code() -> None:
    source = Path(pcodex.__file__).read_text(encoding="utf-8")

    assert "/private/tmp" not in source
    assert "/Users/" not in source
    assert "premode_labs" not in source


def test_generated_prompt_preserves_model_facing_packet_boundary(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    _make_repo(repo)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))

    compiled = pcodex.compile_pcodex_packet(repo, "Update build_config completion behavior in src/app.py.")
    packet = pcodex.compose_final_prompt("Update build_config completion behavior in src/app.py.", compiled["packet"])

    assert "PREMODE_CONTEXT_PACKET_V5" in packet
    assert "schema: ranked-paths-plus-anchors" in packet
    assert "<TASK>" in packet
    assert "<PRIMARY_FILES>" in packet
    assert "<RELATED_TESTS>" in packet
    assert "<END_PREMODE_CONTEXT_PACKET_V5>" in packet
    for forbidden in (
        "<TASK_CLASS>",
        "<SUPPORT_RELATIONS>",
        "<FILE ",
        "CONFIDENCE",
        "VALIDATION",
        "COMMANDS",
        "DO_NOT_EDIT",
    ):
        assert forbidden not in packet


def test_install_command_defaults_to_dry_run(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)

    result = pcodex.install(repo, dry_run=True)

    assert result["status"] == "dry_run"
    assert result["written"] is False
    assert result["would_write"] is True
    assert not (repo / ".pcodex" / "config.toml").exists()


def test_install_apply_writes_repo_local_config(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)

    result = pcodex.install(repo, dry_run=False)

    config_path = repo / ".pcodex" / "config.toml"
    assert result["status"] == "installed"
    assert result["written"] is True
    assert Path(result["config_path"]) == config_path
    assert config_path.exists()
    assert "algorithm = \"literal_symbol\"" in config_path.read_text(encoding="utf-8")


def test_status_reports_literal_symbol_algorithm(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)

    result = pcodex.status(repo)

    assert result["algorithm"] == "literal_symbol"


def test_unknown_config_values_fail_safely_to_default_off(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    path = repo / ".pcodex" / "config.toml"
    path.parent.mkdir()
    path.write_text("[pcodex]\nenabled = \"maybe\"\n", encoding="utf-8")

    result = pcodex.resolve_config(repo)

    assert result.enabled is False
    assert result.source == "repo:invalid"
