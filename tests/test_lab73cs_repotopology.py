from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from premode import cli
from premode import pcodex_bootstrap as pcodex
from premode.benchmark import run_benchmark
from premode.compiler import compile_prompt
from premode.inventory import build_inventory
from premode.topology import (
    build_topology,
    load_topology,
    refresh_topology_if_needed,
    select_project_nodes,
    summarize_topology,
    topology_cache_path,
    topology_is_fresh,
)

LITERAL_SYMBOL_KWARGS = {
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
}


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _commit(repo: Path, message: str = "seed") -> None:
    subprocess.run(
        ["git", "-c", "user.name=Pre Mode", "-c", "user.email=premode@example.test", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _repo(tmp_path: Path, files: dict[str, str], *, commit: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init")
    base = {".gitignore": ".premode/\n"}
    base.update(files)
    for rel, text in base.items():
        if rel.endswith("/"):
            (repo / rel).mkdir(parents=True, exist_ok=True)
        else:
            _write(repo / rel, text)
    _git(repo, "add", ".")
    if commit:
        _commit(repo)
    return repo


def _topology(repo: Path) -> dict[str, Any]:
    inventory = build_inventory(repo).inventory
    assert inventory is not None
    topology = build_topology(repo, inventory).topology
    assert topology is not None
    return topology


def _node(topology: dict[str, Any], root: str) -> dict[str, Any]:
    for node in topology["nodes"]:
        if node["root"] == root:
            return node
    raise AssertionError(f"node not found: {root}")


def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PCODEX_ENABLED", raising=False)
    monkeypatch.delenv("PCODEX_ALGORITHM", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG_PATH", raising=False)


def test_single_package_python_repo_creates_python_node(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "pyproject.toml": "[project]\nname='demo'",
        "src/demo/app.py": "def run(): pass",
        "tests/test_app.py": "def test_run(): pass",
    })
    topology = _topology(repo)
    assert topology["schema_version"] == "repotopology.v1"
    assert topology["repo_shape"] == "single_package"
    node = _node(topology, ".")
    assert node["ecosystem"] == "python"
    assert "src" in node["source_roots"]
    assert "tests" in node["test_roots"]


def test_single_package_node_repo_detects_package_and_tests(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "package.json": '{"name":"demo","scripts":{"test":"vitest"}}',
        "tsconfig.json": "{}",
        "src/index.ts": "export const value = 1",
        "tests/index.test.ts": "test('value', () => {})",
    })
    topology = _topology(repo)
    node = _node(topology, ".")
    assert node["ecosystem"] == "node_ts"
    assert "package.json" in node["package_files"]
    assert node["source_count"] >= 1
    assert node["test_count"] >= 1


def test_go_workspace_detects_child_project_node(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "go.work": "go 1.22\nuse ./services/scheduler",
        "services/scheduler/go.mod": "module example.com/scheduler",
        "services/scheduler/cmd/scheduler/main.go": "package main",
        "services/scheduler/scheduler_test.go": "package main",
    })
    topology = _topology(repo)
    assert _node(topology, ".")["ecosystem"] == "go"
    child = _node(topology, "services/scheduler")
    assert child["ecosystem"] == "go"
    assert child["source_count"] >= 1


def test_rust_workspace_detects_crate_nodes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "Cargo.toml": "[workspace]\nmembers=['crates/core']",
        "crates/core/Cargo.toml": "[package]\nname='core'",
        "crates/core/src/lib.rs": "pub fn run() {}",
        "crates/core/tests/core.rs": "#[test] fn works() {}",
    })
    topology = _topology(repo)
    assert _node(topology, "crates/core")["ecosystem"] == "rust"
    assert topology["repo_shape"] in {"multi_package", "monorepo"}


def test_polyglot_monorepo_detects_multiple_ecosystems(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "packages/api/pyproject.toml": "[project]\nname='api'",
        "packages/api/src/api/main.py": "def main(): pass",
        "apps/web/package.json": '{"name":"web"}',
        "apps/web/src/page.tsx": "export default function Page() { return null }",
    })
    topology = _topology(repo)
    ecosystems = {node["ecosystem"] for node in topology["nodes"]}
    assert {"python", "node_ts"} <= ecosystems
    assert topology["repo_shape"] == "polyglot_monorepo"


def test_bazel_swift_docs_generated_and_unknown_shapes(tmp_path: Path) -> None:
    bazel = _topology(_repo(tmp_path / "bazel", {"WORKSPACE": "", "BUILD.bazel": "cc_library(name='x')", "src/x.cc": "int x;"}))
    assert _node(bazel, ".")["ecosystem"] == "bazel_polyglot"

    swift_repo = _repo(tmp_path / "swift", {"Package.swift": "// swift-tools-version: 5.9", "Sources/App/App.swift": "struct App {}"})
    (swift_repo / "App.xcodeproj").mkdir()
    swift = _topology(swift_repo)
    assert _node(swift, ".")["ecosystem"] == "swift_ios"

    docs = _topology(_repo(tmp_path / "docs", {"mkdocs.yml": "site_name: docs", "docs/index.md": "# Docs", "docs/install.md": "# Install"}))
    assert docs["repo_shape"] == "docs_heavy"

    generated_repo = _repo(
        tmp_path / "generated",
        {
            "package.json": '{"name":"x"}',
            "src/index.ts": "export {}",
            "generated/client.ts": "export {}",
            "vendor/lib/index.js": "module.exports = {}",
        },
    )
    (generated_repo / ".pytest_cache").mkdir()
    generated = _topology(generated_repo)
    assert "generated" in _node(generated, ".")["generated_roots"]
    assert "vendor" in _node(generated, ".")["vendor_roots"]
    assert ".pytest_cache" in _node(generated, ".")["runtime_roots"]

    unknown = _topology(_repo(tmp_path / "unknown", {"notes.todo": "later"}))
    assert unknown["repo_shape"] == "unknown"
    assert _node(unknown, ".")["ecosystem"] == "unknown"


def test_topology_cache_is_ignored_and_content_free(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"pyproject.toml": "[project]\nname='secret-free'", "src/app.py": "SECRET_SOURCE_BODY = 'do not store'"})
    build_inventory(repo)
    topology = _topology(repo)
    path = topology_cache_path(repo)
    assert path == repo / ".premode" / "topology" / "repo_topology.json"
    assert load_topology(repo)["schema_version"] == "repotopology.v1"
    ignored = subprocess.run(["git", "check-ignore", ".premode/topology/repo_topology.json"], cwd=repo, text=True, capture_output=True)
    assert ignored.returncode == 0
    text = path.read_text(encoding="utf-8")
    assert "SECRET_SOURCE_BODY" not in text
    assert "<TASK>" not in text
    assert "Fix the failing test" not in text
    assert "paths" not in summarize_topology(repo, topology)


def test_topology_freshness_states_track_inventory_branch_head_schema_and_marker_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"pyproject.toml": "[project]\nname='demo'", "src/app.py": "x = 1"})
    inventory = build_inventory(repo).inventory
    topology = build_topology(repo, inventory).topology
    assert topology_is_fresh(repo, topology, inventory) == "fresh"
    bad_schema = dict(topology)
    bad_schema["schema_version"] = "old"
    assert topology_is_fresh(repo, bad_schema, inventory) == "stale_schema_changed"
    bad_branch = dict(topology)
    bad_branch["git_branch"] = "other"
    assert topology_is_fresh(repo, bad_branch, inventory) == "stale_branch_changed"
    bad_head = dict(topology)
    bad_head["git_head"] = "0000000"
    assert topology_is_fresh(repo, bad_head, inventory) == "stale_head_changed"
    bad_marker = dict(topology)
    bad_marker["marker_signature"] = "different"
    assert topology_is_fresh(repo, bad_marker, inventory) == "stale_marker_changed"
    _write(repo / "src/new_file.py", "x = 2")
    assert topology_is_fresh(repo, topology) == "stale_inventory_changed"
    refreshed_inventory = build_inventory(repo).inventory
    refreshed_topology = build_topology(repo, refreshed_inventory).topology
    _write(repo / ".premodeignore", "tmp/\n")
    assert topology_is_fresh(repo, refreshed_topology) == "stale_ignore_changed"


def test_node_selection_priority_and_ambiguity(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "packages/auth/package.json": '{"name":"auth"}',
        "packages/auth/src/session.ts": "export const session = 1",
        "packages/billing/package.json": '{"name":"billing"}',
        "packages/billing/src/invoice.ts": "export const invoice = 1",
    })
    topology = _topology(repo)
    explicit = select_project_nodes("Fix tests for packages/auth/src/session.ts", repo, topology, cwd=repo / "packages/billing")
    assert explicit["primary_node"] == "packages/auth"
    cwd = select_project_nodes("Fix the package tests", repo, topology, cwd=repo / "packages/billing")
    assert cwd["primary_node"] == "packages/billing"
    dirty = select_project_nodes("Fix failing tests", repo, topology, dirty_files=["packages/auth/src/session.ts"])
    assert dirty["primary_node"] == "packages/auth"
    term = select_project_nodes("Update the billing package build config", repo, topology)
    assert term["primary_node"] == "packages/billing"
    ambiguous = select_project_nodes("Fix package tests", repo, topology)
    assert ambiguous["ambiguous"] is True
    assert len(ambiguous["selected_nodes"]) >= 2


def test_warm_compile_reuses_fresh_topology_without_walk_or_rglob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, {"pyproject.toml": "[project]\nname='demo'", "src/app.py": "def run(): pass", "tests/test_app.py": "def test_run(): pass"})
    cold = compile_prompt(repo, "Fix src/app.py", "lite", record_artifacts=True, **LITERAL_SYMBOL_KWARGS)
    assert cold["topology"]["cache_hit"] is False

    def forbidden_walk(*_args: Any, **_kwargs: Any):
        raise AssertionError("os.walk forbidden after topology is fresh")

    def forbidden_rglob(*_args: Any, **_kwargs: Any):
        raise AssertionError("Path.rglob forbidden after topology is fresh")

    monkeypatch.setattr(os, "walk", forbidden_walk)
    monkeypatch.setattr(Path, "rglob", forbidden_rglob)

    warm = compile_prompt(repo, "Fix src/app.py", "lite", record_artifacts=False, **LITERAL_SYMBOL_KWARGS)
    assert warm["metrics"]["inventory_cache_hit"] is True
    assert warm["metrics"]["topology_cache_hit"] is True
    assert warm["metrics"]["topology_full_walk_performed"] is False
    assert warm["metrics"]["full_walk_performed"] is False
    assert warm["packet"] == cold["packet"]


def test_status_doctor_compile_and_benchmark_expose_topology_out_of_band(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {"package.json": '{"name":"demo"}', "src/index.ts": "export const x = 1", "tests/index.test.ts": "test('x', () => {})"})
    _isolated_home(monkeypatch, tmp_path)
    compile_prompt(repo, "Fix src/index.ts", "lite", record_artifacts=True, **LITERAL_SYMBOL_KWARGS)
    status = pcodex.status(repo)
    doctor = pcodex.doctor(repo)
    for payload in (status, doctor):
        assert payload["topology"]["state"] == "fresh"
        assert payload["topology"]["repo_shape"] == "single_package"
        assert payload["topology"]["node_count"] >= 1
        assert "nodes" not in payload["topology"]
    assert "Topology: fresh, single_package" in pcodex.format_status(status)
    assert "Topology: fresh, single_package" in pcodex.format_doctor(doctor)

    assert cli.main(["compile", "Fix src/index.ts", "--repo", str(repo), "--plugin", "literal_symbol", "--json", "--no-record"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packet_version"] == "canonical_packet.v1"
    assert payload["routing_authority_receipt"]["authority_id"] == "normal_routing_authority.v1"

    benchmark = run_benchmark(repo, use_repo_map=False, packet_version="v5", packet_variant="tool_assisted_anchors_internal", packet_strategy="literal_symbol")
    assert benchmark["cases"]
    assert "topology_repo_shape" in benchmark["cases"][0]


def test_v5_literal_symbol_packet_and_alias_surfaces_remain_stable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {"pyproject.toml": "[project]\nname='demo'", "src/app.py": "def run(): pass", "tests/test_app.py": "def test_run(): pass"})
    before = compile_prompt(repo, "Fix src/app.py", "lite", record_artifacts=False, **LITERAL_SYMBOL_KWARGS)
    build_inventory(repo)
    build_topology(repo, build_inventory(repo).inventory)
    after = compile_prompt(repo, "Fix src/app.py", "lite", record_artifacts=False, **LITERAL_SYMBOL_KWARGS)
    assert after["packet"] == before["packet"]
    for forbidden in (
        "<TASK_CLASS>",
        "<SUPPORT_RELATIONS>",
        "do-not-edit",
        "<TOPOLOGY>",
        "Topology:",
        "inventory",
        "release_gate",
        "external_fixtures",
    ):
        assert forbidden not in after["packet"]

    assert cli.main(["compile", "Fix src/app.py", "--repo", str(repo), "--plugin", "literal_symbol", "--json", "--no-record"]) == 0
    alias_payload = json.loads(capsys.readouterr().out)
    assert alias_payload["packet_version"] == "canonical_packet.v1"
    assert alias_payload["packet_variant"] == "paths_only"
    assert cli.main([
        "compile",
        "Fix src/app.py",
        "--repo",
        str(repo),
        "--packet-version",
        "v5",
        "--packet-variant",
        "tool_assisted_anchors_internal",
        "--packet-strategy",
        "literal_symbol",
        "--json",
        "--no-record",
    ]) == 0
    explicit_payload = json.loads(capsys.readouterr().out)
    assert explicit_payload["metrics"]["packet_strategy"] == "literal_symbol"
