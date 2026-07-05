from __future__ import annotations

import json
from pathlib import Path

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

    def __init__(self, name: str, metadata):
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
    monkeypatch.delenv("PCODEX_ALGORITHM", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG_PATH", raising=False)


def _make_repo(repo: Path) -> None:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text(
        "def build_config(completion=False):\n"
        "    return {\"completion\": completion}\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_app.py").write_text(
        "from src.app import build_config\n\n"
        "def test_completion_config():\n"
        "    assert build_config(completion=True)[\"completion\"] is True\n",
        encoding="utf-8",
    )


def test_pcodex_enabled_env_enables_status(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("PCODEX_ENABLED", "1")

    result = pcodex.status(repo)

    assert result["enabled"] is True
    assert result["config_source"] == "PCODEX_ENABLED"


def test_pcodex_enabled_env_disables_status(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("PCODEX_ENABLED", "0")

    result = pcodex.status(repo)

    assert result["enabled"] is False
    assert result["config_source"] == "PCODEX_ENABLED"


def test_env_override_wins_over_repo_config(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    monkeypatch.setenv("PCODEX_ENABLED", "0")

    result = pcodex.resolve_config(repo)

    assert result.enabled is False
    assert result.source == "PCODEX_ENABLED"


def test_repo_config_wins_over_default(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    result = pcodex.resolve_config(repo)

    assert result.enabled is True
    assert result.source == "repo"


def test_enabled_dry_run_includes_child_env_propagation(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))
    _make_repo(repo)
    pcodex.set_enabled(repo, True)

    result = pcodex.run_dry_run(repo, "Update build_config completion behavior in src/app.py.")

    assert result["codex_launch"] == "not_executed"
    assert result["child_env"]["PCODEX_ENABLED"] == "1"
    assert result["child_env"]["PCODEX_ALGORITHM"] == "literal_symbol"
    assert result["child_env"]["PCODEX_PACKET_STRATEGY"] == "literal_symbol"
    assert result["packet_path"]


def test_disabled_dry_run_does_not_compile_packet(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex.run_dry_run(repo, "Fix completion")

    assert result["codex_launch"] == "not_executed"
    assert result["child_env"]["PCODEX_ENABLED"] == "0"
    assert result["premode_command"] is None
    assert result["packet_path"] is None


def test_no_secret_like_env_vars_are_printed(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-appear")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-appear")
    pcodex.set_enabled(repo, False)

    result = pcodex.run_dry_run(repo, "Fix SECRET_TOKEN_123 without leaking PASSWORD_abc.")
    text = json.dumps(result)

    assert "should-not-appear" not in text
    assert "GITHUB_TOKEN" not in text
    assert "OPENAI_API_KEY" not in text
    assert "SECRET_TOKEN_123" not in text
    assert "PASSWORD_abc" not in text
    assert "<redacted>" in text


def test_nested_subagent_simulation_inherits_pcodex_env(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    parent = pcodex.run_dry_run(repo, "Fix completion")

    nested_env = {**parent["child_env"]}
    nested = pcodex.resolve_config(repo, env=nested_env)

    assert nested.enabled is True
    assert nested.algorithm == "literal_symbol"
    assert nested.source == "PCODEX_ENABLED"


def test_unknown_env_values_fail_safely(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("PCODEX_ENABLED", "maybe")

    result = pcodex.resolve_config(repo)

    assert result.enabled is False
    assert result.source == "PCODEX_ENABLED:invalid"


def test_unknown_algorithm_env_fails_safely(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("PCODEX_ALGORITHM", "other")

    result = pcodex.resolve_config(repo)

    assert result.enabled is False
    assert result.source == "PCODEX_ALGORITHM:invalid"


def test_no_lab_or_user_paths_are_baked_into_product_code() -> None:
    source = Path(pcodex.__file__).read_text(encoding="utf-8")

    assert "/private/tmp" not in source
    assert "/Users/" not in source
    assert "premode_labs" not in source


def test_packet_boundary_remains_clean(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))
    _make_repo(repo)

    compiled = pcodex.compile_pcodex_packet(repo, "Update build_config completion behavior in src/app.py.")
    packet = pcodex.compose_final_prompt("Update build_config completion behavior in src/app.py.", compiled["packet"])

    assert "PREMODE_CONTEXT_PACKET_V5" in packet
    assert "schema: ranked-paths-plus-anchors" in packet
    for forbidden in (
        "<TASK_CLASS>",
        "<SUPPORT_RELATIONS>",
        "<FILE ",
        "CONFIDENCE",
        "VALIDATION",
        "COMMANDS",
        "DO_NOT_EDIT",
        "diagnostics",
    ):
        assert forbidden not in packet
