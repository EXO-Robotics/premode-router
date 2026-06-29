from pathlib import Path

import pytest

from premode.cli import main


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
