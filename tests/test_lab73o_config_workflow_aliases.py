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


def test_package_metadata_routes_manifest_and_layout_test(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "pyproject.toml", "[project]\nname='demo'\n")
    _write(repo / "src" / "premode" / "cli.py", "def main():\n    return 'benchmark command'\n")
    _write(repo / "tests" / "test_package_layout.py", "def test_layout():\n    assert True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Adjust Python package metadata for the benchmark command while keeping source behavior unchanged.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    related = _paths(result["related_tests"])
    assert "pyproject.toml" in candidates
    assert "tests/test_package_layout.py" in related
    assert "src/premode/cli.py" not in candidates or candidates.index("pyproject.toml") < candidates.index("src/premode/cli.py")
    ledger = {item["path"]: item for item in result["file_decision_ledger"]["records"]}
    hints = ledger["pyproject.toml"]["repo_map_hints"]
    assert any(hint.get("source") == "package_metadata_adjacency" for hint in hints)


def test_test_only_candidate_is_mirrored_to_related_tests(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "src" / "premode" / "benchmark.py", "def validate():\n    return True\n")
    _write(repo / "tests" / "test_v263_benchmark.py", "def test_expectation_validation():\n    assert True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Add a focused regression test for benchmark expectation validation without changing production code.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    related = _paths(result["related_tests"])
    assert "tests/test_v263_benchmark.py" in candidates
    assert "tests/test_v263_benchmark.py" in related
    assert "src/premode/benchmark.py" not in candidates or candidates.index("tests/test_v263_benchmark.py") < candidates.index("src/premode/benchmark.py")
    ledger = {item["path"]: item for item in result["file_decision_ledger"]["records"]}
    hints = ledger["tests/test_v263_benchmark.py"]["repo_map_hints"]
    assert any(hint.get("reason") == "test_candidate_mirrored_to_related_tests" for hint in hints)


def test_smoke_workflow_routes_script_and_local_validation_test(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "scripts" / "smoke_test.sh", "#!/usr/bin/env bash\npython -m pytest tests/test_v266_local_validation.py\n")
    _write(repo / "examples" / "benchmark_prompts.json", '{"prompts":[]}\n')
    _write(repo / "tests" / "test_v266_local_validation.py", "def test_local_validation():\n    assert True\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Tighten the local smoke validation workflow so benchmark regressions are caught in CI-style checks.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    candidates = _paths(result["candidate_edit_files"])
    related = _paths(result["related_tests"])
    assert "scripts/smoke_test.sh" in candidates
    assert "tests/test_v266_local_validation.py" in related
    assert "examples/benchmark_prompts.json" not in candidates
    ledger = {item["path"]: item for item in result["file_decision_ledger"]["records"]}
    hints = ledger["scripts/smoke_test.sh"]["repo_map_hints"]
    assert any(hint.get("source") == "workflow_adjacency" for hint in hints)


def test_semantic_aliases_surface_source_recovery_and_review_modules(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "src" / "premode" / "repo_map.py", "def source_recovery():\n    return []\n")
    _write(repo / "src" / "premode" / "compiler.py", "def compile_prompt():\n    return {}\n")
    _write(repo / "src" / "premode" / "log_scanner.py", "def parse_jsonl():\n    return []\n")
    _write(repo / "src" / "premode" / "review_patch.py", "def review_patch():\n    return 'merge readiness'\n")
    _write(repo / "tests" / "test_v2615_swift_source_recovery.py", "def test_recovery():\n    assert True\n")
    _write(repo / "tests" / "test_v260_review_patch.py", "def test_review():\n    assert True\n")
    _index(repo)

    source_result = compile_prompt(
        repo,
        "In a SwiftUI-like app, recover source candidates for Views and ViewModels while keeping docs as support context.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )
    source_candidates = _paths(source_result["candidate_edit_files"])
    assert {"src/premode/repo_map.py", "src/premode/compiler.py"} <= set(source_candidates)

    review_result = compile_prompt(
        repo,
        "Improve log parsing and review-patch evidence reporting.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )
    review_candidates = _paths(review_result["candidate_edit_files"])
    assert {"src/premode/log_scanner.py", "src/premode/review_patch.py"} <= set(review_candidates)
    assert len(review_candidates) <= 4
    ledger = {item["path"]: item for item in review_result["file_decision_ledger"]["records"]}
    assert any(
        hint.get("source") == "semantic_module_alias"
        for hint in ledger["src/premode/log_scanner.py"]["repo_map_hints"]
    )


def test_related_test_expansion_prefers_direct_tests_over_broad_fallback(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "src" / "premode" / "cli.py", "def packet_mode_help():\n    return '--packet-mode'\n")
    _write(repo / "src" / "premode" / "compiler.py", "from .cli import packet_mode_help\n")
    _write(repo / "tests" / "test_v267_codex_cli_compat.py", "from src.premode.cli import packet_mode_help\n")
    for index in range(12):
        _write(repo / "tests" / f"test_broad_{index}.py", "from src.premode.compiler import packet_mode_help\n")
    _index(repo)

    result = compile_prompt(
        repo,
        "Update the benchmark CLI help text for --packet-mode without changing compile behavior.",
        "lite",
        use_repo_map=True,
        record_artifacts=False,
    )

    related = _paths(result["related_tests"])
    assert "tests/test_v267_codex_cli_compat.py" in related
    assert len(related) <= 6
