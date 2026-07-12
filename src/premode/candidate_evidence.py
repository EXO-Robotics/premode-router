from __future__ import annotations

"""Authoritative pre-ranker evidence records for Routing Base V1."""

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Iterable, Mapping

from .candidate_materializer import MaterializedCandidate


CANDIDATE_EVIDENCE_VERSION = "1.0.0"


@dataclass(frozen=True)
class CandidateEvidence:
    version: str
    candidate_id: str
    normalized_path: str
    provenance: Mapping[str, object]
    final_policy_receipt: Mapping[str, object]
    task_evidence: tuple[str, ...]
    lexical_evidence: tuple[str, ...]
    explicit_path_evidence: tuple[str, ...]
    symbol_evidence: tuple[str, ...]
    literal_evidence: tuple[str, ...]
    path_evidence: tuple[str, ...]
    relation_evidence: tuple[str, ...]
    support_evidence: tuple[str, ...]
    generated_intent_evidence: tuple[str, ...]
    ambiguity_evidence: tuple[str, ...]
    score_components: Mapping[str, int]
    role_hints: tuple[str, ...]
    evidence_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "candidate_id": self.candidate_id,
            "normalized_path": self.normalized_path,
            "provenance": dict(self.provenance),
            "final_policy_receipt": dict(self.final_policy_receipt),
            "task_evidence": list(self.task_evidence),
            "lexical_evidence": list(self.lexical_evidence),
            "explicit_path_evidence": list(self.explicit_path_evidence),
            "symbol_evidence": list(self.symbol_evidence),
            "literal_evidence": list(self.literal_evidence),
            "path_evidence": list(self.path_evidence),
            "relation_evidence": list(self.relation_evidence),
            "support_evidence": list(self.support_evidence),
            "generated_intent_evidence": list(self.generated_intent_evidence),
            "ambiguity_evidence": list(self.ambiguity_evidence),
            "score_components": dict(sorted((str(k), int(v)) for k, v in self.score_components.items())),
            "role_hints": list(self.role_hints),
            "evidence_hash": self.evidence_hash,
        }


def _ordered(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _hash_payload(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_from_materialized(
    candidate: MaterializedCandidate,
    *,
    task_evidence: Iterable[str] = (),
    lexical_evidence: Iterable[str] = (),
    explicit_path_evidence: Iterable[str] = (),
    symbol_evidence: Iterable[str] = (),
    literal_evidence: Iterable[str] = (),
    path_evidence: Iterable[str] = (),
    relation_evidence: Iterable[str] = (),
    support_evidence: Iterable[str] = (),
    generated_intent_evidence: Iterable[str] = (),
    ambiguity_evidence: Iterable[str] = (),
    score_components: Mapping[str, int] | None = None,
    role_hints: Iterable[str] = (),
) -> CandidateEvidence:
    if not candidate.admitted:
        raise ValueError(f"hard/conditionally denied candidate cannot become evidence: {candidate.normalized_path}")
    provenance = {
        "original_path": candidate.original_path,
        "normalized_path": candidate.normalized_path,
        "provenance_sources": list(candidate.provenance_sources),
        "provenance_chain": list(candidate.provenance_chain),
        "first_source": candidate.first_source,
        "relation_parent": candidate.relation_parent,
        "raw_evidence_references": list(candidate.raw_evidence_references),
        "materialization_sequence": candidate.materialization_sequence,
        "explicit_path": candidate.explicit_path,
        "generated_intent": candidate.generated_intent,
        "support_relation": candidate.support_relation,
    }
    fields = {
        "version": CANDIDATE_EVIDENCE_VERSION,
        "candidate_id": candidate.candidate_id,
        "normalized_path": candidate.normalized_path,
        "provenance": provenance,
        "final_policy_receipt": dict(candidate.policy_result.final_policy_receipt),
        "task_evidence": list(_ordered(task_evidence)),
        "lexical_evidence": list(_ordered(lexical_evidence)),
        "explicit_path_evidence": list(_ordered(explicit_path_evidence)),
        "symbol_evidence": list(_ordered(symbol_evidence)),
        "literal_evidence": list(_ordered(literal_evidence)),
        "path_evidence": list(_ordered(path_evidence)),
        "relation_evidence": list(_ordered(relation_evidence)),
        "support_evidence": list(_ordered(support_evidence)),
        "generated_intent_evidence": list(_ordered(generated_intent_evidence)),
        "ambiguity_evidence": list(_ordered(ambiguity_evidence)),
        "score_components": dict(sorted((str(k), int(v)) for k, v in (score_components or {}).items())),
        "role_hints": list(_ordered(role_hints)),
    }
    return CandidateEvidence(
        version=CANDIDATE_EVIDENCE_VERSION,
        candidate_id=candidate.candidate_id,
        normalized_path=candidate.normalized_path,
        provenance=provenance,
        final_policy_receipt=candidate.policy_result.final_policy_receipt,
        task_evidence=_ordered(task_evidence),
        lexical_evidence=_ordered(lexical_evidence),
        explicit_path_evidence=_ordered(explicit_path_evidence),
        symbol_evidence=_ordered(symbol_evidence),
        literal_evidence=_ordered(literal_evidence),
        path_evidence=_ordered(path_evidence),
        relation_evidence=_ordered(relation_evidence),
        support_evidence=_ordered(support_evidence),
        generated_intent_evidence=_ordered(generated_intent_evidence),
        ambiguity_evidence=_ordered(ambiguity_evidence),
        score_components=dict(score_components or {}),
        role_hints=_ordered(role_hints),
        evidence_hash=_hash_payload(fields),
    )


class EvidenceRegistry:
    def __init__(self) -> None:
        self._records: dict[str, CandidateEvidence] = {}

    def add(self, record: CandidateEvidence) -> CandidateEvidence:
        current = self._records.get(record.candidate_id)
        if current is None:
            self._records[record.candidate_id] = record
            return record
        if current.normalized_path != record.normalized_path or current.final_policy_receipt != record.final_policy_receipt:
            raise ValueError("candidate evidence identity/policy collision")
        components = dict(current.score_components)
        for key, value in record.score_components.items():
            components[key] = int(components.get(key, 0)) + int(value)
        merged = replace(
            current,
            task_evidence=_ordered((*current.task_evidence, *record.task_evidence)),
            lexical_evidence=_ordered((*current.lexical_evidence, *record.lexical_evidence)),
            explicit_path_evidence=_ordered((*current.explicit_path_evidence, *record.explicit_path_evidence)),
            symbol_evidence=_ordered((*current.symbol_evidence, *record.symbol_evidence)),
            literal_evidence=_ordered((*current.literal_evidence, *record.literal_evidence)),
            path_evidence=_ordered((*current.path_evidence, *record.path_evidence)),
            relation_evidence=_ordered((*current.relation_evidence, *record.relation_evidence)),
            support_evidence=_ordered((*current.support_evidence, *record.support_evidence)),
            generated_intent_evidence=_ordered((*current.generated_intent_evidence, *record.generated_intent_evidence)),
            ambiguity_evidence=_ordered((*current.ambiguity_evidence, *record.ambiguity_evidence)),
            score_components=components,
            role_hints=_ordered((*current.role_hints, *record.role_hints)),
        )
        payload = merged.to_dict()
        payload.pop("evidence_hash", None)
        merged = replace(merged, evidence_hash=_hash_payload(payload))
        self._records[record.candidate_id] = merged
        return merged

    def values(self) -> tuple[CandidateEvidence, ...]:
        return tuple(sorted(self._records.values(), key=lambda item: (int(item.provenance.get("materialization_sequence", 0)), item.normalized_path.casefold(), item.normalized_path)))
