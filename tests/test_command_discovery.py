from __future__ import annotations

import subprocess
from pathlib import Path

from premode.adapters import detect_projects, load_commands
from premode.command_discovery import discover_commands
from premode.config import init_project
from premode.indexer import index_project


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def test_python_command_discovery_only_suggests_configured_ruff_and_mypy(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    commands = discover_commands(repo, detection)["commands"]
    assert commands["test"]["command"] == "pytest"
    assert commands["lint"]["command"] == "ruff check ."
    assert commands["typecheck"]["command"] == "mypy ."


def test_python_command_discovery_does_not_fake_ruff_when_absent(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    commands = load_commands(repo)
    assert "lint" not in commands["commands"]


def test_node_command_discovery_uses_package_manager_and_scripts(tmp_path):
    repo = _repo(tmp_path)
    (repo / "package.json").write_text('{"scripts":{"build":"vite build","test":"vitest","lint":"eslint .","typecheck":"tsc --noEmit"}}\n', encoding="utf-8")
    (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.ts").write_text("export const x = 1\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    commands = discover_commands(repo, detection)
    assert commands["package_manager"] == "pnpm"
    assert commands["commands"]["build"]["command"] == "pnpm run build"
    assert commands["commands"]["test"]["command"] == "pnpm test"
    assert commands["commands"]["typecheck"]["command"] == "pnpm run typecheck"
