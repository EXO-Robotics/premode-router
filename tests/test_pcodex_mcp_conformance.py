from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
from threading import Barrier, Event
import time

import pytest

from premode import __version__
from premode import pcodex_bootstrap
from premode import pcodex_mcp
from premode import pcodex_mcp_server as server


def _hung_compile_runner(*_args: object, **_kwargs: object) -> dict[str, object]:
    while True:
        time.sleep(60)


TASK = "Inspect src/app.py"


def _initialize(session: server.McpSession) -> None:
    response = session.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": server.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pcodex-test", "version": "1"},
            },
        }
    )
    assert response is not None
    assert response["result"]["protocolVersion"] == server.PROTOCOL_VERSION
    assert response["result"]["serverInfo"]["version"] == __version__
    assert session.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def _tool_call(request_id: int, task: str = TASK) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": pcodex_mcp.TOOL_NAME,
            "arguments": {"subagent_prompt": task, "dry_run": True},
        },
    }


def test_workspace_binding_is_absolute_stable_and_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "bound workspace β"
    wrong_cwd = tmp_path / "wrong cwd"
    workspace.mkdir()
    wrong_cwd.mkdir()
    (workspace / ".git").mkdir()
    (wrong_cwd / ".git").mkdir()
    (wrong_cwd / ".premode").mkdir()
    (wrong_cwd / ".premode/pcodex_state.json").write_text(
        json.dumps(
            {
                "schema_version": "pcodex.state.v1",
                "enabled": False,
                "mode": "off",
                "algorithm": "literal_symbol",
                "tuning_profile": None,
            }
        ),
        encoding="utf-8",
    )
    binding = server.bind_workspace(workspace.resolve())
    monkeypatch.chdir(wrong_cwd)
    session = server.McpSession(workspace=binding)
    _initialize(session)

    response = session.handle(_tool_call(2))

    assert response is not None
    assert response["result"]["structuredContent"]["enabled"] is True
    assert binding.assert_current() == workspace.resolve()


def test_workspace_binding_fails_closed_for_missing_relative_and_symlink(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(server.WorkspaceBindingError, match="required"):
        server.workspace_from_environment({})
    with pytest.raises(server.WorkspaceBindingError, match="absolute"):
        server.bind_workspace("relative")
    with pytest.raises(server.WorkspaceBindingError, match="unavailable"):
        server.bind_workspace(tmp_path / "missing")
    link = tmp_path / "workspace-link"
    try:
        link.symlink_to(workspace, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(server.WorkspaceBindingError, match="symlinks"):
        server.bind_workspace(link.absolute())


def test_cli_server_requires_and_passes_the_registered_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.delenv(server.WORKSPACE_ENV, raising=False)
    assert pcodex_bootstrap.main(["mcp-server"]) == 2

    observed: list[server.WorkspaceBinding] = []

    def fake_serve(*, workspace: server.WorkspaceBinding) -> int:
        observed.append(workspace)
        return 17

    monkeypatch.setenv(server.WORKSPACE_ENV, str(workspace.resolve()))
    monkeypatch.setattr(server, "serve", fake_serve)
    assert pcodex_bootstrap.main(["mcp-server"]) == 17
    assert observed[0].root == workspace.resolve()


def test_protocol_requires_initialize_and_initialized_notification(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = server.McpSession(workspace=server.bind_workspace(workspace.resolve()))
    before = session.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert before is not None and before["error"]["code"] == -32002

    init = session.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "initialize",
            "params": {
                "protocolVersion": "unsupported-version",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    assert init is not None and init["result"]["protocolVersion"] == server.PROTOCOL_VERSION
    waiting = session.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert waiting is not None and waiting["error"]["code"] == -32002
    assert session.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = session.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
    assert listed is not None
    assert listed["result"]["tools"][0]["inputSchema"] == pcodex_mcp.TOOL_INPUT_SCHEMA


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"jsonrpc": "1.0", "id": 1, "method": "tools/list"}, -32600),
        ({"jsonrpc": "2.0", "id": True, "method": "tools/list"}, -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": 4}, -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}, -32602),
    ],
)
def test_request_envelope_is_strict(payload: dict[str, object], code: int) -> None:
    session = server.McpSession(initialized=True, ready=True)
    response = session.handle(payload)
    assert response is not None and response["error"]["code"] == code


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"subagent_prompt": ""},
        {"subagent_prompt": TASK, "unexpected": True},
        {"subagent_prompt": TASK, "dry_run": "true"},
        {"subagent_prompt": TASK, "parent_prompt": 1},
        {"subagent_prompt": TASK, "spawn_metadata": []},
        {"subagent_prompt": "bad\x00task"},
        {"subagent_prompt": "x" * (pcodex_mcp.MAX_TASK_CHARACTERS + 1)},
        {"subagent_prompt": "é" * (pcodex_mcp.MAX_TASK_BYTES // 2 + 1)},
    ],
)
def test_tool_arguments_enforce_the_published_schema(arguments: dict[str, object]) -> None:
    session = server.McpSession(initialized=True, ready=True)
    request = _tool_call(1)
    request["params"]["arguments"] = arguments  # type: ignore[index]
    response = session.handle(request)
    assert response is not None and response["error"]["code"] == -32602


def test_json_and_request_size_errors_are_bounded() -> None:
    invalid = server.handle_line("{bad")
    assert invalid == {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "invalid JSON"}}
    oversized = server.handle_line(" " * (server.MAX_REQUEST_BYTES + 1))
    assert oversized is not None
    assert oversized["error"] == {"code": -32600, "message": "request exceeds the supported input boundary"}


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_numbers_are_rejected(constant: str) -> None:
    response = server.handle_line(
        '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"value":' + constant + "}}"
    )
    assert response is not None
    assert response["error"] == {"code": -32700, "message": "invalid JSON"}


def test_excessive_json_nesting_is_rejected() -> None:
    nested: object = "value"
    for _ in range(server.MAX_JSON_DEPTH + 2):
        nested = [nested]
    response = server.handle_line(json.dumps(nested))
    assert response is not None
    assert response["error"] == {"code": -32700, "message": "invalid JSON"}


@pytest.mark.parametrize(
    "method,params",
    [
        ("ping", {"extra": True}),
        ("tools/list", {"cursor": "unexpected"}),
        ("shutdown", {"extra": True}),
    ],
)
def test_methods_reject_extra_params(method: str, params: dict[str, object]) -> None:
    session = server.McpSession(initialized=True, ready=True)
    response = session.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert response is not None
    assert response["error"]["code"] == -32602


def test_initialize_rejects_extra_params() -> None:
    session = server.McpSession()
    response = session.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": server.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
                "extra": True,
            },
        }
    )
    assert response is not None and response["error"]["code"] == -32602


def test_precancellation_is_bounded_and_persists_until_admission() -> None:
    session = server.McpSession(initialized=True, ready=True)
    for request_id in range(1, server.MAX_CONCURRENT_REQUESTS + 1):
        assert session._cancel(request_id) is True
    assert session._cancel(99) is False
    assert session._begin(99) == "busy"
    assert session._begin(1) == "cancelled"
    assert session._begin(99) == "accepted"
    assert session._finish(99) is False


@pytest.mark.parametrize("request_id", [None, True, {}, [], 1.5])
def test_cancellation_rejects_invalid_request_ids(request_id: object) -> None:
    session = server.McpSession(initialized=True, ready=True)
    assert session.handle(
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": request_id},
        }
    ) is None
    assert not session._cancelled


def test_unknown_notifications_are_ignored_and_unknown_requests_are_bounded() -> None:
    session = server.McpSession(initialized=True, ready=True)
    assert session.handle({"jsonrpc": "2.0", "method": "unknown/notification"}) is None
    response = session.handle({"jsonrpc": "2.0", "id": 1, "method": "unknown/request"})
    assert response is not None and response["error"] == {"code": -32601, "message": "method not found"}


@pytest.mark.parametrize("method", ["notifications/initialized", "notifications/cancelled"])
def test_notification_methods_with_request_ids_are_rejected(method: str) -> None:
    session = server.McpSession(initialized=True, ready=True)
    response = session.handle({"jsonrpc": "2.0", "id": 7, "method": method})
    assert response is not None
    assert response["error"] == {"code": -32600, "message": "invalid notification request"}


def test_concurrent_requests_are_isolated_and_cancellation_is_bounded(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started = Event()
    release = Event()

    def runner(*_args: object, **_kwargs: object) -> dict[str, object]:
        started.set()
        assert release.wait(timeout=5)
        raise RuntimeError("sensitive worker failure")

    session = server.McpSession(
        workspace=server.bind_workspace(workspace.resolve()),
        compile_runner=runner,
        initialized=True,
        ready=True,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(session.handle, _tool_call(41))
        assert started.wait(timeout=5)
        assert session.handle(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 41, "reason": "test"},
            }
        ) is None
        release.set()
        response = future.result(timeout=5)
    assert response is not None
    assert response["error"] == {"code": -32800, "message": "request cancelled"}
    assert "sensitive" not in json.dumps(response)


def test_two_concurrent_requests_preserve_ids_and_exact_tasks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    barrier = Barrier(2)

    def runner(_root: Path, prompt: str, _profile: str | None, **_kwargs: object) -> dict[str, object]:
        barrier.wait(timeout=5)
        return {
            "route": "plugin_alias",
            "packet": prompt,
            "routing_decision": {
                "schema_version": "routing-decision.v1",
                "mode": "abstain",
                "confidence": "low",
                "primary_paths": [],
                "verification_paths": [],
                "support_paths": [],
                "ambiguity_indicators": ["fixture"],
                "decision_reasons": ["fixture"],
                "candidate_provenance": [],
            },
        }

    session = server.McpSession(
        workspace=server.bind_workspace(workspace.resolve()),
        compile_runner=runner,
        initialized=True,
        ready=True,
    )
    tasks = {51: "Inspect alpha.py", 52: "Inspect beta.py"}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            request_id: executor.submit(session.handle, _tool_call(request_id, task))
            for request_id, task in tasks.items()
        }
    responses = {request_id: future.result(timeout=5) for request_id, future in futures.items()}
    for request_id, task in tasks.items():
        response = responses[request_id]
        assert response is not None and response["id"] == request_id
        assert response["result"]["structuredContent"]["transformed_prompt"] == task


@pytest.mark.parametrize("candidate", ["../outside.py", "/outside.py", "escape/outside.py"])
def test_tool_rejects_traversal_absolute_and_symlink_escape_candidates(
    tmp_path: Path, candidate: str,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "outside.py").write_text("SECRET_OUTSIDE = True\n", encoding="utf-8")
    try:
        (workspace / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        if candidate.startswith("escape/"):
            pytest.skip("symlink creation unavailable")

    def runner(_root: Path, prompt: str, _profile: str | None, **_kwargs: object) -> dict[str, object]:
        return {
            "route": "plugin_alias",
            "packet": prompt,
            "routing_decision": {
                "schema_version": "routing-decision.v1",
                "mode": "narrow",
                "confidence": "high",
                "primary_paths": [candidate],
                "verification_paths": [],
                "support_paths": [],
                "ambiguity_indicators": [],
                "decision_reasons": ["fixture"],
                "candidate_provenance": [
                    {
                        "schema_version": "candidate-evidence.v1",
                        "path": candidate,
                        "role": "primary",
                        "rank": 0,
                        "score": 10,
                        "confidence": "high",
                        "matched_signals": ["fixture"],
                        "provenance": ["fixture"],
                    }
                ],
            },
        }

    session = server.McpSession(
        workspace=server.bind_workspace(workspace.resolve()),
        compile_runner=runner,
        initialized=True,
        ready=True,
    )
    response = session.handle(_tool_call(61, "Inspect repository authority"))
    assert response is not None
    structured = response["result"]["structuredContent"]
    assert structured["transform_applied"] is False
    assert structured["error"] == "invalid_routing_decision"
    encoded = json.dumps(response)
    assert "SECRET_OUTSIDE" not in encoded
    assert str(outside.resolve()) not in encoded


def test_shutdown_cancels_new_work_and_serve_uses_bound_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    binding = server.bind_workspace(workspace.resolve())
    session = server.McpSession(workspace=binding)
    _initialize(session)
    shutdown = session.handle({"jsonrpc": "2.0", "id": 9, "method": "shutdown"})
    assert shutdown == {"jsonrpc": "2.0", "id": 9, "result": {}}
    rejected = session.handle({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
    assert rejected is not None and rejected["error"]["code"] == -32002

    stdin = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": server.PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "shutdown"})
        + "\n"
    )
    stdout = io.StringIO()
    assert server.serve(workspace=binding, stdin=stdin, stdout=stdout) == 0
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3]


def test_spawn_workers_cancel_hung_work_and_shutdown_without_queueing(tmp_path: Path) -> None:
    if "spawn" not in server.multiprocessing.get_all_start_methods():
        pytest.skip("spawn worker isolation unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    messages: list[dict[str, object]] = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": server.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    messages.extend(_tool_call(request_id) for request_id in range(10, 15))
    messages.append(
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 10, "reason": "test"},
        }
    )
    messages.append({"jsonrpc": "2.0", "id": 20, "method": "shutdown"})
    stdin = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
    stdout = io.StringIO()

    started = time.monotonic()
    assert server.serve(
        workspace=server.bind_workspace(workspace.resolve()),
        stdin=stdin,
        stdout=stdout,
        compile_runner=_hung_compile_runner,
    ) == 0
    assert time.monotonic() - started < 8
    responses = {response["id"]: response for response in map(json.loads, stdout.getvalue().splitlines())}
    assert responses[14]["error"] == {"code": -32001, "message": "server busy"}
    for request_id in range(10, 14):
        assert responses[request_id]["error"] == {"code": -32800, "message": "request cancelled"}
    assert responses[20] == {"jsonrpc": "2.0", "id": 20, "result": {}}


def test_precancelled_serve_request_never_starts_a_worker(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": server.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}},
        _tool_call(9),
        {"jsonrpc": "2.0", "id": 10, "method": "shutdown"},
    ]
    stdout = io.StringIO()
    assert server.serve(
        workspace=server.bind_workspace(workspace.resolve()),
        stdin=io.StringIO("".join(json.dumps(message) + "\n" for message in messages)),
        stdout=stdout,
    ) == 0
    responses = {response["id"]: response for response in map(json.loads, stdout.getvalue().splitlines())}
    assert responses[9]["error"] == {"code": -32800, "message": "request cancelled"}


def test_tool_result_redacts_internal_paths_errors_and_metadata() -> None:
    secret = "PCODEX_SECRET_CANARY_DO_NOT_LEAK"

    class Result:
        def as_dict(self) -> dict[str, object]:
            return {
                "transformed_prompt": TASK,
                "enabled": True,
                "algorithm": "untrusted-candidate-label",
                "mode": "tuned",
                "effective_mode": "tuned",
                "transform_applied": False,
                "tuning_profile": f"/private/{secret}/profile.json",
                "used_fallback": True,
                "error": f"failure at /private/{secret}",
                "metadata": {
                    "input_prompt_preserved": True,
                    "selected_paths": ["src/app.py", f"/private/{secret}/outside.py", "../outside.py"],
                    "status": secret,
                    "error_status": secret,
                    "routing_mode": "fallback",
                },
            }

    payload = server._tool_result_payload(Result())
    encoded = json.dumps(payload)
    assert secret not in encoded
    assert "/private/" not in encoded
    assert payload["structuredContent"]["transformed_prompt"] == TASK
    assert payload["structuredContent"]["tuning_profile"] is None
    assert payload["structuredContent"]["error"] == "configuration_invalid"
    assert payload["structuredContent"]["algorithm"] == pcodex_bootstrap.PCODEX_PACKET_STRATEGY
    assert payload["structuredContent"]["metadata"]["routing_mode"] == "fallback"
    assert payload["structuredContent"]["metadata"]["selected_paths"] == ["src/app.py"]


def test_legacy_setup_registration_binds_exact_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "workspace with spaces β"
    repo.mkdir()
    observed: list[tuple[list[str], Path | None]] = []
    monkeypatch.setattr(pcodex_bootstrap, "_command_available", lambda _name: True)
    monkeypatch.setattr(pcodex_bootstrap, "_command_path", lambda _name: "/installed/bin/pcodex")

    def fake_run(args: list[str], *, codex_home: Path | None = None) -> dict[str, object]:
        observed.append((args, codex_home))
        return {"returncode": 0, "args": args, "stdout": "", "stderr": ""}

    monkeypatch.setattr(pcodex_bootstrap, "_run_codex_mcp_command", fake_run)
    result = pcodex_bootstrap.register_mcp_for_setup(repo)
    assert result["registered"] is True
    assert observed[0][0] == [
        "add",
        "pcodex",
        "--env",
        f"PCODEX_WORKSPACE={repo.resolve()}",
        "--",
        "/installed/bin/pcodex",
        "mcp-server",
    ]


def test_actual_tool_call_is_literal_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    temp = tmp_path / "temp"
    for path in (workspace, home, temp):
        path.mkdir()
    (workspace / ".git").mkdir()
    (workspace / "src").mkdir()
    (workspace / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TMPDIR", str(temp))

    def snapshot(root: Path) -> dict[str, tuple[int, int, int, str]]:
        result: dict[str, tuple[int, int, int, str]] = {}
        for path in sorted(root.rglob("*")):
            info = path.lstat()
            digest = ""
            if path.is_file() and not path.is_symlink():
                import hashlib

                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[path.relative_to(root).as_posix()] = (info.st_mode, info.st_size, info.st_mtime_ns, digest)
        return result

    before = {"workspace": snapshot(workspace), "home": snapshot(home), "temp": snapshot(temp)}
    session = server.McpSession(workspace=server.bind_workspace(workspace.resolve()))
    _initialize(session)
    response = session.handle(_tool_call(2))
    after = {"workspace": snapshot(workspace), "home": snapshot(home), "temp": snapshot(temp)}

    assert response is not None and "result" in response
    assert after == before
    encoded = json.dumps(response)
    assert str(workspace.resolve()) not in encoded
    assert str(home.resolve()) not in encoded
    assert str(temp.resolve()) not in encoded
