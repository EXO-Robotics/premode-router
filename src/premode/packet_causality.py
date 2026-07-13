from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Literal


TRACE_SCHEMA = "packet-causality-trace.v1"
COMPARISON_SCHEMA = "packet-causality-comparison.v1"

METADATA_ONLY = "METADATA_ONLY"
CONFIDENCE_CHANGED_MODE_UNCHANGED = "CONFIDENCE_CHANGED_MODE_UNCHANGED"
AMBIGUITY_CHANGED_MODE_UNCHANGED = "AMBIGUITY_CHANGED_MODE_UNCHANGED"
RANK_CHANGED_MEMBERSHIP_STABLE = "RANK_CHANGED_MEMBERSHIP_STABLE"
SCORE_CHANGED_RANK_STABLE = "SCORE_CHANGED_RANK_STABLE"
BELOW_PRESELECTION_CUT = "BELOW_PRESELECTION_CUT"
RELATION_TARGET_UNREACHABLE = "RELATION_TARGET_UNREACHABLE"
ROLE_CHANGED_PROJECTION_STABLE = "ROLE_CHANGED_PROJECTION_STABLE"
SUPPORT_CHANGED_BUDGET_CUT = "SUPPORT_CHANGED_BUDGET_CUT"
PATH_REMOVED_BY_DEDUP = "PATH_REMOVED_BY_DEDUP"
MODE_CHANGED_PACKET_EQUIVALENT = "MODE_CHANGED_PACKET_EQUIVALENT"
PACKET_PROJECTION_CHANGED = "PACKET_PROJECTION_CHANGED"
PACKET_BYTES_CHANGED = "PACKET_BYTES_CHANGED"
UNEXPECTED_PACKET_CHANGE = "UNEXPECTED_PACKET_CHANGE"

ComparisonClass = Literal[
    "TARGET_EFFECTIVE",
    "CONTROL_STABLE",
    "INERT",
    "UNEXPECTED_EFFECT",
    "STATICALLY_UNSAFE",
]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: Any) -> str:
    payload = value if isinstance(value, bytes) else _canonical_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def _clean_path(value: Any) -> str | None:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or ".." in PurePosixPath(raw).parts:
        return None
    return PurePosixPath(raw).as_posix()


def _paths(values: Any, *, limit: int = 64) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values if isinstance(values, (list, tuple)) else []:
        value = raw.get("path") if isinstance(raw, dict) else raw
        path = _clean_path(value)
        key = path.casefold() if path else ""
        if path and key not in seen:
            result.append(path)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _stage(value: Any, *, paths: list[str] | None = None, count: int | None = None) -> dict[str, Any]:
    return {
        "sha256": _sha(value),
        "count": int(count if count is not None else len(paths or [])),
        "paths": list(paths or [])[:32],
    }


def _locator_rows(locator: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role, key in (("primary", "primary_files"), ("verification", "verification_files"), ("support", "support_files")):
        for item in locator.get(key) or []:
            if not isinstance(item, dict):
                continue
            path = _clean_path(item.get("path"))
            if not path:
                continue
            rows.append({
                "path": path,
                "role": role,
                "score": int(item.get("score") or 0),
                "confidence": str(item.get("confidence") or ""),
                "signals": sorted(str(signal) for signal in item.get("matched_signals") or []),
            })
    return rows


def _ledger_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = manifest.get("file_decision_ledger") if isinstance(manifest.get("file_decision_ledger"), dict) else {}
    rows: list[dict[str, Any]] = []
    for item in ledger.get("records") or []:
        if not isinstance(item, dict):
            continue
        path = _clean_path(item.get("path"))
        if not path:
            continue
        rows.append({
            "path": path,
            "eligible": bool(item.get("eligible")),
            "skipped": bool(item.get("skipped")),
            "role": str(item.get("role_classification") or ""),
            "score": int(item.get("raw_score") or 0),
            "bucket": str(item.get("final_bucket") or ""),
            "candidate": bool(item.get("candidate")),
            "verification": bool(item.get("verification")),
            "support": bool(item.get("support")),
        })
    return rows


def _projection(routing: dict[str, Any], packet: str) -> dict[str, Any]:
    mode = str(routing.get("mode") or "abstain")
    instruction = ""
    if mode != "abstain":
        lines = packet.rstrip("\n").splitlines()
        instruction = lines[-1] if lines else ""
    return {
        "mode": mode,
        "primary": _paths(routing.get("primary_paths")),
        "verification": _paths(routing.get("verification_paths")),
        "support": _paths(routing.get("support_paths")),
        "instruction_sha256": _sha(instruction.encode("utf-8")),
    }


def build_packet_causality_trace(manifest: dict[str, Any], packet: str) -> dict[str, Any]:
    """Build a task/source-content-free deterministic trace of one compilation."""
    ledger_rows = _ledger_rows(manifest)
    admitted = [row for row in ledger_rows if row["eligible"] and not row["skipped"]]
    locator = manifest.get("locator_evidence") if isinstance(manifest.get("locator_evidence"), dict) else {}
    locator_rows = _locator_rows(locator)
    relations = sorted(
        [
        {
            "source": _clean_path(item.get("source")),
            "target": _clean_path(item.get("target")),
            "relation": str(item.get("relation") or ""),
            "strength": int(item.get("strength") or 0),
        }
        for item in locator.get("dependency_relations") or []
        if isinstance(item, dict) and _clean_path(item.get("source")) and _clean_path(item.get("target"))
        ],
        key=lambda item: (item["source"], item["target"], item["relation"], item["strength"]),
    )
    backbone = manifest.get("tool_assisted_anchors_internal") if isinstance(manifest.get("tool_assisted_anchors_internal"), dict) else {}
    preselection = {
        "primary_before": _paths(backbone.get("primary_files_before")),
        "primary_after": _paths(backbone.get("primary_files_after") or backbone.get("primary_files")),
        "verification_before": _paths(backbone.get("related_tests_before")),
        "verification_after": _paths(backbone.get("related_tests_after") or backbone.get("related_tests")),
        "support": _paths(backbone.get("support_files")),
    }
    routing = manifest.get("routing_decision") if isinstance(manifest.get("routing_decision"), dict) else {}
    routing_summary = {
        "mode": str(routing.get("mode") or "abstain"),
        "confidence": str(routing.get("confidence") or "low"),
        "ambiguity": sorted(str(value) for value in routing.get("ambiguity_indicators") or []),
        "primary": _paths(routing.get("primary_paths")),
        "verification": _paths(routing.get("verification_paths")),
        "support": _paths(routing.get("support_paths")),
        "roles": sorted(
            (str(item.get("role") or ""), _clean_path(item.get("path")) or "")
            for item in routing.get("candidate_provenance") or []
            if isinstance(item, dict) and _clean_path(item.get("path"))
        ),
    }
    projection = _projection(routing, packet)
    ranked_stage = _stage(locator_rows, paths=[row["path"] for row in locator_rows], count=len(locator_rows))
    ranked_stage["score_sha256"] = _sha([(row["path"], row["role"], row["score"]) for row in locator_rows])
    stages = {
        "candidate_inventory": _stage(ledger_rows, paths=[row["path"] for row in ledger_rows], count=len(ledger_rows)),
        "admitted_candidates": _stage(admitted, paths=[row["path"] for row in admitted], count=len(admitted)),
        "candidate_evidence": _stage({"rows": locator_rows, "relations": relations}, paths=[row["path"] for row in locator_rows], count=len(locator_rows)),
        # locator_evidence preserves the selector's emitted within-role order.
        "ranked_candidates": ranked_stage,
        "preselection": _stage(preselection, paths=[*preselection["primary_after"], *preselection["verification_after"], *preselection["support"]]),
        "routing_decision": _stage(routing_summary, paths=[*routing_summary["primary"], *routing_summary["verification"], *routing_summary["support"]]),
        "packet_projection": _stage(projection, paths=[*projection["primary"], *projection["verification"], *projection["support"]]),
        "model_visible_packet": {"sha256": _sha(packet.encode("utf-8")), "bytes": len(packet.encode("utf-8"))},
    }
    trace: dict[str, Any] = {
        "schema_version": TRACE_SCHEMA,
        "exact_task_sha256": str(manifest.get("raw_prompt_sha256") or _sha(str(manifest.get("canonical_user_prompt") or "").encode("utf-8"))),
        "stages": stages,
        "routing_summary": routing_summary,
        "projection_summary": projection,
    }
    trace["trace_sha256"] = _sha(trace)
    return trace


def compare_packet_causality_traces(
    control: dict[str, Any],
    candidate: dict[str, Any],
    *,
    expectation: Literal["target", "control"] | None = None,
    statically_unsafe: bool = False,
) -> dict[str, Any]:
    if statically_unsafe:
        return {"schema_version": COMPARISON_SCHEMA, "classification": "STATICALLY_UNSAFE", "reason_codes": [], "packet_changed": False}
    left_stages = control.get("stages") or {}
    right_stages = candidate.get("stages") or {}
    packet_changed = (left_stages.get("model_visible_packet") or {}).get("sha256") != (right_stages.get("model_visible_packet") or {}).get("sha256")
    projection_changed = (left_stages.get("packet_projection") or {}).get("sha256") != (right_stages.get("packet_projection") or {}).get("sha256")
    reasons: list[str] = []
    left_route = control.get("routing_summary") or {}
    right_route = candidate.get("routing_summary") or {}
    if packet_changed:
        if projection_changed:
            reasons.append(PACKET_PROJECTION_CHANGED)
        else:
            reasons.append(UNEXPECTED_PACKET_CHANGE)
        reasons.append(PACKET_BYTES_CHANGED)
    else:
        if left_route.get("mode") != right_route.get("mode"):
            reasons.append(MODE_CHANGED_PACKET_EQUIVALENT)
        if left_route.get("confidence") != right_route.get("confidence") and left_route.get("mode") == right_route.get("mode"):
            reasons.append(CONFIDENCE_CHANGED_MODE_UNCHANGED)
        if left_route.get("ambiguity") != right_route.get("ambiguity") and left_route.get("mode") == right_route.get("mode"):
            reasons.append(AMBIGUITY_CHANGED_MODE_UNCHANGED)
        if left_route.get("roles") != right_route.get("roles") and not projection_changed:
            reasons.append(ROLE_CHANGED_PROJECTION_STABLE)
        left_ranked = left_stages.get("ranked_candidates") or {}
        right_ranked = right_stages.get("ranked_candidates") or {}
        left_ranked_paths = left_ranked.get("paths") or []
        right_ranked_paths = right_ranked.get("paths") or []
        rank_order_changed = left_ranked_paths != right_ranked_paths
        rank_membership_stable = sorted(path.casefold() for path in left_ranked_paths) == sorted(path.casefold() for path in right_ranked_paths)
        score_changed = left_ranked.get("score_sha256") != right_ranked.get("score_sha256")
        preselection_changed = (left_stages.get("preselection") or {}).get("sha256") != (right_stages.get("preselection") or {}).get("sha256")
        if rank_order_changed and rank_membership_stable and not preselection_changed:
            reasons.append(RANK_CHANGED_MEMBERSHIP_STABLE)
        if score_changed and not rank_order_changed:
            reasons.append(SCORE_CHANGED_RANK_STABLE)
        # BELOW_PRESELECTION_CUT, RELATION_TARGET_UNREACHABLE,
        # SUPPORT_CHANGED_BUDGET_CUT, and PATH_REMOVED_BY_DEDUP are reserved
        # until their pipeline stages expose explicit event receipts; aggregate
        # hashes cannot prove those causes.
        if not reasons:
            reasons.append(METADATA_ONLY)
    classification: ComparisonClass
    if expectation == "control":
        classification = "UNEXPECTED_EFFECT" if packet_changed else "CONTROL_STABLE"
    elif expectation == "target":
        classification = "TARGET_EFFECTIVE" if packet_changed else "INERT"
    else:
        classification = "TARGET_EFFECTIVE" if packet_changed else "INERT"
    return {
        "schema_version": COMPARISON_SCHEMA,
        "classification": classification,
        "reason_codes": list(dict.fromkeys(reasons)),
        "packet_changed": packet_changed,
        "projection_changed": projection_changed,
        "control_trace_sha256": control.get("trace_sha256"),
        "candidate_trace_sha256": candidate.get("trace_sha256"),
    }
