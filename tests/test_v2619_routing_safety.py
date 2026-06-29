from __future__ import annotations

from pathlib import Path

from premode.adapters import detect_projects
from premode.command_discovery import discover_commands
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _init(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")


def _paths(items: list[dict]) -> set[str]:
    return {str(item.get("path")) for item in items if item.get("path")}


def _all_restricted_output_buckets(result: dict) -> set[str]:
    boundary = result["patch_boundary"]
    contract = result["review_contract"]
    impact = result["impact_map"]
    out = set(boundary.get("allowed_edit_files") or [])
    out.update(contract.get("allowed_edit_files") or [])
    for key in ("likely_edit_files", "likely_files", "related_tests"):
        out.update(_paths(result.get(key) or []))
        out.update(_paths(impact.get(key) or []))
    for item in result.get("verification_order") or []:
        if isinstance(item, dict):
            out.add(str(item.get("command") or ""))
    return out


def test_go_generated_output_is_filtered_from_edit_and_review_buckets(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "go.mod").write_text("module k8s.io/kubernetes\n", encoding="utf-8")
    (repo / "cmd" / "kubelet" / "app" / "options").mkdir(parents=True)
    (repo / "cmd" / "kubelet" / "app" / "options" / "options.go").write_text(
        "package options\nfunc ValidateContainerRuntimeEndpoint(endpoint string) bool { return endpoint != \"\" }\n",
        encoding="utf-8",
    )
    (repo / "cmd" / "kubelet" / "app" / "options" / "options_test.go").write_text(
        "package options\nfunc TestValidateContainerRuntimeEndpoint(t *testing.T) {}\n",
        encoding="utf-8",
    )
    (repo / "_output").mkdir()
    (repo / "_output" / "generated.pb.go").write_text(
        "package output\nfunc ValidateContainerRuntimeEndpointGenerated() {}\n",
        encoding="utf-8",
    )
    (repo / "vendor" / "pkg").mkdir(parents=True)
    (repo / "vendor" / "pkg" / "dep.go").write_text("package pkg\n", encoding="utf-8")
    (repo / "staging" / "src").mkdir(parents=True)
    (repo / "staging" / "src" / "thing.go").write_text("package src\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(
        repo,
        "Change kubelet --container-runtime-endpoint validation in the kubelet options code. "
        "Do not touch vendor, staging, generated files, hack scripts, or go.mod.",
        "lite",
        use_repo_map=True,
    )

    restricted = _all_restricted_output_buckets(result)
    edit_paths = set(result["patch_boundary"].get("allowed_edit_files") or [])
    edit_paths.update(result["review_contract"].get("allowed_edit_files") or [])
    edit_paths.update(_paths(result["likely_edit_files"]))
    edit_paths.update(_paths(result["likely_files"]))
    edit_paths.update(_paths(result["related_tests"]))
    assert "cmd/kubelet/app/options/options.go" in _paths(result["likely_edit_files"])
    assert "cmd/kubelet/app/options/options_test.go" in _paths(result["related_tests"])
    assert not any("_output/generated.pb.go" in item for item in restricted)
    assert not any(item.startswith("vendor/") or item.startswith("staging/") or item == "go.mod" for item in edit_paths)
    diagnostics = result["routing_filter_diagnostics"]
    assert diagnostics
    assert diagnostics["filtered_reasons"].get("generated_build_output_boundary") or diagnostics.get("generated_filtered_count")


def test_web_generated_dist_build_outputs_do_not_enter_edit_buckets(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "compiler.ts").write_text("export function compile(input: string) { return input }\n", encoding="utf-8")
    (repo / "src" / "compiler.generated.ts").write_text("export const generated = true\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "compiler.test.ts").write_text("test('compiler', () => {})\n", encoding="utf-8")
    (repo / "dist").mkdir()
    (repo / "dist" / "compiler.generated.js").write_text("module.exports = {}\n", encoding="utf-8")
    (repo / "build").mkdir()
    (repo / "build" / "cache.json").write_text("{}\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(
        repo,
        "Fix compiler behavior in src/compiler.ts. Do not touch generated, dist, or build outputs.",
        "lite",
        use_repo_map=True,
    )

    restricted = _all_restricted_output_buckets(result)
    assert "src/compiler.ts" in _paths(result["likely_edit_files"])
    assert "tests/compiler.test.ts" in _paths(result["related_tests"])
    assert "package.json" not in (result["patch_boundary"].get("allowed_edit_files") or [])
    assert not any("compiler.generated" in item or item.startswith("dist/") or item.startswith("build/") for item in restricted)
    full_text = _paths(result["context_tiers"]["full_text_files"])
    assert "src/compiler.ts" in full_text
    assert not any("compiler.generated" in item or item.startswith("dist/") or item.startswith("build/") for item in full_text)


def test_node_source_prompt_keeps_package_manifest_read_only(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "package.json").write_text('{"scripts":{"test":"vitest"},"dependencies":{"left-pad":"1.3.0"}}\n', encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "index.ts").write_text("export function run() { return 1 }\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "index.test.ts").write_text("test('run', () => {})\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(
        repo,
        "Fix the runtime behavior in src/index.ts. Use package.json only for command discovery; do not edit dependencies, scripts, or manifests.",
        "lite",
        use_repo_map=True,
    )

    assert "src/index.ts" in _paths(result["likely_edit_files"])
    assert "package.json" not in _paths(result["likely_edit_files"])
    assert "package.json" not in _paths(result["likely_files"])
    assert "package.json" not in (result["patch_boundary"].get("allowed_edit_files") or [])
    assert "package.json" not in (result["review_contract"].get("allowed_edit_files") or [])
    assert result["commands"]["commands"]["test"]["command"] == "npm test"


def test_java_command_discovery_prefers_maven_wrapper(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "pom.xml").write_text("<project></project>\n", encoding="utf-8")
    (repo / "mvnw").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
    (repo / "src" / "main" / "java" / "com" / "example" / "App.java").write_text("class App {}\n", encoding="utf-8")
    _init(repo)
    detection = detect_projects(repo, entries=index_project(repo, "lite")["entries"])
    commands = discover_commands(repo, detection)["commands"]
    assert commands["test"]["command"] == "./mvnw test"
    assert commands["test"]["auto_run"] is False


def test_java_command_discovery_prefers_gradle_wrapper(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "settings.gradle").write_text("rootProject.name='demo'\n", encoding="utf-8")
    (repo / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    (repo / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / "src" / "main" / "java").mkdir(parents=True)
    (repo / "src" / "main" / "java" / "App.java").write_text("class App {}\n", encoding="utf-8")
    _init(repo)
    detection = detect_projects(repo, entries=index_project(repo, "lite")["entries"])
    commands = discover_commands(repo, detection)["commands"]
    assert commands["test"]["command"] == "./gradlew test"
    assert commands["test"]["auto_run"] is False
