from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def _commit(repo: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True, text=True)


def test_lab73m_dirty_unrelated_file_does_not_outrank_prompt_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src" / "target.py").write_text("def target():\n    return 'old'\n", encoding="utf-8")
    (repo / "tests" / "test_noise.py").write_text("def test_noise():\n    assert True\n", encoding="utf-8")
    _commit(repo)
    (repo / "tests" / "test_noise.py").write_text("def test_noise():\n    assert False\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")

    result = compile_prompt(repo, "Fix src/target.py behavior without changing anything else.", "lite")

    full_paths = [item["path"] for item in result["context_tiers"]["full_text_files"]]
    assert "src/target.py" in full_paths
    assert "tests/test_noise.py" not in full_paths[:1]
    dirty_records = {
        item["path"]: item
        for item in result["evidence_summary"]["dirty_context_files"]
    }
    assert dirty_records["tests/test_noise.py"]["dirty_demoted_to_context"] is True
    ledger = result["file_decision_ledger"]
    noise = next(item for item in ledger["records"] if item["path"] == "tests/test_noise.py")
    assert noise["dirty_only"] is True
    assert noise["dirty_contribution"] < noise["raw_score"]


def test_lab73m_dirty_prompt_matched_file_still_ranks_high(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src" / "target.py").write_text("def target():\n    return 'old'\n", encoding="utf-8")
    _commit(repo)
    (repo / "src" / "target.py").write_text("def target():\n    return None\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")

    result = compile_prompt(repo, "Fix src/target.py", "lite")

    target = next(item for item in result["selected_context_manifest"] if item["path"] == "src/target.py")
    assert target["dirty_with_prompt_evidence"] is True
    assert target["dirty_only"] is False
    assert "src/target.py" in result["patch_boundary"]["allowed_edit_files"]


def test_lab73m_decision_ledger_artifact_and_metric_split(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src" / "target.py").write_text("def target():\n    return 'old'\n", encoding="utf-8")
    _commit(repo)
    init_project(repo)
    index_project(repo, "lite")

    result = compile_prompt(
        repo,
        "Fix src/target.py",
        "lite",
        cache_optimized=True,
        packet_detail_mode="paths_only",
        record=True,
    )

    ledger_path = repo / ".premode" / "out" / "last_file_decision_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["schema_version"] == "file_decision_ledger.v1"
    target = next(item for item in ledger["records"] if item["path"] == "src/target.py")
    assert target["score_deltas"]
    assert target["final_bucket"] in {"full_text", "summary", "manifest"}
    metrics = result["metrics"]
    assert metrics["model_facing_packet_tokens"] == metrics["packet_total_tokens"]
    assert metrics["saved_context_tokens"] == metrics["selected_context_tokens"]
    assert metrics["model_facing_context_tokens"] is not None
    assert metrics["local_manifest_tokens"] >= 0
    assert "live_cache_adjusted_input_tokens" in metrics
