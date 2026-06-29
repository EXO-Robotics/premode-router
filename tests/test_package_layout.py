from pathlib import Path


def test_package_imports_from_dunder_init():
    import premode
    assert premode.__version__


def test_no_init_py_file_exists():
    import premode
    pkg = Path(premode.__file__).parent
    assert (pkg / "__init__.py").exists()
    assert not (pkg / "init.py").exists()
