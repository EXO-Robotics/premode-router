"""Stable product-facing ranking contract.

This module deliberately knows nothing about ranking implementations, observers,
or experiment identities. Providers receive the exact task and return only the
bounded path guidance consumed by the canonical packet renderer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any, Mapping, Protocol, runtime_checkable


PRODUCTION_RANKING_PROVIDER_VERSION = "production-ranking-provider.v1"
PRODUCTION_RANKING_RESULT_SCHEMA_VERSION = "pcodex.production-ranking-result.v1"
ROUTING_MODES = frozenset({"narrow", "broad", "fallback", "abstain"})
PUBLIC_ABSTENTION_REASONS = frozenset({
    "conservative_safety_boundary",
    "insufficient_path_evidence",
    "provider_declined",
    "unsupported_task_class",
})
FORBIDDEN_PUBLIC_IDENTITY_TERMS = ("candidate", "experiment", "observer", "qwen", "d3", "c2")


class ProductionRankingContractError(ValueError):
    pass


class UnknownProviderVersionError(ProductionRankingContractError):
    pass


def _paths(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ProductionRankingContractError(f"{field} must be an ordered array")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ProductionRankingContractError(f"{field} entries must be non-empty strings")
        path = value.strip()
        key = path.casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


@dataclass(frozen=True)
class ProductionRankingRequestV1:
    exact_task: str
    resolved_repository_context: Mapping[str, Any]
    supported_execution_options: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.exact_task, str):
            raise ProductionRankingContractError("exact_task must be a string")
        if not isinstance(self.resolved_repository_context, Mapping):
            raise ProductionRankingContractError("resolved_repository_context must be a mapping")
        if not isinstance(self.supported_execution_options, Mapping):
            raise ProductionRankingContractError("supported_execution_options must be a mapping")


@dataclass(frozen=True)
class ProductionRankingDecisionReceiptV1:
    exact_task_sha256: str
    routing_mode: str
    primary_path_count: int
    verify_path_count: int
    support_path_count: int
    source_contract: str
    schema_version: str = "pcodex.production-ranking-decision-receipt.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "pcodex.production-ranking-decision-receipt.v1":
            raise ProductionRankingContractError("unsupported decision_receipt schema_version")
        if re.fullmatch(r"[0-9a-f]{64}", self.exact_task_sha256) is None:
            raise ProductionRankingContractError("decision_receipt exact_task_sha256 must be SHA-256")
        if self.routing_mode not in ROUTING_MODES:
            raise ProductionRankingContractError("decision_receipt has unsupported routing_mode")
        for field in ("primary_path_count", "verify_path_count", "support_path_count"):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ProductionRankingContractError(f"decision_receipt {field} must be a non-negative integer")
        if not isinstance(self.source_contract, str) or re.fullmatch(r"[a-z0-9][a-z0-9._-]*", self.source_contract) is None:
            raise ProductionRankingContractError("decision_receipt source_contract must be a public-safe identifier")
        lowered_source = self.source_contract.casefold()
        if any(term in lowered_source for term in FORBIDDEN_PUBLIC_IDENTITY_TERMS):
            raise ProductionRankingContractError("decision_receipt source_contract exposes a non-product identity")


def _receipt(value: object) -> ProductionRankingDecisionReceiptV1:
    if isinstance(value, ProductionRankingDecisionReceiptV1):
        return value
    if not isinstance(value, Mapping):
        raise ProductionRankingContractError("decision_receipt must be a versioned receipt object")
    allowed = {
        "schema_version", "exact_task_sha256", "routing_mode", "primary_path_count",
        "verify_path_count", "support_path_count", "source_contract",
    }
    if set(value) != allowed:
        raise ProductionRankingContractError("decision_receipt contains missing or unsupported fields")
    return ProductionRankingDecisionReceiptV1(
        schema_version=str(value["schema_version"]),
        exact_task_sha256=str(value["exact_task_sha256"]),
        routing_mode=str(value["routing_mode"]),
        primary_path_count=value["primary_path_count"],  # type: ignore[arg-type]
        verify_path_count=value["verify_path_count"],  # type: ignore[arg-type]
        support_path_count=value["support_path_count"],  # type: ignore[arg-type]
        source_contract=str(value["source_contract"]),
    )


@dataclass(frozen=True)
class ProductionRankingResultV1:
    routing_mode: str
    primary_paths: tuple[str, ...]
    verify_paths: tuple[str, ...]
    support_paths: tuple[str, ...]
    abstention_reason: str | None
    decision_receipt: ProductionRankingDecisionReceiptV1 | Mapping[str, Any]
    provider_version: str = PRODUCTION_RANKING_PROVIDER_VERSION
    schema_version: str = PRODUCTION_RANKING_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.provider_version != PRODUCTION_RANKING_PROVIDER_VERSION:
            raise UnknownProviderVersionError(f"unsupported provider_version: {self.provider_version}")
        if self.schema_version != PRODUCTION_RANKING_RESULT_SCHEMA_VERSION:
            raise ProductionRankingContractError(f"unsupported schema_version: {self.schema_version}")
        if self.routing_mode not in ROUTING_MODES:
            raise ProductionRankingContractError(f"unsupported routing_mode: {self.routing_mode}")
        object.__setattr__(self, "primary_paths", _paths(self.primary_paths, "primary_paths"))
        object.__setattr__(self, "verify_paths", _paths(self.verify_paths, "verify_paths"))
        object.__setattr__(self, "support_paths", _paths(self.support_paths, "support_paths"))
        if self.routing_mode == "abstain" and self.abstention_reason not in PUBLIC_ABSTENTION_REASONS:
            raise ProductionRankingContractError("abstain results require a public-safe abstention_reason")
        if self.routing_mode == "abstain" and (self.primary_paths or self.verify_paths or self.support_paths):
            raise ProductionRankingContractError("abstain results cannot contain path guidance")
        if self.routing_mode != "abstain" and self.abstention_reason is not None:
            raise ProductionRankingContractError("abstention_reason is valid only for abstain results")
        receipt = _receipt(self.decision_receipt)
        if receipt.routing_mode != self.routing_mode:
            raise ProductionRankingContractError("decision_receipt routing_mode mismatch")
        if (
            receipt.primary_path_count != len(self.primary_paths)
            or receipt.verify_path_count != len(self.verify_paths)
            or receipt.support_path_count != len(self.support_paths)
        ):
            raise ProductionRankingContractError("decision_receipt path counts mismatch")
        object.__setattr__(self, "decision_receipt", receipt)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "routing_mode": self.routing_mode,
            "primary_paths": list(self.primary_paths),
            "verify_paths": list(self.verify_paths),
            "support_paths": list(self.support_paths),
            "abstention_reason": self.abstention_reason,
            "decision_receipt": asdict(_receipt(self.decision_receipt)),
            "provider_version": self.provider_version,
        }


@runtime_checkable
class ProductionRankingProviderV1(Protocol):
    provider_version: str

    def rank(self, request: ProductionRankingRequestV1) -> ProductionRankingResultV1:
        ...


def ranking_result_from_dict(payload: Mapping[str, Any]) -> ProductionRankingResultV1:
    if payload.get("provider_version") != PRODUCTION_RANKING_PROVIDER_VERSION:
        raise UnknownProviderVersionError(f"unsupported provider_version: {payload.get('provider_version')}")
    return ProductionRankingResultV1(
        schema_version=str(payload.get("schema_version") or ""),
        routing_mode=str(payload.get("routing_mode") or ""),
        primary_paths=_paths(payload.get("primary_paths"), "primary_paths"),
        verify_paths=_paths(payload.get("verify_paths"), "verify_paths"),
        support_paths=_paths(payload.get("support_paths"), "support_paths"),
        abstention_reason=payload.get("abstention_reason") if isinstance(payload.get("abstention_reason"), str) else None,
        decision_receipt=_receipt(payload.get("decision_receipt")),
        provider_version=str(payload["provider_version"]),
    )


def rank_with_provider(
    provider: ProductionRankingProviderV1,
    request: ProductionRankingRequestV1,
) -> ProductionRankingResultV1:
    if getattr(provider, "provider_version", None) != PRODUCTION_RANKING_PROVIDER_VERSION:
        raise UnknownProviderVersionError(
            f"unsupported provider_version: {getattr(provider, 'provider_version', None)}"
        )
    result = provider.rank(request)
    if result.provider_version != provider.provider_version:
        raise ProductionRankingContractError("provider/result version mismatch")
    if result.decision_receipt.exact_task_sha256 != hashlib.sha256(request.exact_task.encode("utf-8")).hexdigest():  # type: ignore[union-attr]
        raise ProductionRankingContractError("decision_receipt exact-task hash mismatch")
    return result
