from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from premode.config import init_project
from premode.indexer import index_project
from premode.compiler import compile_prompt
from premode.doctor import doctor
from premode.plugin import install_local_plugin
from premode.redaction import redact_text
from premode.metrics import ledger_path


def _git_commit(repo: Path):
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)


def test_v2_packet_manifest_sections_classifier_tool_plan(repo):
    init_project(repo)
    (repo / "logs").mkdir(exist_ok=True)
    (repo / "logs" / "build.log").write_text("CompileSwift normal\nerror: missing type CampaignUpkeep\n", encoding="utf-8")
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix the build and compile error, don't expand scope", "lite")
    packet = result["packet"]
    assert packet.startswith("PREMODE_COMPILED_PACKET_V2")
    for section in [
        "## 1. CANONICAL USER PROMPT",
        "## 2. Project detection",
        "## 3. Evidence summary",
        "## 4. Prompt signals detected",
        "## 5. Candidate context / safety boundaries",
        "## 6. Discovered commands",
        "## 7. Full-text files",
        "## 8. Summarized files",
        "## 9. Manifest-only files",
        "## 10. Logs and errors",
        "## 11. Project rules and memory",
        "## 12. Output contract",
    ]:
        assert section in packet
    assert result["primary_intent"] == "compile_repair"
    assert result["intents"]
    assert result["tool_plan"]
    assert result["acceptance_checks"]
    assert result["selected_context_manifest"]
    assert result["excluded_context_summary"]
    assert isinstance(result["redaction_summary"], dict)


def test_git_dirty_and_log_context_are_prioritized(repo):
    init_project(repo)
    _git_commit(repo)
    (repo / "src" / "Broken.swift").write_text("struct Broken { let value = MissingType() }\n", encoding="utf-8")
    (repo / "logs").mkdir(exist_ok=True)
    (repo / "logs" / "build.log").write_text("swiftc\nerror: cannot find MissingType in scope\n", encoding="utf-8")
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix Broken.swift build error", "lite")
    selected = [x["path"] for x in result["selected_context_manifest"]]
    assert "src/Broken.swift" in selected
    assert "logs/build.log" in selected
    manifest = json.loads((repo / ".premode" / "out" / "last_context_manifest.json").read_text(encoding="utf-8"))
    assert manifest["git_state"]["available"] is True
    assert any("Broken.swift" in x for x in manifest["git_state"]["dirty_files"])
    assert manifest["log_state"]["meaningful_errors"]


def test_doctor_reports_real_diagnostics(repo):
    init_project(repo)
    index_project(repo, "lite")
    install_local_plugin(repo)
    result = doctor(repo, True)
    assert result["commands"]["git"]["found"] is True
    assert "codex" in result["commands"]
    assert result["inside_git_repo"] is True
    assert result["config"]["valid"] is True
    assert result["plugin"]["manifest"]["valid"] is True
    assert result["plugin"]["hooks"]["valid"] is True
    assert result["plugin"]["mcp"]["valid"] is True
    assert result["symlink_protection"]["blocked"] in {True, None}
    assert result["secret_deny_paths_configured"]
    assert result["recommendation"]["profile"] in {"lite", "standard", "pro"}


def test_metrics_ledger_location(repo):
    init_project(repo)
    index_project(repo, "lite")
    compile_prompt(repo, "Fix build", "lite")
    assert ledger_path(repo).exists()
    assert ledger_path(repo).name == "usage_ledger.jsonl"
    assert not (repo / ".premode" / "metrics" / "metrics.jsonl").exists()


def test_secret_redaction_catches_common_secret_shapes(repo):
    init_project(repo)
    readme = repo / "README.md"
    readme.write_text(
        "AWS AKIAABCDEFGHIJKLMNOP and ghp_abcdefghijklmnopqrstuvwxyz and token=plainsecret\n"
        "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix docs", "lite")
    packet = result["packet"]
    assert "AKIAABCDEFGHIJKLMNOP" not in packet
    assert "ghp_abcdefghijklmnopqrstuvwxyz" not in packet
    assert "plainsecret" not in packet
    assert "BEGIN PRIVATE KEY" not in packet
    assert result["redaction_summary"]


def test_richer_plugin_skills_created(repo):
    init_project(repo)
    install_local_plugin(repo)
    skills = repo / "plugins" / "pcodex" / "skills"
    for name in ["pcodex", "pcodex-status", "pcodex-dry-run", "pcodex-tune"]:
        assert (skills / name / "SKILL.md").exists()
    assert not (repo / ".agents" / "plugins" / "plugins" / "premode-router").exists()
