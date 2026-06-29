from __future__ import annotations

import subprocess
from pathlib import Path

from premode.config import init_project
from premode.indexer import index_project
from premode.adapters import detect_projects, load_commands
from premode.compiler import compile_prompt


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def test_detect_ios_swift_adapter(tmp_path):
    repo = _repo(tmp_path)
    (repo / "App.xcodeproj").mkdir()
    (repo / "Sources").mkdir()
    (repo / "Sources" / "App.swift").write_text("struct App {}\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "ios_swift"
    packet = compile_prompt(repo, "Fix the xcodebuild compile error", "lite")["packet"]
    assert "ios_swift" in packet
    assert "xcodebuild" in packet


def test_detect_node_adapter(tmp_path):
    repo = _repo(tmp_path)
    (repo / "package.json").write_text('{"scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.ts").write_text("export const x = 1\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "node"
    result = compile_prompt(repo, "Fix the TypeScript build error", "lite")
    assert "npm" in result["packet"] or "node" in result["packet"]


def test_detect_python_adapter_and_commands(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    commands = load_commands(repo)
    assert "pytest" in str(commands) or "ruff" in str(commands)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "python"


def test_generic_fallback_packet_shape(tmp_path):
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# Unknown\n", encoding="utf-8")
    (repo / "notes.custom").write_text("hello\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Review this repo", "lite")
    assert result["project_detection"]["active_project"]["project_kind"] == "generic"
    assert result["packet"].startswith("PREMODE_COMPILED_PACKET_V2")


def test_multi_project_detection(tmp_path):
    repo = _repo(tmp_path)
    (repo / "ios").mkdir()
    (repo / "ios" / "App.xcodeproj").mkdir()
    (repo / "ios" / "App.swift").write_text("struct App {}\n", encoding="utf-8")
    (repo / "web").mkdir()
    (repo / "web" / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "web" / "main.ts").write_text("export {}\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["repo_kind"] == "multi_project"
    kinds = {d["project_kind"] for d in detection["detected_projects"]}
    assert {"ios_swift", "node"}.issubset(kinds)


def test_rules_and_memory_included(tmp_path):
    repo = _repo(tmp_path)
    init_project(repo)
    (repo / ".premode" / "rules.md").write_text("Always keep patches tiny.\n", encoding="utf-8")
    (repo / ".premode" / "memory" / "project_memory.md").write_text("Last good state: green.\n", encoding="utf-8")
    index_project(repo, "lite")
    packet = compile_prompt(repo, "Fix the build", "lite")["packet"]
    assert "Always keep patches tiny" in packet
    assert "Last good state" in packet


def test_marker_root_priority_pyproject_at_repo_root(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "python"
    assert detection["active_project"]["root"] == "."
    assert detection["active_project"]["root_selection"]["strategy"] == "primary_marker"


def test_marker_root_priority_package_json_in_subdir(tmp_path):
    repo = _repo(tmp_path)
    (repo / "web").mkdir()
    (repo / "web" / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "web" / "src").mkdir()
    (repo / "web" / "src" / "main.ts").write_text("export {}\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "node"
    assert detection["active_project"]["root"] == "web"


def test_marker_root_priority_xcodeproj_in_subdir(tmp_path):
    repo = _repo(tmp_path)
    (repo / "ios").mkdir()
    (repo / "ios" / "App.xcodeproj").mkdir()
    (repo / "ios" / "App.swift").write_text("struct App {}\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "ios_swift"
    assert detection["active_project"]["root"] == "ios"


def test_marker_root_priority_package_swift_at_root(tmp_path):
    repo = _repo(tmp_path)
    (repo / "Package.swift").write_text("// swift-tools-version: 6.0\n", encoding="utf-8")
    (repo / "Sources").mkdir()
    (repo / "Sources" / "Lib.swift").write_text("public struct Lib {}\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "ios_swift"
    assert detection["active_project"]["root"] == "."


def test_source_only_python_fallback_stays_safe(tmp_path):
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "python"
    assert detection["active_project"]["root"] in {"src", "."}
    assert detection["active_project"]["root_selection"]["strategy"] == "source_frequency"
