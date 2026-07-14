#!/usr/bin/env python3
"""Installed-artifact qualification for the production OpenClaw adapter."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
import sys
from threading import Thread
from typing import Any, Callable, Sequence

import premode
from premode.no_write import governed_roots_from_product, verify_no_write
from premode.openclaw_integration import openclaw_compatibility
from premode.openclaw_json5 import (
    OpenClawJson5Ownership,
    apply_json5_edit_plan,
    plan_remove_pcodex,
)
from premode.openclaw_mcp_server import (
    TOOL_INPUT_SCHEMA,
    TOOL_OUTPUT_SCHEMA,
    TRANSPORT_SCHEMA_VERSION,
)
from premode.product_contract import validate_payload_against_schema


SUPPORTED_OPENCLAW_VERSION = "2026.4.14"
PRIVATE_RECEIPT_SCHEMA_VERSION = "pcodex.installed-openclaw-adapter-probe.private.v1"
PUBLIC_RECEIPT_SCHEMA_VERSION = "pcodex.installed-openclaw-adapter-probe.public.v1"


def _resolve_schema_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference: {reference}")
    value: Any = root
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(value, dict):
        raise ValueError("schema reference did not resolve to an object")
    return value


def _validate_json_schema(
    instance: Any,
    schema: dict[str, Any],
    *,
    root: dict[str, Any] | None = None,
    path: str = "$",
) -> None:
    """Validate the strict JSON Schema subset used by the MCP transport."""

    authority = schema if root is None else root
    if "$ref" in schema:
        _validate_json_schema(
            instance,
            _resolve_schema_ref(authority, str(schema["$ref"])),
            root=authority,
            path=path,
        )
        return
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        matches = 0
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                continue
            try:
                _validate_json_schema(instance, alternative, root=authority, path=path)
            except ValueError:
                continue
            matches += 1
        if matches == 0:
            raise ValueError(f"{path}: no anyOf alternative matched")
        return
    if "const" in schema and instance != schema["const"]:
        raise ValueError(f"{path}: wrong constant")
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError(f"{path}: value is not in enum")
    expected = schema.get("type")
    if expected == "null":
        if instance is not None:
            raise ValueError(f"{path}: expected null")
        return
    if expected == "object":
        if not isinstance(instance, dict):
            raise ValueError(f"{path}: expected object")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        required = set(schema.get("required") or [])
        if not required <= set(instance):
            raise ValueError(f"{path}: missing required properties")
        if schema.get("additionalProperties") is False and not set(instance) <= set(
            properties
        ):
            raise ValueError(f"{path}: unexpected properties")
        for key, value in instance.items():
            child = properties.get(key)
            if isinstance(child, dict):
                _validate_json_schema(
                    value, child, root=authority, path=f"{path}.{key}"
                )
        return
    if expected == "array":
        if not isinstance(instance, list):
            raise ValueError(f"{path}: expected array")
        if len(instance) < int(schema.get("minItems", 0)):
            raise ValueError(f"{path}: too few items")
        if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
            raise ValueError(f"{path}: too many items")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True) for item in instance]
            if len(encoded) != len(set(encoded)):
                raise ValueError(f"{path}: duplicate items")
        child = schema.get("items")
        if isinstance(child, dict):
            for index, value in enumerate(instance):
                _validate_json_schema(
                    value, child, root=authority, path=f"{path}[{index}]"
                )
        return
    if expected == "string":
        if not isinstance(instance, str):
            raise ValueError(f"{path}: expected string")
        if len(instance) < int(schema.get("minLength", 0)):
            raise ValueError(f"{path}: string too short")
        if "maxLength" in schema and len(instance) > int(schema["maxLength"]):
            raise ValueError(f"{path}: string too long")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, instance) is None:
            raise ValueError(f"{path}: pattern mismatch")
        return
    if expected == "boolean":
        if not isinstance(instance, bool):
            raise ValueError(f"{path}: expected boolean")
        return
    if expected == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            raise ValueError(f"{path}: expected integer")
        return
    if expected == "number" and (
        not isinstance(instance, (int, float))
        or isinstance(instance, bool)
        or not math.isfinite(float(instance))
    ):
        raise ValueError(f"{path}: expected finite number")


def _write(root: Path, relative: str, content: str = "{}\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    expected: set[int] = {0},
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if completed.returncode not in expected:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command returned non-JSON: {' '.join(command)}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("command returned a non-object JSON result")
    return payload


def _pcodex(
    executable: Path,
    workspace: Path,
    env: dict[str, str],
    *arguments: str,
    expected: set[int] = {0},
) -> dict[str, Any]:
    return _run(
        [
            str(executable),
            "integrate",
            "openclaw",
            *arguments,
            "--json",
            "--repo-root",
            str(workspace),
        ],
        cwd=workspace,
        env=env,
        expected=expected,
    )


def _terminate_process(process: subprocess.Popen[str]) -> None:
    """Bounded cleanup for an MCP subprocess on success and every failure path."""

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class _McpLineReader:
    """Read MCP stdout without allowing ``readline`` to block qualification."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            raise RuntimeError("OpenClaw MCP probe stdout is unavailable")
        self.process = process
        self.lines: Queue[str | None] = Queue(maxsize=16)
        self.thread = Thread(
            target=self._drain,
            name="pcodex-installed-openclaw-mcp-reader",
            daemon=True,
        )
        self.thread.start()

    def _drain(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def read(self, *, timeout: float = 30.0) -> dict[str, Any]:
        try:
            line = self.lines.get(timeout=timeout)
        except Empty as exc:
            _terminate_process(self.process)
            raise RuntimeError(
                "OpenClaw MCP probe timed out waiting for a response"
            ) from exc
        if line is None:
            raise RuntimeError("OpenClaw MCP server exited before responding")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenClaw MCP server returned non-JSON output") from exc
        if not isinstance(response, dict):
            raise RuntimeError("OpenClaw MCP server returned a non-object response")
        return response

    def close(self) -> None:
        self.thread.join(timeout=1)


def _registered_command(
    registration: dict[str, Any],
) -> tuple[list[str], dict[str, str]]:
    command = registration.get("command")
    arguments = registration.get("args")
    registration_env = registration.get("env")
    if not isinstance(command, str) or not command or not Path(command).is_absolute():
        raise RuntimeError(
            "OpenClaw registration command is not an absolute executable"
        )
    if not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise RuntimeError("OpenClaw registration arguments are invalid")
    if not isinstance(registration_env, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in registration_env.items()
    ):
        raise RuntimeError("OpenClaw registration environment is invalid")
    return [command, *arguments], dict(registration_env)


def _mcp_probe(
    registration: dict[str, Any],
    workspace: Path,
    env: dict[str, str],
    *,
    response_timeout: float = 30.0,
) -> dict[str, Any]:
    requests: list[dict[str, Any]] = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "artifact-probe", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "premode_preflight",
                "arguments": {
                    "task": (
                        "Inspect AGENTS.md and PROJECT/AI/tests/test_authority.py "
                        "for current OpenClaw authority."
                    ),
                    "profile": "openclaw",
                },
            },
        },
        {"jsonrpc": "2.0", "id": 4, "method": "shutdown"},
    ]
    command, registration_env = _registered_command(registration)
    process = subprocess.Popen(
        command,
        cwd=workspace,
        env={**env, **registration_env},
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    reader = _McpLineReader(process)
    by_id: dict[int, dict[str, Any]] = {}
    try:
        for request in requests:
            process.stdin.write(json.dumps(request, sort_keys=True) + "\n")
            process.stdin.flush()
            if "id" not in request:
                continue
            by_id[int(request["id"])] = reader.read(timeout=response_timeout)
        process.stdin.close()
        try:
            returncode = process.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            _terminate_process(process)
            raise RuntimeError("OpenClaw MCP server did not shut down") from exc
    except BaseException:
        _terminate_process(process)
        raise
    finally:
        reader.close()
    stderr = process.stderr.read() if process.stderr is not None else ""
    if returncode != 0:
        raise RuntimeError(f"OpenClaw MCP server failed: {stderr}")
    initialized = by_id.get(1, {})
    listed = by_id.get(2, {})
    called = by_id.get(3, {})
    shutdown = by_id.get(4, {})
    tools = dict(listed.get("result") or {}).get("tools") or []
    tool_names = [
        item.get("name") if isinstance(item, dict) else None for item in tools
    ]
    result = dict(called.get("result") or {})
    content = result.get("content") or []
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        structured = {}
    listed_tool = tools[0] if len(tools) == 1 and isinstance(tools[0], dict) else {}
    input_schema_authoritative = listed_tool.get("inputSchema") == TOOL_INPUT_SCHEMA
    output_schema_authoritative = listed_tool.get("outputSchema") == TOOL_OUTPUT_SCHEMA
    try:
        _validate_json_schema(structured, TOOL_OUTPUT_SCHEMA)
    except ValueError:
        structured_content_schema_valid = False
    else:
        structured_content_schema_valid = True
    likely_paths = structured.get("likely_paths")
    validation_paths = structured.get("expected_validation_surfaces")
    classifications = structured.get("authority_classifications")
    path_evidence = {
        item
        for item in [
            *(likely_paths if isinstance(likely_paths, list) else []),
            *(validation_paths if isinstance(validation_paths, list) else []),
            *(
                [entry.get("path") for entry in classifications]
                if isinstance(classifications, list)
                else []
            ),
        ]
        if isinstance(item, str)
    }
    expected_path_evidence = bool(
        path_evidence.intersection(
            {
                "AGENTS.md",
                "PROJECT/tasks.json",
                "PROJECT/AI/worker_start/WORKER_START_HERE.md",
                "PROJECT/AI/tests/test_authority.py",
            }
        )
    )
    return {
        "passed": (
            dict(initialized.get("result") or {}).get("protocolVersion") == "2024-11-05"
            and tool_names == ["premode_preflight"]
            and input_schema_authoritative
            and output_schema_authoritative
            and bool(content)
            and structured_content_schema_valid
            and structured.get("schema_version") == TRANSPORT_SCHEMA_VERSION
            and structured.get("status") == "ready"
            and expected_path_evidence
            and "result" in shutdown
        ),
        "protocol_version": dict(initialized.get("result") or {}).get(
            "protocolVersion"
        ),
        "tools": tool_names,
        "input_schema_authoritative": input_schema_authoritative,
        "output_schema_authoritative": output_schema_authoritative,
        "structured_content_schema_valid": structured_content_schema_valid,
        "transport_schema_version": structured.get("schema_version"),
        "tool_call_succeeded": bool(content),
        "tool_status": structured.get("status"),
        "expected_path_evidence": expected_path_evidence,
        "observed_paths": sorted(path_evidence),
        "shutdown_succeeded": "result" in shutdown,
    }


def _no_write_result(verification: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": verification.get("passed") is True,
        "changes": dict(verification.get("comparison") or {}).get("changes"),
        "exceptions": list(verification.get("exceptions") or []),
        "process_observation": verification.get("process_observation"),
        "filesystem_observation": verification.get("filesystem_observation"),
        "forbidden_processes_launched": len(
            verification.get("forbidden_processes_launched") or []
        ),
        "transient_filesystem_events": len(
            verification.get("transient_filesystem_events") or []
        ),
    }


def _verified_no_write(
    operation: Callable[[], dict[str, Any]], roots: Sequence[Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    verification = verify_no_write(
        operation,
        roots=roots,
        monitor_processes=True,
        monitor_filesystem=True,
    )
    value = verification.pop("value")
    if not isinstance(value, dict):
        raise RuntimeError("OpenClaw no-write command did not return a result")
    return value, _no_write_result(verification)


def _load_installed_schema(prefix: Path, name: str) -> dict[str, Any]:
    path = prefix / "share" / "premode-router" / "schemas" / name
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"installed schema is not an object: {name}")
    return value


def _validated_receipts(
    core: dict[str, Any], *, prefix: Path, installed_package_path: str
) -> dict[str, Any]:
    mcp = core.get("mcp")
    mcp_evidence = mcp if isinstance(mcp, dict) else {}
    validation = {
        "openclaw_integration_state": True,
        "mcp_input_schema_authority": (
            mcp_evidence.get("input_schema_authoritative") is True
        ),
        "mcp_output_schema_authority": (
            mcp_evidence.get("output_schema_authoritative") is True
        ),
        "mcp_structured_content": (
            mcp_evidence.get("structured_content_schema_valid") is True
        ),
        "public_receipt": True,
        "private_receipt": True,
    }
    public_receipt = {
        "schema_version": PUBLIC_RECEIPT_SCHEMA_VERSION,
        **core,
        "schemas_validated": validation,
    }
    public_schema = _load_installed_schema(
        prefix, "pcodex.installed-openclaw-adapter-probe.public.v1.schema.json"
    )
    validate_payload_against_schema(public_receipt, public_schema)
    private_receipt = {
        "schema_version": PRIVATE_RECEIPT_SCHEMA_VERSION,
        **core,
        "installed_package_path": installed_package_path,
        "schemas_validated": validation,
        "public_receipt": public_receipt,
    }
    private_schema = _load_installed_schema(
        prefix, "pcodex.installed-openclaw-adapter-probe.private.v1.schema.json"
    )
    validate_payload_against_schema(private_receipt, private_schema)
    return private_receipt


def probe(*, pcodex: Path, control_root: Path) -> dict[str, Any]:
    package_path = Path(premode.__file__).resolve()
    prefix = Path(sys.prefix).resolve()
    if prefix not in package_path.parents:
        raise RuntimeError(
            f"installed probe imported premode outside its environment: {package_path}"
        )
    executable = shutil.which("openclaw")
    compatibility = openclaw_compatibility()
    if (
        executable is None
        or compatibility.get("version") != SUPPORTED_OPENCLAW_VERSION
        or compatibility.get("supported") is not True
    ):
        raise RuntimeError(
            f"qualified OpenClaw {SUPPORTED_OPENCLAW_VERSION} is required: "
            f"{compatibility}"
        )

    workspace = control_root / "OpenClaw artifact workspace Ω with spaces"
    workspace.mkdir(parents=True)
    _write(workspace, "AGENTS.md", "# current authority\n")
    _write(workspace, "PROJECT/tasks.json")
    _write(
        workspace,
        "PROJECT/AI/worker_start/WORKER_START_HERE.md",
        "# current worker authority\n",
    )
    _write(workspace, "PROJECT/AI/tests/test_authority.py", "# verification\n")
    home = control_root / "home"
    temp_root = control_root / "tmp"
    config = home / ".openclaw/openclaw.json"
    config.parent.mkdir(parents=True)
    unrelated = (
        b"{\n  // preserve formatting and an unrelated MCP registration\n"
        b'  mcp: {servers: {unrelated: {command: "/usr/bin/true"}}},\n}\n'
    )
    config.write_bytes(unrelated)
    temp_root.mkdir(parents=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "OPENCLAW_CONFIG_PATH": str(config),
        "XDG_CONFIG_HOME": str(control_root / "xdg-config"),
        "XDG_CACHE_HOME": str(control_root / "xdg-cache"),
        "XDG_DATA_HOME": str(control_root / "xdg-data"),
        "TMPDIR": str(temp_root),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    roots = governed_roots_from_product(
        workspace, home=home, temp_root=temp_root, environ=env
    )

    no_write_commands = {
        "preview": ["--dry-run"],
        "status_absent": ["--status"],
    }
    no_write: dict[str, Any] = {}
    for name, arguments in no_write_commands.items():

        def operation(arguments: list[str] = arguments) -> dict[str, Any]:
            return _pcodex(
                pcodex,
                workspace,
                env,
                *arguments,
                expected={0, 1} if arguments == ["--status"] else {0},
            )

        _value, no_write[name] = _verified_no_write(
            operation,
            roots,
        )

    installed = _pcodex(pcodex, workspace, env, "--write")
    repeated = _pcodex(pcodex, workspace, env, "--write")
    ready = _pcodex(pcodex, workspace, env, "--status")
    state_path = workspace / ".pcodex/openclaw-integration-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    schema_root = prefix / "share/premode-router/schemas"
    validate_payload_against_schema(
        state,
        json.loads(
            (
                schema_root / "pcodex.openclaw-integration-state.v1.schema.json"
            ).read_text(encoding="utf-8")
        ),
    )

    live_validate = _run(
        [str(executable), "config", "validate", "--json"],
        cwd=workspace,
        env=env,
    )
    live_show = _run(
        [str(executable), "mcp", "show", "pcodex", "--json"],
        cwd=workspace,
        env=env,
    )
    expected_registration = {
        "args": ["-m", "premode.pcodex_bootstrap", "openclaw-mcp-server"],
        "env": {"PCODEX_WORKSPACE": str(workspace)},
    }
    exact_live_registration = (
        live_show.get("args") == expected_registration["args"]
        and live_show.get("env") == expected_registration["env"]
        and Path(str(live_show.get("command"))).is_absolute()
        and Path(str(live_show.get("command"))).resolve()
        == Path(sys.executable).resolve()
    )
    mcp = _mcp_probe(live_show, workspace, env)

    disabled = _pcodex(pcodex, workspace, env, "--disable")
    disabled_status = _pcodex(pcodex, workspace, env, "--status", expected={0, 1})
    reenabled = _pcodex(pcodex, workspace, env, "--write")
    owned = state["editor_ownership"]
    ownership = OpenClawJson5Ownership(
        schema_version=owned["schema_version"],
        target_path=tuple(owned["target_path"]),
        target_value_sha256=owned["target_value_sha256"],
        created_containers=tuple(owned["created_containers"]),
    )
    current_config = config.read_bytes()
    config.write_bytes(
        apply_json5_edit_plan(
            current_config, plan_remove_pcodex(current_config, ownership)
        )
    )
    repair_preview, no_write["repair_preview"] = _verified_no_write(
        lambda: _pcodex(
            pcodex, workspace, env, "--repair", "--dry-run", expected={0, 1}
        ),
        roots,
    )
    repair_preview_no_write = no_write["repair_preview"]["passed"] is True
    repaired = _pcodex(pcodex, workspace, env, "--repair")
    ready_after_repair = _pcodex(pcodex, workspace, env, "--status")
    uninstall_preview, no_write["uninstall_preview"] = _verified_no_write(
        lambda: _pcodex(pcodex, workspace, env, "--uninstall", "--dry-run"),
        roots,
    )
    uninstall_preview_no_write = no_write["uninstall_preview"]["passed"] is True
    uninstalled = _pcodex(pcodex, workspace, env, "--uninstall")
    unrelated_preserved = config.read_bytes() == unrelated
    reinstalled = _pcodex(pcodex, workspace, env, "--write")
    final_ready = _pcodex(pcodex, workspace, env, "--status")
    final_uninstall = _pcodex(pcodex, workspace, env, "--uninstall")

    lifecycle = {
        "install": installed.get("status"),
        "idempotent": repeated.get("idempotent") is True,
        "ready": ready.get("readiness"),
        "live_config_valid": live_validate.get("valid") is True,
        "live_registration_exact": exact_live_registration,
        "disable": disabled.get("status"),
        "disabled_status": disabled_status.get("readiness"),
        "reenable": reenabled.get("status"),
        "repair_preview": repair_preview.get("status"),
        "repair_preview_no_write": repair_preview_no_write,
        "repair": repaired.get("status"),
        "ready_after_repair": ready_after_repair.get("readiness"),
        "uninstall_preview": uninstall_preview.get("status"),
        "uninstall_preview_no_write": uninstall_preview_no_write,
        "uninstall": uninstalled.get("status"),
        "unrelated_preserved": unrelated_preserved,
        "reinstall": reinstalled.get("status"),
        "final_ready": final_ready.get("readiness"),
        "final_uninstall": final_uninstall.get("status"),
    }
    passed = (
        all(item.get("passed") is True for item in no_write.values())
        and lifecycle
        == {
            "install": "installed",
            "idempotent": True,
            "ready": "READY",
            "live_config_valid": True,
            "live_registration_exact": True,
            "disable": "disabled",
            "disabled_status": "NEEDS_ACTION",
            "reenable": "installed",
            "repair_preview": "repair_preview",
            "repair_preview_no_write": True,
            "repair": "installed",
            "ready_after_repair": "READY",
            "uninstall_preview": "uninstall_preview",
            "uninstall_preview_no_write": True,
            "uninstall": "uninstalled",
            "unrelated_preserved": True,
            "reinstall": "installed",
            "final_ready": "READY",
            "final_uninstall": "uninstalled",
        }
        and mcp.get("passed") is True
    )
    return _validated_receipts(
        {
            "passed": passed,
            "installed_import_isolated": True,
            "openclaw_version": compatibility.get("version"),
            "no_write": no_write,
            "lifecycle": lifecycle,
            "mcp": mcp,
        },
        prefix=prefix,
        installed_package_path=str(package_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcodex", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    args = parser.parse_args()
    result = probe(
        pcodex=args.pcodex.resolve(), control_root=args.control_root.resolve()
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
