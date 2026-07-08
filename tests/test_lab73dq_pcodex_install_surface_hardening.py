from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from premode import cli
from premode import pcodex_bootstrap as pcodex


ROOT = Path(__file__).resolve().parents[1]


def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PCODEX_ENABLED", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG", raising=False)
    monkeypatch.delenv("PCODEX_CONFIG_PATH", raising=False)


def _tracked_status(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    return completed.stdout


def test_pcodex_help_includes_first_run_and_cleanup(capsys: pytest.CaptureFixture[str]) -> None:
    assert pcodex.main(["--help"]) == 0

    help_text = capsys.readouterr().out

    assert "first-run" in help_text
    assert "cleanup" in help_text


def test_pcodex_first_run_json_returns_content_free_status(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _isolated_home(monkeypatch, tmp_path)

    assert pcodex.main(["first-run", "--json", "--repo-root", str(repo)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "pcodex.first_run.v1"
    assert payload["status"] == "ok"
    assert payload["codex_launch"] == "not_executed"
    assert payload["global_codex_config_mutation"] is False
    assert payload["next_action"] == "pcodex setup --skip-tune --no-mcp --json"
    assert "pcodex cleanup --local-state --dry-run" in payload["cleanup_commands"]
    assert "packet" not in json.dumps(payload).lower()


def test_pcodex_first_run_advisory_json_records_no_writes(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    before = sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*"))

    assert pcodex.main(["first-run", "--advisory", "--json", "--repo-root", str(repo)]) == 0
    payload = json.loads(capsys.readouterr().out)
    after = sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*"))

    assert payload["advisory"] is True
    assert payload["writes_performed"] is False
    assert payload["codex_launch"] == "not_executed"
    assert before == after


def test_pcodex_cleanup_local_state_dry_run_previews_without_delete(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    state_file = repo / ".premode" / "pcodex_state.json"
    tuning_file = repo / ".premode" / "tuning" / "repo_profile.json"
    tuning_file.parent.mkdir(parents=True)
    state_file.write_text("{}", encoding="utf-8")
    tuning_file.write_text("{}", encoding="utf-8")

    result = pcodex.cleanup_local_state(repo, dry_run=True)

    assert result["status"] == "preview"
    assert result["deleted_paths"] == []
    assert ".premode/pcodex_state.json" in result["planned_paths"]
    assert ".premode/tuning" in result["planned_paths"]
    assert state_file.exists()
    assert tuning_file.exists()
    assert result["codex_launch"] == "not_executed"


def test_pcodex_cleanup_local_state_yes_deletes_only_known_generated_state(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    generated = repo / ".premode" / "out" / "last_packet.json"
    preserved = repo / ".premodeignore"
    generated.parent.mkdir(parents=True)
    generated.write_text("{}", encoding="utf-8")
    preserved.write_text(".premode/out/\n", encoding="utf-8")

    result = pcodex.cleanup_local_state(repo, yes=True)

    assert result["status"] == "deleted"
    assert ".premode/out" in result["deleted_paths"]
    assert not generated.exists()
    assert preserved.exists()
    assert (repo / "README.md").exists()
    assert result["codex_launch"] == "not_executed"


def test_pcodex_cleanup_requires_explicit_dry_run_or_yes(repo: Path) -> None:
    with pytest.raises(ValueError):
        pcodex.cleanup_local_state(repo)


def test_unknown_pcodex_command_exits_nonzero_and_does_not_call_codex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("unknown pcodex command must not route to premode codex"))

    assert cli.pcodex_main(["__definitely_unknown_command__"]) != 0


def test_command_shaped_unknown_input_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("command-shaped input must not launch Codex"))

    assert cli.pcodex_main(["does-not-exist", "--json"]) != 0


def test_only_explicit_pcodex_run_enters_run_path(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, str, str | None]] = []

    def fake_dry_run(repo_root: Path, prompt: str, profile: str | None = "lite", **_: object) -> dict[str, object]:
        calls.append((repo_root, prompt, profile))
        return {"status": "dry_run", "codex_launch": "not_executed"}

    monkeypatch.setattr(pcodex, "run_dry_run", fake_dry_run)
    assert pcodex.main(["first-run", "--repo-root", str(repo)]) == 0
    assert calls == []

    assert pcodex.main(["run", "Inspect hello.txt", "--dry-run", "--repo", str(repo)]) == 0
    assert calls == [(repo, "Inspect hello.txt", "lite")]


def test_pcodex_run_dry_run_reports_codex_launch_not_executed(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    pcodex.set_enabled(repo, False)

    result = pcodex.run_dry_run(repo, "Inspect hello.txt")

    assert result["status"] == "dry_run"
    assert result["codex_launch"] == "not_executed"


def test_source_installer_smoke_checks_required_command_surface() -> None:
    script = (ROOT / "scripts" / "install_pcodex_from_source.sh").read_text(encoding="utf-8")

    assert "first-run --json" in script
    assert "cleanup --local-state --dry-run" in script
    assert "__definitely_unknown_command__" in script
    assert "installed pcodex --help is missing first-run" in script
    assert "installed pcodex --help is missing cleanup" in script


def test_install_surface_checks_do_not_mutate_tracked_source(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "add", "README.md", "AGENTS.md", "src/App.swift"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True, text=True)

    assert pcodex.main(["first-run", "--advisory", "--json", "--repo-root", str(repo)]) == 0
    assert pcodex.main(["cleanup", "--local-state", "--dry-run", "--repo-root", str(repo)]) == 0

    assert _tracked_status(repo) == ""


def test_docs_command_list_matches_first_run_and_cleanup_help_surface(capsys: pytest.CaptureFixture[str]) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "docs" / "PCODEX_BOOTSTRAP.md").read_text(encoding="utf-8")

    assert pcodex.main(["--help"]) == 0
    help_text = capsys.readouterr().out

    for command in ("first-run", "cleanup"):
        assert command in help_text
        assert f"pcodex {command}" in readme
        assert f"pcodex {command}" in bootstrap
