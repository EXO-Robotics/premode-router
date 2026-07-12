from pathlib import Path

import pytest

from premode.cli import main
from premode import plugins


def test_core_install_includes_stable_default_without_entry_point(monkeypatch):
    monkeypatch.setattr(plugins, "_entry_points", lambda group=plugins.ENTRY_POINT_GROUP: [])

    assert "literal_symbol" in plugins.available_plugin_aliases()
    resolved = plugins.resolve_packet_plugin("literal_symbol")

    assert resolved.plugin_package == "premode-router"
    assert resolved.packet_version == "v5"
    assert resolved.packet_variant == "tool_assisted_anchors_internal"
    assert resolved.packet_strategy == "literal_symbol"


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
