from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, Sequence

from .candidate_evidence import CandidateEvidence


RANKER_PROTOCOL_VERSION = "1.0.0"


@dataclass(frozen=True)
class RankedCandidate:
    candidate_id: str
    normalized_path: str
    final_score: int
    final_rank: int
    evidence_hash: str
    role_hints: tuple[str, ...]


@dataclass(frozen=True)
class RankedCandidates:
    configuration_hash: str
    candidates: tuple[RankedCandidate, ...]


def rank(evidence: Sequence[CandidateEvidence], ranker_configuration: "RankerConfiguration") -> RankedCandidates:
    """Frozen B0 adapter over incumbent locator scores.

    B0 preserves the incumbent aggregate under the explicitly named
    ``compatibility_adjustment`` component while authority migrates. No ranked
    locator output is accepted.
    """
    ranker_configuration.validate()
    if not all(isinstance(item, CandidateEvidence) for item in evidence):
        raise TypeError("RankerProtocolV1 accepts CandidateEvidence only")
    ids = [item.candidate_id for item in evidence]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate candidate evidence identity")
    records = list(evidence)
    records.sort(key=lambda item: (-sum(int(value) for value in item.score_components.values()), item.normalized_path.casefold(), item.normalized_path))
    return RankedCandidates(
        configuration_hash=ranker_configuration.configuration_hash,
        candidates=tuple(
            RankedCandidate(
                item.candidate_id,
                item.normalized_path,
                sum(int(value) for value in item.score_components.values()),
                index,
                item.evidence_hash,
                item.role_hints,
            )
            for index, item in enumerate(records, start=1)
        ),
    )


@dataclass(frozen=True)
class RankerConfiguration:
    schema_version: str
    strategy_id: str
    weights: Mapping[str, object]
    relation_bonuses: Mapping[str, object]
    ambiguity_penalties: Mapping[str, int]
    confidence_thresholds: Mapping[str, int]
    path_budgets: Mapping[str, int]
    generated_intent_policy: str
    fallback_policy: str

    def validate(self) -> None:
        if self.schema_version != "ranker_configuration.v1":
            raise ValueError("unsupported ranker configuration schema")
        if not self.strategy_id:
            raise ValueError("strategy_id is required")
        required_thresholds = {"primary_viable_score", "primary_high_score", "narrow_margin_basis_points", "support_qualified_score"}
        if not required_thresholds.issubset(self.confidence_thresholds):
            raise ValueError("ranker confidence thresholds are incomplete")
        required_budgets = {"narrow_primary", "narrow_verification", "narrow_support", "broad_primary", "broad_verification", "broad_support"}
        if not required_budgets.issubset(self.path_budgets):
            raise ValueError("ranker path budgets are incomplete")
        if any(int(value) < 0 for value in [*self.confidence_thresholds.values(), *self.path_budgets.values()]):
            raise ValueError("ranker thresholds and budgets must be non-negative")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "weights": dict(sorted(self.weights.items())),
            "relation_bonuses": dict(sorted(self.relation_bonuses.items())),
            "ambiguity_penalties": dict(sorted(self.ambiguity_penalties.items())),
            "confidence_thresholds": dict(sorted(self.confidence_thresholds.items())),
            "path_budgets": dict(sorted(self.path_budgets.items())),
            "generated_intent_policy": self.generated_intent_policy,
            "fallback_policy": self.fallback_policy,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def configuration_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


B0_ROUTING_BASE_V1 = RankerConfiguration(
    schema_version="ranker_configuration.v1",
    strategy_id="B0_ROUTING_BASE_V1",
    weights={"incumbent_locator": 1},
    relation_bonuses={"incumbent": True},
    ambiguity_penalties={"duplicate_basename": 10000, "cross_package": 6000, "generated_uncertainty": 8000, "repository_wide": 10000},
    confidence_thresholds={"primary_viable_score": 240, "primary_high_score": 420, "narrow_margin_basis_points": 3500, "support_qualified_score": 180},
    path_budgets={"narrow_primary": 2, "narrow_verification": 2, "narrow_support": 1, "broad_primary": 5, "broad_verification": 3, "broad_support": 3},
    generated_intent_policy="qualified_explicit_or_resolved",
    fallback_policy="fail_closed_abstain",
)
B0_ROUTING_BASE_V1.validate()
