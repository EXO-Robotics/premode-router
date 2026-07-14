from pathlib import Path

import pytest

from premode.cli import main
from premode import plugins


class _EntryPoint:
    name = "literal_symbol"

    def __init__(self, metadata):
        self.metadata = metadata

    def load(self):
        return lambda: self.metadata


def test_core_install_includes_stable_default_without_entry_point(monkeypatch):
    monkeypatch.setattr(plugins, "_entry_points", lambda group=plugins.ENTRY_POINT_GROUP: [])

    assert "literal_symbol" in plugins.available_plugin_aliases()
    resolved = plugins.resolve_packet_plugin("literal_symbol")

    assert resolved.plugin_package == "premode-router"
    assert resolved.packet_version == "v5"
    assert resolved.packet_variant == "tool_assisted_anchors_internal"
    assert resolved.packet_strategy == "literal_symbol"


def test_compatible_legacy_default_cannot_override_bundled_authority(monkeypatch):
    legacy = _EntryPoint({
        "name": "legacy-package",
        "strategy_id": "literal_symbol",
        "packet_version": "v5",
        "packet_variant": "tool_assisted_anchors_internal",
        "packet_strategy": "literal_symbol",
    })
    monkeypatch.setattr(plugins, "_entry_points", lambda group=plugins.ENTRY_POINT_GROUP: [legacy])

    assert plugins.resolve_packet_plugin("literal_symbol").plugin_package == "premode-router"


def test_legacy_default_with_conflicting_declared_schema_fails_closed(monkeypatch):
    legacy = _EntryPoint({
        "name": "legacy-package",
        "strategy_id": "literal_symbol",
        "packet_version": "v5",
        "packet_variant": "tool_assisted_anchors_internal",
        "packet_strategy": "literal_symbol",
        "schema_version": "future.v2",
    })
    monkeypatch.setattr(plugins, "_entry_points", lambda group=plugins.ENTRY_POINT_GROUP: [legacy])

    with pytest.raises(plugins.PluginAliasError, match="schema_version"):
        plugins.resolve_packet_plugin("literal_symbol")


def test_legacy_third_party_entry_point_adapts_to_v1_descriptor(monkeypatch):
    legacy = _EntryPoint({
        "name": "third-party-package",
        "strategy_id": "third_party",
        "packet_version": "v5",
        "packet_variant": "tool_assisted_anchors_internal",
        "packet_strategy": "literal_symbol",
    })
    legacy.name = "third_party"
    monkeypatch.setattr(plugins, "_entry_points", lambda group=plugins.ENTRY_POINT_GROUP: [legacy])

    resolved = plugins.resolve_packet_plugin("third_party")

    assert resolved.schema_version == plugins.PACKET_STRATEGY_PLUGIN_SCHEMA_VERSION
    assert resolved.sensitivity_classification == "public_safe"
    assert resolved.plugin_package == "third-party-package"


def test_third_party_entry_point_with_unknown_declared_schema_fails_closed(monkeypatch):
    legacy = _EntryPoint({
        "name": "third-party-package",
        "strategy_id": "third_party",
        "packet_version": "v5",
        "packet_variant": "tool_assisted_anchors_internal",
        "packet_strategy": "literal_symbol",
        "schema_version": "future.v2",
    })
    legacy.name = "third_party"
    monkeypatch.setattr(plugins, "_entry_points", lambda group=plugins.ENTRY_POINT_GROUP: [legacy])

    with pytest.raises(plugins.PluginAliasError, match="unsupported schema_version"):
        plugins.resolve_packet_plugin("third_party")


def test_conflicting_legacy_default_fails_closed(monkeypatch):
    legacy = _EntryPoint({
        "name": "legacy-package",
        "strategy_id": "literal_symbol",
        "packet_version": "v4",
        "packet_variant": "other",
        "packet_strategy": "other",
    })
    monkeypatch.setattr(plugins, "_entry_points", lambda group=plugins.ENTRY_POINT_GROUP: [legacy])

    with pytest.raises(plugins.PluginAliasError, match="conflicts with the bundled stable default"):
        plugins.resolve_packet_plugin("literal_symbol")


def test_package_imports_from_dunder_init():
    import premode
    assert premode.__version__


def test_no_init_py_file_exists():
    import premode
    pkg = Path(premode.__file__).parent
    assert (pkg / "__init__.py").exists()
    assert not (pkg / "init.py").exists()


def test_cli_version_flag_prints_package_version(capsys):
    import premode
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"premode {premode.__version__}"
