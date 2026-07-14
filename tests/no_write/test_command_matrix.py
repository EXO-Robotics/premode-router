from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from premode import pcodex_bootstrap as pcodex
from premode import cli as premode_cli
from premode import inventory as inventory_module
from premode import openclaw_lifecycle
from premode import topology as topology_module
from premode import __version__
from premode.no_write import GovernedRoot, verify_no_write


def _repo(tmp_path: Path, name: str = "repository with spaces β") -> Path:
    repo = tmp_path / name
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0"\n', encoding="utf-8")
    (repo / "src" / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    return repo


def _controlled_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    temp = tmp_path / "empty-tmp"
    binary = tmp_path / "bin"
    for path in (home, temp, binary):
        path.mkdir()
    marker = home / "forbidden-agent-invocation"
    for name in ("codex", "openclaw", "mcp-server"):
        script = binary / name
        script.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n", encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TMPDIR", str(temp))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg-config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "xdg-cache"))
    monkeypatch.setenv("CODEX_HOME", str(home / "codex-home"))
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ.get("PATH", ""))
    return home, temp, marker


def _execute(argv: list[str]) -> tuple[int, str]:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        code = pcodex.main(argv)
    return code, stream.getvalue()


@pytest.mark.parametrize(
    "scenario,prepare",
    [
        ("missing", lambda repo: None),
        ("dirty-untracked", lambda repo: (repo / "untracked.txt").write_text("user", encoding="utf-8")),
        ("corrupt", lambda repo: ((repo / ".premode").mkdir(), (repo / ".premode" / "pcodex_state.json").write_text("{bad", encoding="utf-8"))),
        ("future", lambda repo: ((repo / ".premode").mkdir(), (repo / ".premode" / "pcodex_state.json").write_text(json.dumps({"schema_version": "pcodex.state.v999", "mode": "on"}), encoding="utf-8"))),
    ],
)
def test_advisory_status_and_doctor_leave_adversarial_state_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    prepare,
) -> None:
    repo = _repo(tmp_path, f"{scenario} repository β")
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    prepare(repo)
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    for command in (["status", "--advisory", "--json"], ["doctor", "--advisory", "--json"]):
        verification = verify_no_write(
            lambda command=command: _execute([*command, "--repo-root", str(repo)]),
            roots=roots,
            monitor_processes=False,
            monitor_filesystem=True,
        )
        assert verification["passed"], verification["comparison"]["changes"]
        assert verification["value"][0] == 0
        assert not marker.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "Inspect src/app.py exactly", "--dry-run", "--json"],
        ["integrate", "codex", "--dry-run", "--json"],
        ["uninstall", "--dry-run", "--json"],
        ["repair", "--dry-run", "--json"],
        ["cleanup", "--local-state", "--dry-run", "--json"],
        ["install"],
        ["first-run", "--advisory", "--json"],
        ["plugin", "init", "--local-marketplace", "--dry-run", "--json"],
        ["compile", "Inspect src/app.py exactly", "--dry-run", "--json"],
    ],
)
def test_every_advertised_pcodex_preview_is_literal_no_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    repo = _repo(tmp_path)
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    root_flag = "--repo" if argv[0] in {"run", "compile"} else "--repo-root"
    verification = verify_no_write(
        lambda: _execute([*argv, root_flag, str(repo)]),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert verification["value"][0] == 0, verification["value"][1]
    assert verification["passed"], verification["comparison"]["changes"]
    assert not marker.exists()


@pytest.mark.parametrize("operation", ["--dry-run", "--status"])
def test_openclaw_preview_and_status_are_literal_no_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    repo = _repo(tmp_path, "OpenClaw authority workspace β")
    (repo / "AGENTS.md").write_text("# authority\n", encoding="utf-8")
    (repo / "PROJECT/AI/worker_start").mkdir(parents=True)
    (repo / "PROJECT/tasks.json").write_text("{}\n", encoding="utf-8")
    (repo / "PROJECT/AI/worker_start/WORKER_START_HERE.md").write_text(
        "# worker\n", encoding="utf-8"
    )
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(
        openclaw_lifecycle,
        "openclaw_compatibility",
        lambda: {
            "installed": True,
            "version": "2026.4.14",
            "supported": True,
            "reason": "supported",
        },
    )
    monkeypatch.setattr(
        openclaw_lifecycle,
        "_installed_helper_authority_available",
        lambda _path: True,
    )
    roots = [
        GovernedRoot("repo", repo),
        GovernedRoot("home", home),
        GovernedRoot("temp", temp),
    ]

    verification = verify_no_write(
        lambda: _execute(
            [
                "integrate",
                "openclaw",
                operation,
                "--json",
                "--repo-root",
                str(repo),
            ]
        ),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )

    assert verification["passed"], verification["comparison"]["changes"]
    assert verification["value"][0] in {0, 1}
    assert not marker.exists()


def test_repair_preview_for_damaged_installed_state_is_strict_literal_no_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path, "damaged installed repository β")
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    assert pcodex.install(repo, dry_run=False)["lifecycle_after"]["readiness"] == "READY"
    marker.unlink(missing_ok=True)
    (repo / ".premode" / "pcodex-install.json").unlink()
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    verification = verify_no_write(
        lambda: _execute(["repair", "--dry-run", "--json", "--repo-root", str(repo)]),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert verification["passed"], verification["comparison"]["changes"]
    assert verification["value"][0] == 0
    assert not marker.exists()


def test_run_dry_run_does_not_create_state_when_compile_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    monkeypatch.setattr(pcodex, "compile_pcodex_packet", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failure")))
    verification = verify_no_write(
        lambda: pcodex.run_dry_run(repo, "Exact private task"),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert verification["passed"], verification["comparison"]["changes"]
    assert verification["value"]["effective_state"] == pcodex.EFFECTIVE_SAFE_PASSTHROUGH
    assert not marker.exists()


def test_wrapped_compile_runner_receives_advisory_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    observed = {}

    def wrapper(repo_root, prompt, profile, *, write_policy):
        observed["write_policy"] = write_policy
        return pcodex.compile_pcodex_packet(repo_root, prompt, profile, write_policy=write_policy)

    verification = verify_no_write(
        lambda: pcodex.run_dry_run(repo, "Exact task", compile_runner=wrapper),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert observed["write_policy"] is pcodex.ADVISORY
    assert verification["passed"], verification["comparison"]["changes"]
    assert not marker.exists()


def test_kwargs_only_compile_runner_cannot_drop_advisory_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    called = False

    def wrapper(*args, **kwargs):
        nonlocal called
        called = True
        return pcodex.compile_pcodex_packet(*args, **kwargs)

    verification = verify_no_write(
        lambda: pcodex.run_dry_run(repo, "Exact task", compile_runner=wrapper),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert called is False
    assert verification["passed"], verification["comparison"]["changes"]
    assert verification["value"]["effective_state"] == pcodex.EFFECTIVE_SAFE_PASSTHROUGH
    assert not marker.exists()


def test_premode_codex_dry_run_and_read_only_inspection_surfaces_do_not_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]

    def invoke() -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return premode_cli.main(
                [
                    "codex",
                    "Exact task for src/app.py",
                    "--repo",
                    str(repo),
                    "--dry-run",
                    "--no-save",
                ]
            )

    verification = verify_no_write(invoke, roots=roots, monitor_processes=False, monitor_filesystem=True)
    assert verification["value"] == 0
    assert verification["passed"], verification["comparison"]["changes"]
    assert not marker.exists()


def test_ui_inspection_preserves_unrelated_external_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    codex_home = home / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('[mcp_servers.unrelated]\ncommand="unrelated"\n', encoding="utf-8")
    marketplace = repo / ".agents" / "plugins"
    marketplace.mkdir(parents=True)
    (marketplace / "marketplace.json").write_text('{"plugins":[{"name":"unrelated"}]}\n', encoding="utf-8")
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    verification = verify_no_write(
        lambda: _execute(["ui", "--json", "--repo-root", str(repo)]),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert verification["value"][0] == 0
    assert verification["passed"], verification["comparison"]["changes"]
    assert not marker.exists()


def test_run_dry_run_does_not_refresh_real_git_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, "committed repository")
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    git_env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    subprocess.run(["git", "init", "-q"], cwd=repo, env=git_env, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, env=git_env, check=True)
    subprocess.run(
        ["git", "-c", "user.name=pCodex Test", "-c", "user.email=pcodex@example.invalid", "commit", "-qm", "fixture"],
        cwd=repo,
        env=git_env,
        check=True,
    )
    time.sleep(1.05)
    os.utime(repo / "src" / "app.py", None)
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    verification = verify_no_write(
        lambda: _execute(["run", "Inspect src/app.py exactly", "--dry-run", "--json", "--repo", str(repo)]),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert verification["value"][0] == 0
    assert verification["passed"], verification["comparison"]["changes"]
    assert not marker.exists()


def test_advisory_surfaces_do_not_execute_git_freshness_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    home, temp, marker = _controlled_environment(tmp_path, monkeypatch)
    state = repo / ".premode"
    (state / "inventory").mkdir(parents=True)
    (state / "topology").mkdir(parents=True)
    root_hash = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()
    (state / "inventory" / "files.json").write_text(
        json.dumps({"schema_version": inventory_module.INVENTORY_SCHEMA_VERSION, "lcc_version": __version__, "repo_root_hash": root_hash, "paths": []}),
        encoding="utf-8",
    )
    (state / "topology" / "repo_topology.json").write_text(
        json.dumps({"schema_version": topology_module.TOPOLOGY_SCHEMA_VERSION, "lcc_version": __version__, "repo_root_hash": root_hash, "nodes": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(inventory_module, "_git_text", lambda *args, **kwargs: pytest.fail("advisory inventory executed git"))
    monkeypatch.setattr(topology_module, "_git_text", lambda *args, **kwargs: pytest.fail("advisory topology executed git"))
    roots = [GovernedRoot("repo", repo), GovernedRoot("home", home), GovernedRoot("temp", temp)]
    verification = verify_no_write(
        lambda: _execute(["status", "--advisory", "--json", "--repo-root", str(repo)]),
        roots=roots,
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert verification["value"][0] == 0
    assert verification["passed"], verification["comparison"]["changes"]
    assert not marker.exists()
