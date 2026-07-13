from __future__ import annotations

"""Compatibility adapter for the unchanged incumbent ranking implementation."""

import hashlib
from pathlib import Path
from typing import Any

from .production_ranking import (
    PRODUCTION_RANKING_PROVIDER_VERSION,
    ProductionRankingDecisionReceiptV1,
    ProductionRankingRequestV1,
    ProductionRankingResultV1,
)
from .routing_contract import decision_from_manifest


class IncumbentManifestRankingProviderV1:
    provider_version = PRODUCTION_RANKING_PROVIDER_VERSION

    def rank(self, request: ProductionRankingRequestV1) -> ProductionRankingResultV1:
        repo_root = Path(str(request.resolved_repository_context.get("repo_root") or ""))
        manifest = request.resolved_repository_context.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("resolved_repository_context.manifest must be an object")
        if str(manifest.get("canonical_user_prompt") or "") != request.exact_task:
            raise ValueError("resolved repository context changed exact_task")
        decision = decision_from_manifest(repo_root, manifest)
        reason = "insufficient_path_evidence" if decision.mode == "abstain" else None
        receipt = ProductionRankingDecisionReceiptV1(
            exact_task_sha256=hashlib.sha256(request.exact_task.encode("utf-8")).hexdigest(),
            routing_mode=decision.mode,
            primary_path_count=len(decision.primary_paths),
            verify_path_count=len(decision.verification_paths),
            support_path_count=len(decision.support_paths),
            source_contract=decision.schema_version,
        )
        return ProductionRankingResultV1(
            routing_mode=decision.mode,
            primary_paths=decision.primary_paths,
            verify_paths=decision.verification_paths,
            support_paths=decision.support_paths,
            abstention_reason=reason,
            decision_receipt=receipt,
        )
