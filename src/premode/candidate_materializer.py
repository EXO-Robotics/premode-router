from __future__ import annotations

"""Sole path-candidate creation authority for Routing Base V1."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .candidate_policy import CandidateAdmissibility, evaluate_candidate
from .ignore import IgnoreMatcher
from .task_intent import TaskIntentV1


MATERIALIZER_VERSION = "1.0.0"


@dataclass(frozen=True)
class RepositoryInventory:
    repository_root: Path
    paths: tuple[str, ...]
    source: str

    @classmethod
    def capture(cls, repository_root: Path, paths: Sequence[str] | None = None) -> "RepositoryInventory":
        root = Path(repository_root).resolve(strict=False)
        if paths is None:
            values = tuple(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
            source = "fallback_walk"
        else:
            values = tuple(map(str, paths))
            source = "inventory"
        return cls(root, values, source)


@dataclass(frozen=True)
class MaterializedCandidate:
    candidate_id: str
    original_path: str
    normalized_path: str
    provenance_sources: tuple[str, ...]
    provenance_chain: tuple[str, ...]
    first_source: str
    relation_parent: str | None
    raw_evidence_references: tuple[str, ...]
    explicit_path: bool
    generated_intent: bool
    support_relation: bool
    materialization_sequence: int
    policy_result: CandidateAdmissibility

    @property
    def admitted(self) -> bool:
        return self.policy_result.admitted


@dataclass(frozen=True)
class MaterializationResult:
    version: str
    inventory: RepositoryInventory
    candidates: tuple[MaterializedCandidate, ...]
    policy_results: tuple[CandidateAdmissibility, ...]

    @property
    def admitted(self) -> tuple[MaterializedCandidate, ...]:
        return tuple(item for item in self.candidates if item.admitted)


def _merge(existing: MaterializedCandidate, incoming: MaterializedCandidate) -> MaterializedCandidate:
    # A later merge cannot erase an earlier denial. Hard/conditional policy is
    # re-evaluated for every source, and any rejected receipt keeps the path out.
    policy = incoming.policy_result if not incoming.admitted else existing.policy_result
    return replace(
        existing,
        provenance_sources=tuple(dict.fromkeys((*existing.provenance_sources, *incoming.provenance_sources))),
        provenance_chain=tuple(dict.fromkeys((*existing.provenance_chain, *incoming.provenance_chain))),
        relation_parent=existing.relation_parent or incoming.relation_parent,
        raw_evidence_references=tuple(dict.fromkeys((*existing.raw_evidence_references, *incoming.raw_evidence_references))),
        explicit_path=existing.explicit_path or incoming.explicit_path,
        generated_intent=existing.generated_intent or incoming.generated_intent,
        support_relation=existing.support_relation or incoming.support_relation,
        policy_result=policy,
    )


def materialize_candidates(
    task: str,
    intent: TaskIntentV1,
    inventory: RepositoryInventory,
    repository_state: Mapping[str, object] | None = None,
    compatibility_inputs: Iterable[Mapping[str, object]] | None = None,
) -> MaterializationResult:
    root = inventory.repository_root
    state = dict(repository_state or {})
    state.setdefault("ignore_matcher", IgnoreMatcher.from_repo(root))
    context = intent.to_candidate_context()
    inputs: list[tuple[str, str, str | None, tuple[str, ...]]] = [
        (path, inventory.source, None, (f"{inventory.source}:{index}",))
        for index, path in enumerate(inventory.paths)
    ]
    inputs.extend((path, "explicit_prompt_path", None, ("task_intent.explicit_path",)) for path in intent.explicit_paths)
    for item in compatibility_inputs or ():
        path = str(item.get("path") or item.get("normalized_path") or "")
        if path:
            inputs.append((path, "legacy_adapter", str(item.get("relation_parent") or "") or None, ("compatibility_input",)))

    by_path: dict[str, MaterializedCandidate] = {}
    policies: list[CandidateAdmissibility] = []
    for sequence, (path, source, parent, refs) in enumerate(inputs):
        policy = evaluate_candidate(root, path, source, context, state)
        policies.append(policy)
        candidate = MaterializedCandidate(
            candidate_id=policy.candidate_id,
            original_path=path,
            normalized_path=policy.normalized_path,
            provenance_sources=(source,),
            provenance_chain=policy.provenance_chain,
            first_source=source,
            relation_parent=parent,
            raw_evidence_references=refs,
            explicit_path=policy.explicit_path,
            generated_intent=policy.generated_intent,
            support_relation=policy.support_only,
            materialization_sequence=sequence,
            policy_result=policy,
        )
        key = candidate.normalized_path.casefold()
        by_path[key] = _merge(by_path[key], candidate) if key in by_path else candidate
    ordered = tuple(sorted(by_path.values(), key=lambda item: (item.materialization_sequence, item.normalized_path.casefold(), item.normalized_path)))
    return MaterializationResult(MATERIALIZER_VERSION, inventory, ordered, tuple(policies))


def materialize_relation_candidate(
    base: MaterializedCandidate,
    *,
    relation_source: str,
    relation_parent: str,
    raw_evidence_reference: str,
    task: str,
    intent: TaskIntentV1,
    inventory: RepositoryInventory,
    repository_state: Mapping[str, object] | None = None,
) -> MaterializedCandidate:
    state = dict(repository_state or {})
    state.setdefault("ignore_matcher", IgnoreMatcher.from_repo(inventory.repository_root))
    policy = evaluate_candidate(
        inventory.repository_root,
        base.normalized_path,
        relation_source,
        intent.to_candidate_context(support_only=relation_source == "support_relation"),
        state,
    )
    related = MaterializedCandidate(
        candidate_id=policy.candidate_id,
        original_path=base.original_path,
        normalized_path=policy.normalized_path,
        provenance_sources=(relation_source,),
        provenance_chain=tuple(dict.fromkeys((*base.provenance_chain, relation_source))),
        first_source=base.first_source,
        relation_parent=relation_parent,
        raw_evidence_references=tuple(dict.fromkeys((*base.raw_evidence_references, raw_evidence_reference))),
        explicit_path=base.explicit_path,
        generated_intent=base.generated_intent,
        support_relation=relation_source == "support_relation",
        materialization_sequence=base.materialization_sequence,
        policy_result=policy,
    )
    return _merge(base, related)


def materialize_signal_candidate(
    base: MaterializedCandidate,
    *,
    source: str,
    raw_evidence_reference: str,
    intent: TaskIntentV1,
    inventory: RepositoryInventory,
) -> MaterializedCandidate:
    policy = evaluate_candidate(
        inventory.repository_root,
        base.normalized_path,
        source,
        intent.to_candidate_context(),
        {"ignore_matcher": IgnoreMatcher.from_repo(inventory.repository_root)},
    )
    event = MaterializedCandidate(
        candidate_id=policy.candidate_id,
        original_path=base.original_path,
        normalized_path=policy.normalized_path,
        provenance_sources=(source,),
        provenance_chain=(source,),
        first_source=base.first_source,
        relation_parent=None,
        raw_evidence_references=(raw_evidence_reference,),
        explicit_path=base.explicit_path,
        generated_intent=base.generated_intent,
        support_relation=False,
        materialization_sequence=base.materialization_sequence,
        policy_result=policy,
    )
    return _merge(base, event)
