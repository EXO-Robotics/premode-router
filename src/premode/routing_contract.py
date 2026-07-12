from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Literal
from pathlib import Path

from .candidate_policy import CandidateIntent, classify_candidate, is_generated_candidate_path


RoutingMode = Literal["narrow", "broad", "abstain"]
CandidateRole = Literal["primary", "verification", "support"]
ConfidenceBand = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class CandidateEvidenceV1:
    schema_version: str
    path: str
    role: CandidateRole
    rank: int
    score: int
    confidence: ConfidenceBand
    matched_signals: tuple[str, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class RoutingDecisionV1:
    schema_version: str
    mode: RoutingMode
    primary_paths: tuple[str, ...]
    verification_paths: tuple[str, ...]
    support_paths: tuple[str, ...]
    confidence: ConfidenceBand
    ambiguity_indicators: tuple[str, ...]
    candidate_provenance: tuple[CandidateEvidenceV1, ...]
    decision_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        path = str(value or "").strip()
        key = path.casefold()
        if path and key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def _is_verification_path(path: str) -> bool:
    normalized = path.replace("\\", "/").casefold()
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized.startswith(("tests/", "test/", "spec/", "specs/"))
        or "/tests/" in normalized or "/test/" in normalized
        or name.startswith(("test_", "spec_"))
        or re.search(r"(?:^|[._-])(?:test|tests|spec|specs)(?:[._-]|$)", name) is not None
    )


def decision_from_manifest(repo_root: Path, manifest: dict[str, Any]) -> RoutingDecisionV1:
    locator = manifest.get("locator_evidence") if isinstance(manifest.get("locator_evidence"), dict) else {}
    backbone = manifest.get("tool_assisted_anchors_internal") if isinstance(manifest.get("tool_assisted_anchors_internal"), dict) else {}
    exact_task = str(manifest.get("canonical_user_prompt") or "")
    explicit_paths = {str(path).casefold() for path in __import__("re").findall(r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+(?![\w.-])", exact_task)}
    generated_intent = bool(__import__("re").search(r"(?i)\b(generated|vendor|dist|build output|generated code)\b", exact_task))
    def admitted(values: list[Any], provenance: str) -> tuple[str, ...]:
        accepted: list[str] = []
        for raw in values:
            path = str(raw or "")
            is_explicit = path.casefold() in explicit_paths
            decision = classify_candidate(repo_root, path, intent=CandidateIntent(explicit=is_explicit, generated_required=is_explicit and (generated_intent or is_generated_candidate_path(path))), provenance=(provenance,))
            if decision.admitted and decision.normalized_path:
                accepted.append(decision.normalized_path)
        return _unique(accepted)
    primary = admitted(list(backbone.get("primary_files_after") or backbone.get("primary_files") or []), "canonical_primary")
    verification = admitted(list(backbone.get("related_tests_after") or backbone.get("related_tests") or []), "canonical_verification")
    primary_verification = [path for path in primary if _is_verification_path(path)]
    primary = tuple(path for path in primary if not _is_verification_path(path))
    verification = _unique([*verification, *primary_verification])
    verification_keys = {path.casefold() for path in verification}
    primary = tuple(path for path in primary if path.casefold() not in verification_keys)
    primary_keys = {path.casefold() for path in primary}
    locator_support = [item for item in locator.get("support_files") or [] if isinstance(item, dict)]
    qualified_support: list[str] = []
    for item in locator_support:
        path = str(item.get("path") or "")
        signals = tuple(str(signal) for signal in item.get("matched_signals") or [])
        strong_relation = any(signal.startswith(("import_", "imported_by:", "source_test_", "shared_", "option_", "symbol:")) for signal in signals)
        is_explicit = path.casefold() in explicit_paths
        decision = classify_candidate(repo_root, path, intent=CandidateIntent(explicit=is_explicit, generated_required=is_explicit and (generated_intent or is_generated_candidate_path(path)), support_only=True), provenance=("support_relation",))
        if decision.admitted and decision.normalized_path and strong_relation and decision.normalized_path.casefold() not in primary_keys | verification_keys:
            qualified_support.append(decision.normalized_path)
    ambiguity = tuple(str(reason) for reason in locator.get("ambiguity_reasons") or [])
    raw_confidence = str(locator.get("confidence") or "low").lower()
    confidence: ConfidenceBand = raw_confidence if raw_confidence in {"low", "medium", "high"} else "low"  # type: ignore[assignment]
    evidence: list[CandidateEvidenceV1] = []
    rank = 0
    evidence_seen: set[tuple[str, str]] = set()
    for locator_role, items in (("primary", locator.get("primary_files") or []), ("verification", locator.get("verification_files") or []), ("support", locator_support)):
        for item in items:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            raw_path = str(item["path"])
            is_explicit = raw_path.casefold() in explicit_paths
            policy = classify_candidate(
                repo_root,
                raw_path,
                intent=CandidateIntent(
                    explicit=is_explicit,
                    generated_required=is_explicit and (generated_intent or is_generated_candidate_path(raw_path)),
                    support_only=False,
                ),
                provenance=(f"locator_{locator_role}",),
            )
            if not policy.admitted or not policy.normalized_path:
                continue
            normalized_key = policy.normalized_path.casefold()
            role: CandidateRole | None = (
                "primary" if normalized_key in primary_keys
                else "verification" if normalized_key in verification_keys
                else "support" if normalized_key in {path.casefold() for path in qualified_support}
                else None
            )
            if role is None or (role, normalized_key) in evidence_seen:
                continue
            evidence_seen.add((role, normalized_key))
            signals = tuple(str(signal) for signal in item.get("matched_signals") or [])
            evidence.append(CandidateEvidenceV1(
                schema_version="candidate-evidence.v1",
                path=policy.normalized_path, role=role, rank=rank,
                score=int(item.get("score") or 0), confidence=confidence,
                matched_signals=signals,
                provenance=tuple(dict.fromkeys([*policy.provenance, f"locator_{locator_role}", *[signal.split(":", 1)[0] for signal in signals]])),
            ))
            rank += 1
    selected_by_role = {
        "primary": {path.casefold() for path in primary},
        "verification": {path.casefold() for path in verification},
        "support": {path.casefold() for path in qualified_support},
    }
    # Locator confidence may only authorize paths that the canonical backbone
    # actually selected.  Keeping unrelated locator hits here would allow one
    # file's evidence to open a route for a different file.
    evidence = [candidate for candidate in evidence if candidate.path.casefold() in selected_by_role[candidate.role]]
    evidenced_primary = {candidate.path.casefold() for candidate in evidence if candidate.role == "primary"}
    primary = tuple(path for path in primary if path.casefold() in evidenced_primary)
    primary_keys = {path.casefold() for path in primary}
    strong_prefixes = ("explicit_path:", "prompt_mentioned", "symbol:", "symbol_term:", "filename_match:", "option_flag:", "behavior_source:", "source_test_relation:")
    strong_primary = any(
        candidate.role == "primary" and any(signal.startswith(strong_prefixes) for signal in candidate.matched_signals)
        for candidate in evidence
    )
    if any(path.casefold() in explicit_paths and path.casefold() in evidenced_primary for path in primary):
        strong_primary = True
    if not primary or (confidence == "low" and not strong_primary):
        return RoutingDecisionV1("routing-decision.v1", "abstain", (), (), (), confidence, ambiguity or ("insufficient_candidate_evidence",), tuple(evidence), ("no sufficiently supported primary path",))
    mode: RoutingMode = "narrow" if confidence == "high" and not ambiguity and len(primary) <= 2 else "broad"
    budget = 2 if mode == "narrow" else 4
    reasons = ("high-confidence bounded selection",) if mode == "narrow" else ("ambiguity or multi-surface evidence requires broader bounded context",)
    return RoutingDecisionV1("routing-decision.v1", mode, primary, verification, _unique(qualified_support)[:budget], confidence, ambiguity, tuple(evidence), reasons)
