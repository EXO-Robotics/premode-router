from __future__ import annotations

"""Sole normal production orchestration authority for Routing Base V1."""

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .candidate_materializer import RepositoryInventory, materialize_candidates
from .locator import LocateResult, locate_files, locate_media_files
from .ranker_protocol import B0_ROUTING_BASE_V1, RankedCandidates, RankerConfiguration
from .routing_decision import decide_routing, render_model_request, routing_decision_metadata, routing_input_from_ranked, validate_packet_projection
from .task_intent import compute_task_intent


ROUTING_BASE_VERSION = "1.0.0"
AUTHORITY_ID = "normal_routing_authority.v1"


def _authority_receipt(
    *,
    intent_hash: str,
    materialized_ids: list[str],
    evidence_hashes: list[str],
    ranked: RankedCandidates,
    packet_source: str,
) -> dict[str, object]:
    payload = {
        "authority_id": AUTHORITY_ID,
        "routing_base_version": ROUTING_BASE_VERSION,
        "task_intent_sha256": intent_hash,
        "materialized_candidate_ids": materialized_ids,
        "candidate_evidence_hashes": evidence_hashes,
        "ranked_candidate_ids": [item.candidate_id for item in ranked.candidates],
        "ranker_configuration_hash": ranked.configuration_hash,
        "packet_source": packet_source,
    }
    canonical = repr(sorted(payload.items())).encode("utf-8")
    return {**payload, "receipt_sha256": hashlib.sha256(canonical).hexdigest()}


def compile_routing_base(
    repository_root: Path,
    exact_task: str,
    *,
    ranker_configuration: RankerConfiguration = B0_ROUTING_BASE_V1,
    inventory_paths: list[str] | None = None,
    max_files: int = 8,
    save: bool = False,
) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=False)
    task = str(exact_task)
    intent = compute_task_intent(task)
    inventory = RepositoryInventory.capture(root, inventory_paths)
    materialization = materialize_candidates(task, intent, inventory)
    admissible_shape_paths = [item.normalized_path for item in materialization.admitted]
    context_selection_mode = "routing_base_v1"
    compile_degraded = False
    compile_degraded_reason = None
    large_repo_safety = None

    if intent.media_lookup_intent:
        located = locate_media_files(
            root,
            task,
            max_files=max_files,
            inventory_paths=inventory_paths,
            task_intent=intent,
            repository_inventory=inventory,
            materialization_result=materialization,
        )
        context_selection_mode = "asset_media_fast_path"
        large_repo_safety = {
            "schema_version": "large_repo_safety.v1",
            "context_selection_mode": context_selection_mode,
            "fallback_strategy": "metadata_only_media_lookup",
            "content_reads": 0,
            "asset_media_fast_path": {
                key: value for key, value in located.metadata.items() if not str(key).startswith("_")
            },
        }
    else:
        # The old compiler owns no routing decisions; only its frozen repository
        # shape arithmetic is retained as a compatibility helper.
        from . import compiler as legacy_shape

        shape = legacy_shape._repo_shape_from_inventory(None, admissible_shape_paths)
        if legacy_shape._large_repo_broad_degrade(task, shape):
            context_selection_mode = "large_repo_degraded"
            compile_degraded = True
            compile_degraded_reason = "large_repo_budget_exceeded"
            policy_records = [item.policy_result.to_metadata() for item in materialization.candidates]
            located = LocateResult([], [], [], "low", [], [], [compile_degraded_reason], metadata={
                "context_selection_mode": context_selection_mode,
                "content_reads": 0,
                "candidate_policy": {"records": policy_records},
                "candidate_provenance": policy_records,
                "candidate_evidence": [],
                "materialization_receipts": [
                    {"candidate_id": item.candidate_id, "normalized_path": item.normalized_path, "provenance_chain": list(item.provenance_chain), "policy_receipt": dict(item.policy_result.final_policy_receipt)}
                    for item in materialization.candidates
                ],
            }, ranked_candidates=RankedCandidates(ranker_configuration.configuration_hash, ()))
            large_repo_safety = legacy_shape._large_repo_safety_sidecar(
                repo_shape=shape,
                context_selection_mode=context_selection_mode,
                compile_degraded=True,
                compile_degraded_reason=compile_degraded_reason,
                fallback_strategy="json_only_structured_degrade",
            )
        else:
            located = locate_files(
                root,
                task,
                max_files=max_files,
                inventory_paths=inventory_paths,
                task_intent=intent,
                repository_inventory=inventory,
                materialization_result=materialization,
            )

    evidence_objects = tuple(located.candidate_evidence_objects)
    ranked_candidates = located.ranked_candidates
    if not isinstance(ranked_candidates, RankedCandidates):
        raise TypeError("normal routing requires RankedCandidates from CandidateEvidence")
    evidence_ids = {item.candidate_id for item in evidence_objects}
    materialized_ids = {item.candidate_id for item in materialization.admitted}
    for ranked in ranked_candidates.candidates:
        if ranked.candidate_id not in evidence_ids or ranked.candidate_id not in materialized_ids:
            raise ValueError("ranked candidate lineage invariant failed")

    routing_input = routing_input_from_ranked(located, ranked_candidates)
    decision = decide_routing(
        routing_input,
        task,
        task_intent=intent,
        ranker_configuration=ranker_configuration,
        strict_policy_closure=True,
    )
    packet = render_model_request(decision)
    if not validate_packet_projection(decision, packet):
        raise ValueError("canonical packet does not equal RoutingDecision projection")
    packet_source = "standard_passthrough" if decision.mode.value == "ABSTAIN" else "canonical_packet_v1"
    receipt = _authority_receipt(
        intent_hash=intent.exact_task_sha256,
        materialized_ids=[item.candidate_id for item in materialization.candidates],
        evidence_hashes=[item.evidence_hash for item in evidence_objects],
        ranked=ranked_candidates,
        packet_source=packet_source,
    )
    roles = {**{path: "primary" for path in decision.primary_paths}, **{path: "verification" for path in decision.verification_paths}, **{path: "support" for path in decision.support_paths}}
    evidence_metadata = []
    rank_by_id = {item.candidate_id: item.final_rank for item in ranked_candidates.candidates}
    for item in evidence_objects:
        payload = item.to_dict()
        payload["final_rank"] = rank_by_id.get(item.candidate_id)
        payload["selected_role"] = roles.get(item.normalized_path)
        payload["emitted_to_packet"] = item.normalized_path in roles
        evidence_metadata.append(payload)
    selected = list(decision.packet_projection.paths)
    result: dict[str, object] = {
        "routing_base_version": ROUTING_BASE_VERSION,
        "routing_authority_receipt": receipt,
        "packet_source": packet_source,
        "status": "compile_degraded" if compile_degraded else "compiled",
        "packet": packet,
        "compiled_packet_sha256": hashlib.sha256(packet.encode("utf-8")).hexdigest(),
        "packet_version": "canonical_packet.v1",
        "packet_variant": "paths_only",
        "canonical_core_packet": True,
        "routing_mode": decision.mode.value,
        "routing_decision": routing_decision_metadata(decision),
        "task_intent": intent.to_dict(),
        "candidate_policy": located.metadata.get("candidate_policy"),
        "candidate_provenance": evidence_metadata,
        "materialization_receipts": located.metadata.get("materialization_receipts") or [],
        "ranker_configuration_hash": ranker_configuration.configuration_hash,
        "model_facing_selected_paths": selected,
        "selected_paths": selected,
        "context_selection_mode": context_selection_mode,
        "large_repo_safety": large_repo_safety,
        "asset_media_fast_path": {key: value for key, value in located.metadata.items() if not str(key).startswith("_")} if context_selection_mode == "asset_media_fast_path" else None,
        "compile_degraded": compile_degraded,
        "compile_degraded_reason": compile_degraded_reason,
        "strategy_selected": ranker_configuration.strategy_id,
    }
    if save:
        out_dir = root / ".premode" / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        packet_path = out_dir / "last_packet.md"
        json_path = out_dir / "last_packet.json"
        receipt_path = out_dir / "last_routing_authority_receipt.json"
        packet_path.write_text(packet, encoding="utf-8")
        json_path.write_text(json.dumps({key: value for key, value in result.items() if key != "packet"}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["saved_artifacts"] = {
            "last_packet_md": str(packet_path),
            "last_packet_json": str(json_path),
            "last_routing_authority_receipt_json": str(receipt_path),
        }
    else:
        result["saved_artifacts"] = None
    return result
