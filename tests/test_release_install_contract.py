from __future__ import annotations

import os
import ast
from pathlib import Path, PurePosixPath
import re
import tomllib
import zipfile

import premode
from premode.locator import LocatedFile, LocateResult, locate_files


ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "0.3.0b1"


def _project_metadata() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


def test_release_version_is_synchronized():
    project = _project_metadata()
    assert project["version"] == RELEASE_VERSION
    assert premode.__version__ == RELEASE_VERSION


def test_core_install_has_no_runtime_dependency_or_optional_ranker_requirement():
    project = _project_metadata()
    assert project["dependencies"] == []
    assert callable(locate_files)
    assert LocatedFile.__module__ == "premode.locator"
    assert LocateResult.__module__ == "premode.locator"


def test_release_console_scripts_are_declared():
    project = _project_metadata()
    assert project["scripts"] == {
        "premode": "premode.cli:main",
        "pcodex": "premode.pcodex_bootstrap:main",
    }


def _wheel_path_from_environment() -> Path | None:
    value = os.environ.get("PREMODE_RELEASE_WHEEL")
    if not value:
        return None
    wheel = Path(value)
    assert wheel.is_file(), f"PREMODE_RELEASE_WHEEL is not a file: {wheel}"
    return wheel


def _production_modules() -> set[str]:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "PRODUCTION_MODULES" for target in node.targets):
            call = node.value
            assert isinstance(call, ast.Call) and call.args
            return set(ast.literal_eval(call.args[0]))
    raise AssertionError("setup.py does not define PRODUCTION_MODULES")


def _expected_wheel_members() -> set[str]:
    package = {f"premode/{name}.py" for name in _production_modules()}
    dist = "premode_router-0.3.0b1.dist-info"
    metadata = {f"{dist}/{name}" for name in ("METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD", "licenses/LICENSE")}
    return package | metadata


def test_release_wheel_artifact_allowlist_when_supplied():
    wheel = _wheel_path_from_environment()
    if wheel is None:
        return

    with zipfile.ZipFile(wheel) as archive:
        members = sorted(name for name in archive.namelist() if not name.endswith("/"))

    assert members
    assert "premode/__init__.py" in members
    assert any(name.endswith(".dist-info/METADATA") for name in members)
    assert set(members) == _expected_wheel_members()
    assert not any(name.startswith("premode/lab") or name in {"premode/benchmark.py", "premode/live_token_harness.py", "premode/sharded_runner.py"} for name in members)
