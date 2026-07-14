"""Installed-artifact access to the authoritative product manifest snapshot."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import sys
from typing import Any


def installed_contract_paths(prefix: Path | str | None = None) -> tuple[Path, Path]:
    root = Path(sys.prefix if prefix is None else prefix)
    share = root / "share" / "premode-router"
    return (
        share / "premode.product.json",
        share / "schemas" / "premode.product.schema.json",
    )


def _resolve_ref(root_schema: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference: {reference}")
    value: Any = root_schema
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(value, dict):
        raise ValueError(f"schema reference is not an object: {reference}")
    return value


def validate_payload_against_schema(instance: Any, schema: dict[str, Any]) -> None:
    _validate(instance, schema, "$", schema)


def _validate(
    instance: Any, schema: dict[str, Any], path: str, root_schema: dict[str, Any]
) -> None:
    if "$ref" in schema:
        _validate(
            instance, _resolve_ref(root_schema, str(schema["$ref"])), path, root_schema
        )
        return
    if "const" in schema and instance != schema["const"]:
        raise ValueError(f"{path}: wrong constant")
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError(f"{path}: value is not in enum")
    expected = schema.get("type")
    if isinstance(expected, list):
        matches = (
            ("null" in expected and instance is None)
            or ("string" in expected and isinstance(instance, str))
            or ("object" in expected and isinstance(instance, dict))
            or ("array" in expected and isinstance(instance, list))
            or ("boolean" in expected and isinstance(instance, bool))
            or (
                "integer" in expected
                and isinstance(instance, int)
                and not isinstance(instance, bool)
            )
            or (
                "number" in expected
                and isinstance(instance, (int, float))
                and not isinstance(instance, bool)
                and math.isfinite(float(instance))
            )
        )
        if not matches:
            raise ValueError(f"{path}: wrong type")
        return
    if expected == "object":
        if not isinstance(instance, dict):
            raise ValueError(f"{path}: expected object")
        required = set(schema.get("required", []))
        if not required <= set(instance):
            raise ValueError(f"{path}: missing {sorted(required - set(instance))}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and not set(instance) <= set(
            properties
        ):
            raise ValueError(
                f"{path}: unexpected {sorted(set(instance) - set(properties))}"
            )
        for key, value in instance.items():
            if key in properties:
                _validate(value, properties[key], f"{path}.{key}", root_schema)
    elif expected == "array":
        if not isinstance(instance, list):
            raise ValueError(f"{path}: expected array")
        if len(instance) < int(schema.get("minItems", 0)):
            raise ValueError(f"{path}: too few items")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(value, sort_keys=True) for value in instance]
            if len(encoded) != len(set(encoded)):
                raise ValueError(f"{path}: duplicate items")
        for index, value in enumerate(instance):
            _validate(value, schema.get("items", {}), f"{path}[{index}]", root_schema)
    elif expected == "string":
        if not isinstance(instance, str):
            raise ValueError(f"{path}: expected string")
        if len(instance) < int(schema.get("minLength", 0)):
            raise ValueError(f"{path}: string too short")
        if (
            schema.get("pattern")
            and re.search(str(schema["pattern"]), instance) is None
        ):
            raise ValueError(f"{path}: pattern mismatch")
    elif expected == "boolean" and not isinstance(instance, bool):
        raise ValueError(f"{path}: expected boolean")
    elif expected == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            raise ValueError(f"{path}: expected integer")
        if "minimum" in schema and instance < int(schema["minimum"]):
            raise ValueError(f"{path}: below minimum")
    elif expected == "number":
        if (
            not isinstance(instance, (int, float))
            or isinstance(instance, bool)
            or not math.isfinite(float(instance))
        ):
            raise ValueError(f"{path}: expected finite number")


def validate_installed_product_contract(
    prefix: Path | str | None = None,
) -> dict[str, Any]:
    manifest_path, schema_path = installed_contract_paths(prefix)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate_payload_against_schema(manifest, schema)
    required_contracts = {
        "ContextRequestV1",
        "ContextSelectionV1",
        "ContextPacketV1",
        "ContextReceiptV1",
        "PacketStrategyPluginV1",
        "AgentAdapterV1",
    }
    contracts = manifest.get("cross_process_contracts")
    names = (
        [item.get("name") for item in contracts] if isinstance(contracts, list) else []
    )
    if len(names) != len(required_contracts) or set(names) != required_contracts:
        raise ValueError(
            "$.cross_process_contracts: exactly one authority per required contract is required"
        )
    required_openclaw_contracts = {
        "OpenClawPreflightRequestV1",
        "OpenClawPreflightResultV1",
        "OpenClawPreflightReceiptV1",
    }
    integration_contracts = manifest.get("integration_contracts")
    openclaw_contracts = (
        integration_contracts.get("openclaw")
        if isinstance(integration_contracts, dict)
        else None
    )
    openclaw_names = (
        [item.get("name") for item in openclaw_contracts]
        if isinstance(openclaw_contracts, list)
        and all(isinstance(item, dict) for item in openclaw_contracts)
        else []
    )
    if (
        len(openclaw_names) != len(required_openclaw_contracts)
        or set(openclaw_names) != required_openclaw_contracts
    ):
        raise ValueError(
            "$.integration_contracts.openclaw: exactly one authority per "
            "required OpenClaw application contract is required"
        )
    return {
        "status": "valid",
        "schema_version": manifest["schema_version"],
        "product_name": manifest["product_name"],
        "release_target": manifest.get("release_target"),
    }


def validate_installed_contract_goldens(
    prefix: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(sys.prefix if prefix is None else prefix) / "share" / "premode-router"
    pairs = {
        "production-ranking-request-v1.json": "production-ranking-request-v1.schema.json",
        "production-ranking-result-v1.json": "production-ranking-provider-v1.schema.json",
        "context-packet-v1.json": "context-packet-v1.schema.json",
        "context-receipt-v1.json": "context-receipt-v1.schema.json",
        "packet-strategy-plugin-v1.json": "packet-strategy-plugin-v1.schema.json",
        "agent-adapter-v1.json": "agent-adapter-v1.schema.json",
        "openclaw-preflight-request-v1.json": "pcodex.openclaw-preflight-request.v1.schema.json",
        "openclaw-preflight-result-v1.json": "pcodex.openclaw-preflight-result.v1.schema.json",
        "openclaw-preflight-receipt-v1.json": "pcodex.openclaw-preflight-receipt.v1.schema.json",
    }
    for golden_name, schema_name in pairs.items():
        golden = json.loads(
            (root / "contracts" / "goldens" / golden_name).read_text(encoding="utf-8")
        )
        schema = json.loads(
            (root / "schemas" / schema_name).read_text(encoding="utf-8")
        )
        validate_payload_against_schema(golden, schema)
    return {
        "status": "valid",
        "schema_version": "pcodex.installed-contract-goldens.v1",
        "validated_contracts": sorted(pairs),
    }
