from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
from threading import Barrier, Event
import time

import pytest
from jsonschema import Draft202012Validator

from premode import openclaw_mcp_server as server
from premode import pcodex_mcp
from premode import pcodex_mcp_server as codex_server


TASK = "Inspect OpenClaw repository authority"


def _hung_preflight_runner(
    _root: Path, _task: str, _profile: str | None
) -> dict[str, object]:
    while True:
        time.sleep(60)


def _ready_result(path: str = "src/app.py") -> dict[str, object]:
    return {
        "status": "ready",
        "routing_mode": "narrow",
        "likely_paths": [path],
        "authority_classifications": [
            {"path": path, "classification": "implementation"}
        ],
        "dangerous_mutation_zones": ["PROJECT/tasks.json", "*.uasset"],
        "expected_validation_surfaces": ["tests/test_app.py"],
        "receipt_id": "receipt_01",
    }


def _tool_call(request_id: int, task: str = TASK) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": server.TOOL_NAME,
            "arguments": {"task": task, "profile": "openclaw"},
        },
    }


def _initialize(session: server.McpSession) -> dict[str, object]:
    response = session.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "openclaw-test", "version": "1"},
            },
        }
    )
    assert response is not None
    assert (
        session.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        is None
    )
    return response


def test_catalogs_are_fixed_and_codex_compatible(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = server.McpSession(workspace=server.bind_workspace(workspace.resolve()))
    initialized = _initialize(session)
    assert initialized["result"]["protocolVersion"] == server.PROTOCOL_VERSION  # type: ignore[index]
    assert initialized["result"]["serverInfo"]["name"] == "pcodex-openclaw"  # type: ignore[index]
    listed = session.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed is not None
    assert [tool["name"] for tool in listed["result"]["tools"]] == [server.TOOL_NAME]
    assert listed["result"]["tools"][0]["inputSchema"] == server.TOOL_INPUT_SCHEMA
    assert listed["result"]["tools"][0]["outputSchema"] == server.TOOL_OUTPUT_SCHEMA
    assert [tool["name"] for tool in codex_server.TOOLS] == [pcodex_mcp.TOOL_NAME]
    assert server.TOOL_NAME != pcodex_mcp.TOOL_NAME


def test_transport_schemas_are_versioned_strict_and_bounded() -> None:
    input_schema = server.TOOL_INPUT_SCHEMA
    assert input_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert input_schema["$id"] == "urn:pcodex:schema:openclaw-mcp-preflight-request:v1"
    assert input_schema["required"] == ["task"]
    assert input_schema["additionalProperties"] is False
    assert set(input_schema["properties"]) == {"task", "profile"}
    assert input_schema["properties"]["task"]["maxLength"] == 32_768
    assert server.MAX_TASK_BYTES == 32_768
    Draft202012Validator.check_schema(input_schema)
    input_validator = Draft202012Validator(input_schema)
    input_validator.validate({"task": TASK, "profile": "openclaw"})
    assert list(input_validator.iter_errors({"task": TASK, "root": "/tmp"}))

    output_schema = server.TOOL_OUTPUT_SCHEMA
    assert output_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert output_schema["$id"] == "urn:pcodex:schema:openclaw-mcp-preflight-result:v1"
    assert output_schema["additionalProperties"] is False
    assert output_schema["properties"]["schema_version"] == {
        "const": server.TRANSPORT_SCHEMA_VERSION
    }
    assert set(output_schema["required"]) == set(output_schema["properties"])
    for name in (
        "likely_paths",
        "authority_classifications",
        "dangerous_mutation_zones",
        "expected_validation_surfaces",
    ):
        assert output_schema["properties"][name]["maxItems"] == server.MAX_RESULT_ITEMS
        assert output_schema["properties"][name]["uniqueItems"] is True
    classification = output_schema["properties"]["authority_classifications"]["items"]
    assert classification["additionalProperties"] is False
    assert set(classification["required"]) == {"path", "classification"}
    Draft202012Validator.check_schema(output_schema)


def test_successful_call_matches_declared_structured_transport(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = server.call_tool(
        server.TOOL_NAME,
        {"task": TASK, "profile": "openclaw"},
        workspace=server.bind_workspace(workspace.resolve()),
        preflight_runner=lambda _root, _task, _profile: _ready_result(),
    )
    structured = result["structuredContent"]
    assert structured == {
        "schema_version": server.TRANSPORT_SCHEMA_VERSION,
        **_ready_result(),
    }
    assert result["content"] == [
        {"type": "text", "text": json.dumps(structured, sort_keys=True)}
    ]
    assert set(structured) == set(server.TOOL_OUTPUT_SCHEMA["required"])
    Draft202012Validator(server.TOOL_OUTPUT_SCHEMA).validate(structured)


def test_workspace_binding_is_exact_and_caller_cannot_override_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "bound workspace β"
    wrong = tmp_path / "wrong cwd"
    workspace.mkdir()
    wrong.mkdir()
    observed: list[tuple[Path, str, str | None]] = []

    def runner(root: Path, task: str, profile: str | None) -> dict[str, object]:
        observed.append((root, task, profile))
        return _ready_result()

    monkeypatch.chdir(wrong)
    session = server.McpSession(
        workspace=server.bind_workspace(workspace.resolve()),
        preflight_runner=runner,
        initialized=True,
        ready=True,
    )
    response = session.handle(_tool_call(2))
    assert response is not None and "result" in response
    assert observed == [(workspace.resolve(), TASK, "openclaw")]
    assert str(workspace.resolve()) not in json.dumps(response)
    assert str(wrong.resolve()) not in json.dumps(response)


def test_workspace_binding_rejects_missing_relative_symlink_and_replacement(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert (
        server.workspace_from_environment(
            {server.WORKSPACE_ENV: str(workspace.resolve())}
        ).root
        == workspace.resolve()
    )
    with pytest.raises(server.WorkspaceBindingError, match="required"):
        server.workspace_from_environment({})
    with pytest.raises(server.WorkspaceBindingError, match="absolute"):
        server.bind_workspace("relative")
    with pytest.raises(server.WorkspaceBindingError, match="unavailable"):
        server.bind_workspace(tmp_path / "missing")
    link = tmp_path / "workspace-link"
    link.symlink_to(workspace, target_is_directory=True)
    with pytest.raises(server.WorkspaceBindingError, match="symlinks"):
        server.bind_workspace(link.absolute())

    binding = server.bind_workspace(workspace.resolve())
    moved = tmp_path / "moved"
    workspace.rename(moved)
    workspace.mkdir()
    session = server.McpSession(
        workspace=binding,
        initialized=True,
        ready=True,
    )
    response = session.handle(_tool_call(3))
    assert response is not None
    assert response["error"] == {
        "code": -32602,
        "message": "configured workspace identity changed",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"task": ""},
        {"task": TASK, "profile": "generic"},
        {"task": TASK, "profile": None},
        {"task": "bad\x00task"},
        {"task": "x" * (server.MAX_TASK_CHARACTERS + 1)},
        {"task": "é" * (server.MAX_TASK_BYTES // 2 + 1)},
        {"task": TASK, "project_root": "/tmp/repo"},
        {"task": TASK, "root": "/tmp/repo"},
        {"task": TASK, "cwd": "/tmp/repo"},
        {"task": TASK, "command": "rm"},
        {"task": TASK, "args": ["--write"]},
        {"task": TASK, "env": {"TOKEN": "secret"}},
        {"task": TASK, "environment": {"TOKEN": "secret"}},
        {"task": TASK, "validation": "pytest"},
    ],
)
def test_tool_input_is_strict_and_has_no_authority_or_execution_fields(
    arguments: dict[str, object],
) -> None:
    session = server.McpSession(initialized=True, ready=True)
    request = _tool_call(2)
    request["params"]["arguments"] = arguments  # type: ignore[index]
    response = session.handle(request)
    assert response is not None
    assert response["error"]["code"] == -32602


def test_json_shape_size_nonfinite_and_unknown_methods_are_bounded() -> None:
    invalid = server.handle_line("{bad")
    assert invalid == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "invalid JSON"},
    }
    oversized = server.handle_line(" " * (server.MAX_REQUEST_BYTES + 1))
    assert oversized is not None
    assert oversized["error"] == {
        "code": -32600,
        "message": "request exceeds the supported input boundary",
    }
    nonfinite = server.handle_line(
        '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":NaN}}'
    )
    assert nonfinite is not None and nonfinite["error"]["code"] == -32700
    nested: object = "value"
    for _ in range(server.MAX_JSON_DEPTH + 2):
        nested = [nested]
    too_deep = server.handle_line(json.dumps(nested))
    assert too_deep is not None and too_deep["error"]["code"] == -32700

    session = server.McpSession(initialized=True, ready=True)
    unknown = session.handle({"jsonrpc": "2.0", "id": 4, "method": "unknown/request"})
    assert unknown is not None
    assert unknown["error"] == {"code": -32601, "message": "method not found"}
    wrong_tool = _tool_call(5)
    wrong_tool["params"]["name"] = pcodex_mcp.TOOL_NAME  # type: ignore[index]
    rejected = session.handle(wrong_tool)
    assert rejected is not None and rejected["error"]["code"] == -32000


def test_concurrent_calls_preserve_ids_and_exact_tasks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    barrier = Barrier(2)
    observed: list[str] = []

    def runner(_root: Path, task: str, _profile: str | None) -> dict[str, object]:
        observed.append(task)
        barrier.wait(timeout=5)
        return _ready_result()

    session = server.McpSession(
        workspace=server.bind_workspace(workspace.resolve()),
        preflight_runner=runner,
        initialized=True,
        ready=True,
    )
    tasks = {51: "Inspect alpha.py", 52: "Inspect beta.py"}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            request_id: executor.submit(session.handle, _tool_call(request_id, task))
            for request_id, task in tasks.items()
        }
    responses = {
        request_id: future.result(timeout=5) for request_id, future in futures.items()
    }
    assert set(observed) == set(tasks.values())
    for request_id in tasks:
        assert responses[request_id] is not None
        assert responses[request_id]["id"] == request_id  # type: ignore[index]


def test_active_cancellation_returns_only_fixed_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started = Event()
    release = Event()

    def runner(_root: Path, _task: str, _profile: str | None) -> dict[str, object]:
        started.set()
        assert release.wait(timeout=5)
        raise RuntimeError("PCODEX_SECRET_CANARY")

    session = server.McpSession(
        workspace=server.bind_workspace(workspace.resolve()),
        preflight_runner=runner,
        initialized=True,
        ready=True,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(session.handle, _tool_call(61))
        assert started.wait(timeout=5)
        assert (
            session.handle(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": 61, "reason": "test"},
                }
            )
            is None
        )
        release.set()
        response = future.result(timeout=5)
    assert response is not None
    assert response["error"] == {"code": -32800, "message": "request cancelled"}
    assert "SECRET" not in json.dumps(response)


def test_result_and_backend_errors_are_sanitized(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    secret = "PCODEX_SECRET_CANARY"

    def unsafe(_root: Path, _task: str, _profile: str | None) -> dict[str, object]:
        return {
            **_ready_result(),
            "likely_paths": [
                "src/app.py",
                "../outside.py",
                "/private/secret.py",
                "C:\\private\\secret.py",
                "escape/secret.py",
            ],
            "receipt_id": f"bad receipt {secret}",
            "unexpected": f"/private/{secret}",
        }

    binding = server.bind_workspace(workspace.resolve())
    safe = server.call_tool(
        server.TOOL_NAME,
        {"task": TASK},
        workspace=binding,
        preflight_runner=unsafe,
    )
    encoded = json.dumps(safe)
    assert secret not in encoded
    assert "/private/" not in encoded
    assert safe["structuredContent"]["likely_paths"] == ["src/app.py"]
    assert safe["structuredContent"]["receipt_id"] is None

    def failing(_root: Path, _task: str, _profile: str | None) -> dict[str, object]:
        raise server.ToolRequestError(f"failure /private/{secret}")

    failed_session = server.McpSession(
        workspace=binding,
        preflight_runner=failing,
        initialized=True,
        ready=True,
    )
    failure = failed_session.handle(_tool_call(7))
    assert failure is not None
    assert failure["error"] == {"code": -32603, "message": "internal tool error"}
    assert secret not in json.dumps(failure)


def test_default_backend_is_fail_safe_and_no_task_is_echoed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = server.McpSession(
        workspace=server.bind_workspace(workspace.resolve()),
        initialized=True,
        ready=True,
    )
    response = session.handle(_tool_call(8, "SENSITIVE EXACT TASK"))
    assert response is not None
    assert response["result"]["structuredContent"]["status"] == "backend_unavailable"
    assert "SENSITIVE EXACT TASK" not in json.dumps(response)


def test_spawn_worker_profile_is_picklable_and_returns_bounded_result(
    tmp_path: Path,
) -> None:
    if "spawn" not in server.multiprocessing.get_all_start_methods():
        pytest.skip("spawn worker isolation unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    binding = server.bind_workspace(workspace.resolve())
    session = server.McpSession(
        workspace=binding,
        initialized=True,
        ready=True,
    )
    responses: list[dict[str, object]] = []
    completed = Event()

    def write_response(response: dict[str, object] | None) -> None:
        if response is not None:
            responses.append(response)
            completed.set()

    manager = server.ProcessWorkerManager(
        session=session,
        workspace=binding,
        write_response=write_response,
    )
    session.cancel_callback = manager.cancel
    work = session.dispatch(_tool_call(9), defer_tool=True)
    assert isinstance(work, server.ToolWork)
    manager.start(work)
    assert completed.wait(timeout=8)
    manager.close()
    assert responses[0]["result"]["structuredContent"]["status"] == (  # type: ignore[index]
        "backend_unavailable"
    )


def test_shutdown_and_spawn_worker_cancellation_are_bounded(tmp_path: Path) -> None:
    if "spawn" not in server.multiprocessing.get_all_start_methods():
        pytest.skip("spawn worker isolation unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
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
            "params": {"requestId": 10},
        }
    )
    messages.append({"jsonrpc": "2.0", "id": 20, "method": "shutdown"})
    stdin = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
    stdout = io.StringIO()
    started = time.monotonic()
    assert (
        server.serve(
            workspace=server.bind_workspace(workspace.resolve()),
            stdin=stdin,
            stdout=stdout,
            preflight_runner=_hung_preflight_runner,
        )
        == 0
    )
    assert time.monotonic() - started < 8
    responses = {
        response["id"]: response
        for response in map(json.loads, stdout.getvalue().splitlines())
    }
    assert responses[14]["error"] == {"code": -32001, "message": "server busy"}
    for request_id in range(10, 14):
        assert responses[request_id]["error"] == {
            "code": -32800,
            "message": "request cancelled",
        }
    assert responses[20] == {"jsonrpc": "2.0", "id": 20, "result": {}}


def test_serve_requires_bound_workspace() -> None:
    assert server.serve(stdin=io.StringIO(), stdout=io.StringIO()) == 2
