from __future__ import annotations

import json
from pathlib import Path

from premode.adapters import detect_projects
from premode.compiler import compile_prompt, _metric_from_manifest
from premode.indexer import index_project
from premode.command_discovery import discover_commands


def make_openclaw_repo(root: Path) -> None:
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("# Agents\nOpenClaw authority.\n", encoding="utf-8")
    (root / "WORKFLOW.md").write_text("# Workflow\nRead worker start first.\n", encoding="utf-8")
    (root / "README.md").write_text("# OpenClaw\n", encoding="utf-8")
    (root / "executor").mkdir()
    (root / "executor" / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
    (root / "PROJECT" / "AI" / "worker_start").mkdir(parents=True)
    (root / "PROJECT" / "AI" / "worker_start" / "WORKER_START_HERE.md").write_text("# Worker start\n", encoding="utf-8")
    (root / "PROJECT" / "AI").mkdir(exist_ok=True)
    (root / "PROJECT" / "AI" / "OUTPUT_HYGIENE_GUARDRAILS.md").write_text("# Hygiene\n", encoding="utf-8")
    (root / "PROJECT" / "state" / "worker_start").mkdir(parents=True)
    (root / "PROJECT" / "state" / "worker_start" / "WORKER_STARTER_CONTEXT_V1.json").write_text('{"current":true}', encoding="utf-8")
    (root / "PROJECT" / "state").mkdir(exist_ok=True)
    (root / "PROJECT" / "state" / "task_queue_normalized_latest.json").write_text('{"tasks":[]}', encoding="utf-8")
    (root / "PROJECT" / "state" / "path_authority_latest.json").write_text('{"paths":{}}', encoding="utf-8")
    (root / "PROJECT" / "state" / "artifact_authority_latest.json").write_text('{"artifacts":{}}', encoding="utf-8")
    (root / "PROJECT" / "tasks.json").write_text('{"tasks":[]}', encoding="utf-8")
    (root / "_claw_output" / "runs").mkdir(parents=True)
    (root / "_claw_output" / "runs" / "old_proof.json").write_text('{"historical":true}', encoding="utf-8")
    (root / "tools" / "gamebot").mkdir(parents=True)
    (root / "tools" / "gamebot" / "task_queue.py").write_text("print('help')\n", encoding="utf-8")
    (root / "tools" / "symphony").mkdir(parents=True)
    (root / "tools" / "symphony" / "validator.py").write_text("def validate(): return True\n", encoding="utf-8")
    (root / "tests" / "symphony").mkdir(parents=True)
    (root / "tests" / "symphony" / "test_validator.py").write_text("def test_ok(): assert True\n", encoding="utf-8")


def test_openclaw_markers_outrank_nested_node_executor(tmp_path: Path) -> None:
    make_openclaw_repo(tmp_path)
    idx = index_project(tmp_path, "lite")
    detection = detect_projects(tmp_path, entries=idx["entries"], prompt="Run the OpenClaw proof-governed task packet")
    active = detection["active_project"]
    assert active["project_kind"] == "openclaw_control_plane"
    assert active["root"] == "."
    assert active["authority_model"] == "proof_governed_control_plane"
    assert any(p["project_kind"] == "node" for p in detection["detected_projects"])


def test_openclaw_compile_includes_proof_policy_and_authority_surfaces(tmp_path: Path) -> None:
    make_openclaw_repo(tmp_path)
    result = compile_prompt(tmp_path, "Review the OpenClaw task queue proof packet. Do not mutate bridge-write or Unreal.", "lite")
    assert result["project_detection"]["active_project"]["project_kind"] == "openclaw_control_plane"
    policy = result["proof_policy"]
    assert policy["authority_model"] == "proof_governed_control_plane"
    assert policy["proof_policy"]["do_not_claim_runtime_from_static_or_browser_evidence"] is True
    assert policy["proof_policy"]["do_not_mutate_bridge_unreal_or_blender_without_authorization"] is True
    flags = []
    for tier_name in ("full_text_files", "summarized_files", "manifest_only_files"):
        for item in result["context_tiers"][tier_name]:
            flags.extend(item.get("evidence_flags", []))
    assert "current_authority_surface" in flags
    assert "bridge_write" in result["commands"]["commands"]
    assert result["commands"]["commands"]["bridge_write"]["safe_to_suggest"] is False


def test_openclaw_command_discovery_is_safe_profile(tmp_path: Path) -> None:
    make_openclaw_repo(tmp_path)
    detection = detect_projects(tmp_path)
    commands = discover_commands(tmp_path, detection)
    assert "test_symphony" in commands["commands"]
    assert "bridge_write" in commands["commands"]
    assert commands["commands"]["bridge_write"]["safe_to_suggest"] is False


def test_savings_precision_does_not_round_to_false_100() -> None:
    metrics = _metric_from_manifest({"metrics": {"eligible_readable_repo_tokens": 67_948_617}}, "x" * (20_495 * 4))
    assert metrics["estimated_savings_vs_eligible_repo_percent"] < 100.0
    assert metrics["estimated_savings_vs_eligible_repo_percent"] == 99.9698
