"""Versioned logistics contracts shared across product and agent adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import math
import re
from typing import Any, Mapping, Protocol, runtime_checkable


CONTEXT_PACKET_SCHEMA_VERSION = "pcodex.context-packet.v1"
CONTEXT_RECEIPT_SCHEMA_VERSION = "pcodex.context-receipt.v1"
AGENT_ADAPTER_CONTRACT_SCHEMA_VERSION = "pcodex.agent-adapter-contract.v1"
PRIVATE_SENSITIVITY = "sensitive_private"
PRIVATE_METADATA_SENSITIVITY = "private_metadata"
PUBLIC_SAFE_SENSITIVITY = "public_safe"


class ContextContractError(ValueError):
    """Raised when a versioned product contract fails closed."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ContextContractError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _strict_fields(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise ContextContractError(f"{label} contains missing or unsupported fields")


@dataclass(frozen=True)
class ContextPacketV1:
    """Typed wrapper around the unchanged canonical model-facing packet."""

    rendered_packet: str
    exact_task_sha256: str
    exact_task_length: int
    packet_sha256: str
    renderer_id: str = "canonical_core_v1"
    schema_version: str = CONTEXT_PACKET_SCHEMA_VERSION
    sensitivity_classification: str = PRIVATE_SENSITIVITY

    def __post_init__(self) -> None:
        if self.schema_version != CONTEXT_PACKET_SCHEMA_VERSION:
            raise ContextContractError(
                f"unsupported context packet schema_version: {self.schema_version}"
            )
        if self.renderer_id != "canonical_core_v1":
            raise ContextContractError(f"unsupported renderer_id: {self.renderer_id}")
        if self.sensitivity_classification != PRIVATE_SENSITIVITY:
            raise ContextContractError("context packets must remain sensitive/private")
        if not isinstance(self.rendered_packet, str):
            raise ContextContractError("rendered_packet must be a string")
        if not isinstance(self.exact_task_length, int) or isinstance(self.exact_task_length, bool) or self.exact_task_length < 0:
            raise ContextContractError("exact_task_length must be a non-negative integer")
        _require_sha256(self.exact_task_sha256, "exact_task_sha256")
        _require_sha256(self.packet_sha256, "packet_sha256")
        if self.packet_sha256 != _sha256(self.rendered_packet):
            raise ContextContractError("packet_sha256 does not match rendered_packet")
        prefix = "TASK\n"
        if not self.rendered_packet.startswith(prefix):
            raise ContextContractError("canonical packet must start with the TASK field")
        task_start = len(prefix)
        task_end = task_start + self.exact_task_length
        exact_task = self.rendered_packet[task_start:task_end]
        suffix = self.rendered_packet[task_end:]
        if not suffix.startswith(("\nLIKELY FILES\n", "\n\n")):
            raise ContextContractError("canonical packet TASK field length or section boundary is invalid")
        if self.exact_task_sha256 != _sha256(exact_task):
            raise ContextContractError("exact_task_sha256 does not match the canonical TASK field")

    @classmethod
    def from_task_and_packet(cls, exact_task: str, rendered_packet: str) -> ContextPacketV1:
        if not isinstance(exact_task, str):
            raise ContextContractError("exact_task must be a string")
        if not isinstance(rendered_packet, str):
            raise ContextContractError("rendered_packet must be a string")
        if not rendered_packet.startswith(f"TASK\n{exact_task}\n"):
            raise ContextContractError(
                "canonical packet must project exact_task into the single leading TASK field"
            )
        return cls(
            rendered_packet=rendered_packet,
            exact_task_sha256=_sha256(exact_task),
            exact_task_length=len(exact_task),
            packet_sha256=_sha256(rendered_packet),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def context_packet_from_dict(payload: Mapping[str, Any]) -> ContextPacketV1:
    expected = {field.name for field in fields(ContextPacketV1)}
    _strict_fields(payload, expected, "context packet")
    return ContextPacketV1(
        rendered_packet=payload["rendered_packet"],  # type: ignore[arg-type]
        exact_task_sha256=payload["exact_task_sha256"],  # type: ignore[arg-type]
        exact_task_length=payload["exact_task_length"],  # type: ignore[arg-type]
        packet_sha256=payload["packet_sha256"],  # type: ignore[arg-type]
        renderer_id=payload["renderer_id"],  # type: ignore[arg-type]
        schema_version=payload["schema_version"],  # type: ignore[arg-type]
        sensitivity_classification=payload["sensitivity_classification"],  # type: ignore[arg-type]
    )


@dataclass(frozen=True, kw_only=True)
class ContextReceiptV1:
    context_boundary_mode: str
    packet_mode: str | None
    packet_detail_mode: str | None
    packet_detail_mode_requested: str | None
    packet_detail_mode_selected: str | None
    profile: str | None
    repo_map_enabled: bool
    packet_total_tokens: int | float | None
    model_facing_packet_tokens: int | float | None
    hard_packet_token_budget: int | float | None
    selected_context_tokens: int | float | None
    saved_context_tokens: int | float | None
    model_facing_context_tokens: int | float | None
    model_facing_evidence_tokens: int | float | None
    local_manifest_tokens: int | float | None
    paths_only_packet_tokens: int | float | None
    evidence_snippet_packet_tokens: int | float | None
    full_repo_reduction_percent: int | float | None
    policy_metadata_tokens: int | float | None
    output_contract_tokens: int | float | None
    budget_exceeded: bool
    budget_exceeded_by: int | float | None
    over_budget_reason: str | None
    full_text_file_count: int | float | None
    summary_file_count: int | float | None
    manifest_file_count: int | float | None
    schema_version: str = CONTEXT_RECEIPT_SCHEMA_VERSION
    sensitivity_classification: str = PRIVATE_METADATA_SENSITIVITY

    def __post_init__(self) -> None:
        if self.schema_version != CONTEXT_RECEIPT_SCHEMA_VERSION:
            raise ContextContractError(
                f"unsupported context receipt schema_version: {self.schema_version}"
            )
        if self.sensitivity_classification != PRIVATE_METADATA_SENSITIVITY:
            raise ContextContractError("context receipt sensitivity is invalid")
        for name in (
            "context_boundary_mode",
            "packet_mode",
            "packet_detail_mode",
            "packet_detail_mode_requested",
            "packet_detail_mode_selected",
            "profile",
            "over_budget_reason",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ContextContractError(f"{name} must be a string or null")
        if not isinstance(self.repo_map_enabled, bool):
            raise ContextContractError("repo_map_enabled must be a boolean")
        if not isinstance(self.budget_exceeded, bool):
            raise ContextContractError("budget_exceeded must be a boolean")
        for field in fields(self):
            if not field.name.endswith(("_tokens", "_budget", "_percent", "_by", "_count")):
                continue
            value = getattr(self, field.name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContextContractError(f"{field.name} must be a finite number or null")
            if not math.isfinite(float(value)):
                raise ContextContractError(f"{field.name} must be finite")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def context_receipt_from_dict(payload: Mapping[str, Any]) -> ContextReceiptV1:
    expected = {field.name for field in fields(ContextReceiptV1)}
    _strict_fields(payload, expected, "context receipt")
    return ContextReceiptV1(**dict(payload))


@dataclass(frozen=True)
class AgentAdapterContractV1:
    adapter_id: str
    adapter_version: str
    supported_platforms: tuple[str, ...]
    supported_agent_versions: tuple[str, ...]
    lifecycle_operations: tuple[str, ...]
    workspace_binding: str = "configured_root_immutable"
    exact_task_transport: str = "single_canonical_field"
    schema_version: str = AGENT_ADAPTER_CONTRACT_SCHEMA_VERSION
    sensitivity_classification: str = PUBLIC_SAFE_SENSITIVITY

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_ADAPTER_CONTRACT_SCHEMA_VERSION:
            raise ContextContractError(
                f"unsupported agent adapter schema_version: {self.schema_version}"
            )
        if self.sensitivity_classification != PUBLIC_SAFE_SENSITIVITY:
            raise ContextContractError("agent adapter descriptors must be public-safe")
        for name in ("adapter_id", "adapter_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value) is None:
                raise ContextContractError(f"{name} must be a public-safe identifier")
        if self.workspace_binding != "configured_root_immutable":
            raise ContextContractError("agent adapters must bind one immutable configured root")
        if self.exact_task_transport != "single_canonical_field":
            raise ContextContractError("agent adapters must preserve the canonical task field")
        allowed_operations = {
            "preview",
            "install",
            "status",
            "discovery",
            "repair",
            "disable",
            "reinstall",
            "uninstall",
        }
        for name in ("supported_platforms", "supported_agent_versions"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not values or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise ContextContractError(f"{name} must be a non-empty ordered tuple")
            if len(set(values)) != len(values):
                raise ContextContractError(f"{name} contains duplicates")
        if not isinstance(self.lifecycle_operations, tuple) or not self.lifecycle_operations:
            raise ContextContractError("lifecycle_operations must be a non-empty tuple")
        if set(self.lifecycle_operations) - allowed_operations:
            raise ContextContractError("lifecycle_operations contains unsupported values")
        if len(set(self.lifecycle_operations)) != len(self.lifecycle_operations):
            raise ContextContractError("lifecycle_operations contains duplicates")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in (
            "supported_platforms",
            "supported_agent_versions",
            "lifecycle_operations",
        ):
            payload[name] = list(payload[name])
        return payload


def agent_adapter_contract_from_dict(
    payload: Mapping[str, Any],
) -> AgentAdapterContractV1:
    expected = {field.name for field in fields(AgentAdapterContractV1)}
    _strict_fields(payload, expected, "agent adapter contract")
    for name in (
        "supported_platforms",
        "supported_agent_versions",
        "lifecycle_operations",
    ):
        if not isinstance(payload[name], (list, tuple)):
            raise ContextContractError(f"{name} must be an ordered array")
    return AgentAdapterContractV1(
        adapter_id=payload["adapter_id"],  # type: ignore[arg-type]
        adapter_version=payload["adapter_version"],  # type: ignore[arg-type]
        supported_platforms=tuple(payload["supported_platforms"]),  # type: ignore[arg-type]
        supported_agent_versions=tuple(payload["supported_agent_versions"]),  # type: ignore[arg-type]
        lifecycle_operations=tuple(payload["lifecycle_operations"]),  # type: ignore[arg-type]
        workspace_binding=payload["workspace_binding"],  # type: ignore[arg-type]
        exact_task_transport=payload["exact_task_transport"],  # type: ignore[arg-type]
        schema_version=payload["schema_version"],  # type: ignore[arg-type]
        sensitivity_classification=payload["sensitivity_classification"],  # type: ignore[arg-type]
    )


@runtime_checkable
class AgentAdapterV1(Protocol):
    adapter_contract: AgentAdapterContractV1

    def describe(self) -> AgentAdapterContractV1:
        ...
