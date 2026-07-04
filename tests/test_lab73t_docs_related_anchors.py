from __future__ import annotations

import subprocess
from pathlib import Path

from premode.benchmark import run_benchmark
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


def test_readme_rst_beats_issue_templates_for_user_facing_docs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.rst", "Quickstart usage docs.\n")
    _write(repo / "github" / "ISSUE_TEMPLATE" / "1_bug_report.md", "Issue template usage.\n")
    _write(repo / "src" / "app.py", "def run(): return True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the getting-started usage docs without changing runtime source code.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    assert _paths(result["candidate_edit_files"]) == ["README.rst"]
    assert "src/app.py" not in _paths(result["candidate_edit_files"])


def test_specific_getting_started_doc_beats_agent_reference_docs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "Overview.\n")
    _write(repo / "docs" / "01-app" / "01-getting-started" / "usage.mdx", "Getting started usage.\n")
    _write(repo / "agents" / "skills" / "update-docs" / "references" / "CODE-TO-DOCS-MAPPING.md", "Internal docs mapping.\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the getting-started usage docs without changing runtime source code.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    assert "docs/01-app/01-getting-started/usage.mdx" in candidates
    assert "agents/skills/update-docs/references/CODE-TO-DOCS-MAPPING.md" not in candidates


def test_docs_config_still_wins_for_docs_build_prompt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "Usage docs.\n")
    _write(repo / "docs" / "conf.py", "project = 'demo'\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the docs build configuration for the usage site.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    assert "docs/conf.py" in _paths(result["candidate_edit_files"])


def test_troubleshooting_docs_beat_readme_for_troubleshooting_prompt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "General usage overview.\n")
    _write(repo / "docs" / "troubleshooting.md", "Troubleshooting steps.\n")
    _write(repo / "docs" / "guide.md", "General guide.\n")
    _write(repo / "src" / "app.py", "def run(): return True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the troubleshooting docs without changing runtime source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    assert candidates == ["docs/troubleshooting.md"]
    assert "README.md" not in candidates
    assert "src/app.py" not in candidates


def test_faq_docs_beat_issue_template_and_runtime_source(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "Overview.\n")
    _write(repo / "docs" / "faq.md", "FAQ.\n")
    _write(repo / ".github" / "ISSUE_TEMPLATE" / "bug_report.md", "FAQ issue template.\n")
    _write(repo / "src" / "faq.py", "def answer(): return True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the FAQ docs without changing runtime source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    assert candidates == ["docs/faq.md"]
    assert ".github/ISSUE_TEMPLATE/bug_report.md" not in candidates
    assert "src/faq.py" not in candidates


def test_how_to_docs_beat_unrelated_docs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "Overview.\n")
    _write(repo / "docs" / "how-to" / "deploy.md", "How-to deploy.\n")
    _write(repo / "docs" / "architecture.md", "Architecture notes.\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the how-to documentation for deploy without changing source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    assert candidates == ["docs/how-to/deploy.md"]
    assert "docs/architecture.md" not in candidates


def test_governance_docs_remain_demoted_unless_explicitly_requested(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "Overview.\n")
    _write(repo / "docs" / "faq.md", "FAQ.\n")
    _write(repo / "CODE_OF_CONDUCT.md", "Conduct policy.\n")
    _write(repo / "SECURITY.md", "Security policy.\n")
    _write(repo / "CONTRIBUTING.md", "Contribution policy.\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the FAQ docs without changing source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    assert candidates == ["docs/faq.md"]
    assert "CODE_OF_CONDUCT.md" not in candidates
    assert "SECURITY.md" not in candidates
    assert "CONTRIBUTING.md" not in candidates


def test_docs_config_remains_demoted_without_docs_build_prompt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "Overview.\n")
    _write(repo / "docs" / "faq.md", "FAQ.\n")
    _write(repo / "docs" / "conf.py", "project = 'demo'\n")
    _write(repo / "docs" / ".vitepress" / "config.ts", "export default {}\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the FAQ docs without changing source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    assert candidates == ["docs/faq.md"]
    assert "docs/conf.py" not in candidates
    assert "docs/.vitepress/config.ts" not in candidates


def test_related_tests_include_resolution_reason_for_same_basename(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "packages" / "tool" / "src" / "runner.ts", "export function runner() { return true }\n")
    _write(repo / "packages" / "tool" / "src" / "__tests__" / "runner.test.ts", "import '../runner'\n")
    _write(repo / "packages" / "other" / "src" / "__tests__" / "runner.test.ts", "import '../../../tool/src/runner'\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Fix the runtime behavior in the runner command.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    related = result["related_tests"]
    paths = _paths(related)
    assert "packages/tool/src/__tests__/runner.test.ts" in paths
    selected = next(item for item in related if item["path"] == "packages/tool/src/__tests__/runner.test.ts")
    assert selected["related_test_resolution_reason"] in {"same_basename", "same_package", "source_adjacent_test"}
    assert selected["related_test_anchor_confidence"] in {"high", "medium"}


def test_test_only_mirroring_uses_allowed_reason_name(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "src" / "app.py", "def run(): return True\n")
    _write(repo / "tests" / "test_app.py", "def test_run(): assert True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Add focused regression coverage for app behavior without changing production source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    assert _paths(result["candidate_edit_files"]) == ["tests/test_app.py"]
    assert result["related_tests"][0]["related_test_resolution_reason"] == "test_candidate_mirrored"


def test_docs_only_without_expected_tests_does_not_warn_when_no_validation_terms(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "Quickstart.\n")
    _write(repo / "benchmark_prompts.json", '{"prompts":[{"name":"docs","task_type":"docs_only","prompt":"Update the user-facing quickstart docs without changing source code.","expected_files":["README.md"]}]}\n')
    _index(repo)

    report = run_benchmark(repo, profile="lite", use_repo_map=True)

    case = report["cases"][0]
    assert case["benchmark_status"] == "pass"
    assert not case["validation_warnings"]
    assert report["summary"]["warning_category_counts"] == {}
