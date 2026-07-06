from __future__ import annotations

from pathlib import Path

from premode import pcodex_bootstrap as pcodex


def test_parse_codex_cli_semver() -> None:
    assert pcodex.parse_codex_cli_version("codex-cli 0.142.5") == "0.142.5"
    assert pcodex.parse_codex_cli_version("OpenAI Codex v0.142.5") == "0.142.5"


def test_warns_for_old_codex_cli_version() -> None:
    warning = pcodex.codex_cli_version_warning("0.121.0")

    assert warning is not None
    assert "older than 0.142.5" in warning
    assert "direct codex exec" in warning


def test_current_codex_cli_version_has_no_warning() -> None:
    assert pcodex.codex_cli_version_warning("0.142.5") is None
    assert pcodex.codex_cli_version_warning("0.150.0") is None


def test_codex_config_detects_default_service_tier(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('service_tier = "default"\n', encoding="utf-8")

    result = pcodex.inspect_codex_config(path)

    assert result["exists"] is True
    assert result["readable"] is True
    assert result["service_tier"] == "default"
    assert "may be incompatible" in str(result["service_tier_warning"])


def test_codex_config_accepts_flex_service_tier(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('service_tier = "flex"\n', encoding="utf-8")

    result = pcodex.inspect_codex_config(path)

    assert result["service_tier"] == "flex"
    assert result["service_tier_warning"] is None


def test_codex_config_handles_missing_config(tmp_path: Path) -> None:
    result = pcodex.inspect_codex_config(tmp_path / "missing.toml")

    assert result["exists"] is False
    assert result["readable"] is False
    assert result["service_tier"] is None
    assert result["service_tier_warning"] is None


def test_codex_config_handles_invalid_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("service_tier = [\n", encoding="utf-8")

    result = pcodex.inspect_codex_config(path)

    assert result["exists"] is True
    assert result["readable"] is False
    assert result["service_tier"] is None
    assert "Could not read Codex config safely" in str(result["service_tier_warning"])


def test_codex_config_handles_unreadable_config_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.mkdir()

    result = pcodex.inspect_codex_config(path)

    assert result["exists"] is True
    assert result["readable"] is False
    assert result["service_tier"] is None
    assert "Could not read Codex config safely" in str(result["service_tier_warning"])
