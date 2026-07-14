"""OpenClaw-specific authority policy isolated from general repository routing."""

from __future__ import annotations

from typing import Any


OPENCLAW_AUTHORITY_MARKERS: tuple[str, ...] = (
    "AGENTS.md",
    "WORKFLOW.md",
    "PROJECT/tasks.json",
    "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    "PROJECT/state/worker_start/WORKER_STARTER_CONTEXT_V1.json",
    "PROJECT/state/task_queue_normalized_latest.json",
    "PROJECT/state/path_authority_latest.json",
    "PROJECT/state/artifact_authority_latest.json",
    "PROJECT/AI/OUTPUT_HYGIENE_GUARDRAILS.md",
    "ARTIFACT_STORAGE.md",
    "EXTERNAL_ARTIFACTS_INDEX.md",
)

OPENCLAW_EVIDENCE_ONLY_PATTERNS: tuple[str, ...] = (
    "_claw_output/",
    "PROJECT/state/history/",
    "PROJECT/state/archive/",
    "PROJECT/artifacts/generated/",
    "logs/",
    "proof/",
    "proofs/",
)

OPENCLAW_DANGEROUS_MUTATION_ZONES: tuple[str, ...] = (
    "PROJECT/tasks.json",
    "PROJECT/state/task_queue_normalized_latest.json",
    "PROJECT/state/path_authority_latest.json",
    "PROJECT/state/artifact_authority_latest.json",
    "_claw_output/",
    "Content/",
    "*.uasset",
    "*.umap",
    "*.blend",
)

OPENCLAW_PROOF_POLICY: dict[str, bool] = {
    "do_not_claim_runtime_from_static_or_browser_evidence": True,
    "do_not_claim_collision_or_input_proof_without_same_run_evidence": True,
    "do_not_mutate_bridge_unreal_or_blender_without_authorization": True,
    "do_not_mutate_project_task_queue_without_authorization": True,
    "do_not_treat_historical_proof_as_current_truth": True,
    "human_review_required_for_public_synthesis": True,
}


def is_openclaw_authority_path(path: str) -> bool:
    lower = path.strip("/").lower()
    return any(lower == marker.lower() for marker in OPENCLAW_AUTHORITY_MARKERS)


def is_openclaw_evidence_only_path(path: str) -> bool:
    lower = path.strip("/").lower()
    return any(
        lower.startswith(pattern.lower())
        or (pattern.startswith("*") and lower.endswith(pattern[1:].lower()))
        for pattern in OPENCLAW_EVIDENCE_ONLY_PATTERNS
    )


def openclaw_policy_from_detection(detection: dict[str, Any]) -> dict[str, Any] | None:
    """Return policy only when the OpenClaw adapter was explicitly selected."""
    active = detection.get("active_project", {}) if isinstance(detection, dict) else {}
    if active.get("adapter") != "openclaw_control_plane":
        return None
    return {
        "authority_model": "proof_governed_control_plane",
        "authority_surfaces": list(OPENCLAW_AUTHORITY_MARKERS),
        "evidence_only_patterns": list(OPENCLAW_EVIDENCE_ONLY_PATTERNS),
        "dangerous_mutation_zones": list(OPENCLAW_DANGEROUS_MUTATION_ZONES),
        "proof_policy": dict(OPENCLAW_PROOF_POLICY),
        "notes": [
            "Current authority surfaces outrank historical/generated proof artifacts.",
            "Generated proof/log folders are evidence-only unless explicitly task-named.",
            "Bridge, Unreal, Blender, and task-queue mutation require explicit authorization.",
        ],
    }
