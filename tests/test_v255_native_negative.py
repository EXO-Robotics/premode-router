from __future__ import annotations

from pathlib import Path

from premode.compiler import compile_prompt
from premode.fixture import init_project
from premode.indexer import index_project
from premode.repo_map import build_repo_map, task_impact_hints
from premode.adapters import detect_projects


def _init(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")


def test_negative_prompt_paths_are_read_only_not_allowed(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "package.json").write_text('{"scripts":{"test":"npm test"}}', encoding="utf-8")
    worker = repo / "tools" / "worker"
    (worker / "src" / "worker").mkdir(parents=True)
    (worker / "tests").mkdir()
    (worker / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (worker / "src" / "worker" / "cli.py").write_text("def main(): return 1\n", encoding="utf-8")
    (worker / "tests" / "test_cli.py").write_text("def test_cli(): assert True\n", encoding="utf-8")
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
    (repo / "generated").mkdir()
    (repo / "generated" / "state.json").write_text("{}\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(repo, "Edit tools/worker/src/worker/cli.py only. Do not touch frontend/package.json or generated/state.json.", "lite", use_repo_map=True)
    boundary = result["patch_boundary"]
    assert result["project_detection"]["task_root"] == "tools/worker"
    assert "tools/worker/src/worker/cli.py" in set(boundary.get("allowed_edit_files") or [])
    assert "frontend/package.json" not in set(boundary.get("allowed_edit_files") or [])
    assert "generated/state.json" not in set(boundary.get("allowed_edit_files") or [])
    assert "frontend/package.json" in set(boundary.get("forbidden_without_user_confirmation") or [])
    assert "generated/state.json" in set(boundary.get("forbidden_without_user_confirmation") or [])
    assert "frontend/package.json" in set(result["evidence_summary"].get("prompt_forbidden_files") or [])


def test_secret_like_paths_are_suppressed_from_context_tiers(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "pkg.py").write_text("def main(): return 1\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=abc\n", encoding="utf-8")
    (repo / "id_rsa").write_text("PRIVATE KEY\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(repo, "Fix pkg.py and do not print secrets from .env.", "lite", use_repo_map=True)
    paths = {item.get("path") for tier in result["context_tiers"].values() for item in tier}
    assert ".env" not in paths
    assert "id_rsa" not in paths
    assert result["redaction_summary"]["secret_like_paths_suppressed"] >= 1


def test_native_cpp_scons_engine_detection_wins_over_platform_python(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "SConstruct").write_text("# scons\n", encoding="utf-8")
    for d in ["core", "scene", "modules", "platform", "servers", "drivers"]:
        (repo / d).mkdir()
    (repo / "core" / "object.cpp").write_text("void object_init() {}\n", encoding="utf-8")
    (repo / "scene" / "node.cpp").write_text("void node_init() {}\n", encoding="utf-8")
    (repo / "modules" / "module.cpp").write_text("void module_init() {}\n", encoding="utf-8")
    (repo / "platform" / "detect.py").write_text("def can_build(): return True\n", encoding="utf-8")
    _init(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"], prompt="Change engine CLI platform option parsing")
    assert detection["active_project"]["project_kind"] == "native_cpp"
    assert detection["active_project"]["root"] == "."
    assert "native_engine_repo" in detection["traits"]


def test_go_root_command_flag_routing(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "go.mod").write_text("module github.com/nektos/act\n", encoding="utf-8")
    (repo / "main.go").write_text("package main\n", encoding="utf-8")
    (repo / "cmd").mkdir()
    (repo / "cmd" / "root.go").write_text('package cmd\nfunc parseEventPath() {}\nfunc init() { rootCmd.Flags().String("eventpath", "", "") }\n', encoding="utf-8")
    (repo / "cmd" / "root_test.go").write_text("package cmd\nfunc TestEventPath(t *testing.T) {}\n", encoding="utf-8")
    _init(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    impact = task_impact_hints("Change act CLI argument validation for --eventpath.", repo_map)
    assert "cmd/root.go" in {item["path"] for item in impact["likely_files"]}
    assert "cmd/root_test.go" in {item["path"] for item in impact["related_tests"]}


def test_self_repo_concept_routing_for_context_receipt(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "pyproject.toml").write_text("[project]\nname='premode-router'\n", encoding="utf-8")
    (repo / "src" / "premode").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "premode" / "repo_map.py").write_text("def build_repo_map(): return {}\n", encoding="utf-8")
    (repo / "src" / "premode" / "compiler.py").write_text("def context_receipt(): return {}\n", encoding="utf-8")
    (repo / "src" / "premode" / "packet_schema.py").write_text("SCHEMA = {}\n", encoding="utf-8")
    (repo / "tests" / "test_v253_output_hardening.py").write_text("def test_receipt(): assert True\n", encoding="utf-8")
    _init(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    impact = task_impact_hints("Change repo-map context receipt output and update tests only.", repo_map)
    likely = {item["path"] for item in impact["likely_files"]}
    assert "src/premode/repo_map.py" in likely
    assert "src/premode/compiler.py" in likely
    assert "tests/test_v253_output_hardening.py" in {item["path"] for item in impact["related_tests"]} or "tests/test_v253_output_hardening.py" in likely
