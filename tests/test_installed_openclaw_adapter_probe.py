from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

from scripts.installed_openclaw_adapter_probe import (
    _mcp_probe,
    _no_write_result,
    _registered_command,
    _validated_receipts,
    _verified_no_write,
)
from scripts.build_release_artifacts import persist_openclaw_adapter_probe
from premode.openclaw_mcp_server import (
    TOOL_INPUT_SCHEMA,
    TOOL_OUTPUT_SCHEMA,
    TRANSPORT_SCHEMA_VERSION,
)


ROOT = Path(__file__).resolve().parents[1]


def _fake_server(tmp_path: Path) -> Path:
    script = tmp_path / "fake registered server.py"
    source = """\
import json
import os
import sys
import time

INPUT_SCHEMA = __INPUT_SCHEMA__
OUTPUT_SCHEMA = __OUTPUT_SCHEMA__

if sys.argv[1:] != ["registered-token"]:
    raise SystemExit(19)
if os.environ.get("FAKE_STALL") == "1":
    Path = __import__("pathlib").Path
    Path(os.environ["PID_FILE"]).write_text(str(os.getpid()))
    time.sleep(60)
    raise SystemExit(0)
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05"}
    elif method == "tools/list":
        input_schema = dict(INPUT_SCHEMA)
        output_schema = dict(OUTPUT_SCHEMA)
        if os.environ.get("FAKE_INPUT_SCHEMA_BAD") == "1":
            input_schema["additionalProperties"] = True
        if os.environ.get("FAKE_OUTPUT_SCHEMA_BAD") == "1":
            output_schema["additionalProperties"] = True
        result = {"tools": [{
            "name": "premode_preflight",
            "inputSchema": input_schema,
            "outputSchema": output_schema,
        }]}
    elif method == "tools/call":
        structured = {
            "schema_version": "pcodex.openclaw-mcp-preflight-result.v1",
            "status": os.environ.get("FAKE_STATUS", "ready"),
            "routing_mode": "narrow",
            "likely_paths": (
                ["AGENTS.md"] if os.environ.get("FAKE_PATH", "1") == "1" else []
            ),
            "expected_validation_surfaces": [],
            "authority_classifications": [],
            "dangerous_mutation_zones": [],
            "receipt_id": "fake-receipt",
        }
        if os.environ.get("FAKE_STRUCTURED_BAD") == "1":
            structured["unexpected"] = True
        if os.environ.get("FAKE_SCHEMA_VERSION_BAD") == "1":
            structured["schema_version"] = "future"
        result = {
            "content": [{"type": "text", "text": json.dumps(structured)}],
            "structuredContent": structured,
        }
    elif method == "shutdown":
        result = {}
    else:
        raise SystemExit(20)
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
    if method == "shutdown":
        break
"""
    source = source.replace("__INPUT_SCHEMA__", repr(TOOL_INPUT_SCHEMA)).replace(
        "__OUTPUT_SCHEMA__", repr(TOOL_OUTPUT_SCHEMA)
    )
    script.write_text(
        source,
        encoding="utf-8",
    )
    return script


def _registration(script: Path, **extra_env: str) -> dict[str, object]:
    return {
        "command": sys.executable,
        "args": [str(script), "registered-token"],
        "env": {"PCODEX_WORKSPACE": str(script.parent), **extra_env},
    }


def test_registered_command_is_the_command_that_the_probe_executes(
    tmp_path: Path,
) -> None:
    script = _fake_server(tmp_path)
    result = _mcp_probe(_registration(script), tmp_path, dict(os.environ))

    assert result["passed"] is True
    assert result["tool_status"] == "ready"
    assert result["input_schema_authoritative"] is True
    assert result["output_schema_authoritative"] is True
    assert result["structured_content_schema_valid"] is True
    assert result["transport_schema_version"] == TRANSPORT_SCHEMA_VERSION
    assert result["expected_path_evidence"] is True
    assert result["observed_paths"] == ["AGENTS.md"]


@pytest.mark.parametrize(
    ("extra_env", "expected_status"),
    [
        ({"FAKE_STATUS": "backend_unavailable"}, "backend_unavailable"),
        ({"FAKE_PATH": "0"}, "ready"),
    ],
)
def test_mcp_probe_rejects_unready_or_pathless_results(
    tmp_path: Path, extra_env: dict[str, str], expected_status: str
) -> None:
    script = _fake_server(tmp_path)
    result = _mcp_probe(_registration(script, **extra_env), tmp_path, dict(os.environ))

    assert result["passed"] is False
    assert result["tool_status"] == expected_status


@pytest.mark.parametrize(
    ("extra_env", "failed_check"),
    [
        ({"FAKE_INPUT_SCHEMA_BAD": "1"}, "input_schema_authoritative"),
        ({"FAKE_OUTPUT_SCHEMA_BAD": "1"}, "output_schema_authoritative"),
        ({"FAKE_STRUCTURED_BAD": "1"}, "structured_content_schema_valid"),
        ({"FAKE_SCHEMA_VERSION_BAD": "1"}, "structured_content_schema_valid"),
    ],
)
def test_mcp_probe_rejects_schema_drift_and_invalid_structured_content(
    tmp_path: Path, extra_env: dict[str, str], failed_check: str
) -> None:
    script = _fake_server(tmp_path)
    result = _mcp_probe(_registration(script, **extra_env), tmp_path, dict(os.environ))

    assert result["passed"] is False
    assert result[failed_check] is False


def test_mcp_probe_timeout_terminates_the_registered_process(tmp_path: Path) -> None:
    script = _fake_server(tmp_path)
    pid_file = tmp_path / "server.pid"
    started = time.monotonic()

    with pytest.raises(RuntimeError, match="timed out waiting for a response"):
        _mcp_probe(
            _registration(script, FAKE_STALL="1", PID_FILE=str(pid_file)),
            tmp_path,
            dict(os.environ),
            response_timeout=0.1,
        )

    assert time.monotonic() - started < 8
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_registered_command_rejects_nonabsolute_or_malformed_registration() -> None:
    with pytest.raises(RuntimeError, match="absolute executable"):
        _registered_command({"command": "python", "args": [], "env": {}})
    with pytest.raises(RuntimeError, match="arguments"):
        _registered_command({"command": sys.executable, "args": "bad", "env": {}})
    with pytest.raises(RuntimeError, match="environment"):
        _registered_command({"command": sys.executable, "args": [], "env": []})


def test_no_write_summary_requires_full_monitor_result() -> None:
    summary = _no_write_result(
        {
            "passed": False,
            "comparison": {"changes": [{"kind": "metadata"}]},
            "exceptions": ["RuntimeError"],
            "process_observation": "complete",
            "filesystem_observation": "complete",
            "forbidden_processes_launched": [{"pid": 1}],
            "transient_filesystem_events": [{"path": "temporary"}],
        }
    )

    assert summary == {
        "passed": False,
        "changes": [{"kind": "metadata"}],
        "exceptions": ["RuntimeError"],
        "process_observation": "complete",
        "filesystem_observation": "complete",
        "forbidden_processes_launched": 1,
        "transient_filesystem_events": 1,
    }


def test_verified_no_write_enables_process_filesystem_and_metadata_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_verify(operation: object, **kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        assert callable(operation)
        return {
            "value": operation(),
            "passed": True,
            "comparison": {"changes": []},
            "exceptions": [],
            "process_observation": "complete",
            "filesystem_observation": "complete",
            "forbidden_processes_launched": [],
            "transient_filesystem_events": [],
        }

    monkeypatch.setattr(
        "scripts.installed_openclaw_adapter_probe.verify_no_write", fake_verify
    )
    value, evidence = _verified_no_write(lambda: {"status": "preview"}, ["root"])

    assert value == {"status": "preview"}
    assert evidence["passed"] is True
    assert observed == {
        "roots": ["root"],
        "monitor_processes": True,
        "monitor_filesystem": True,
    }


def _installed_schema_prefix(tmp_path: Path) -> Path:
    target = tmp_path / "prefix/share/premode-router/schemas"
    target.mkdir(parents=True)
    for name in (
        "pcodex.installed-openclaw-adapter-probe.private.v1.schema.json",
        "pcodex.installed-openclaw-adapter-probe.public.v1.schema.json",
    ):
        shutil.copyfile(ROOT / "schemas" / name, target / name)
    return tmp_path / "prefix"


def _core_receipt() -> dict[str, object]:
    no_write_item = {
        "passed": True,
        "changes": [],
        "exceptions": [],
        "process_observation": "complete",
        "filesystem_observation": "complete",
        "forbidden_processes_launched": 0,
        "transient_filesystem_events": 0,
    }
    return {
        "passed": True,
        "installed_import_isolated": True,
        "openclaw_version": "2026.4.14",
        "no_write": {
            name: deepcopy(no_write_item)
            for name in (
                "preview",
                "status_absent",
                "repair_preview",
                "uninstall_preview",
            )
        },
        "lifecycle": {
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
        },
        "mcp": {
            "passed": True,
            "protocol_version": "2024-11-05",
            "tools": ["premode_preflight"],
            "input_schema_authoritative": True,
            "output_schema_authoritative": True,
            "structured_content_schema_valid": True,
            "transport_schema_version": TRANSPORT_SCHEMA_VERSION,
            "tool_call_succeeded": True,
            "tool_status": "ready",
            "expected_path_evidence": True,
            "observed_paths": ["AGENTS.md"],
            "shutdown_succeeded": True,
        },
    }


def test_distinct_public_private_receipts_validate_before_persistence(
    tmp_path: Path,
) -> None:
    receipts = _validated_receipts(
        _core_receipt(),
        prefix=_installed_schema_prefix(tmp_path),
        installed_package_path="/private/installed/premode/__init__.py",
    )

    assert receipts["schema_version"].endswith(".private.v1")
    public = receipts["public_receipt"]
    assert isinstance(public, dict)
    assert public["schema_version"].endswith(".public.v1")
    assert "installed_package_path" not in public
    assert receipts["schemas_validated"] == {
        "openclaw_integration_state": True,
        "mcp_input_schema_authority": True,
        "mcp_output_schema_authority": True,
        "mcp_structured_content": True,
        "public_receipt": True,
        "private_receipt": True,
    }

    output = tmp_path / "evidence"
    persisted = persist_openclaw_adapter_probe(output, "wheel", receipts)
    assert persisted == public
    assert (
        json.loads(
            (output / "receipts/installed-openclaw-adapter-wheel.json").read_text()
        )
        == public
    )
    assert (
        json.loads(
            (output / "private-receipts/openclaw-adapter/wheel.json").read_text()
        )
        == receipts
    )


def test_receipt_schema_failure_prevents_any_persistence(tmp_path: Path) -> None:
    receipts = _validated_receipts(
        _core_receipt(),
        prefix=_installed_schema_prefix(tmp_path),
        installed_package_path="/private/installed/premode/__init__.py",
    )
    public = receipts["public_receipt"]
    assert isinstance(public, dict)
    public["unexpected"] = True
    output = tmp_path / "evidence"

    with pytest.raises(ValueError, match="unexpected"):
        persist_openclaw_adapter_probe(output, "wheel", receipts)

    assert not output.exists()


def test_public_private_evidence_disagreement_prevents_persistence(
    tmp_path: Path,
) -> None:
    receipts = _validated_receipts(
        _core_receipt(),
        prefix=_installed_schema_prefix(tmp_path),
        installed_package_path="/private/installed/premode/__init__.py",
    )
    public = receipts["public_receipt"]
    assert isinstance(public, dict)
    public["passed"] = False
    output = tmp_path / "evidence"

    with pytest.raises(RuntimeError, match="disagree"):
        persist_openclaw_adapter_probe(output, "wheel", receipts)

    assert not output.exists()
