from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.repo_map import build_repo_map, task_impact_hints


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def test_prompt_mentioned_source_file_appears_in_impact_map(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='gamebot'\n", encoding="utf-8")
    (repo / "tools" / "gamebot").mkdir(parents=True)
    (repo / "tools" / "gamebot" / "task_queue.py").write_text("def main(): return 0\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    impact = task_impact_hints("Modify tools/gamebot/task_queue.py to improve CLI argument validation.", repo_map)
    assert any(item["path"] == "tools/gamebot/task_queue.py" and item["reason"] == "prompt_mentioned_source_file" for item in impact["likely_files"])


def test_python_ast_captures_try_except_reexport_imports(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='httpx-fixture'\n[project.scripts]\nhttpx='httpx:main'\n", encoding="utf-8")
    (repo / "httpx").mkdir()
    (repo / "httpx" / "__init__.py").write_text("try:\n    from ._main import main\nexcept ImportError:\n    main = None\n", encoding="utf-8")
    (repo / "httpx" / "_main.py").write_text("def main(): return 0\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    init_info = repo_map["files"]["httpx/__init__.py"]
    assert "._main" in init_info["imports"]
    assert any(edge["from"] == "httpx/__init__.py" and edge["to"] == "httpx/_main.py" for edge in repo_map["edges"])


def test_console_script_reexport_resolves_to_implementation_and_related_test(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='httpx-fixture'\n[project.scripts]\nhttpx='httpx:main'\n", encoding="utf-8")
    (repo / "httpx").mkdir()
    (repo / "httpx" / "__init__.py").write_text("try:\n    from ._main import main\nexcept ImportError:\n    main = None\n", encoding="utf-8")
    (repo / "httpx" / "_main.py").write_text("def main(): return 0\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_main.py").write_text("from httpx._main import main\n\ndef test_main(): assert main() == 0\n", encoding="utf-8")
    (repo / "tests" / "test_unrelated.py").write_text("def test_unrelated(): assert True\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    impact = task_impact_hints("Find the right files for a safe Python CLI patch that changes command-line argument handling.", repo_map)
    likely_paths = [item["path"] for item in impact["likely_files"]]
    assert "httpx/__init__.py" in likely_paths
    assert "httpx/_main.py" in likely_paths
    related = [item["path"] for item in impact["related_tests"]]
    assert "tests/test_main.py" in related
    assert "tests/test_unrelated.py" not in related


def test_targeted_tests_prompt_does_not_flood_likely_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n[project.scripts]\nx='x:main'\n", encoding="utf-8")
    (repo / "x").mkdir()
    (repo / "x" / "__init__.py").write_text("from ._main import main\n", encoding="utf-8")
    (repo / "x" / "_main.py").write_text("def main(): return 0\n", encoding="utf-8")
    (repo / "tests").mkdir()
    for name in ["test_main.py", "test_alpha.py", "test_beta.py"]:
        (repo / "tests" / name).write_text("def test_ok(): assert True\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    repo_map = build_repo_map(repo, idx["entries"], "lite")
    impact = task_impact_hints("Change CLI args. Run targeted tests if present.", repo_map)
    likely_paths = [item["path"] for item in impact["likely_files"]]
    assert "tests/test_alpha.py" not in likely_paths
    assert "tests/test_beta.py" not in likely_paths


def test_prompt_mentioned_generated_file_is_read_only_not_allowed_edit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    (repo / "WORKFLOW.md").write_text("# workflow\n", encoding="utf-8")
    (repo / "PROJECT" / "state").mkdir(parents=True)
    (repo / "PROJECT" / "state" / "task_queue_normalized_latest.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "tasks.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "AI" / "worker_start").mkdir(parents=True)
    (repo / "PROJECT" / "AI" / "worker_start" / "WORKER_START_HERE.md").write_text("# start\n", encoding="utf-8")
    (repo / "_claw_output").mkdir()
    (repo / "_claw_output" / "report.json").write_text("{}\n", encoding="utf-8")
    (repo / "tools" / "gamebot").mkdir(parents=True)
    (repo / "tools" / "gamebot" / "task_queue.py").write_text("def main(): return 0\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Use _claw_output/report.json as evidence while editing tools/gamebot/task_queue.py.", "lite", use_repo_map=True)
    boundary = result["patch_boundary"]
    allowed = set(boundary.get("allowed_edit_files") or [])
    control = boundary.get("control_plane_boundary") or {}
    assert "_claw_output/report.json" not in allowed
    assert any("_claw_output" in p for p in control.get("evidence_only_generated_outputs", []))


def test_openclaw_lite_uses_compact_governance(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    (repo / "WORKFLOW.md").write_text("# workflow\n", encoding="utf-8")
    (repo / "ARTIFACT_STORAGE.md").write_text("# artifacts\n", encoding="utf-8")
    (repo / "EXTERNAL_ARTIFACTS_INDEX.md").write_text("# external\n", encoding="utf-8")
    (repo / "PROJECT" / "state").mkdir(parents=True)
    (repo / "PROJECT" / "state" / "task_queue_normalized_latest.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "state" / "path_authority_latest.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "state" / "artifact_authority_latest.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "tasks.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT" / "AI" / "worker_start").mkdir(parents=True)
    (repo / "PROJECT" / "AI" / "worker_start" / "WORKER_START_HERE.md").write_text("# start\n", encoding="utf-8")
    (repo / "_claw_output").mkdir()
    (repo / "_claw_output" / "report.json").write_text("{}\n", encoding="utf-8")
    (repo / "tools" / "gamebot").mkdir(parents=True)
    (repo / "tools" / "gamebot" / "task_queue.py").write_text("def main(): return 0\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Modify tools/gamebot/task_queue.py to improve task queue CLI argument validation.", "lite", use_repo_map=True)
    assert result["proof_policy"]["proof_policy"]["do_not_claim_runtime_from_static_or_browser_evidence"] is True
    assert "openclaw_brief_governance" in result["packet"]
    assert "compact_control_plane_policy" in result["packet"]
    assert result["metrics"]["policy_metadata_tokens"] < 12000
