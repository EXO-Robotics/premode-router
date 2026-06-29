from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.cli import main
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.repo_map import build_repo_map, task_impact_hints


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def test_repo_map_extracts_python_ast_and_related_tests(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "src" / "premode").mkdir(parents=True)
    (repo / "src" / "premode" / "compiler.py").write_text(
        "import json\nfrom pathlib import Path\n\nclass Builder:\n    def run(self): return Path('.')\n\ndef compile_prompt(): return json.dumps({})\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_compiler.py").write_text("def test_compile_prompt(): assert True\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    info = repo_map["files"]["src/premode/compiler.py"]
    assert "json" in info["imports"]
    assert "Builder" in info["classes"]
    assert "compile_prompt" in info["functions"]
    assert "tests/test_compiler.py" in info["related_tests"]
    assert "content" not in json.dumps(info).lower()


def test_repo_map_extracts_cargo_entrypoint_for_cli(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "Cargo.toml").write_text(
        "[package]\nname='rg-fixture'\nversion='0.1.0'\n\n[[bin]]\nname='rg'\npath='crates/core/main.rs'\n",
        encoding="utf-8",
    )
    (repo / "crates" / "core").mkdir(parents=True)
    (repo / "crates" / "core" / "main.rs").write_text("use std::env;\nfn main() { let _args = env::args(); }\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    assert {e["path"] for e in repo_map["entrypoints"]} == {"crates/core/main.rs"}
    hints = task_impact_hints("Change CLI argument handling safely", repo_map)
    assert hints["likely_files"][0]["path"] == "crates/core/main.rs"


def test_compile_use_repo_map_promotes_manifest_entrypoint(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "Cargo.toml").write_text(
        "[package]\nname='rg-fixture'\nversion='0.1.0'\n\n[[bin]]\nname='rg'\npath='crates/core/main.rs'\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# rg fixture\n", encoding="utf-8")
    (repo / "crates" / "core").mkdir(parents=True)
    (repo / "crates" / "core" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(
        repo,
        "Find the right files for a safe Rust CLI patch that changes argument handling without touching packaging or release scripts.",
        "lite",
        use_repo_map=True,
    )
    selected = json.dumps(result["context_tiers"])
    assert "crates/core/main.rs" in selected
    assert result["impact_map"]["likely_files"][0]["path"] == "crates/core/main.rs"
    assert result["repo_map_summary"]["entrypoints"][0]["path"] == "crates/core/main.rs"


def test_repo_map_hash_is_stable_for_unchanged_repo(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='stable'\n", encoding="utf-8")
    (repo / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    monkeypatch.setenv("PREMODE_TEST_FIXED_TIME", "2026-01-01T00:00:00Z")
    first = build_repo_map(repo, idx["entries"], "lite")
    monkeypatch.setenv("PREMODE_TEST_FIXED_TIME", "2026-01-02T00:00:00Z")
    second = build_repo_map(repo, idx["entries"], "lite")
    assert first["repo_map_sha256"] == second["repo_map_sha256"]


def test_cli_map_json_and_out(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='cli-map'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def main(): return 0\n", encoding="utf-8")
    init_project(repo)
    monkeypatch.chdir(repo)
    assert main(["map", "--json", "--profile", "lite"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["file_count"] >= 2
    output_path = repo / ".premode" / "out" / "repo_map.json"
    assert main(["map", "--profile", "lite", "--out", str(output_path)]) == 0
    assert output_path.exists()
