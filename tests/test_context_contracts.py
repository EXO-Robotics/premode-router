from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
from jsonschema import Draft202012Validator

from premode.codex_plugin import CANONICAL_CODEX_AGENT_ADAPTER
from premode.context_contracts import (
    AgentAdapterV1,
    ContextContractError,
    agent_adapter_contract_from_dict,
    context_packet_from_dict,
    context_receipt_from_dict,
)
from premode.core_packet import CorePath, render_context_packet_v1
from premode.plugins import resolve_packet_plugin
from premode.production_ranking import (
    ProductionRankingContractError,
    ProductionRankingRequestV1,
    ranking_request_from_dict,
    ranking_result_from_dict,
)
from premode.product_contract import validate_installed_contract_goldens


ROOT = Path(__file__).resolve().parents[1]
GOLDENS = ROOT / "contracts/goldens"
SCHEMAS = ROOT / "schemas"
CONTRACT_SCHEMA_PAIRS = {
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


@pytest.mark.parametrize(("golden_name", "schema_name"), CONTRACT_SCHEMA_PAIRS.items())
def test_contract_goldens_validate_against_draft_2020_12(
    golden_name: str,
    schema_name: str,
) -> None:
    golden = json.loads((GOLDENS / golden_name).read_text(encoding="utf-8"))
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(golden)


def test_production_ranking_request_is_strict_versioned_and_json_safe() -> None:
    golden = json.loads(
        (GOLDENS / "production-ranking-request-v1.json").read_text(encoding="utf-8")
    )
    request = ranking_request_from_dict(golden)

    assert request.to_dict() == golden
    with pytest.raises(ProductionRankingContractError, match="unsupported request"):
        ranking_request_from_dict({**golden, "schema_version": "future.v2"})
    with pytest.raises(ProductionRankingContractError, match="unsupported fields"):
        ranking_request_from_dict({**golden, "unknown": True})
    with pytest.raises(ProductionRankingContractError, match="non-JSON"):
        ProductionRankingRequestV1("task", {"bad": object()}, {})


def test_production_ranking_result_rejects_unknown_fields() -> None:
    golden = json.loads(
        (GOLDENS / "production-ranking-result-v1.json").read_text(encoding="utf-8")
    )

    assert ranking_result_from_dict(golden).to_dict() == golden
    with pytest.raises(ProductionRankingContractError, match="unsupported fields"):
        ranking_result_from_dict({**golden, "candidate_id": "forbidden"})
    with pytest.raises(ProductionRankingContractError, match="source_contract must be a string"):
        ranking_result_from_dict(
            {**golden, "decision_receipt": {**golden["decision_receipt"], "source_contract": 123}}
        )
    with pytest.raises(ProductionRankingContractError, match="abstention_reason must be"):
        ranking_result_from_dict({**golden, "abstention_reason": 123})


def test_context_packet_structurally_preserves_one_task_field_and_exact_paths() -> None:
    packet = render_context_packet_v1(
        "README.md",
        [CorePath("docs/README.md", role="primary")],
    )

    assert packet.rendered_packet.startswith("TASK\nREADME.md\nLIKELY FILES\n")
    assert packet.rendered_packet.splitlines().count("README.md") == 1
    assert "* docs/README.md" in packet.rendered_packet
    assert context_packet_from_dict(packet.to_dict()) == packet


def test_context_packet_and_receipt_unknown_versions_fail_closed() -> None:
    packet = json.loads((GOLDENS / "context-packet-v1.json").read_text(encoding="utf-8"))
    receipt = json.loads((GOLDENS / "context-receipt-v1.json").read_text(encoding="utf-8"))

    with pytest.raises(ContextContractError, match="unsupported context packet"):
        context_packet_from_dict({**packet, "schema_version": "future.v2"})
    with pytest.raises(ContextContractError, match="unsupported context receipt"):
        context_receipt_from_dict({**receipt, "schema_version": "future.v2"})
    with pytest.raises(ContextContractError, match="exact_task_sha256 does not match"):
        context_packet_from_dict({**packet, "exact_task_sha256": "0" * 64})
    with pytest.raises(ContextContractError, match="section boundary"):
        context_packet_from_dict({**packet, "exact_task_length": packet["exact_task_length"] + 1})


def test_packet_strategy_and_codex_agent_adapter_match_goldens() -> None:
    plugin_golden = json.loads(
        (GOLDENS / "packet-strategy-plugin-v1.json").read_text(encoding="utf-8")
    )
    adapter_golden = json.loads(
        (GOLDENS / "agent-adapter-v1.json").read_text(encoding="utf-8")
    )

    assert resolve_packet_plugin("literal_symbol").as_dict() == plugin_golden
    assert isinstance(CANONICAL_CODEX_AGENT_ADAPTER, AgentAdapterV1)
    assert CANONICAL_CODEX_AGENT_ADAPTER.describe().to_dict() == adapter_golden
    assert agent_adapter_contract_from_dict(adapter_golden).to_dict() == adapter_golden


def test_agent_adapter_unknown_version_and_scalar_arrays_fail_closed() -> None:
    golden = json.loads((GOLDENS / "agent-adapter-v1.json").read_text(encoding="utf-8"))

    with pytest.raises(ContextContractError, match="unsupported agent adapter"):
        agent_adapter_contract_from_dict({**golden, "schema_version": "future.v2"})
    with pytest.raises(ContextContractError, match="ordered array"):
        agent_adapter_contract_from_dict({**golden, "supported_platforms": "darwin"})


def test_contract_goldens_validate_from_installed_share_layout(tmp_path: Path) -> None:
    share = tmp_path / "share/premode-router"
    shutil.copytree(SCHEMAS, share / "schemas")
    shutil.copytree(GOLDENS, share / "contracts/goldens")

    result = validate_installed_contract_goldens(tmp_path)

    assert result["status"] == "valid"
    assert len(result["validated_contracts"]) == len(CONTRACT_SCHEMA_PAIRS)
