from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).parents[1] / "scripts" / "scouting_corpus.py"
SPEC = importlib.util.spec_from_file_location("scouting_corpus", SCRIPT)
assert SPEC and SPEC.loader
scouting_corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scouting_corpus)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def test_profile_and_five_task_self_tests(tmp_path: Path) -> None:
    repo = tmp_path / "fixture"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    files = {
        "src/app.py": 'MODE = "stable"\n\ndef enabled():\n    return True\n',
        "src/other.py": 'LABEL = "stable"\n',
        "tests/test_app.py": 'def test_mode():\n    assert "stable" == "stable"\n',
        "pyproject.toml": '[project]\nname = "fixture"\nversion = "1.0.0"\n',
        "docs/guide.md": '# Guide\n\nRun the "stable" mode.\n',
    }
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture")
    git(repo, "remote", "add", "origin", "https://example.invalid/fixture.git")

    profile = scouting_corpus.profile_repository(repo, "repo-01", "synthetic", "MIT")
    assert profile["tracked_files"] == 5
    assert profile["source_files"] == 2
    tasks = scouting_corpus.generate_tasks(repo, "repo-01", tmp_path / "corpus")
    assert [task["task_class"] for task in tasks] == list(scouting_corpus.TASK_CLASSES)
    results = [scouting_corpus.self_test_task(task, repo) for task in tasks]
    assert all(result["passed"] for result in results)


def test_discovery_stops_at_repository_boundary(tmp_path: Path) -> None:
    repo = tmp_path / "outer" / "repo"
    repo.mkdir(parents=True)
    git(repo, "init")
    nested = repo / "nested"
    nested.mkdir()
    git(nested, "init")
    assert scouting_corpus.discover_repositories([tmp_path], max_depth=5) == [repo.resolve()]
