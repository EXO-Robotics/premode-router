from __future__ import annotations

"""The sole confidence, mode, support, and packet-projection authority for Routing Base V1."""

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable, Mapping

from .candidate_policy import CandidateAdmissibility, assert_final_admissibility
from .core_packet import CorePath, render_core_packet
from .locator import FileRelation, LocateResult, LocatedFile
from .ranker_protocol import B0_ROUTING_BASE_V1, RankedCandidates, RankerConfiguration
from .task_intent import TaskIntentV1, compute_task_intent


# Compatibility names for callers that previously imported fixed budgets.
NARROW_PRIMARY_BUDGET = int(B0_ROUTING_BASE_V1.path_budgets["narrow_primary"])
NARROW_VERIFICATION_BUDGET = int(B0_ROUTING_BASE_V1.path_budgets["narrow_verification"])
NARROW_SUPPORT_BUDGET = int(B0_ROUTING_BASE_V1.path_budgets["narrow_support"])
BROAD_PRIMARY_BUDGET = int(B0_ROUTING_BASE_V1.path_budgets["broad_primary"])
BROAD_VERIFICATION_BUDGET = int(B0_ROUTING_BASE_V1.path_budgets["broad_verification"])
BROAD_SUPPORT_BUDGET = int(B0_ROUTING_BASE_V1.path_budgets["broad_support"])


class RoutingMode(str, Enum):
    NARROW = "NARROW"
    BROAD = "BROAD"
    ABSTAIN = "ABSTAIN"


class SupportConfidence(str, Enum):
    STRONG = "STRONG"
    QUALIFIED = "QUALIFIED"
    WEAK = "WEAK"


class SupportAuthority(str, Enum):
    TASK_EXPLICIT = "TASK_EXPLICIT"
    DIRECT_RELATION = "DIRECT_RELATION"
    REPOSITORY_AUTHORITY = "REPOSITORY_AUTHORITY"
    PACKAGE_AUTHORITY = "PACKAGE_AUTHORITY"
    QUALIFIED_GLOBAL = "QUALIFIED_GLOBAL"
    WEAK_GLOBAL = "WEAK_GLOBAL"


@dataclass(frozen=True)
class ConfidenceDimensions:
    primary_confidence: int
    verification_confidence: int
    support_confidence: int
    ambiguity_penalty: int
    route_confidence: int
    primary_margin_basis_points: int
    primary_gate_passed: bool


@dataclass(frozen=True)
class SupportDecision:
    path: str
    role: str
    evidence: tuple[str, ...]
    confidence: SupportConfidence
    authority: SupportAuthority
    relation_to_primary: tuple[str, ...]
    provenance: tuple[object, ...] = ()
    admissibility: str = "admitted"
    emitted: bool = False


@dataclass(frozen=True)
class PacketProjection:
    exact_task: str
    primary_paths: tuple[str, ...] = ()
    verification_paths: tuple[str, ...] = ()
    support_paths: tuple[str, ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        return self.primary_paths + self.verification_paths + self.support_paths


@dataclass(frozen=True)
class RoutingDecision:
    mode: RoutingMode
    primary_paths: tuple[str, ...]
    verification_paths: tuple[str, ...]
    support_paths: tuple[str, ...]
    confidence: str
    ambiguity_flags: tuple[str, ...]
    reasons: tuple[str, ...]
    candidate_provenance: tuple[object, ...]
    packet_projection: PacketProjection
    support_decisions: tuple[SupportDecision, ...] = ()
    confidence_dimensions: ConfidenceDimensions | None = None
    final_policy_receipts: tuple[Mapping[str, object], ...] = ()
    ranker_configuration_hash: str = ""


@dataclass(frozen=True)
class RoutingInputV1:
    primary_files: tuple[LocatedFile, ...]
    verification_files: tuple[LocatedFile, ...]
    support_files: tuple[LocatedFile, ...]
    confidence: str
    covered_prompt_terms: tuple[str, ...]
    uncovered_prompt_terms: tuple[str, ...]
    ambiguity_reasons: tuple[str, ...]
    dependency_relations: tuple[FileRelation, ...]
    relation_degraded_reasons: tuple[str, ...]
    metadata: Mapping[str, object]
    ranked_candidates: RankedCandidates


def routing_input_from_ranked(result: LocateResult, ranked: RankedCandidates) -> RoutingInputV1:
    ranked_by_path = {item.normalized_path: item for item in ranked.candidates}
    for item in result.primary_files + result.verification_files + result.support_files:
        record = ranked_by_path.get(item.path)
        if record is None or int(record.final_score) != int(item.score):
            raise ValueError(f"RoutingInputV1 path is not derived from RankedCandidates: {item.path}")
    return RoutingInputV1(
        tuple(result.primary_files), tuple(result.verification_files), tuple(result.support_files),
        result.confidence, tuple(result.covered_prompt_terms), tuple(result.uncovered_prompt_terms),
        tuple(result.ambiguity_reasons), tuple(result.dependency_relations),
        tuple(result.relation_degraded_reasons), result.metadata, ranked,
    )


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        key = clean.casefold()
        if clean and key not in seen:
            out.append(clean)
            seen.add(key)
    return tuple(out)


def _score(items: Iterable[LocatedFile]) -> int:
    return max((max(0, int(item.score)) for item in items), default=0)


def _primary_margin(items: Iterable[LocatedFile]) -> int:
    scores = sorted((max(0, int(item.score)) for item in items), reverse=True)
    if not scores:
        return 0
    if len(scores) == 1:
        return 10_000
    return max(0, ((scores[0] - scores[1]) * 10_000) // max(1, scores[0]))


def _ambiguity_penalty(flags: Iterable[str], intent: TaskIntentV1, config: RankerConfiguration) -> int:
    penalty = 0
    combined = tuple(flags) + intent.ambiguity_flags
    for flag in combined:
        lower = flag.casefold()
        if "duplicate" in lower:
            penalty += int(config.ambiguity_penalties.get("duplicate_basename", 0))
        elif "cross_package" in lower or "cross-package" in lower:
            penalty += int(config.ambiguity_penalties.get("cross_package", 0))
        elif "generated" in lower:
            penalty += int(config.ambiguity_penalties.get("generated_uncertainty", 0))
        elif "repository_wide" in lower or "repository-wide" in lower:
            penalty += int(config.ambiguity_penalties.get("repository_wide", 0))
        else:
            penalty += 250
    return penalty


def _dimensions(result: LocateResult, intent: TaskIntentV1, config: RankerConfiguration) -> ConfidenceDimensions:
    primary = _score(result.primary_files)
    verification = _score(result.verification_files)
    support = _score(result.support_files)
    penalty = _ambiguity_penalty(result.ambiguity_reasons, intent, config)
    margin = _primary_margin(result.primary_files)
    viable = primary >= int(config.confidence_thresholds["primary_viable_score"])
    # Verification and support are deliberately excluded: they describe context
    # quality after the hard primary gate, never primary viability itself.
    return ConfidenceDimensions(primary, verification, support, penalty, max(0, primary - penalty), margin, viable)


def _related(path: str, primary: tuple[str, ...], relations: Iterable[FileRelation]) -> tuple[FileRelation, ...]:
    anchors = set(primary)
    return tuple(sorted((item for item in relations if (item.source in anchors and item.target == path) or (item.target in anchors and item.source == path)), key=lambda item: (-item.strength, item.relation, item.source, item.target)))


def _same_package(path: str, primary: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    if len(candidate.parts) < 2:
        return False
    parent = candidate.parent
    return any(parent == PurePosixPath(item).parent or parent in PurePosixPath(item).parents for item in primary)


def _support_authority(candidate: LocatedFile, primary: tuple[str, ...], relations: Iterable[FileRelation]) -> tuple[SupportAuthority, SupportConfidence, tuple[str, ...]]:
    signals = tuple(sorted(set(map(str, candidate.matched_signals))))
    related = _related(candidate.path, primary, relations)
    names = tuple(item.relation for item in related)
    if related and any(signal.startswith(("explicit_path:", "symbol:", "quoted_literal:", "option_flag:")) for signal in signals):
        return SupportAuthority.TASK_EXPLICIT, SupportConfidence.STRONG, names
    if related and any(item.strength >= 60 for item in related):
        return SupportAuthority.DIRECT_RELATION, SupportConfidence.STRONG, names
    if candidate.role == "config" and len(PurePosixPath(candidate.path).parts) == 1 and any(signal in {"build_config", "package_manifest", "command_surface", "cli_entrypoint"} or signal.startswith("option_flag:") for signal in signals):
        return SupportAuthority.REPOSITORY_AUTHORITY, SupportConfidence.STRONG, names
    if candidate.role == "config" and related and _same_package(candidate.path, primary) and signals:
        return SupportAuthority.PACKAGE_AUTHORITY, SupportConfidence.QUALIFIED, names
    evidence_kinds = {signal.split(":", 1)[0] for signal in signals if not signal.startswith(("role:", "negative_constraint:"))}
    if len(evidence_kinds) >= 2 and related:
        return SupportAuthority.QUALIFIED_GLOBAL, SupportConfidence.QUALIFIED, names
    return SupportAuthority.WEAK_GLOBAL, SupportConfidence.WEAK, names


def _provenance(result: LocateResult) -> tuple[object, ...]:
    raw = result.metadata.get("candidate_provenance", ())
    if isinstance(raw, (str, bytes, Mapping)):
        return (raw,)
    return tuple(raw) if isinstance(raw, Iterable) else ()


def _policy_record_map(result: LocateResult) -> dict[str, Mapping[str, object]]:
    records = ((result.metadata.get("candidate_policy") or {}).get("records") if isinstance(result.metadata.get("candidate_policy"), Mapping) else None) or ()
    return {str(item.get("normalized_path")): item for item in records if isinstance(item, Mapping) and item.get("normalized_path")}


def _validate_selected_policy(result: LocateResult, roles: Mapping[str, str], *, strict: bool) -> tuple[Mapping[str, object], ...]:
    records = _policy_record_map(result)
    receipts: list[Mapping[str, object]] = []
    for path, role in roles.items():
        record = records.get(path)
        if record is None:
            if strict:
                raise ValueError(f"selected candidate lacks final policy receipt: {path}")
            continue
        final = record.get("final_admissibility")
        allowed = {"ALLOW", "ALLOW_IF_EXPLICIT_SATISFIED", "SUPPORT_ONLY_QUALIFIED", "GENERATED_EXCEPTION_QUALIFIED"}
        if final not in allowed or (final == "SUPPORT_ONLY_QUALIFIED" and role != "support"):
            raise ValueError(f"selected candidate failed final policy closure: {path}")
        receipt = record.get("final_policy_receipt")
        if not isinstance(receipt, Mapping) or not receipt.get("receipt_sha256"):
            raise ValueError(f"selected candidate lacks an auditable policy receipt: {path}")
        receipts.append(receipt)
    return tuple(receipts)


def decide_routing(result: RoutingInputV1 | LocateResult, exact_task: str, *, task_intent: TaskIntentV1 | None = None, ranker_configuration: RankerConfiguration = B0_ROUTING_BASE_V1, strict_policy_closure: bool = True) -> RoutingDecision:
    if strict_policy_closure and isinstance(result, LocateResult):
        raise TypeError("RoutingDecisionV1 accepts RoutingInputV1 derived from RankedCandidates; use the explicit legacy adapter for LocateResult")
    task = str(exact_task)
    intent = task_intent or compute_task_intent(task)
    ranker_configuration.validate()
    dimensions = _dimensions(result, intent, ranker_configuration)
    ambiguity = _ordered_unique((*result.ambiguity_reasons, *intent.ambiguity_flags))
    severe = any(any(term in flag.casefold() for term in ("duplicate", "no_files", "no_transportable", "only_surface", "test_only", "repository_wide_without_target", "generated_intent_without_path")) for flag in ambiguity)
    reasons: list[str] = []
    if not dimensions.primary_gate_passed:
        mode = RoutingMode.ABSTAIN
        reasons.append("primary_confidence_below_minimum_viable_threshold")
    elif severe:
        mode = RoutingMode.ABSTAIN
        reasons.append("severe_unresolved_ambiguity")
    else:
        narrow = (
            dimensions.route_confidence >= int(ranker_configuration.confidence_thresholds["primary_high_score"])
            and dimensions.primary_margin_basis_points >= int(ranker_configuration.confidence_thresholds["narrow_margin_basis_points"])
            and dimensions.ambiguity_penalty <= 1_000
            and len(result.primary_files) <= int(ranker_configuration.path_budgets["narrow_primary"])
        )
        mode = RoutingMode.NARROW if narrow else RoutingMode.BROAD
        if narrow:
            reasons.append("concentrated_high_confidence_primary")
        else:
            if dimensions.primary_margin_basis_points < int(ranker_configuration.confidence_thresholds["narrow_margin_basis_points"]):
                reasons.append("rank_margin_below_narrow_threshold")
            if result.confidence != "high":
                reasons.append("primary_confidence_not_high")
            if ambiguity:
                reasons.append("bounded_ambiguity_present")
            if not reasons:
                reasons.append("viable_primary_with_distributed_evidence")
        if mode is RoutingMode.BROAD:
            qualified_support = any(
                _support_authority(item, _ordered_unique(value.path for value in result.primary_files), result.dependency_relations)[0]
                is not SupportAuthority.WEAK_GLOBAL
                for item in result.support_files
            )
            if not ambiguity and dimensions.verification_confidence < int(ranker_configuration.confidence_thresholds["support_qualified_score"]) and not qualified_support:
                mode = RoutingMode.ABSTAIN
                reasons = ["broad_route_lacks_distributed_or_qualified_context"]

    provenance = _provenance(result)
    if mode is RoutingMode.ABSTAIN:
        projection = PacketProjection(task)
        return RoutingDecision(mode, (), (), (), result.confidence, ambiguity, tuple(reasons), provenance, projection, confidence_dimensions=dimensions, ranker_configuration_hash=ranker_configuration.configuration_hash)

    prefix = "narrow" if mode is RoutingMode.NARROW else "broad"
    primary = _ordered_unique(item.path for item in result.primary_files)[: int(ranker_configuration.path_budgets[f"{prefix}_primary"])]
    occupied = {item.casefold() for item in primary}
    verification = _ordered_unique(item.path for item in result.verification_files if item.path.casefold() not in occupied)[: int(ranker_configuration.path_budgets[f"{prefix}_verification"])]
    occupied |= {item.casefold() for item in verification}
    support_records: list[tuple[LocatedFile, SupportAuthority, SupportConfidence, tuple[str, ...]]] = []
    for item in result.support_files:
        if item.path.casefold() in occupied:
            continue
        authority, confidence, relations = _support_authority(item, primary, result.dependency_relations)
        support_records.append((item, authority, confidence, relations))
    authority_rank = {value: index for index, value in enumerate(SupportAuthority)}
    support_records.sort(key=lambda item: (authority_rank[item[1]], -item[0].score, item[0].path.casefold(), item[0].path))
    narrow_allowed = {SupportAuthority.TASK_EXPLICIT, SupportAuthority.DIRECT_RELATION, SupportAuthority.REPOSITORY_AUTHORITY, SupportAuthority.PACKAGE_AUTHORITY}
    broad_allowed = narrow_allowed | {SupportAuthority.QUALIFIED_GLOBAL}
    allowed = narrow_allowed if mode is RoutingMode.NARROW else broad_allowed
    support = _ordered_unique(item.path for item, authority, confidence, _ in support_records if authority in allowed and (mode is RoutingMode.BROAD or confidence is SupportConfidence.STRONG))[: int(ranker_configuration.path_budgets[f"{prefix}_support"])]
    emitted = {item.casefold() for item in support}
    support_decisions = tuple(SupportDecision(item.path, item.role, tuple(sorted(set(item.matched_signals))), confidence, authority, relations, tuple(record for record in provenance if not isinstance(record, Mapping) or str(record.get("normalized_path") or record.get("path") or item.path) == item.path), emitted=item.path.casefold() in emitted) for item, authority, confidence, relations in support_records)
    roles = {**{path: "primary" for path in primary}, **{path: "verification" for path in verification}, **{path: "support" for path in support}}
    receipts = _validate_selected_policy(result, roles, strict=strict_policy_closure)
    projection = PacketProjection(task, primary, verification, support)
    return RoutingDecision(mode, primary, verification, support, result.confidence, ambiguity, tuple(reasons), provenance, projection, support_decisions, dimensions, receipts, ranker_configuration.configuration_hash)


def render_model_request(decision: RoutingDecision) -> str:
    if decision.mode is RoutingMode.ABSTAIN:
        return decision.packet_projection.exact_task
    projection = decision.packet_projection
    paths = tuple(CorePath(path, role="primary") for path in projection.primary_paths) + tuple(CorePath(path, role="verification") for path in projection.verification_paths) + tuple(CorePath(path, role="support") for path in projection.support_paths)
    return render_core_packet(projection.exact_task, paths)


def metadata_paths_equal_projection(decision: RoutingDecision, *, primary_paths: Iterable[str], verification_paths: Iterable[str], support_paths: Iterable[str]) -> bool:
    return tuple(primary_paths) == decision.packet_projection.primary_paths and tuple(verification_paths) == decision.packet_projection.verification_paths and tuple(support_paths) == decision.packet_projection.support_paths


def validate_packet_projection(decision: RoutingDecision, packet: str) -> bool:
    return decision.primary_paths == decision.packet_projection.primary_paths and decision.verification_paths == decision.packet_projection.verification_paths and decision.support_paths == decision.packet_projection.support_paths and packet == render_model_request(decision)


def routing_decision_metadata(decision: RoutingDecision) -> dict[str, object]:
    dimensions = decision.confidence_dimensions
    return {
        "mode": decision.mode.value, "confidence": decision.confidence,
        "ambiguity_flags": list(decision.ambiguity_flags), "reasons": list(decision.reasons),
        "primary_paths": list(decision.primary_paths), "verification_paths": list(decision.verification_paths), "support_paths": list(decision.support_paths),
        "confidence_dimensions": None if dimensions is None else dimensions.__dict__,
        "candidate_provenance": list(decision.candidate_provenance),
        "final_policy_receipts": [dict(item) for item in decision.final_policy_receipts],
        "ranker_configuration_hash": decision.ranker_configuration_hash,
        "support_decisions": [{"path": item.path, "role": item.role, "evidence": list(item.evidence), "confidence": item.confidence.value, "authority": item.authority.value, "relation_to_primary": list(item.relation_to_primary), "provenance": list(item.provenance), "admissibility": item.admissibility, "emitted": item.emitted} for item in decision.support_decisions],
        "packet_projection": {"exact_task": decision.packet_projection.exact_task, "primary_paths": list(decision.packet_projection.primary_paths), "verification_paths": list(decision.packet_projection.verification_paths), "support_paths": list(decision.packet_projection.support_paths)},
    }
