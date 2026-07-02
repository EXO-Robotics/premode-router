from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    return tmp_path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _index(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")


def _paths(items) -> list[str]:
    return [str(item.get("path")) for item in items or [] if isinstance(item, dict)]


def test_readme_beats_conduct_and_docs_config_for_user_facing_docs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "# Demo\nQuickstart usage docs.\n")
    _write(repo / "CODE_OF_CONDUCT.md", "# Conduct\nQuickstart usage docs.\n")
    _write(repo / "docs" / "conf.py", "project = 'demo'\n")
    _write(repo / "docs" / ".vitepress" / "config.ts", "export default {}\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the user-facing quickstart or usage docs without changing runtime source code.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    support = _paths(result["read_only_support_files"])
    assert candidates == ["README.md"]
    assert "CODE_OF_CONDUCT.md" in support
    assert "docs/conf.py" in support


def test_docs_build_prompt_can_target_docs_config(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "# Demo\nUsage.\n")
    _write(repo / "docs" / ".vitepress" / "config.ts", "export default {}\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the docs build configuration for the quickstart site.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    assert "docs/.vitepress/config.ts" in _paths(result["candidate_edit_files"])


def test_root_manifests_beat_nested_manifests_and_benchmark_prompts(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "package.json", '{"name":"root"}\n')
    _write(repo / "packages" / "tool" / "package.json", '{"name":"tool"}\n')
    _write(repo / "examples" / "demo" / "package.json", '{"name":"demo"}\n')
    _write(repo / "benchmark_prompts.json", '{"prompts":[]}\n')
    _write(repo / "tests" / "__init__.py", "")
    _index(repo)

    result = compile_prompt(
        repo,
        "Adjust package metadata for the published package while keeping source behavior unchanged.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    related = _paths(result["related_tests"])
    assert candidates == ["package.json"]
    assert "benchmark_prompts.json" not in candidates
    assert "tests/__init__.py" in related
    assert len(related) <= 2


def test_nested_manifest_wins_only_with_explicit_workspace_scope(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "package.json", '{"name":"root"}\n')
    _write(repo / "packages" / "tool" / "package.json", '{"name":"tool"}\n')
    _index(repo)

    result = compile_prompt(
        repo,
        "Adjust package metadata for packages/tool workspace package.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    assert "package.json" in candidates
    assert "packages/tool/package.json" in candidates
    assert len([path for path in candidates if path.endswith("package.json")]) <= 2


def test_workflow_precision_prefers_ci_and_test_over_release_issue_workflows(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    for name in ["release.yml", "publish.yml", "stale.yml", "issue-labeler.yml", "docs-deploy.yml"]:
        _write(repo / ".github" / "workflows" / name, "name: ignored\n")
    _write(repo / ".github" / "workflows" / "ci.yml", "name: CI\n")
    _write(repo / ".github" / "workflows" / "build_and_test.yml", "name: Build and test\n")
    _write(repo / "benchmark_prompts.json", '{"prompts":[]}\n')
    _write(repo / "tests" / "test_local_validation.py", "def test_local_validation(): assert True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Tighten the CI or local validation workflow so regressions are caught before release.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    assert ".github/workflows/ci.yml" in candidates
    assert ".github/workflows/build_and_test.yml" in candidates
    assert "benchmark_prompts.json" not in candidates
    assert not any(path.endswith(("release.yml", "publish.yml", "stale.yml", "issue-labeler.yml")) for path in candidates)
    assert len(candidates) <= 3


def test_related_test_resolver_prefers_package_local_tests_and_caps_broad_fallback(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "packages" / "tool" / "src" / "index.ts", "export const runCommand = () => true\n")
    _write(repo / "packages" / "tool" / "src" / "__tests__" / "index.test.ts", "import '../index'\n")
    for index in range(8):
        _write(repo / "packages" / "other" / "__tests__" / f"other{index}.test.ts", "import '../../tool/src/index'\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Fix the runtime behavior in the command entrypoint.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    related = _paths(result["related_tests"])
    assert "packages/tool/src/__tests__/index.test.ts" in related
    assert len(related) <= 3


def test_test_only_prompt_mirrors_expected_test_and_demotes_source(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "src" / "app.py", "def run(): return True\n")
    _write(repo / "tests" / "test_app.py", "def test_run(): assert True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Add focused regression test coverage for app behavior without changing production source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    related = _paths(result["related_tests"])
    assert candidates == ["tests/test_app.py"]
    assert related == ["tests/test_app.py"]
