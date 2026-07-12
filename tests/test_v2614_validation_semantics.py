from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.cli import main
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_compile_out_json_out_prints_compact_receipt(monkeypatch, capsys, tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def value(): return 1\n", encoding="utf-8")
    init_project(repo)
    monkeypatch.chdir(repo)

    rc = main([
        "compile",
        "Fix src/app.py",
        "--profile",
        "lite",
        "--out",
        ".premode/out/packet.md",
        "--json-out",
        ".premode/out/meta.json",
    ])

    assert rc == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "compiled"
    assert payload["out"] == ".premode/out/packet.md"
    assert payload["json_out"] == ".premode/out/meta.json"
    assert payload["packet_version"].startswith("PREMODE_COMPILED_PACKET")
    assert "## 1. Task" not in stdout
    assert "--- BEGIN FILE" not in stdout
    assert (repo / ".premode" / "out" / "packet.md").exists()
    assert (repo / ".premode" / "out" / "meta.json").exists()


def test_compile_show_raw_preserves_packet_stdout(monkeypatch, capsys, tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def value(): return 1\n", encoding="utf-8")
    init_project(repo)
    monkeypatch.chdir(repo)

    rc = main([
        "compile",
        "Fix src/app.py",
        "--profile",
        "lite",
        "--out",
        ".premode/out/packet.md",
        "--json-out",
        ".premode/out/meta.json",
        "--show-raw",
    ])

    assert rc == 0
    stdout = capsys.readouterr().out
    assert stdout.startswith("Fix src/app.py\n")
    assert "PREMODE_COMPILED_PACKET" not in stdout
    assert "[raw prompt requested with --show-raw]" in stdout


def test_semantic_impact_buckets_separate_forbidden_and_support_files(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (repo / "README.md").write_text("# support context\n", encoding="utf-8")
    (repo / "tools" / "worker" / "src" / "worker").mkdir(parents=True)
    (repo / "tools" / "worker" / "src" / "worker" / "cli.py").write_text("def main(): return 1\n", encoding="utf-8")
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (repo / "generated").mkdir()
    (repo / "generated" / "state.json").write_text("{}\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")

    result = compile_prompt(
        repo,
        "Use README.md for context. Edit tools/worker/src/worker/cli.py only. Do not touch frontend/package.json or generated/state.json.",
        "lite",
        use_repo_map=True,
    )
    impact = result["impact_map"]

    likely_edit = {item["path"] for item in impact["likely_edit_files"]}
    likely_compat = {item["path"] for item in impact["likely_files"]}
    forbidden = {item["path"] for item in impact["prompt_forbidden_files"]}
    support = {item["path"] for item in impact["read_only_support_files"]}
    assert "tools/worker/src/worker/cli.py" in likely_edit
    assert likely_compat == likely_edit
    assert "frontend/package.json" in forbidden
    assert "generated/state.json" in forbidden
    assert "frontend/package.json" not in likely_edit
    assert "generated/state.json" not in likely_edit
    assert "README.md" in support


def _make_control_plane_repo(repo: Path) -> None:
    (repo / "AGENTS.md").write_text("# authority\n", encoding="utf-8")
    (repo / "WORKFLOW.md").write_text("# workflow\n", encoding="utf-8")
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
    (repo / "tests").mkdir()
    (repo / "tests" / "test_task_queue.py").write_text("def test_queue(): assert True\n", encoding="utf-8")


def test_openclaw_single_prompt_file_limits_allowed_edit_files(tmp_path: Path) -> None:
    repo = tmp_path
    _make_control_plane_repo(repo)
    init_project(repo)
    index_project(repo, "lite")

    result = compile_prompt(
        repo,
        "Modify tools/gamebot/task_queue.py to improve CLI validation. Do not mutate PROJECT/tasks.json, PROJECT/state authority files, _claw_output, Unreal, Blender, or bridge-write outputs.",
        "lite",
        use_repo_map=True,
        cache_optimized=True,
    )
    allowed = set(result["patch_boundary"]["allowed_edit_files"])

    assert "tools/gamebot/task_queue.py" in allowed
    assert "tools/catalog/build_catalog.py" not in allowed
    assert all(path == "tools/gamebot/task_queue.py" or path.startswith("tests/") for path in allowed)
    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]
