from __future__ import annotations

import json
from pathlib import Path

from premode.cli import main
from premode.codex_exec import CodexOptions, run_codex
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _prepare(repo: Path) -> None:
    init_project(repo)
    (repo / "src" / "worker.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_worker.py").write_text("from src.worker import run\n\ndef test_run():\n    assert run() == 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")
    index_project(repo, "lite")


def test_v3_packet_cache_aware_order_and_metrics(repo):
    _prepare(repo)
    result = compile_prompt(repo, "Fix src/worker.py without touching pyproject.toml", "lite", use_repo_map=True, cache_optimized=True)
    packet = result["packet"]
    assert packet.startswith("PREMODE_COMPILED_PACKET_V3")
    assert "## CACHEABLE PREFIX" in packet
    assert "## 1. Packet schema/version" in packet
    assert "## 2. Stable agent contract" in packet
    assert "## DYNAMIC SUFFIX" in packet
    assert "## 10. CANONICAL USER PROMPT" in packet
    assert "## 11. Candidate Files" in packet
    assert "## 12. Do-Not-Edit Paths" in packet
    assert "## 13. Discovered Commands" in packet
    assert packet.index("## 1. Packet schema/version") < packet.index("## 10. CANONICAL USER PROMPT")
    assert "Fix src/worker.py without touching pyproject.toml" in packet
    assert packet.index("raw_prompt_sha256") > packet.index("## DYNAMIC SUFFIX")
    assert result["packet_version"] == "PREMODE_COMPILED_PACKET_V3"
    assert 0 < result["cacheable_prefix_tokens"] < 1024
    assert result["dynamic_suffix_tokens"] > 0
    assert result["cacheable_prefix_sha256"]
    assert result["dynamic_suffix_sha256"]
    assert result["repo_map_sha256"]
    assert result["packet_sha256"] == result["compiled_packet_sha256"]
    assert result["metrics"]["packet_version"] == "PREMODE_COMPILED_PACKET_V3"


def test_v3_prefix_hash_stable_and_dynamic_suffix_changes(repo):
    _prepare(repo)
    first = compile_prompt(repo, "Fix src/worker.py", "lite", use_repo_map=True, cache_optimized=True)
    second = compile_prompt(repo, "Add a unit test for src/worker.py", "lite", use_repo_map=True, cache_optimized=True)
    assert first["cacheable_prefix_sha256"] == second["cacheable_prefix_sha256"]
    assert first["dynamic_suffix_sha256"] != second["dynamic_suffix_sha256"]


def test_cache_optimized_and_packet_version_select_v3_but_v2_still_works(repo):
    _prepare(repo)
    v3a = compile_prompt(repo, "Fix worker", "lite", cache_optimized=True)
    v3b = compile_prompt(repo, "Fix worker", "lite", packet_version="v3")
    v2 = compile_prompt(repo, "Fix worker", "lite", packet_version="v2")
    assert v3a["packet"].startswith("PREMODE_COMPILED_PACKET_V3")
    assert v3b["packet"].startswith("PREMODE_COMPILED_PACKET_V3")
    assert v2["packet"].startswith("PREMODE_COMPILED_PACKET_V2")
    assert v2["cacheable_prefix_tokens"] is None


def test_compile_save_writes_last_packet_artifacts(repo):
    _prepare(repo)
    result = compile_prompt(repo, "Fix worker", "lite", use_repo_map=True, cache_optimized=True, save=True)
    out = repo / ".premode" / "out"
    assert (out / "last_packet.md").read_text(encoding="utf-8") == result["packet"]
    packet_json = json.loads((out / "last_packet.json").read_text(encoding="utf-8"))
    receipt = json.loads((out / "last_context_receipt.json").read_text(encoding="utf-8"))
    repo_map = json.loads((out / "last_repo_map_summary.json").read_text(encoding="utf-8"))
    assert packet_json["packet_version"] == "PREMODE_COMPILED_PACKET_V3"
    assert receipt["repo_map_enabled"] is True
    assert repo_map["repo_map_sha256"] == result["repo_map_sha256"]
    assert result["saved_artifacts"]["last_packet_md"].endswith("last_packet.md")


def test_cli_flags_select_v3_and_save(monkeypatch, capsys, repo):
    _prepare(repo)
    monkeypatch.chdir(repo)
    rc = main(["compile", "Fix worker", "--profile", "lite", "--use-repo-map", "--cache-optimized", "--save", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packet_version"] == "PREMODE_COMPILED_PACKET_V3"
    assert payload["cacheable_prefix_tokens"] == 0
    assert payload["production_ranking"]["routing_mode"] == "abstain"
    assert (repo / ".premode" / "out" / "last_packet.md").exists()


def test_codex_default_uses_repo_map_cache_v3_and_saves(repo):
    _prepare(repo)
    dry = run_codex(repo, "Fix worker", None, CodexOptions(dry_run=True))
    settings = dry["compile_settings"]
    assert settings["profile"] == "lite"
    assert settings["use_repo_map"] is True
    assert settings["cache_optimized"] is True
    assert settings["packet_version"] == "PREMODE_COMPILED_PACKET_V3"
    assert dry["command"][-1] == "-"
    assert dry["saved_artifacts"] is None
    assert not (repo / ".premode" / "out" / "last_packet.md").exists()


def test_codex_no_repo_map_opt_out(repo):
    _prepare(repo)
    dry = run_codex(repo, "Fix worker", "lite", CodexOptions(dry_run=True, use_repo_map=False))
    assert dry["compile_settings"]["use_repo_map"] is False
    assert not (repo / ".premode" / "out" / "last_repo_map_summary.json").exists()
