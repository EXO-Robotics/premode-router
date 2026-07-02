from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.role_model import classify_path_role, infer_prompt_intent


FORBIDDEN_PUBLIC_REPO_PATTERNS = {
    "psf/black", "pallets/click", "fastapi/typer", "psf/requests",
    "encode/httpx", "pytest-dev/pytest", "python-poetry/poetry",
    "vitejs/vite", "facebook/react", "vercel/next.js", "nodejs/undici",
    "yargs/yargs", "rust-lang/rust-clippy", "burntsushi/ripgrep",
    "spf13/cobra", "gin-gonic/gin", "gohugoio/hugodocs",
    "microsoft/vscode-extension-samples",
}


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


def test_role_model_classifies_cross_ecosystem_paths() -> None:
    node = classify_path_role("packages/tool/src/index.ts")
    assert node.ecosystem == "node"
    assert node.role == "source"
    assert node.source_root_kind == "packages_src"
    assert node.entrypoint_likelihood == "high"

    rust = classify_path_role("crates/cli/src/main.rs")
    assert rust.ecosystem == "rust"
    assert rust.role == "source"
    assert rust.source_root_kind == "crates_src"

    workflow = classify_path_role(".github/workflows/test.yml")
    assert workflow.role == "workflow"
    assert workflow.workflow_likelihood == "high"

    test = classify_path_role("Sources/App/FeatureTests.swift")
    assert test.is_test is True
    assert test.role == "test"

    manifest = classify_path_role("pubspec.yaml")
    assert manifest.role == "config"
    assert manifest.manifest_likelihood == "high"


def test_prompt_intent_honors_negative_clauses() -> None:
    docs = infer_prompt_intent("Update the README usage guide without changing runtime source.")
    assert docs.intent == "docs"
    assert docs.primary_roles == ("docs",)
    assert "source" in docs.negative_roles

    tests = infer_prompt_intent("Add regression test coverage without changing production code.")
    assert tests.intent == "test_edit"
    assert tests.primary_roles == ("test",)

    workflow = infer_prompt_intent("Tighten CI workflow local validation checks.")
    assert workflow.intent == "workflow"
    assert workflow.primary_roles == ("workflow",)


def test_role_model_routes_generic_node_source_and_related_test(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "package.json", '{"name":"demo","main":"packages/tool/src/index.ts","scripts":{"test":"vitest"}}\n')
    _write(repo / "packages" / "tool" / "src" / "index.ts", "export function runCommand() { return 'ok' }\n")
    _write(repo / "packages" / "tool" / "src" / "__tests__" / "index.test.ts", "import { runCommand } from '../index'\n")
    _write(repo / "docs" / "usage.md", "# Usage\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Fix the runtime behavior in the command entrypoint without changing package metadata or docs.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    related = _paths(result["related_tests"])
    assert "packages/tool/src/index.ts" in candidates
    assert "packages/tool/src/__tests__/index.test.ts" in related
    assert "package.json" not in candidates


def test_role_model_routes_root_manifest_and_workflow_without_broad_examples(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "pyproject.toml", "[project]\nname='demo'\n")
    for index in range(12):
        _write(repo / "examples" / f"sample_{index}" / "pyproject.toml", "[project]\nname='sample'\n")
    _write(repo / ".github" / "workflows" / "ci.yml", "name: CI\n")
    _write(repo / "scripts" / "test_smoke.sh", "pytest tests/test_local_validation.py\n")
    _write(repo / "tests" / "test_package_layout.py", "def test_layout(): assert True\n")
    _write(repo / "tests" / "test_local_validation.py", "def test_validation(): assert True\n")
    _index(repo)

    config = compile_prompt(
        repo,
        "Adjust package metadata for the published package while keeping source behavior unchanged.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )
    config_candidates = _paths(config["candidate_edit_files"])
    assert "pyproject.toml" in config_candidates
    assert config_candidates.index("pyproject.toml") == 0
    assert len([path for path in config_candidates if path.endswith("pyproject.toml")]) <= 4

    workflow = compile_prompt(
        repo,
        "Tighten the CI workflow and local validation script so regressions are caught before release.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )
    workflow_candidates = _paths(workflow["candidate_edit_files"])
    workflow_related = _paths(workflow["related_tests"])
    assert ".github/workflows/ci.yml" in workflow_candidates
    assert "scripts/test_smoke.sh" in workflow_candidates
    assert "tests/test_local_validation.py" in workflow_related


def test_core_source_does_not_hardcode_public_matrix_repo_names() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "premode"
    offenders: list[str] = []
    for path in root.glob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for pattern in FORBIDDEN_PUBLIC_REPO_PATTERNS:
            if pattern in text:
                offenders.append(f"{path.name}:{pattern}")
    assert offenders == []
