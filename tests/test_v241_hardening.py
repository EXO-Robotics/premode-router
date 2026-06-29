from __future__ import annotations

import json
import subprocess
from pathlib import Path

from premode.adapters import load_commands
from premode.config import init_project
from premode.indexer import index_project
from premode.compiler import compile_prompt


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def test_log_scanner_does_not_parse_source_file_named_log_scanner(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "src" / "premode").mkdir(parents=True)
    (repo / "src" / "premode" / "log_scanner.py").write_text('ERROR_RE = "error: cannot find fake"\n', encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix the build", "lite")
    assert result["evidence_summary"]["first_meaningful_error"] is None
    scanned = {x["path"] for x in result["evidence_summary"].get("logs_scanned", []) if isinstance(x, dict)}
    assert "src/premode/log_scanner.py" not in scanned


def test_prompt_mentioned_paths_do_not_treat_builds_sentence_as_path(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "make sure the app builds.", "lite")
    assert "builds" not in result["evidence_summary"]["prompt_mentioned_files"]
    assert result["evidence_summary"]["prompt_mentioned_files"] == []


def test_patch_boundary_categories_are_mutually_exclusive(tmp_path):
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# docs\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix the build", "lite")
    boundary = result["patch_boundary"]
    keys = [
        "read_only_context_files",
        "allowed_edit_files",
        "allowed_if_justified",
        "discouraged_files",
        "forbidden_without_user_confirmation",
    ]
    seen: dict[str, str] = {}
    for key in keys:
        for item in boundary[key]:
            lower = item.lower()
            assert lower not in seen, f"{item} appears in both {seen.get(lower)} and {key}"
            seen[lower] = key
    assert "README.md" not in boundary["allowed_edit_files"]


def test_generated_commands_are_not_reported_as_user_overrides(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    init_result = init_project(repo)
    commands_file = json.loads((repo / ".premode" / "commands.json").read_text(encoding="utf-8"))
    assert commands_file["commands"] == {}
    assert (repo / ".premode" / "out" / "discovered_commands.json").exists()
    commands = load_commands(repo)
    assert commands.get("user_overrides_applied") == []
    assert "test" in commands["commands"]
    assert "discovered_commands" in init_result


def test_legacy_generated_commands_json_is_not_treated_as_user_override(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    init_project(repo)
    legacy = {
        "schema_version": 2,
        "project_root": ".",
        "discovery": "deterministic",
        "sources": ["pyproject.toml"],
        "commands": {"test": {"command": "pytest", "source": "pyproject.toml"}},
    }
    (repo / ".premode" / "commands.json").write_text(json.dumps(legacy), encoding="utf-8")
    commands = load_commands(repo)
    assert commands.get("user_overrides_applied") == []
    assert commands.get("legacy_generated_commands_ignored") is True


def test_hard_budget_excludes_positive_score_manifest_overflow(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        "[project]\nname='x'\n[tool.premode.profile_overrides.lite]\nhard_packet_token_budget=6000\nhard_manifest_count=500\nhard_summary_count=10\nhard_full_text_file_count=2\n",
        encoding="utf-8",
    )
    (repo / ".premode").mkdir(exist_ok=True)
    (repo / ".premode" / "config.json").write_text(json.dumps({
        "resource_profile": "lite",
        "profile_overrides": {"lite": {
            "hard_packet_token_budget": 6000,
            "hard_manifest_count": 500,
            "hard_summary_count": 10,
            "hard_full_text_file_count": 2,
        }},
    }), encoding="utf-8")
    (repo / "src").mkdir()
    for i in range(220):
        (repo / "src" / f"build_module_{i}.py").write_text(f"def build_{i}(): return {i}\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix the build", "lite")
    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]
    reasons = result["excluded_context_summary"]["by_reason"]
    assert reasons.get("hard packet budget reached", 0) > 0
