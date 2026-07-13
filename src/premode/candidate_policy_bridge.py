"""Content-free subprocess bridge to the production candidate policy.

The observer is packaged separately from :mod:`premode`.  This module keeps the
policy authority on the production side of that boundary while returning only
bounded path classifications and hashes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from .candidate_policy import CandidateIntent, classify_candidate


BRIDGE_SCHEMA_VERSION = "candidate-policy-bridge.v1"
POLICY_VERSION = "candidate-admissibility.v1"
MAX_PATHS = 256


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classify_packet_paths(repo_root: Path, requests: list[dict[str, Any]]) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=True)
    if len(requests) > MAX_PATHS:
        raise ValueError(f"at most {MAX_PATHS} packet paths may be classified")
    decisions: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, dict) or not isinstance(request.get("path"), str):
            raise ValueError("every request must contain a string path")
        intent_value = request.get("intent") if isinstance(request.get("intent"), dict) else {}
        intent = CandidateIntent(
            explicit=bool(intent_value.get("explicit")),
            generated_required=bool(intent_value.get("generated_required")),
            support_only=bool(intent_value.get("support_only")),
        )
        decision = classify_candidate(
            root,
            request["path"],
            intent=intent,
            provenance=("observer_recommendation_safety",),
        )
        decisions.append(
            {
                "request_index": len(decisions),
                "normalized_path": decision.normalized_path,
                "classification": decision.classification.value,
                "admitted": decision.admitted,
                "editable": decision.editable,
                "reason": decision.reason,
            }
        )
    bridge_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    policy_digest = hashlib.sha256(Path(__file__).with_name("candidate_policy.py").read_bytes()).hexdigest()
    request_hash = _canonical_hash(requests)
    policy_state = {
        "policy_version": POLICY_VERSION,
        "bridge_digest": bridge_digest,
        "policy_digest": policy_digest,
        "request_hash": request_hash,
        "decisions": decisions,
    }
    return {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "evidence_complete": len(decisions) == len(requests),
        "request_count": len(requests),
        "request_hash": request_hash,
        "bridge_digest": bridge_digest,
        "policy_digest": policy_digest,
        "decisions": decisions,
        "policy_state_hash": _canonical_hash(policy_state),
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        root = payload.get("repo_root")
        requests = payload.get("requests")
        if not isinstance(root, str) or not isinstance(requests, list):
            raise ValueError("repo_root and requests are required")
        result = classify_packet_paths(Path(root), requests)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "evidence_complete": False,
            "error_type": type(exc).__name__,
            "error_code": "POLICY_CLASSIFICATION_FAILED",
        }
        json.dump(result, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 2
    json.dump(result, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
