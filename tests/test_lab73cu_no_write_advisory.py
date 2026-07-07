from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from premode import cli
from premode import pcodex_bootstrap as pcodex
from premode.compiler import compile_prompt
from premode.inventory import refresh_inventory_if_needed
from premode.topology import refresh_topology_if_needed
from premode.write_policy import ADVISORY, NO_RECORD, NORMAL, resolve_write_policy


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


def _commit(repo: Path, message: str = "seed") -> None:
    subprocess.run(
        ["git", "-c", "user.name=Pre Mode", "-c", "user.email=premode@example.test", "commit", "-m", message],
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


def _snapshot(repo: Path) -> dict[str, tuple[str, int, str | None]]:
    snapshot: dict[str, tuple[str, int, str | None]] = {}
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo).as_posix()
        if rel.startswith(".git/"):
            continue
        if path.is_dir():
            snapshot[rel + "/"] = ("dir", 0, None)
            continue
        data = path.read_bytes()
        snapshot[rel] = ("file", len(data), __import__("hashlib").sha256(data).hexdigest())
    return snapshot


def _assert_no_repo_change(repo: Path, before: dict[str, tuple[str, int, str | None]]) -> None:
    assert _snapshot(repo) == before


def _flatten(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def test_write_policy_definitions_are_explicit() -> None:
    assert resolve_write_policy("normal") is NORMAL
    assert resolve_write_policy("no-record") is NO_RECORD
    assert resolve_write_policy("advisory") is ADVISORY
    assert NORMAL.can_write_lockfile is True
    assert ADVISORY.can_write_lockfile is False
    assert ADVISORY.can_write_cache_manifest is False
    assert ADVISORY.can_write_inventory is False
    assert ADVISORY.can_write_topology is False
    assert ADVISORY.can_write_telemetry is False
    assert ADVISORY.can_register_mcp is False
    assert ADVISORY.can_run_codex is False
    assert ADVISORY.can_delete_local_state is False


def test_status_advisory_json_writes_nothing_and_does_not_create_premode(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    before = _snapshot(repo)

    assert cli.pcodex_main(["status", "--repo-root", str(repo), "--advisory", "--json"]) == 0

    _assert_no_repo_change(repo, before)
    assert not (repo / ".premode").exists()


def test_advisory_policy_hooks_do_not_refresh_inventory_or_topology(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    before = _snapshot(repo)

    inventory = refresh_inventory_if_needed(repo, policy=ADVISORY)
    topology = refresh_topology_if_needed(repo, policy=ADVISORY)

    assert inventory.freshness == "missing"
    assert topology.freshness == "missing"
    _assert_no_repo_change(repo, before)
    assert not (repo / ".premode").exists()


def test_doctor_and_first_run_advisory_json_write_nothing(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    before = _snapshot(repo)

    assert cli.pcodex_main(["doctor", "--repo-root", str(repo), "--advisory", "--json"]) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert cli.pcodex_main(["first-run", "--repo-root", str(repo), "--advisory", "--json"]) == 0
    first_payload = json.loads(capsys.readouterr().out)

    _assert_no_repo_change(repo, before)
    assert not (repo / ".premode").exists()
    for payload in (doctor_payload, first_payload):
        assert payload["schema_version"] == "pcodex.advisory_receipt.v1"
        assert payload["advisory"]["enabled"] is True
        assert payload["advisory"]["writes_performed"] is False
        assert payload["advisory"]["write_policy"] == "advisory"


def test_advisory_json_reports_missing_state_without_refreshing(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)

    assert cli.pcodex_main(["status", "--repo-root", str(repo), "--advisory", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["advisory"]["writes_performed"] is False
    assert {"inventory", "topology"}.issubset(set(payload["advisory"]["would_refresh"]))
    assert {"lockfile", "cache_manifest", "inventory", "topology"}.issubset(set(payload["advisory"]["would_write"]))
    assert {"lockfile", "cache_manifest", "inventory", "topology"}.issubset(set(payload["advisory"]["missing_or_stale"]))
    assert payload["state"]["inventory"]["state"] == "missing"
    assert payload["state"]["topology"]["state"] == "missing"
    assert not (repo / ".premode").exists()


def test_advisory_reports_stale_inventory_topology_without_refreshing(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    pcodex.run_dry_run(repo, "Fix src/app.py")
    _write(repo / "src" / "new_file.py", "VALUE = 2")
    _git(repo, "add", "src/new_file.py")
    _commit(repo, "change head")
    before = _snapshot(repo)

    assert cli.pcodex_main(["first-run", "--repo-root", str(repo), "--advisory", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    _assert_no_repo_change(repo, before)
    assert payload["state"]["inventory"]["state"] == "stale_head_changed"
    assert payload["state"]["topology"]["state"] == "stale_head_changed"
    assert {"inventory", "topology"}.issubset(set(payload["advisory"]["would_refresh"]))
    assert {"inventory", "topology"}.issubset(set(payload["advisory"]["would_write"]))


def test_advisory_receipts_are_paste_safe_json_and_human(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    secret_prompt = "SECRET_TOKEN_123 Fix src/app.py without leaking PASSWORD_abc."

    assert cli.pcodex_main(["status", "--repo-root", str(repo), "--advisory", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    flat = _flatten(payload)
    assert payload["privacy"]["content_free"] is True
    for forbidden in (
        "SECRET_TOKEN_123",
        "PASSWORD_abc",
        secret_prompt,
        "PREMODE_CONTEXT_PACKET",
        "def run",
        str(repo),
        "PCODEX_ENABLED",
        "raw_task_preview",
        "final_prompt_preview",
    ):
        assert forbidden not in flat

    assert cli.pcodex_main(["status", "--repo-root", str(repo), "--advisory"]) == 0
    human = capsys.readouterr().out
    assert "Advisory mode: enabled" in human
    assert "Writes performed: no" in human
    assert "Receipt is paste-safe" in human
    assert str(repo) not in human
    assert "SECRET_TOKEN_123" not in human


def test_normal_mode_still_writes_expected_state(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)

    assert not (repo / ".premode").exists()
    status_payload = pcodex.status(repo)
    assert status_payload["lockfile"]["status"] == "written"
    assert (repo / ".premode" / "lcc.lock.json").exists()

    pcodex.set_enabled(repo, True)
    pcodex.run_dry_run(repo, "Fix src/app.py")
    assert (repo / ".premode" / "pcodex_state.json").exists()
    assert (repo / ".premode" / "inventory" / "files.json").exists()
    assert (repo / ".premode" / "topology" / "repo_topology.json").exists()
    assert (repo / ".premode" / "out" / "cache_manifest.json").exists()


def test_no_record_compile_and_v5_literal_symbol_packet_remain_stable(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    before = compile_prompt(repo, "Fix src/app.py", "lite", **LITERAL_SYMBOL_KWARGS)

    assert cli.pcodex_main(["status", "--repo-root", str(repo), "--advisory", "--json"]) == 0
    capsys.readouterr()
    after = compile_prompt(repo, "Fix src/app.py", "lite", **LITERAL_SYMBOL_KWARGS)
    assert after["packet"] == before["packet"]
    for forbidden in ("<TASK_CLASS>", "<SUPPORT_RELATIONS>", "do-not-edit", "first-run", "advisory"):
        assert forbidden not in after["packet"]

    assert cli.main(["compile", "Fix src/app.py", "--repo", str(repo), "--plugin", "literal_symbol", "--json", "--no-record"]) == 0
    alias_payload = json.loads(capsys.readouterr().out)
    assert alias_payload["packet_version"] == "v5"
    assert not (repo / ".premode" / "audit").exists()
    assert not (repo / ".premode" / "metrics").exists()

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


def test_cleanup_dry_run_and_yes_remain_safe(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, True)
    pcodex.run_dry_run(repo, "Fix src/app.py")
    _write(repo / ".pcodex" / "config.toml", "[pcodex]\nenabled = true")
    _write(repo / "src" / "user_file.py", "VALUE = 1")

    dry = pcodex.cleanup_local_state(repo, dry_run=True)
    assert dry["writes_or_deletes"] is False
    assert (repo / ".premode" / "lcc.lock.json").exists()

    applied = pcodex.cleanup_local_state(repo, dry_run=False)
    assert applied["writes_or_deletes"] is True
    assert not (repo / ".premode" / "lcc.lock.json").exists()
    assert not (repo / ".premode" / "inventory").exists()
    assert not (repo / ".premode" / "topology").exists()
    assert (repo / ".pcodex" / "config.toml").exists()
    assert (repo / ".premodeignore").exists()
    assert (repo / "src" / "user_file.py").exists()
