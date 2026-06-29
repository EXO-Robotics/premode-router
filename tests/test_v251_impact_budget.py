from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.repo_map import build_repo_map, compact_repo_map_summary, task_impact_hints


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def test_lite_repo_map_summary_omits_broad_notable_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n[project.scripts]\nx='x.cli:main'\n", encoding="utf-8")
    (repo / "src" / "x").mkdir(parents=True)
    (repo / "src" / "x" / "cli.py").write_text("def main(): return 0\n", encoding="utf-8")
    for i in range(20):
        (repo / "src" / "x" / f"module_{i}.py").write_text(f"class C{i}: pass\ndef f{i}(): return {i}\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    impact = task_impact_hints("Change CLI argument handling", repo_map)
    summary = compact_repo_map_summary(repo_map, profile_name="lite", impact_map=impact)
    assert "notable_files" not in summary
    assert summary["likely_files"][0]["path"] == "src/x/cli.py"
    assert summary["omitted_repo_map_detail_count"] >= 20


def test_compile_with_repo_map_stays_under_lite_budget(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n[project.scripts]\nx='x.cli:main'\n", encoding="utf-8")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    (repo / "src" / "x").mkdir(parents=True)
    (repo / "src" / "x" / "cli.py").write_text("def main(): return 0\n", encoding="utf-8")
    for i in range(60):
        (repo / "src" / "x" / f"module_{i}.py").write_text(
            f"import x.cli\nclass C{i}: pass\ndef f{i}(): return {i}\n", encoding="utf-8"
        )
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Find the right files for a safe CLI patch that changes argument handling.", "lite", use_repo_map=True)
    assert result["metrics"]["budget_exceeded_by"] == 0
    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]
    assert result["repo_map_summary"]["summary_profile"] == "lite"
    assert "notable_files" not in result["repo_map_summary"]
    assert result["impact_map"]["verification_order"]
    assert result["impact_map"]["full_text_guardrail"] == "repo-map relevance alone does not promote files to full text"


def test_impact_map_reports_dependencies_and_dependents(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n[project.scripts]\nx='x.cli:main'\n", encoding="utf-8")
    (repo / "src" / "x").mkdir(parents=True)
    (repo / "src" / "x" / "cli.py").write_text("from x.core import parse_args\ndef main(): return parse_args()\n", encoding="utf-8")
    (repo / "src" / "x" / "core.py").write_text("def parse_args(): return 0\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_cli.py").write_text("def test_main(): assert True\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    impact = task_impact_hints("Change CLI argument handling", repo_map)
    assert impact["likely_files"][0]["path"] == "src/x/cli.py"
    assert any(edge["to"] == "src/x/core.py" for edge in impact["direct_dependencies"])
    assert any(item["command"] == "python -m pytest" for item in impact["verification_order"])
    assert "direct_dependents" in impact
