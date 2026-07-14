from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
from pathlib import Path
from typing import Any

from premode import cli
from premode import pcodex_bootstrap as pcodex
from premode.compiler import compile_prompt
from premode.inventory import build_inventory
from premode.install_manifest import (
    build_install_manifest,
    should_exclude_source_install_path,
    validate_install_manifest,
)


RAW_PROMPT = "SECRET_LCC_PROMPT_NEVER_STORE Fix src/app.py"
LITERAL_SYMBOL_KWARGS = {
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
    "record_artifacts": False,
}


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _commit(repo: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Pre Mode", "-c", "user.email=premode@example.test", "commit", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo / ".gitignore", ".premode/\n")
    _write(repo / ".premodeignore", "secrets/\n")
    _write(repo / "pyproject.toml", "[project]\nname='demo'")
    _write(repo / "src" / "app.py", "def run():\n    return 'ok'")
    _write(repo / "tests" / "test_app.py", "def test_run():\n    assert True")
    _git(repo, "add", ".")
    _commit(repo)
    return repo


def _isolated_home(monkeypatch: Any, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PCODEX_ENABLED", raising=False)
    monkeypatch.delenv("PCODEX_ALGORITHM", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG_PATH", raising=False)


def _flatten(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def test_first_run_receipt_json_is_valid_content_free_and_actionable(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    pcodex.run_dry_run(repo, RAW_PROMPT)

    receipt = pcodex.first_run_receipt(repo)
    text = _flatten(receipt)

    assert receipt["schema_version"] == "pcodex.first_run_receipt.v1"
    assert receipt["lcc_installed"] is True
    assert receipt["lcc_version"]
    assert receipt["mode"]["public_mode"] == "on"
    assert receipt["mode"]["plugin_alias"] == "literal_symbol"
    assert receipt["first_run"]["next_action"] == 'pcodex run --dry-run "<task>"'
    assert receipt["privacy"]["content_free"] is True
    assert receipt["privacy"]["raw_prompts"] is False
    assert receipt["state"]["inventory"]["state"] == "fresh"
    assert receipt["state"]["topology"]["state"] == "fresh"
    assert "paths" not in receipt["state"]["inventory"]
    assert "nodes" not in receipt["state"]["topology"]
    assert "SECRET_LCC_PROMPT_NEVER_STORE" not in text
    assert "def run" not in text
    assert "PREMODE_CONTEXT_PACKET" not in text
    assert "API_KEY" not in text
    assert "PCODEX_ENABLED" not in text


def test_first_run_cli_json_and_human_output(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)

    assert cli.pcodex_main(["first-run", "--repo-root", str(repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "pcodex.first_run.v1"
    assert "pcodex cleanup --local-state --dry-run" in payload["cleanup_commands"]

    assert cli.pcodex_main(["first-run", "--repo-root", str(repo)]) == 0
    human = capsys.readouterr().out
    assert "pCodex first-run check complete." in human
    assert "Codex launch: not_executed" in human


def test_source_install_manifest_schema_records_provenance(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    build_repo = tmp_path / "build-copy"
    _write(build_repo / "src" / "premode" / "__init__.py", "")
    manifest = build_install_manifest(
        install_root=tmp_path / "install",
        source_repo=repo,
        build_repo=build_repo,
        python_executable="/usr/bin/python3",
        installer_script="scripts/install_pcodex_from_source.sh",
    )

    validated = validate_install_manifest(manifest)
    assert validated["schema_version"] == "pcodex.install_manifest.v1"
    assert validated["install_channel"] == "source_checkout"
    assert validated["source_type"] == "git_checkout"
    assert validated["source_branch"] in {"main", "master"}
    assert validated["source_head"]
    assert validated["source_dirty"] is False
    assert validated["console_scripts"] == ["premode", "pcodex"]
    assert validated["plugin_packages"] == []
    assert validated["builtin_strategies"] == ["literal_symbol"]
    assert validated["files_installed_count"] >= 1
    assert validated["provenance_status"] == "clean_source"


def test_source_installer_excludes_generated_runtime_and_lab_state() -> None:
    excluded = [
        ".premode/inventory/files.json",
        ".premode/topology/repo_topology.json",
        ".premode/out/cache_manifest.json",
        ".premode/lcc.lock.json",
        ".pytest_cache/v/cache/nodeids",
        "src/premode/__pycache__/cli.cpython-311.pyc",
        "premode_router.egg-info/SOURCES.txt",
        ".pcodex/config.toml",
        ".agents/plugins/example.json",
        "private/tmp/premode_labs/result.json",
    ]
    included = ["src/premode/cli.py", "docs/FIRST_RUN.md", "packages/premode-plugin-literal-symbol/pyproject.toml"]

    for path in excluded:
        assert should_exclude_source_install_path(path), path
    for path in included:
        assert not should_exclude_source_install_path(path), path


def test_legacy_v1_install_manifest_remains_readable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = build_install_manifest(install_root=tmp_path / "install", source_repo=repo)
    manifest.pop("builtin_strategies")
    validated = validate_install_manifest(manifest)
    assert validated["builtin_strategies"] == []


def test_cleanup_dry_run_lists_only_generated_local_state_and_does_not_delete(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    pcodex.run_dry_run(repo, "Fix src/app.py")
    _write(repo / ".pcodex" / "config.toml", "[pcodex]\nenabled = true")
    _write(repo / "src" / "user_file.py", "VALUE = 1")

    result = pcodex.cleanup_local_state(repo, dry_run=True)

    assert result["dry_run"] is True
    assert result["writes_or_deletes"] is False
    assert any(item["path"] == ".premode/lcc.lock.json" and item["action"] == "remove" for item in result["actions"])
    assert all(str(item["path"]).startswith(".premode/") for item in result["actions"])
    assert (repo / ".premode" / "lcc.lock.json").exists()
    assert (repo / ".pcodex" / "config.toml").exists()
    assert (repo / "src" / "user_file.py").exists()


def test_cleanup_yes_removes_only_safe_generated_state(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    pcodex.run_dry_run(repo, "Fix src/app.py")
    _write(repo / ".premodeignore", "keep\n")
    _write(repo / ".pcodex" / "config.toml", "[pcodex]\nenabled = true")
    _write(repo / "src" / "user_file.py", "VALUE = 1")

    result = pcodex.cleanup_local_state(repo, dry_run=False)

    assert result["dry_run"] is False
    assert ".premode/lcc.lock.json" in result["removed"]
    assert not (repo / ".premode" / "lcc.lock.json").exists()
    assert not (repo / ".premode" / "inventory").exists()
    assert not (repo / ".premode" / "topology").exists()
    assert (repo / ".pcodex" / "config.toml").exists()
    assert (repo / ".premodeignore").exists()
    assert (repo / "src" / "user_file.py").exists()


def test_cleanup_cli_requires_local_state_and_supports_json(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)

    assert cli.pcodex_main(["cleanup", "--repo-root", str(repo), "--dry-run"]) == 2
    capsys.readouterr()

    assert cli.pcodex_main(["cleanup", "--repo-root", str(repo), "--local-state", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "pcodex.cleanup_local_state.v1"
    assert payload["dry_run"] is True


def test_status_and_doctor_include_first_run_readiness_and_install_provenance(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    status = pcodex.status(repo)
    doctor = pcodex.doctor(repo)

    assert status["first_run"]["readiness"] == "ready_for_dry_run_refresh"
    assert doctor["first_run"]["next_action"] == 'pcodex run --dry-run "<task>"'
    assert status["install"]["provenance_status"] in {"missing_manifest", "unknown"}
    assert "source_repo_hash" in status["install"]
    assert "install_root_hash" in doctor["install"]
    assert "files_installed_count" in doctor["install"]
    assert "Readiness:" in pcodex.format_status(status)
    assert "Install provenance:" in pcodex.format_doctor(doctor)


def test_doctor_strict_returns_nonzero_for_blockers_and_zero_when_ready(
    monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(
        pcodex,
        "doctor",
        lambda _root, advisory=False: {
            "strict_ready": False,
            "strict_failures": ["managed_lifecycle_not_ready"],
        },
    )
    assert pcodex.main(["doctor", "--strict", "--json"]) == 2
    capsys.readouterr()

    monkeypatch.setattr(
        pcodex,
        "doctor",
        lambda _root, advisory=False: {"strict_ready": True, "strict_failures": []},
    )
    assert pcodex.main(["doctor", "--strict", "--json"]) == 0


def test_docs_and_manifest_point_to_canonical_first_run_and_future_package_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    first_run = (root / "docs" / "GETTING_STARTED.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    ai_start = (root / "AI_START_HERE.md").read_text(encoding="utf-8")
    manifest = json.loads((root / "premode.ai.json").read_text(encoding="utf-8"))

    assert "pcodex doctor --advisory --json" in first_run
    assert "premode_router-0.3.0b1-py3-none-any.whl" in first_run
    assert "not a public package installation claim" in first_run
    assert "docs/GETTING_STARTED.md" in readme
    assert "docs/GETTING_STARTED.md" in ai_start
    assert manifest["current_install"]["canonical_first_run_doc"] == "docs/GETTING_STARTED.md"
    assert "pcodex cleanup --local-state --dry-run" in manifest["cleanup"]


def test_v5_literal_symbol_packet_and_compile_surfaces_remain_stable(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    before = compile_prompt(repo, "Fix src/app.py", "lite", **LITERAL_SYMBOL_KWARGS)

    pcodex.set_enabled(repo, True)
    pcodex.first_run_receipt(repo)
    pcodex.cleanup_local_state(repo, dry_run=True)
    after = compile_prompt(repo, "Fix src/app.py", "lite", **LITERAL_SYMBOL_KWARGS)

    assert after["packet"] == before["packet"]
    for forbidden in ("<TASK_CLASS>", "<SUPPORT_RELATIONS>", "do-not-edit", "<TOPOLOGY>", "inventory", "first-run"):
        assert forbidden not in after["packet"]

    assert cli.main(["compile", "Fix src/app.py", "--repo", str(repo), "--plugin", "literal_symbol", "--json", "--no-record"]) == 0
    alias_payload = json.loads(capsys.readouterr().out)
    assert alias_payload["packet_version"] == "v5"
    assert alias_payload["packet_variant"] == "tool_assisted_anchors_internal"

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


def test_parallel_inventory_writes_use_unique_temp_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _index: build_inventory(repo, write=True), range(18)))

    cache_path = repo / ".premode" / "inventory" / "files.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "premode.git_file_inventory.v1"
    assert all(result.freshness == "fresh" for result in results)
    assert not list(cache_path.parent.glob("files.json*.tmp"))
