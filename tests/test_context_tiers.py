from __future__ import annotations

import subprocess
from pathlib import Path

from premode.config import init_project
from premode.indexer import index_project
from premode.compiler import compile_prompt


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    return tmp_path


def _commit(repo: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True, text=True)


def test_compile_repair_uses_tiers_not_whole_source_tree_full_text(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "src").mkdir()
    for i in range(24):
        (repo / "src" / f"module_{i}.py").write_text(f"def f_{i}(): return {i}\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix the build", "lite")
    tiers = result["context_tiers"]
    source_full = [x for x in tiers["full_text_files"] if x["path"].startswith("src/")]
    assert len(source_full) < 5
    assert tiers["summarized_files"] or tiers["manifest_only_files"]
    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]


def test_dirty_file_becomes_full_text_and_related_files_are_compressed(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "foo.py").write_text("def foo(): return 1\n", encoding="utf-8")
    (repo / "tests" / "test_foo.py").write_text("from src.foo import foo\ndef test_foo(): assert foo() == 1\n", encoding="utf-8")
    _commit(repo)
    (repo / "src" / "foo.py").write_text("def foo(): return None\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix src/foo.py failing test", "lite")
    full_paths = {x["path"] for x in result["context_tiers"]["full_text_files"]}
    assert "src/foo.py" in full_paths
    assert "context_tiers" in result
    assert result["patch_boundary"]["allowed_edit_files"]


def test_packet_v2_evidence_boundary_and_metrics_exist(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    (repo / "logs").mkdir()
    (repo / "logs" / "build.log").write_text("pytest\nerror: src/app.py:1 cannot find MissingType\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix the build error", "lite")
    assert result["packet"].startswith("PREMODE_COMPILED_PACKET_V2")
    assert "## 3. Evidence summary" in result["packet"]
    assert result["evidence_summary"]["first_meaningful_error"]
    assert result["root_cause_hypotheses"]
    assert result["patch_boundary"]["forbidden_without_user_confirmation"]
    assert result["metrics"]["eligible_readable_repo_tokens"] >= result["metrics"]["full_text_tokens"]
