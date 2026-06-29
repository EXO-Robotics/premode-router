from __future__ import annotations

from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.repo_map import build_repo_map, task_impact_hints


def _make_ignore_boundary_fixture(root: Path) -> None:
    native = root / "app_native"
    (native / ".git").mkdir(parents=True)
    (native / "Source" / "Player").mkdir(parents=True)
    (native / "Source" / "Player" / "Movement.cpp").write_text("void MovePlayer() {}\n", encoding="utf-8")
    (native / "Source" / "Player" / "Movement.h").write_text("void MovePlayer();\n", encoding="utf-8")

    ios = root / "app_ios"
    (ios / ".git").mkdir(parents=True)
    (ios / "App.xcodeproj").mkdir()
    (ios / "Sources").mkdir()
    (ios / "Sources" / "View.swift").write_text("struct View {}\n", encoding="utf-8")

    external = root / "_external_references" / "vendor" / "upstream"
    (external / "agent" / "tools").mkdir(parents=True)
    (external / "agent" / "tools" / "edit_code.py").write_text("def edit_code(): return None\n", encoding="utf-8")
    (external / "agent" / "tools" / "base.py").write_text("def base(): return None\n", encoding="utf-8")
    (external / "viewer" / "api").mkdir(parents=True)
    (external / "viewer" / "api" / "browse_index.ts").write_text("export function browseIndex() {}\n", encoding="utf-8")
    (external / "tests").mkdir()
    (external / "tests" / "test_tool.py").write_text("def test_tool(): assert True\n", encoding="utf-8")

    (root / "node_modules" / "react").mkdir(parents=True)
    (root / "node_modules" / "react" / "package.json").write_text('{"name":"react"}\n', encoding="utf-8")


def _impact(root: Path, prompt: str) -> dict:
    init_project(root)
    idx = index_project(root, "lite")
    repo_map = build_repo_map(root, idx["entries"], "lite")
    return task_impact_hints(prompt, repo_map)


def _paths(items: list[dict]) -> list[str]:
    return [str(item.get("path")) for item in items if item.get("path")]


def _commands(items: list[dict]) -> list[str]:
    return [str(item.get("command")) for item in items if item.get("command")]


def test_v2613_native_prompt_excludes_external_references_from_routing(tmp_path: Path) -> None:
    _make_ignore_boundary_fixture(tmp_path)
    prompt = "Find likely files for a small native C++ gameplay bug. Avoid external references and node_modules."
    impact = _impact(tmp_path, prompt)

    likely = _paths(impact["likely_files"])
    related = _paths(impact["related_tests"])
    verify = _commands(impact["verification_order"])
    assert not any("_external_references" in path for path in likely)
    assert not any("_external_references" in path for path in related)
    assert not any("_external_references" in command for command in verify)
    assert not any("node_modules" in path for path in likely + related)
    assert not likely or "app_native/Source/Player/Movement.cpp" in likely
    assert impact["routing_filter_diagnostics"]["negative_boundary_prompt"] is True

    result = compile_prompt(tmp_path, prompt, "lite", use_repo_map=True)
    selected = [item.get("path") for tier in result["context_tiers"].values() for item in tier]
    assert not any(str(path).startswith("_external_references/") for path in selected)
    assert not any("node_modules" in str(path) for path in selected)


def test_v2613_web_prompt_does_not_fallback_to_external_web_repo(tmp_path: Path) -> None:
    _make_ignore_boundary_fixture(tmp_path)
    prompt = "Find likely files for a TypeScript web UI bug. Avoid external references and node_modules."
    impact = _impact(tmp_path, prompt)

    likely = _paths(impact["likely_files"])
    related = _paths(impact["related_tests"])
    verify = _commands(impact["verification_order"])
    assert not any("_external_references" in path for path in likely)
    assert not any("_external_references" in path for path in related)
    assert not any("_external_references" in command for command in verify)
    assert not any("node_modules" in path for path in likely + related)
    assert impact["routing_filter_diagnostics"]["negative_boundary_prompt"] is True


def test_v2613_explicit_external_path_may_surface(tmp_path: Path) -> None:
    _make_ignore_boundary_fixture(tmp_path)
    explicit = "_external_references/vendor/upstream/agent/tools/edit_code.py"
    impact = _impact(tmp_path, f"Inspect {explicit} only.")

    likely = _paths(impact["likely_files"])
    assert explicit in likely
