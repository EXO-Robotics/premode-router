from __future__ import annotations

from pathlib import Path
import subprocess
import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Keep scope tight.\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.swift").write_text("struct App { let value = 1 }\n", encoding="utf-8")
    return tmp_path
