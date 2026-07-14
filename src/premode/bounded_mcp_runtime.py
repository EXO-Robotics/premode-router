from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import multiprocessing
from pathlib import Path
import stat
import sys
from threading import Lock, Thread, current_thread
from typing import Any, Callable, TextIO

from . import __version__


PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({PROTOCOL_VERSION})
WORKSPACE_ENV = "PCODEX_WORKSPACE"
MAX_REQUEST_BYTES = 1_048_576
MAX_CONCURRENT_REQUESTS = 4
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 4096
WORKER_STOP_TIMEOUT_SECONDS = 1.0


class ToolRequestError(ValueError):
    """A bounded client-input error whose message is safe for JSON-RPC."""

    def __init__(self, message: str, *, code: int = -32602) -> None:
        super().__init__(message)
        self.code = code


class WorkspaceBindingError(ValueError):
    """Raised when the registered MCP workspace cannot be bound safely."""


@dataclass(frozen=True)
class WorkspaceBinding:
    root: Path
    device: int
    inode: int

    def assert_current(self) -> Path:
        try:
            current = self.root.resolve(strict=True)
            info = self.root.stat(follow_symlinks=False)
        except OSError as exc:
            raise WorkspaceBindingError("configured workspace is unavailable") from exc
        if current != self.root or not stat.S_ISDIR(info.st_mode):
            raise WorkspaceBindingError("configured workspace identity changed")
        if (info.st_dev, info.st_ino) != (self.device, self.inode):
            raise WorkspaceBindingError("configured workspace identity changed")
        return self.root


def bind_workspace(value: str | Path | None) -> WorkspaceBinding:
    if value is None or not str(value).strip():
        raise WorkspaceBindingError("configured workspace is required")
    lexical = Path(str(value))
    if not lexical.is_absolute() or ".." in lexical.parts:
        raise WorkspaceBindingError(
            "configured workspace must be an absolute normalized path"
        )
    try:
        resolved = lexical.resolve(strict=True)
        info = lexical.stat(follow_symlinks=False)
    except OSError as exc:
        raise WorkspaceBindingError("configured workspace is unavailable") from exc
    if resolved != lexical or not stat.S_ISDIR(info.st_mode):
        raise WorkspaceBindingError("configured workspace must not use symlinks")
    return WorkspaceBinding(resolved, info.st_dev, info.st_ino)


def workspace_from_environment(environ: Mapping[str, str]) -> WorkspaceBinding:
    return bind_workspace(environ.get(WORKSPACE_ENV))


def _response(id_value: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    out = {"jsonrpc": "2.0", "id": id_value}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def _error(id_value: Any, code: int, message: str) -> dict[str, Any]:
    return _response(id_value, error={"code": code, "message": message})


def _valid_request_id(value: Any) -> bool:
    return value is None or (
        isinstance(value, (str, int)) and not isinstance(value, bool)
    )


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _contains_forbidden_control(value: str) -> bool:
    return any(
        (ord(character) < 32 and character not in "\n\r\t") or ord(character) == 127
        for character in value
    )


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _validate_json_shape(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ValueError("JSON structure exceeds the supported boundary")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, float) and not (
            -float("inf") < current < float("inf")
        ):
            raise ValueError("non-finite JSON number is not allowed")


def _loads_json(line: str) -> Any:
    value = json.loads(line, parse_constant=_reject_nonfinite)
    _validate_json_shape(value)
    return value


def _safe_relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or _contains_forbidden_control(value):
        return None
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


@dataclass(frozen=True)
class ToolBackend:
    """Immutable tool profile injected into the bounded MCP transport."""

    server_name: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    validate_arguments: Callable[..., Any]
    execute: Callable[..., Any]
    worker_name: str
    output_schema: dict[str, Any] | None = None
    allow_in_process_cwd_fallback: bool = False

    def tools(self) -> list[dict[str, Any]]:
        tool: dict[str, Any] = {
            "name": self.tool_name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.output_schema is not None:
            tool["outputSchema"] = self.output_schema
        return [tool]


@dataclass(frozen=True)
class ToolWork:
    request_id: Any
    name: str
    arguments: dict[str, Any]


@dataclass
class McpSession:
    backend: ToolBackend
    workspace: WorkspaceBinding | None = None
    backend_context: Any = None
    initialized: bool = False
    ready: bool = False
    shutting_down: bool = False
    cancel_callback: Callable[[Any], None] | None = None
    _cancelled: set[str] = field(default_factory=set)
    _in_flight: set[str] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock)

    @staticmethod
    def _request_key(request_id: Any) -> str:
        return json.dumps(request_id, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _exact_params(
        params: dict[str, Any],
        allowed: set[str],
        required: set[str] | None = None,
    ) -> bool:
        required = set() if required is None else required
        return required <= set(params) <= allowed

    def _begin(self, request_id: Any) -> str:
        key = self._request_key(request_id)
        with self._lock:
            if key in self._cancelled:
                self._cancelled.discard(key)
                return "cancelled"
            if self.shutting_down:
                return "cancelled"
            if (
                key in self._in_flight
                or len(self._in_flight | self._cancelled) >= MAX_CONCURRENT_REQUESTS
            ):
                return "busy"
            self._in_flight.add(key)
        return "accepted"

    def _finish(self, request_id: Any) -> bool:
        key = self._request_key(request_id)
        with self._lock:
            cancelled = key in self._cancelled
            self._cancelled.discard(key)
            self._in_flight.discard(key)
        return cancelled

    def _cancel(self, request_id: Any) -> bool:
        if request_id is None or not _valid_request_id(request_id):
            return False
        key = self._request_key(request_id)
        accepted = False
        with self._lock:
            if key in self._in_flight or key in self._cancelled:
                self._cancelled.add(key)
                accepted = True
            elif len(self._in_flight | self._cancelled) < MAX_CONCURRENT_REQUESTS:
                self._cancelled.add(key)
                accepted = True
        if accepted and self.cancel_callback is not None:
            self.cancel_callback(request_id)
        return accepted

    def is_cancelled(self, request_id: Any) -> bool:
        key = self._request_key(request_id)
        with self._lock:
            return key in self._cancelled

    def dispatch(
        self,
        request: dict[str, Any],
        *,
        cwd: Path | None = None,
        defer_tool: bool = False,
    ) -> dict[str, Any] | ToolWork | None:
        request_id = request.get("id")
        is_notification = "id" not in request
        if request.get("jsonrpc") != "2.0" or not isinstance(
            request.get("method"), str
        ):
            return (
                None
                if is_notification
                else _error(request_id, -32600, "invalid request")
            )
        if not is_notification and not _valid_request_id(request_id):
            return _error(None, -32600, "invalid request")
        method = request["method"]
        params = request.get("params", {})
        if not isinstance(params, dict):
            return (
                None
                if is_notification
                else _error(request_id, -32602, "invalid params")
            )

        if method == "initialize":
            if is_notification or self.initialized or self.shutting_down:
                return (
                    None
                    if is_notification
                    else _error(request_id, -32600, "invalid initialize request")
                )
            if not self._exact_params(
                params,
                {"protocolVersion", "capabilities", "clientInfo"},
                {"protocolVersion", "capabilities", "clientInfo"},
            ):
                return _error(request_id, -32602, "invalid initialize params")
            protocol = params["protocolVersion"]
            capabilities = params["capabilities"]
            client_info = params["clientInfo"]
            if (
                not isinstance(protocol, str)
                or not isinstance(capabilities, dict)
                or not isinstance(client_info, dict)
            ):
                return _error(request_id, -32602, "invalid initialize params")
            self.initialized = True
            negotiated = (
                protocol
                if protocol in SUPPORTED_PROTOCOL_VERSIONS
                else PROTOCOL_VERSION
            )
            return _response(
                request_id,
                result={
                    "protocolVersion": negotiated,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": self.backend.server_name,
                        "version": __version__,
                    },
                },
            )
        if method == "notifications/initialized":
            if not is_notification:
                return _error(request_id, -32600, "invalid notification request")
            if params:
                return None
            if self.initialized and not self.shutting_down:
                self.ready = True
            return None
        if method == "notifications/cancelled":
            if not is_notification:
                return _error(request_id, -32600, "invalid notification request")
            if not self._exact_params(params, {"requestId", "reason"}, {"requestId"}):
                return None
            cancel_id = params["requestId"]
            reason = params.get("reason")
            if cancel_id is None or not _valid_request_id(cancel_id):
                return None
            if reason is not None and not isinstance(reason, str):
                return None
            self._cancel(cancel_id)
            return None
        if method == "shutdown":
            if is_notification or not self.initialized:
                return (
                    None
                    if is_notification
                    else _error(request_id, -32600, "invalid shutdown request")
                )
            if params:
                return _error(request_id, -32602, "invalid shutdown params")
            with self._lock:
                self.shutting_down = True
                active = tuple(self._in_flight)
                self._cancelled.update(active)
            if self.cancel_callback is not None:
                for key in active:
                    self.cancel_callback(json.loads(key))
            return _response(request_id, result={})
        if is_notification:
            return None
        if not self.ready or self.shutting_down:
            return _error(request_id, -32002, "server is not ready")
        if method == "ping":
            if params:
                return _error(request_id, -32602, "invalid ping params")
            return _response(request_id, result={})
        if method == "tools/list":
            if params:
                return _error(request_id, -32602, "invalid tools/list params")
            return _response(request_id, result={"tools": self.backend.tools()})
        if method != "tools/call":
            return _error(request_id, -32601, "method not found")
        try:
            if set(params) != {"name", "arguments"} or not isinstance(
                params.get("name"), str
            ):
                raise ToolRequestError("invalid tool call params")
            if params["name"] != self.backend.tool_name:
                raise ToolRequestError("unsupported tool", code=-32000)
            arguments = self.backend.validate_arguments(params["arguments"])
            execution_workspace = self.workspace
            if (
                execution_workspace is None
                and self.backend.allow_in_process_cwd_fallback
            ):
                execution_workspace = bind_workspace(
                    (cwd or Path.cwd()).resolve(strict=True)
                )
            if execution_workspace is None:
                raise WorkspaceBindingError("configured workspace is required")
            execution_workspace.assert_current()
            admission = self._begin(request_id)
            if admission == "cancelled":
                return _error(request_id, -32800, "request cancelled")
            if admission == "busy":
                return _error(request_id, -32001, "server busy")
            work = ToolWork(
                request_id=request_id, name=params["name"], arguments=arguments
            )
            if defer_tool:
                return work
            result = self.backend.execute(
                work.name,
                work.arguments,
                execution_workspace,
                self.backend_context,
            )
        except (ToolRequestError, WorkspaceBindingError) as exc:
            cancelled = self._finish(request_id)
            code = exc.code if isinstance(exc, ToolRequestError) else -32602
            return (
                _error(request_id, -32800, "request cancelled")
                if cancelled
                else _error(request_id, code, str(exc))
            )
        except Exception:
            cancelled = self._finish(request_id)
            return (
                _error(request_id, -32800, "request cancelled")
                if cancelled
                else _error(request_id, -32603, "internal tool error")
            )
        cancelled = self._finish(request_id)
        return (
            _error(request_id, -32800, "request cancelled")
            if cancelled
            else _response(request_id, result=result)
        )

    def handle(
        self, request: dict[str, Any], *, cwd: Path | None = None
    ) -> dict[str, Any] | None:
        dispatched = self.dispatch(request, cwd=cwd)
        if isinstance(dispatched, ToolWork):
            raise RuntimeError("unexpected deferred MCP work")
        return dispatched


def _worker_main(
    connection: Any,
    work: ToolWork,
    workspace: WorkspaceBinding,
    backend: ToolBackend,
    backend_context: Any,
) -> None:
    try:
        workspace.assert_current()
        result = backend.execute(
            work.name,
            work.arguments,
            workspace,
            backend_context,
        )
        workspace.assert_current()
        connection.send({"result": result})
    except ToolRequestError as exc:
        connection.send({"error": {"code": exc.code, "message": str(exc)}})
    except WorkspaceBindingError:
        connection.send(
            {
                "error": {
                    "code": -32602,
                    "message": "configured workspace identity changed",
                }
            }
        )
    except BaseException:
        connection.send({"error": {"code": -32603, "message": "internal tool error"}})
    finally:
        connection.close()


@dataclass
class _WorkerRecord:
    work: ToolWork
    process: Any
    connection: Any
    monitor: Thread | None = None


class ProcessWorkerManager:
    def __init__(
        self,
        *,
        session: McpSession,
        workspace: WorkspaceBinding,
        write_response: Callable[[dict[str, Any] | None], None],
        backend: ToolBackend,
        backend_context: Any = None,
    ) -> None:
        if "spawn" not in multiprocessing.get_all_start_methods():
            raise RuntimeError("spawn worker isolation is unavailable")
        # Never fork after the first monitor thread has started. On macOS and
        # Linux a later fork can inherit library locks held by another thread
        # and deadlock an otherwise read-only request. Spawn gives each bounded
        # worker a clean interpreter and keeps cancellation process-addressable.
        self._context = multiprocessing.get_context("spawn")
        self._session = session
        self._workspace = workspace
        self._write_response = write_response
        self._backend = backend
        self._backend_context = backend_context
        self._records: dict[str, _WorkerRecord] = {}
        self._monitors: set[Thread] = set()
        self._lock = Lock()

    def start(self, work: ToolWork) -> None:
        if self._session.is_cancelled(work.request_id):
            self._session._finish(work.request_id)
            self._write_response(_error(work.request_id, -32800, "request cancelled"))
            return
        parent_connection, child_connection = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=_worker_main,
            args=(
                child_connection,
                work,
                self._workspace,
                self._backend,
                self._backend_context,
            ),
            name=self._backend.worker_name,
        )
        record = _WorkerRecord(work=work, process=process, connection=parent_connection)
        key = self._session._request_key(work.request_id)
        try:
            process.start()
        except BaseException:
            parent_connection.close()
            child_connection.close()
            self._session._finish(work.request_id)
            self._write_response(_error(work.request_id, -32603, "internal tool error"))
            return
        child_connection.close()
        monitor = Thread(target=self._monitor, args=(key, record), daemon=True)
        record.monitor = monitor
        with self._lock:
            self._records[key] = record
            self._monitors.add(monitor)
        monitor.start()
        if self._session.is_cancelled(work.request_id):
            self.cancel(work.request_id)

    def _monitor(self, key: str, record: _WorkerRecord) -> None:
        try:
            received = record.connection.recv()
            payload = (
                received
                if isinstance(received, dict)
                else {"error": {"code": -32603, "message": "internal tool error"}}
            )
        except (EOFError, OSError):
            payload = {"error": {"code": -32603, "message": "internal tool error"}}
        finally:
            record.connection.close()
        with self._lock:
            current = self._records.get(key)
            if current is not record:
                self._monitors.discard(current_thread())
                return
            self._records.pop(key, None)
        record.process.join(timeout=WORKER_STOP_TIMEOUT_SECONDS)
        if record.process.is_alive():
            self._stop_process(record.process)
        cancelled = self._session._finish(record.work.request_id)
        if cancelled:
            response = _error(record.work.request_id, -32800, "request cancelled")
        elif "error" in payload:
            response = _response(record.work.request_id, error=payload["error"])
        else:
            response = _response(record.work.request_id, result=payload.get("result"))
        self._write_response(response)
        with self._lock:
            self._monitors.discard(current_thread())

    @staticmethod
    def _stop_process(process: Any) -> None:
        if process.is_alive():
            process.terminate()
            process.join(timeout=WORKER_STOP_TIMEOUT_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(timeout=WORKER_STOP_TIMEOUT_SECONDS)

    def cancel(self, request_id: Any) -> None:
        key = self._session._request_key(request_id)
        with self._lock:
            record = self._records.pop(key, None)
        if record is None:
            return
        self._stop_process(record.process)
        self._session._finish(request_id)
        self._write_response(_error(request_id, -32800, "request cancelled"))

    def close(self) -> None:
        with self._lock:
            request_ids = [record.work.request_id for record in self._records.values()]
        for request_id in request_ids:
            self.cancel(request_id)
        with self._lock:
            monitors = tuple(self._monitors)
        for monitor in monitors:
            if monitor is not current_thread():
                monitor.join(timeout=WORKER_STOP_TIMEOUT_SECONDS)


def handle_request(
    request: dict[str, Any],
    *,
    backend: ToolBackend,
    workspace: WorkspaceBinding | None = None,
    backend_context: Any = None,
    session: McpSession | None = None,
) -> dict[str, Any] | None:
    if session is None:
        session = McpSession(
            backend=backend,
            workspace=workspace,
            backend_context=backend_context,
        )
        if request.get("method") != "initialize":
            session.initialized = True
            session.ready = True
    return session.handle(request)


def handle_line(
    line: str,
    *,
    backend: ToolBackend,
    workspace: WorkspaceBinding | None = None,
    backend_context: Any = None,
    session: McpSession | None = None,
) -> dict[str, Any] | None:
    if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
        return _error(None, -32600, "request exceeds the supported input boundary")
    try:
        request = _loads_json(line)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return _error(None, -32700, "invalid JSON")
    if not isinstance(request, dict):
        return _error(None, -32600, "request must be a JSON object")
    return handle_request(
        request,
        backend=backend,
        workspace=workspace,
        backend_context=backend_context,
        session=session,
    )


def serve(
    *,
    backend: ToolBackend,
    workspace: WorkspaceBinding | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    backend_context: Any = None,
) -> int:
    try:
        if workspace is None:
            raise WorkspaceBindingError("configured workspace is required")
        binding = workspace
        binding.assert_current()
    except WorkspaceBindingError:
        return 2
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    session = McpSession(
        backend=backend,
        workspace=binding,
        backend_context=backend_context,
    )
    output_lock = Lock()

    def write_response(response: dict[str, Any] | None) -> None:
        if response is None:
            return
        with output_lock:
            output_stream.write(
                json.dumps(response, sort_keys=True, allow_nan=False) + "\n"
            )
            output_stream.flush()

    try:
        manager = ProcessWorkerManager(
            session=session,
            workspace=binding,
            write_response=write_response,
            backend=backend,
            backend_context=backend_context,
        )
    except RuntimeError:
        return 2
    session.cancel_callback = manager.cancel
    try:
        while not session.shutting_down:
            line = input_stream.readline(MAX_REQUEST_BYTES + 1)
            if not line:
                break
            if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
                if not line.endswith("\n"):
                    while True:
                        remainder = input_stream.readline(MAX_REQUEST_BYTES + 1)
                        if not remainder or remainder.endswith("\n"):
                            break
                write_response(
                    _error(None, -32600, "request exceeds the supported input boundary")
                )
                continue
            if not line.strip():
                continue
            try:
                parsed = _loads_json(line)
            except (json.JSONDecodeError, RecursionError, ValueError):
                write_response(_error(None, -32700, "invalid JSON"))
                continue
            if not isinstance(parsed, dict):
                write_response(_error(None, -32600, "request must be a JSON object"))
                continue
            dispatched = session.dispatch(parsed, defer_tool=True)
            if isinstance(dispatched, ToolWork):
                manager.start(dispatched)
            else:
                write_response(dispatched)
    finally:
        manager.close()
    return 0
