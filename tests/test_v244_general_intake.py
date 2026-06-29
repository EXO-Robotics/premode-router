from __future__ import annotations

import subprocess
from pathlib import Path

from premode.adapters import detect_projects
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def _make_generic_control_plane(repo: Path) -> None:
    (repo / "AGENTS.md").write_text("# Agents\nUse current state first.\n", encoding="utf-8")
    (repo / "WORKFLOW.md").write_text("# Workflow\nValidate before mutation.\n", encoding="utf-8")
    (repo / "state" / "history").mkdir(parents=True)
    (repo / "state" / "latest.json").write_text('{"current": true}', encoding="utf-8")
    (repo / "state" / "history" / "old.json").write_text('{"old": true}', encoding="utf-8")
    (repo / "artifacts" / "generated").mkdir(parents=True)
    (repo / "artifacts" / "generated" / "proof.json").write_text('{"generated": true}', encoding="utf-8")
    (repo / "tools" / "executor").mkdir(parents=True)
    (repo / "tools" / "executor" / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")


def test_generic_control_plane_gets_traits_without_openclaw_adapter(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _make_generic_control_plane(repo)
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] != "openclaw_control_plane"
    assert "proof_governed_candidate" in detection["traits"]
    assert "control_plane_candidate" in detection["traits"]
    assert "nested_executor_present" in detection["traits"]
    assert "proof_governed_control_plane" in detection["policy_packs"]
    assert detection["active_project_kind"] == "proof_governed_control_plane"


def test_generic_control_plane_keeps_root_authority_over_nested_executor(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _make_generic_control_plane(repo)
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    # The nested executor package is detected, but the generic intake warning prevents root hijack.
    assert detection["active_project"].get("root") in {".", "tools/executor"}
    assert any(w["type"] == "nested_executor_present" for w in detection["intake_warnings"])
    result = compile_prompt(repo, "Review the current control-plane task packet without mutating generated artifacts.", "lite")
    boundary = result["patch_boundary"]
    forbidden = "\n".join(boundary["forbidden_without_user_confirmation"]).lower()
    assert "artifacts/generated" in forbidden or "state/*" in forbidden
    assert result["intake_policy"]["authority_model"] == "control_plane"


def test_ordinary_python_with_agents_is_not_control_plane(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("Keep patches small.\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='ordinary'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert detection["active_project"]["project_kind"] == "python"
    assert "proof_governed_candidate" not in detection["traits"]
    assert "control_plane_candidate" not in detection["traits"]


def test_generated_artifact_dirs_are_evidence_only_without_openclaw_name(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("Use generated artifacts as evidence only.\n", encoding="utf-8")
    (repo / "WORKFLOW.md").write_text("Regenerate from source.\n", encoding="utf-8")
    (repo / "state" / "latest.json").parent.mkdir(parents=True)
    (repo / "state" / "latest.json").write_text("{}", encoding="utf-8")
    (repo / "reports" / "generated").mkdir(parents=True)
    (repo / "reports" / "generated" / "snapshot.json").write_text("{}", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert "generated_artifact_heavy" in detection["traits"]
    evidence_dirs = detection["intake_report"]["artifact_model"]["evidence_only_dirs"]
    assert evidence_dirs


def test_infra_repo_flags_destructive_command_patterns(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "main.tf").write_text('resource "null_resource" "x" {}\n', encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert "infra_sensitive" in detection["traits"]
    dangerous = str(detection["intake_report"]["command_model"]["dangerous_command_patterns"])
    assert "terraform apply" in dangerous
    assert "terraform destroy" in dangerous


def test_migration_repo_marks_existing_migrations_sensitive(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "migrations").mkdir()
    (repo / "migrations" / "001_init.sql").write_text("create table t(id int);\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert "migration_sensitive" in detection["traits"]
    zones = "\n".join(detection["intake_report"]["mutation_model"]["requires_explicit_authorization"]).lower()
    assert "migrations" in zones


def test_binary_asset_heavy_repo_keeps_assets_manifest_or_forbidden(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "Content").mkdir()
    (repo / "Content" / "level.umap").write_bytes(b"binary-map")
    (repo / "src").mkdir()
    (repo / "src" / "game.py").write_text("def run(): return True\n", encoding="utf-8")
    init_project(repo)
    idx = index_project(repo, "lite")
    detection = detect_projects(repo, entries=idx["entries"])
    assert "binary_asset_heavy" in detection["traits"]
    result = compile_prompt(repo, "Fix the game logic, do not edit assets", "lite")
    forbidden = "\n".join(result["patch_boundary"]["forbidden_without_user_confirmation"]).lower()
    assert "content" in forbidden or "level.umap" in forbidden
