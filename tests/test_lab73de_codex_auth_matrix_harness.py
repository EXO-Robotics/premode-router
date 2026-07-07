from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import pcodex_bootstrap
from premode.live_token_harness import (
    CODEX_AUTH_ALLOW_COPY_ENV,
    CODEX_AUTH_MODE_ENV,
    CODEX_AUTH_SOURCE_HOME_ENV,
    LIVE_MATRIX_ENV,
    LIVE_SPEND_ENV,
    _bootstrap_lane_auth,
    _codex_exec_command,
    run_live_token_harness,
)


def _git_fixture(path: Path) -> None:
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    (path / "app.py").write_text("def message():\n    return 'ok'\n", encoding="utf-8")
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Pre Mode", "-c", "user.email=premode@example.test", "commit", "-m", "fixture"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _matrix(tmp_path: Path, fixture: Path, count: int = 6) -> Path:
    tasks = []
    for index in range(count):
        tasks.append(
            {
                "task_id": f"task_{index}",
                "fixture_path": str(fixture),
                "fixture": fixture.name,
                "prompt_text": f"Update disposable fixture task {index}.",
                "expected_files": ["README.md"],
                "expected_tests": [],
                "forbidden_files": ["src/forbidden.py"],
                "validation_command": ["python", "-m", "py_compile", "app.py"],
            }
        )
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps({"schema_version": "test.matrix.v1", "random_seed": 17, "tasks": tasks}), encoding="utf-8")
    return path


def test_matrix_task_file_parsing_and_dry_run_creates_twelve_lane_records(tmp_path: Path, repo: Path) -> None:
    fixture = tmp_path / "fixture"
    _git_fixture(fixture)
    matrix = _matrix(tmp_path, fixture)

    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path / "artifacts", mode="dry_run_mock", task_matrix=matrix)

    assert result["schema_version"] == "premode.live_token_harness.matrix_result.v1"
    assert result["task_pair_count"] == 6
    assert result["lane_record_count"] == 12
    assert result["live_codex_run"] is False
    assert result["safety"]["repo_isolation_verified"] is True
    assert all(row["standard"]["usage_unavailable_reason"] == "dry_run_mock_no_live_codex" for row in result["tasks"])
    assert all(row["enhanced"]["usage_unavailable_reason"] == "dry_run_mock_no_live_codex" for row in result["tasks"])


def test_matrix_records_seed_order_and_isolated_repo_copies(tmp_path: Path, repo: Path) -> None:
    fixture = tmp_path / "fixture"
    _git_fixture(fixture)
    matrix = _matrix(tmp_path, fixture, count=2)

    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path / "artifacts", mode="dry_run_mock", task_matrix=matrix, matrix_seed=5)

    assert result["matrix_seed"] == 5
    assert result["lane_order_randomized"] is True
    assert {tuple(row["lane_order"]) for row in result["tasks"]} <= {("standard", "enhanced"), ("enhanced", "standard")}
    assert all(row["safety"]["repo_isolation_verified"] for row in result["tasks"])


def test_live_matrix_refuses_without_live_spend_flag(tmp_path: Path, repo: Path) -> None:
    fixture = tmp_path / "fixture"
    _git_fixture(fixture)
    matrix = _matrix(tmp_path, fixture, count=1)

    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path / "artifacts", mode="live_matrix", task_matrix=matrix, env={})

    assert result["live_codex_run"] is False
    assert result["standard"]["usage_unavailable_reason"] == f"{LIVE_SPEND_ENV}_not_enabled"


def test_live_matrix_refuses_without_matrix_flag(tmp_path: Path, repo: Path) -> None:
    fixture = tmp_path / "fixture"
    _git_fixture(fixture)
    matrix = _matrix(tmp_path, fixture, count=1)

    result = run_live_token_harness(
        source_repo=repo,
        artifact_root=tmp_path / "artifacts",
        mode="live_matrix",
        task_matrix=matrix,
        env={LIVE_SPEND_ENV: "1"},
    )

    assert result["live_codex_run"] is False
    assert result["delta"]["conclusion"] == f"{LIVE_MATRIX_ENV}_not_enabled"


def test_auth_cache_copy_refuses_without_explicit_copy_opt_in(tmp_path: Path) -> None:
    env = {
        "HOME": str(tmp_path / "lane_home"),
        "CODEX_HOME": str(tmp_path / "codex_home"),
        CODEX_AUTH_MODE_ENV: "inherit_auth_cache",
    }
    result = _bootstrap_lane_auth(env)

    assert result["authenticated"] is False
    assert result["reason"] == f"{CODEX_AUTH_ALLOW_COPY_ENV}_not_enabled"
    assert result["auth_contents_serialized"] is False


def test_auth_cache_copy_does_not_serialize_auth_contents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_home = tmp_path / "source_home"
    auth = source_home / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text('{"secret":"do-not-serialize"}', encoding="utf-8")

    monkeypatch.setattr("premode.live_token_harness._codex_login_status", lambda _env: {"authenticated": True, "status": "authenticated"})
    env = {
        "HOME": str(tmp_path / "lane_home"),
        "CODEX_HOME": str(tmp_path / "codex_home"),
        CODEX_AUTH_MODE_ENV: "inherit_auth_cache",
        CODEX_AUTH_ALLOW_COPY_ENV: "1",
        CODEX_AUTH_SOURCE_HOME_ENV: str(source_home),
    }
    result = _bootstrap_lane_auth(env)

    aggregate = json.dumps(result, sort_keys=True)
    assert result["authenticated"] is True
    assert "do-not-serialize" not in aggregate
    assert result["auth_contents_serialized"] is False
    assert (tmp_path / "lane_home" / ".codex" / "auth.json").exists()


def test_missing_lane_auth_stops_before_live_execution(tmp_path: Path, repo: Path) -> None:
    fixture = tmp_path / "fixture"
    _git_fixture(fixture)
    matrix = _matrix(tmp_path, fixture, count=1)

    result = run_live_token_harness(
        source_repo=repo,
        artifact_root=tmp_path / "artifacts",
        mode="live_matrix",
        task_matrix=matrix,
        env={LIVE_SPEND_ENV: "1", LIVE_MATRIX_ENV: "1", CODEX_AUTH_MODE_ENV: "none"},
    )

    assert result["live_codex_run"] is False
    assert "codex_auth_unavailable" in result["caveats"]
    assert result["lane_record_count"] == 0


def test_standard_live_command_shape_uses_workspace_write_ephemeral_json(repo: Path) -> None:
    command = _codex_exec_command(repo)

    assert command[:2] == ["codex", "exec"]
    assert "-C" in command or "--cd" in command
    assert "--sandbox" in command
    assert "workspace-write" in command
    assert "--ephemeral" in command
    assert "--json" in command
    assert command[-1] == "-"


def test_pcodex_live_run_requests_json_usage(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        pcodex_bootstrap,
        "resolve_mode_state",
        lambda *_args, **_kwargs: {"configured_mode": "on", "effective_mode": "on"},
    )
    monkeypatch.setattr(pcodex_bootstrap, "update_lockfile_from_resolver", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pcodex_bootstrap, "record_runtime_telemetry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pcodex_bootstrap, "child_env_for_mode_state", lambda *_args, **_kwargs: {})

    def fake_run_codex(_repo: Path, _prompt: str, _profile: str | None, options: object) -> dict[str, object]:
        captured["options"] = options
        return {"returncode": 0, "stdout": "", "stderr": "", "actual_usage": None}

    monkeypatch.setattr(pcodex_bootstrap, "run_codex", fake_run_codex)

    result = pcodex_bootstrap.run_enabled(repo, "Update the disposable file.", "lite")
    options = captured["options"]

    assert result["returncode"] == 0
    assert getattr(options, "json") is True
    assert getattr(options, "lane") == "pcodex"
    assert getattr(options, "packet_strategy") == "literal_symbol"


def test_matrix_aggregate_omits_raw_prompt_and_source_snippets(tmp_path: Path, repo: Path) -> None:
    fixture = tmp_path / "fixture"
    _git_fixture(fixture)
    prompt = "Unique raw prompt text that must not appear in aggregate."
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "safe",
                        "fixture_path": str(fixture),
                        "prompt_text": prompt,
                        "expected_files": ["README.md"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path / "artifacts", mode="dry_run_mock", task_matrix=matrix)
    aggregate = json.dumps(result, sort_keys=True)

    assert prompt not in aggregate
    assert "def message" not in aggregate
    assert result["safety"]["raw_prompt_in_aggregate"] is False
    assert result["safety"]["auth_contents_in_aggregate"] is False


def test_enhanced_matrix_lane_includes_current_pcodex_setup_path(tmp_path: Path, repo: Path) -> None:
    fixture = tmp_path / "fixture"
    _git_fixture(fixture)
    matrix = _matrix(tmp_path, fixture, count=1)

    result = run_live_token_harness(source_repo=repo, artifact_root=tmp_path / "artifacts", mode="dry_run_mock", task_matrix=matrix)
    commands = result["tasks"][0]["enhanced"]["command"]

    assert commands[:4] == [
        "pcodex setup --skip-tune --no-mcp",
        "pcodex on",
        "pcodex first-run --json",
        "pcodex run --dry-run <prompt>",
    ]
    assert result["tasks"][0]["enhanced"]["transform_applied"] is True
