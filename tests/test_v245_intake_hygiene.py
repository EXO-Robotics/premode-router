from __future__ import annotations

import subprocess
from pathlib import Path

from premode.adapters import detect_projects
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.log_scanner import scan_logs
from premode.profiles import resolve_profile


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def test_ci_workflow_is_not_infra_sensitive(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.1.0'\n", encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert "ci_sensitive" in detection["traits"]
    assert "infra_sensitive" not in detection["traits"]
    dangerous = str(detection["intake_report"]["command_model"]["dangerous_command_patterns"])
    assert "terraform apply" not in dangerous
    assert "kubectl delete" not in dangerous


def test_real_infra_still_infra_sensitive(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "main.tf").write_text('resource "null_resource" "x" {}\n', encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert "infra_sensitive" in detection["traits"]
    dangerous = str(detection["intake_report"]["command_model"]["dangerous_command_patterns"])
    assert "terraform apply" in dangerous


def test_log_scanner_strips_ansi_and_dedupes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "build.log").write_text(
        "\x1b[31merror: cannot find Foo in scope\x1b[0m\n"
        "\x1b[31merror: cannot find Foo in scope\x1b[0m\n",
        encoding="utf-8",
    )
    state = scan_logs(repo, resolve_profile("lite"))
    first = state["first_meaningful_error"]
    assert first is not None
    assert "\x1b" not in first["message"]
    assert first["message"] == "error: cannot find Foo in scope"
    assert len(state["meaningful_errors"]) == 1
    assert state["log_dedupe_summary"]["duplicate_error_count"] == 1


def test_historical_generated_log_is_downgraded_not_root_error(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "state" / "history").mkdir(parents=True)
    (repo / "state" / "history" / "build.log").write_text("error: stale old failure\n", encoding="utf-8")
    state = scan_logs(repo, resolve_profile("lite"))
    assert state["first_meaningful_error"] is None
    assert state["log_dedupe_summary"]["stale_or_generated_logs_downgraded"] >= 1
    assert state["logs_scanned"][0]["downgraded"] is True


def test_control_plane_boundary_has_semantic_categories(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# authority\n", encoding="utf-8")
    (repo / "WORKFLOW.md").write_text("# workflow\n", encoding="utf-8")
    (repo / "PROJECT" / "state").mkdir(parents=True)
    (repo / "PROJECT" / "state" / "task_queue_normalized_latest.json").write_text("{}", encoding="utf-8")
    (repo / "PROJECT" / "state" / "path_authority_latest.json").write_text("{}", encoding="utf-8")
    (repo / "PROJECT" / "state" / "artifact_authority_latest.json").write_text("{}", encoding="utf-8")
    (repo / "PROJECT" / "AI" / "worker_start").mkdir(parents=True)
    (repo / "PROJECT" / "AI" / "worker_start" / "WORKER_START_HERE.md").write_text("start", encoding="utf-8")
    (repo / "PROJECT" / "tasks.json").write_text("{}", encoding="utf-8")
    (repo / "_claw_output").mkdir()
    (repo / "_claw_output" / "proof.log").write_text("ok", encoding="utf-8")
    (repo / "tools" / "gamebot").mkdir(parents=True)
    (repo / "tools" / "gamebot" / "runner.py").write_text("print('safe')\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Review the current control-plane task packet without mutating generated artifacts.", "lite")
    boundary = result["patch_boundary"]["control_plane_boundary"]
    assert "AGENTS.md" in boundary["authority_read_only"]
    assert any("state" in p.lower() for p in boundary["state_mutation_requires_explicit_authorization"])
    assert any("_claw_output" in p.lower() for p in boundary["evidence_only_generated_outputs"])


def test_small_low_risk_repo_uses_tiny_packet_mode(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "Cargo.toml").write_text("[package]\nname='tiny'\nversion='0.1.0'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.rs").write_text("fn main() { println!(\"hi\"); }\n", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Find the right files for a safe Rust CLI patch.", "lite")
    assert result["packet_mode"] == "tiny"
    assert result["metrics"]["packet_mode"] == "tiny"
    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]
    assert "selected_context_tokens" in result["metrics"]
    assert "policy_metadata_tokens" in result["metrics"]


def test_openclaw_like_repo_does_not_use_tiny_mode(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# authority\n", encoding="utf-8")
    (repo / "WORKFLOW.md").write_text("# workflow\n", encoding="utf-8")
    (repo / "state" / "history").mkdir(parents=True)
    (repo / "state" / "latest.json").write_text("{}", encoding="utf-8")
    (repo / "state" / "history" / "old.json").write_text("{}", encoding="utf-8")
    (repo / "artifacts" / "generated").mkdir(parents=True)
    (repo / "artifacts" / "generated" / "proof.json").write_text("{}", encoding="utf-8")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Review control-plane state.", "lite")
    assert result["packet_mode"] == "standard"
