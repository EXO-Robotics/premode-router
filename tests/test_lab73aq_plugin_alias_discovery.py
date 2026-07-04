from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from premode import cli
from premode import plugins as plugin_module
from premode.config import init_project
from premode.indexer import index_project
from premode.plugins import PluginAliasError, resolve_packet_plugin


ROOT = Path(__file__).resolve().parents[1]


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


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _make_repo(repo: Path) -> None:
    _write(
        repo / "src" / "helpers.py",
        """
def normalize_shell(value):
    return value.strip()
""",
    )
    _write(
        repo / "src" / "app.py",
        """
from src.helpers import normalize_shell

def build_config(completion=False):
    return {"completion": completion}

def shell_completion(value):
    return normalize_shell(value)
""",
    )
    _write(
        repo / "tests" / "test_app.py",
        """
from src.app import build_config, shell_completion

def test_completion_config():
    assert build_config(completion=True)["completion"] is True

def test_shell_completion():
    assert shell_completion(" zsh ") == "zsh"
""",
    )
    _write(repo / "README.md", "# Completion\n\nShell completion is documented here.")
    init_project(repo)
    index_project(repo, "lite")


def test_plugin_discovery_loads_mocked_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))

    resolved = resolve_packet_plugin("literal_symbol")

    assert resolved.as_dict() == {
        "plugin_name": "literal_symbol",
        "plugin_package": "premode-plugin-literal-symbol",
        "packet_version": "v5",
        "packet_variant": "tool_assisted_anchors_internal",
        "packet_strategy": "literal_symbol",
    }


def test_literal_symbol_alias_resolves_to_core_packet_options(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))

    resolved = resolve_packet_plugin(
        "literal_symbol",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
    )

    assert resolved.packet_version == "v5"
    assert resolved.packet_variant == "tool_assisted_anchors_internal"
    assert resolved.packet_strategy == "literal_symbol"


def test_explicit_compile_flags_still_work_without_plugin_alias(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_repo(repo)

    rc = cli.main(
        [
            "compile",
            "Update build_config completion behavior in src/app.py.",
            "--repo",
            str(repo),
            "--profile",
            "lite",
            "--packet-version",
            "v5",
            "--packet-variant",
            "tool_assisted_anchors_internal",
            "--packet-strategy",
            "literal_symbol",
            "--json",
            "--no-record",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packet_variant"] == "tool_assisted_anchors_internal"
    assert payload["metrics"]["strategy_selected"] == "literal_symbol"
    assert "plugin_alias_resolution" not in payload


def test_compile_plugin_alias_with_matching_explicit_flag_works(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _make_repo(repo)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))

    rc = cli.main(
        [
            "compile",
            "Update build_config completion behavior in src/app.py.",
            "--repo",
            str(repo),
            "--profile",
            "lite",
            "--plugin",
            "literal_symbol",
            "--packet-version",
            "v5",
            "--json",
            "--no-record",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plugin_alias_resolution"]["packet_variant"] == "tool_assisted_anchors_internal"
    assert payload["metrics"]["strategy_selected"] == "literal_symbol"


def test_plugin_alias_with_conflicting_packet_variant_fails(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _make_repo(repo)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))

    with pytest.raises(SystemExit) as excinfo:
        cli.main(
            [
                "compile",
                "Update build_config completion behavior in src/app.py.",
                "--repo",
                str(repo),
                "--plugin",
                "literal_symbol",
                "--packet-variant",
                "ranked_paths_plus_anchors",
                "--no-record",
            ]
        )

    assert excinfo.value.code == 2
    assert "conflicts with explicit packet options" in capsys.readouterr().err


def test_unknown_plugin_alias_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))

    with pytest.raises(PluginAliasError, match="Unknown Pre-mode plugin alias 'missing'"):
        resolve_packet_plugin("missing")


def test_invalid_plugin_metadata_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = dict(PLUGIN_METADATA)
    invalid.pop("packet_strategy")
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", invalid))

    with pytest.raises(PluginAliasError, match="packet_strategy"):
        resolve_packet_plugin("literal_symbol")


def test_duplicate_alias_fails_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(
        monkeypatch,
        FakeEntryPoint("literal_symbol", PLUGIN_METADATA),
        FakeEntryPoint("literal_symbol", PLUGIN_METADATA),
    )

    with pytest.raises(PluginAliasError, match="Duplicate Pre-mode plugin alias"):
        resolve_packet_plugin("literal_symbol")


def test_package_get_plugin_metadata_still_matches_alias_contract() -> None:
    sys.path.insert(0, str(ROOT / "packages" / "premode-plugin-literal-symbol" / "src"))
    from premode_plugin_literal_symbol.plugin import get_plugin

    metadata = get_plugin()
    assert metadata["strategy_id"] == "literal_symbol"
    assert metadata["packet_variant"] == "tool_assisted_anchors_internal"
    assert metadata["packet_strategy"] == "literal_symbol"
    assert metadata["private_package"] is True


def test_model_facing_packet_is_unchanged_for_alias_invocation(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_repo(repo)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))
    prompt = "Update build_config completion behavior in src/app.py."
    alias_packet = tmp_path / "alias_packet.txt"
    explicit_packet = tmp_path / "explicit_packet.txt"

    assert cli.main(["compile", prompt, "--repo", str(repo), "--profile", "lite", "--plugin", "literal_symbol", "--out", str(alias_packet), "--no-record"]) == 0
    assert cli.main(
        [
            "compile",
            prompt,
            "--repo",
            str(repo),
            "--profile",
            "lite",
            "--packet-version",
            "v5",
            "--packet-variant",
            "tool_assisted_anchors_internal",
            "--packet-strategy",
            "literal_symbol",
            "--out",
            str(explicit_packet),
            "--no-record",
        ]
    ) == 0

    packet = alias_packet.read_text(encoding="utf-8")
    assert packet == explicit_packet.read_text(encoding="utf-8")
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


def test_alias_discovery_metadata_has_no_lab_or_local_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))
    resolved = resolve_packet_plugin("literal_symbol").as_dict()

    metadata_text = repr(resolved)
    assert "/private/tmp" not in metadata_text
    assert "premode_labs" not in metadata_text
    assert "/Users/" not in metadata_text
    assert "Local Context Compiler" not in metadata_text


def test_cli_help_includes_plugin_alias_flag() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "premode.cli", "compile", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert proc.returncode == 0
    assert "--plugin" in proc.stdout
    assert "Resolve packet options from an installed Pre-mode plugin alias" in " ".join(proc.stdout.split())


def test_benchmark_explicit_flags_still_work(repo: Path) -> None:
    _make_repo(repo)

    rc = cli.main(
        [
            "benchmark",
            "--repo",
            str(repo),
            "--profile",
            "lite",
            "--packet-version",
            "v5",
            "--packet-variant",
            "tool_assisted_anchors_internal",
            "--packet-strategy",
            "literal_symbol",
            "--json",
        ]
    )

    assert rc == 0


def test_benchmark_plugin_alias_works(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _make_repo(repo)
    _patch_entry_points(monkeypatch, FakeEntryPoint("literal_symbol", PLUGIN_METADATA))

    rc = cli.main(["benchmark", "--repo", str(repo), "--profile", "lite", "--plugin", "literal_symbol", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plugin_alias_resolution"]["packet_strategy"] == "literal_symbol"
    assert payload["packet_variant_requested"] == "tool_assisted_anchors_internal"
