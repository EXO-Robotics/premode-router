from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.repo_map import build_repo_map, estimate_repo_map_json_bytes, limit_repo_map_files, summarize_repo_map


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def test_map_summary_json_shape_is_compact(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n[project.scripts]\nx='x.cli:main'\n", encoding="utf-8")
    (repo / "x").mkdir()
    (repo / "x" / "cli.py").write_text("def main(): return 0\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    summary = summarize_repo_map(repo_map)
    assert summary["repo_map_sha256"]
    assert summary["file_count"] >= 2
    assert "languages" in summary
    assert "files" not in summary
    assert "edges" not in summary


def test_map_json_max_files_caps_file_output(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "pkg").mkdir()
    for i in range(15):
        (repo / "pkg" / f"m{i}.py").write_text(f"def f{i}(): return {i}\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    limited = limit_repo_map_files(repo_map, 5)
    assert len(limited["files"]) == 5
    assert limited["omitted_file_count"] >= 10
    assert estimate_repo_map_json_bytes(limited) < estimate_repo_map_json_bytes(repo_map)


def test_cli_map_summary_json_and_max_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "x.py").write_text("def main(): return 0\n", encoding="utf-8")
    init_project(repo)
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    summary = subprocess.run(
        [sys.executable, "-m", "premode", "map", "--summary-json"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "repo_map_sha256" in json.loads(summary.stdout)
    capped = subprocess.run(
        [sys.executable, "-m", "premode", "map", "--json", "--max-files", "1"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(capped.stdout)["included_file_count"] == 1


def test_compile_returns_context_receipt_and_why_included(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n[project.scripts]\nx='x.cli:main'\n", encoding="utf-8")
    (repo / "x").mkdir()
    (repo / "x" / "cli.py").write_text("def main(): return 0\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_cli.py").write_text("from x.cli import main\ndef test_main(): assert main() == 0\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Find the right files for a safe Python CLI patch that changes argument handling.", "lite", use_repo_map=True)
    receipt = result["context_receipt"]
    assert receipt["packet_total_tokens"] == result["metrics"]["packet_total_tokens"]
    assert receipt["repo_map_enabled"] is True
    chosen = result["context_tiers"]["summarized_files"] + result["context_tiers"]["full_text_files"]
    assert chosen
    assert all(item.get("why_included") for item in chosen)


def test_large_guidance_file_is_not_full_text_without_direct_evidence(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "README.md").write_text("# Huge docs\n" + ("details\n" * 9000), encoding="utf-8")
    (repo / "pkg.py").write_text("def fix_me(): return 1\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix pkg.py only.", "lite", use_repo_map=False)
    full_paths = {item["path"] for item in result["context_tiers"]["full_text_files"]}
    assert "README.md" not in full_paths
    candidates = result["context_tiers"]["summarized_files"] + result["context_tiers"]["manifest_only_files"]
    readme = next(item for item in candidates if item["path"] == "README.md")
    if readme["tier"] == "summary":
        assert "large file summarized" in readme.get("reason", "")
    else:
        assert "large_file" in readme.get("why_excluded", [])
