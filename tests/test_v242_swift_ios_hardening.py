from __future__ import annotations

import subprocess
from pathlib import Path

from premode.adapters import detect_projects, load_commands
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.redaction import redact_text
from premode.router import classify_task


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    return tmp_path


def test_compile_detection_preserves_xcodeproj_directory_marker(tmp_path):
    repo = _repo(tmp_path)
    (repo / "GoldpineValley.xcodeproj").mkdir()
    (repo / "GoldpineValley").mkdir()
    (repo / "GoldpineValley" / "GameState.swift").write_text("struct GameState {}\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")

    # The readable index contains Swift source files, but not the .xcodeproj directory itself.
    assert "GoldpineValley.xcodeproj" not in {e["path"] for e in idx["entries"]}

    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "ios_swift"
    assert detection["active_project"]["root"] == "."
    assert detection["active_project"]["root_selection"]["strategy"] == "primary_marker"

    commands = load_commands(repo, detection)
    assert "build" in commands["commands"]
    assert "xcodebuild" in commands["commands"]["build"]["command"]

    result = compile_prompt(repo, "Fix the xcodebuild compile error", "lite")
    assert result["project_detection"]["active_project"]["root"] == "."
    assert "xcodebuild" in str(result["commands"])


def test_long_swift_repo_path_survives_redaction_and_path_extraction(tmp_path):
    repo = _repo(tmp_path)
    (repo / "GoldpineValley.xcodeproj").mkdir()
    target = repo / "GoldpineValley" / "Views" / "PlayerActivities" / "StarterMinigames" / "RepairAssistGameEngine.swift"
    target.parent.mkdir(parents=True)
    target.write_text("struct RepairAssistGameEngine {}\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")

    rel = "GoldpineValley/Views/PlayerActivities/StarterMinigames/RepairAssistGameEngine.swift"
    redacted = redact_text(f"Fix {rel}")
    assert rel in redacted.text
    assert "[REDACTED:high_entropy].swift" not in redacted.text

    result = compile_prompt(repo, f"Fix {rel} hold input receipt. Keep patch minimal.", "lite")
    assert rel.lower() in result["evidence_summary"]["prompt_mentioned_files"]
    full_paths = {x["path"].lower() for x in result["context_tiers"]["full_text_files"]}
    assert rel.lower() in full_paths


def test_day_report_prompt_is_not_documentation_intent(tmp_path):
    repo = _repo(tmp_path)
    (repo / "GoldpineValley.xcodeproj").mkdir()
    (repo / "GoldpineValley").mkdir()
    (repo / "GoldpineValley" / "DayReport.swift").write_text("struct DayReport {}\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")

    prompt = "Add risk receipts to the Day Report and block unavailable characters from jobs."
    classification = classify_task(prompt)
    assert classification["primary_intent"] != "documentation"

    result = compile_prompt(repo, prompt, "lite")
    assert result["primary_intent"] != "documentation"


def test_premode_generated_files_do_not_pollute_dirty_state(tmp_path):
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "pyproject.toml", "src/app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True, text=True)

    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Review dirty branch", "lite")
    assert not any(p.startswith(".premode") for p in result["evidence_summary"]["dirty_files"])
