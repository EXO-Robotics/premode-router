from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.cli import build_parser, main
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.codex_exec import CodexOptions, run_codex
from premode.indexer import index_project
from premode.review_patch import format_review_report, review_patch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _commit_baseline(repo: Path) -> None:
    if not (repo / ".git").exists():
        _git(repo, "init")
    init_project(repo)
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def _paths(items: list[dict]) -> set[str]:
    return {str(item.get("path")) for item in items if item.get("path")}


def _make_control_plane(repo: Path) -> None:
    (repo / "AGENTS.md").write_text("# Agents\nOpenClaw authority.\n", encoding="utf-8")
    (repo / "WORKFLOW.md").write_text("# Workflow\n", encoding="utf-8")
    (repo / "PROJECT" / "AI" / "worker_start").mkdir(parents=True)
    (repo / "PROJECT" / "AI" / "worker_start" / "WORKER_START_HERE.md").write_text("# start\n", encoding="utf-8")
    (repo / "PROJECT" / "AI" / "OUTPUT_HYGIENE_GUARDRAILS.md").write_text("# hygiene\n", encoding="utf-8")
    (repo / "PROJECT" / "state").mkdir(parents=True)
    (repo / "PROJECT" / "state" / "task_queue_normalized_latest.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "state" / "path_authority_latest.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "state" / "artifact_authority_latest.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "tasks.json").write_text("{}\n", encoding="utf-8")
    (repo / "tools" / "gamebot").mkdir(parents=True)
    (repo / "tools" / "gamebot" / "task_queue.py").write_text("def validate_cli(): return True\n", encoding="utf-8")
    (repo / "tools" / "catalog").mkdir(parents=True)
    (repo / "tools" / "catalog" / "build_catalog.py").write_text("def validate_cli_catalog(): return True\n", encoding="utf-8")


def test_context_only_compile_exposes_candidate_boundary_aliases(repo: Path) -> None:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("from src.app import value\n", encoding="utf-8")
    _commit_baseline(repo)

    result = compile_prompt(
        repo,
        "Fix src/app.py without touching pyproject.toml",
        "lite",
        use_repo_map=True,
        cache_optimized=True,
        context_only=True,
        save=True,
    )

    assert result["context_boundary_mode"] == "context_only"
    assert result["context_receipt"]["context_boundary_mode"] == "context_only"
    assert _paths(result["candidate_edit_files"]) == _paths(result["likely_edit_files"])
    assert result["review_contract"]["candidate_edit_files"] == result["review_contract"]["allowed_edit_files"]
    assert "context hints" in result["review_contract"]["contract_semantics"]
    assert result["suggested_tests"] == result["related_tests"]
    assert "pyproject.toml" in result["review_contract"]["prompt_forbidden_files"]


def test_context_only_relaxes_control_plane_single_file_narrowing(tmp_path: Path) -> None:
    repo = tmp_path
    _make_control_plane(repo)
    _commit_baseline(repo)
    (repo / "tools" / "catalog" / "build_catalog.py").write_text("def validate_cli_catalog(): return False\n", encoding="utf-8")
    index_project(repo, "lite")

    prompt = "Modify tools/gamebot/task_queue.py to improve CLI validation. Do not mutate PROJECT/tasks.json or PROJECT/state authority files."
    standard = compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=True)
    context_only = compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=True, context_only=True)

    assert "tools/gamebot/task_queue.py" in standard["patch_boundary"]["allowed_edit_files"]
    assert "tools/catalog/build_catalog.py" not in standard["patch_boundary"]["allowed_edit_files"]
    assert "tools/catalog/build_catalog.py" in context_only["patch_boundary"]["candidate_edit_files"]
    assert "Context-only mode avoids strong candidate narrowing" in " ".join(context_only["patch_boundary"]["notes"])


def test_review_patch_uses_context_contract_wording(repo: Path) -> None:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    _commit_baseline(repo)
    compile_prompt(repo, "Fix src/app.py", "lite", use_repo_map=True, cache_optimized=True, save=True)
    (repo / "README.md").write_text("# Outside contract\n", encoding="utf-8")

    result = review_patch(repo, since_compile=True)
    rendered = format_review_report(result)

    assert result["working_tree_readiness"] == "warning"
    assert result["staged_patch_readiness"] == "not_evaluated"
    assert "README.md" in result["changed_unlisted_files"]
    assert any("outside the saved context contract" in item for item in result["warning_findings"])
    assert "Changed unlisted files: 1" in rendered
    assert "Allowed:" not in rendered


def test_cli_context_only_and_primary_help_hides_experiments(repo: Path, monkeypatch, capsys) -> None:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    _commit_baseline(repo)
    monkeypatch.chdir(repo)

    rc = main(["compile", "Fix src/app.py", "--profile", "lite", "--context-only", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["context_boundary_mode"] == "context_only"

    help_text = build_parser().format_help()
    assert "Experimental/deferred surface" not in help_text
    for command in ("plugin", "lab", "hook", "mcp-server"):
        assert command not in help_text


def test_context_only_compile_no_record_avoids_premode_writes(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", "src/app.py")
    _git(repo, "commit", "-m", "baseline")

    result = compile_prompt(
        repo,
        "Fix src/app.py without touching Docs or .premode.",
        "lite",
        use_repo_map=True,
        cache_optimized=True,
        context_only=True,
        record_artifacts=False,
    )

    assert result["context_boundary_mode"] == "context_only"
    assert result["audit_path"] is None
    assert not (repo / ".premode").exists()


def test_codex_context_only_no_save_dry_run_avoids_premode_writes(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", "src/app.py")
    _git(repo, "commit", "-m", "baseline")

    dry = run_codex(
        repo,
        "Fix src/app.py without touching .premode.",
        "lite",
        CodexOptions(dry_run=True, context_only=True, save=False, record=False),
    )

    assert dry["compile_settings"]["context_only"] is True
    assert dry["compile_settings"]["save"] is False
    assert dry["compile_settings"]["record"] is False
    assert dry["saved_artifacts"] is None
    assert not (repo / ".premode").exists()


def test_release_manifest_excludes_runtime_outputs() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    for pattern in (
        "recursive-exclude .git *",
        "recursive-exclude .venv *",
        "recursive-exclude **/__pycache__ *",
        "recursive-exclude .pytest_cache *",
        "recursive-exclude .premode/out *",
        "recursive-exclude .premode/audit *",
        "recursive-exclude .premode/metrics *",
        "global-exclude .DS_Store",
    ):
        assert pattern in manifest
