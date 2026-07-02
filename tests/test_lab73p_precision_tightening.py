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


def test_docs_only_benchmark_guide_keeps_adjacent_docs_as_support(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "docs" / "BENCHMARK.md", "# Benchmark guide\nExpectation hit-rate warnings.\n")
    _write(repo / "docs" / "PUBLIC_MVP_GUIDE.md", "# Public guide\nRuntime source notes.\n")
    _write(repo / "docs" / "PRODUCT_ROADMAP.md", "# Product roadmap\nRuntime source.\n")
    _write(repo / "README.md", "# Project\nRuntime source.\n")
    _write(repo / "tests" / "test_v263_benchmark.py", "def test_benchmark():\n    assert True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the benchmark guide to document expectation hit-rate warnings without changing runtime source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    support = _paths(result["read_only_support_files"])
    assert "docs/BENCHMARK.md" in candidates
    assert "docs/PRODUCT_ROADMAP.md" not in candidates
    assert "README.md" not in candidates
    assert "docs/PRODUCT_ROADMAP.md" in support
    assert "README.md" in support


def test_migration_refactor_does_not_promote_negative_cli_or_tests(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "pyproject.toml", "[project.scripts]\npremode='premode.cli:main'\n")
    _write(repo / "src" / "premode" / "cli.py", "def main():\n    return '--flag'\n")
    _write(repo / "src" / "premode" / "hook.py", "def main():\n    return 0\n")
    _write(repo / "src" / "premode" / "repo_map.py", "def candidate_ranking():\n    return []\n")
    _write(repo / "tests" / "test_v250_repo_map.py", "from src.premode import repo_map\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Refactor repo-map benchmark candidate ranking during a migration without changing public CLI flags.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    related = _paths(result["related_tests"])
    support = _paths(result["read_only_support_files"])
    assert "src/premode/repo_map.py" in candidates
    assert "src/premode/cli.py" not in candidates
    assert "src/premode/hook.py" not in candidates
    assert "tests/test_v250_repo_map.py" not in candidates
    assert "tests/test_v250_repo_map.py" in related
    assert "src/premode/cli.py" in support or "src/premode/cli.py" not in candidates


def test_typo_docs_prompt_keeps_readme_and_local_validation_without_broad_docs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "README.md", "# Benchmark docs\nbenchmak typo\n")
    _write(repo / "docs" / "PRODUCT_ROADMAP.md", "# Roadmap\nlocal docs\n")
    _write(repo / "docs" / "SECURITY_MODEL.md", "# Security\nlocal docs\n")
    _write(repo / "docs" / "V2.5_EXECUTION_GUIDE.md", "# Guide\nlocal docs\n")
    _write(repo / "scripts" / "smoke_test.sh", "#!/usr/bin/env bash\npython -m pytest\n")
    _write(repo / "tests" / "test_v266_local_validation.py", "def test_local_validation():\n    assert True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Fix the benchmak docs typo and add the smallest local validation coverage.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    related = _paths(result["related_tests"])
    support = _paths(result["read_only_support_files"])
    assert "README.md" in candidates
    assert "tests/test_v266_local_validation.py" in related
    assert "scripts/smoke_test.sh" not in candidates
    assert "docs/PRODUCT_ROADMAP.md" not in candidates
    assert "docs/SECURITY_MODEL.md" not in candidates
    assert "docs/PRODUCT_ROADMAP.md" in support


def test_decision_ledger_records_projection_and_demotion_reasons(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "docs" / "BENCHMARK.md", "# Benchmark guide\nExpectation hit-rate warnings.\n")
    _write(repo / "docs" / "PRODUCT_ROADMAP.md", "# Product roadmap\nRuntime source.\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the benchmark guide to document expectation hit-rate warnings without changing runtime source.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )
    records = {item["path"]: item for item in result["file_decision_ledger"]["records"]}

    assert records["docs/BENCHMARK.md"]["candidate_projection_reason"]
    assert records["docs/PRODUCT_ROADMAP.md"]["support_projection_reason"]
    assert records["docs/PRODUCT_ROADMAP.md"]["demotion_reason"]
