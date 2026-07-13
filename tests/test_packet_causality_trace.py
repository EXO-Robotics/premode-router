from __future__ import annotations

import json

from premode.packet_causality import (
    AMBIGUITY_CHANGED_MODE_UNCHANGED,
    CONFIDENCE_CHANGED_MODE_UNCHANGED,
    PACKET_BYTES_CHANGED,
    PACKET_PROJECTION_CHANGED,
    RANK_CHANGED_MEMBERSHIP_STABLE,
    SCORE_CHANGED_RANK_STABLE,
    build_packet_causality_trace,
    compare_packet_causality_traces,
)


def _manifest(*, mode: str = "broad", confidence: str = "medium", ambiguity: list[str] | None = None, primary: list[str] | None = None) -> dict:
    primary = primary or ["src/app.py"]
    return {
        "raw_prompt_sha256": "a" * 64,
        "canonical_user_prompt": "private task bytes must not appear",
        "file_decision_ledger": {
            "records": [
                {
                    "path": path,
                    "eligible": True,
                    "skipped": False,
                    "role_classification": "source",
                    "raw_score": 900 - index,
                    "final_bucket": "full_text",
                    "candidate": True,
                }
                for index, path in enumerate(primary)
            ]
        },
        "locator_evidence": {
            "primary_files": [{"path": path, "score": 800 - index, "confidence": confidence, "matched_signals": ["symbol:app"]} for index, path in enumerate(primary)],
            "support_files": [],
            "verification_files": [],
            "dependency_relations": [],
        },
        "tool_assisted_anchors_internal": {
            "primary_files_before": primary,
            "primary_files_after": primary,
            "related_tests_before": [],
            "related_tests_after": [],
            "support_files": [],
        },
        "routing_decision": {
            "mode": mode,
            "confidence": confidence,
            "ambiguity_indicators": ambiguity or [],
            "primary_paths": primary,
            "verification_paths": [],
            "support_paths": [],
            "candidate_provenance": [{"path": path, "role": "primary"} for path in primary],
        },
    }


def test_trace_is_deterministic_and_content_free() -> None:
    manifest = _manifest()
    packet = "TASK\nDo the task.\nLIKELY FILES\n\nPRIMARY\n\n* src/app.py\n\nStart here.\n"
    first = build_packet_causality_trace(manifest, packet)
    second = build_packet_causality_trace(manifest, packet)

    assert first == second
    assert first["schema_version"] == "packet-causality-trace.v1"
    rendered = json.dumps(first, sort_keys=True)
    assert "private task bytes" not in rendered
    assert packet not in rendered


def test_confidence_and_ambiguity_changes_are_mechanically_inert() -> None:
    packet = "TASK\nDo the task.\nLIKELY FILES\n\nPRIMARY\n\n* src/app.py\n\nStart here.\n"
    control = build_packet_causality_trace(_manifest(confidence="high"), packet)
    candidate = build_packet_causality_trace(_manifest(confidence="medium", ambiguity=["uncertain"]), packet)

    comparison = compare_packet_causality_traces(control, candidate, expectation="target")

    assert comparison["classification"] == "INERT"
    assert CONFIDENCE_CHANGED_MODE_UNCHANGED in comparison["reason_codes"]
    assert AMBIGUITY_CHANGED_MODE_UNCHANGED in comparison["reason_codes"]


def test_projection_change_is_target_effective() -> None:
    control_packet = "TASK\nDo the task.\nLIKELY FILES\n\nPRIMARY\n\n* src/app.py\n\nStart here.\n"
    candidate_packet = "TASK\nDo the task.\nLIKELY FILES\n\nPRIMARY\n\n* src/other.py\n\nStart here.\n"
    control = build_packet_causality_trace(_manifest(primary=["src/app.py"]), control_packet)
    candidate = build_packet_causality_trace(_manifest(primary=["src/other.py"]), candidate_packet)

    comparison = compare_packet_causality_traces(control, candidate, expectation="target")

    assert comparison["classification"] == "TARGET_EFFECTIVE"
    assert comparison["reason_codes"] == [PACKET_PROJECTION_CHANGED, PACKET_BYTES_CHANGED]


def test_control_packet_change_is_unexpected() -> None:
    control = build_packet_causality_trace(_manifest(), "TASK\nOne\n")
    candidate = build_packet_causality_trace(_manifest(), "TASK\nTwo\n")

    comparison = compare_packet_causality_traces(control, candidate, expectation="control")

    assert comparison["classification"] == "UNEXPECTED_EFFECT"
    assert PACKET_BYTES_CHANGED in comparison["reason_codes"]


def test_rank_and_score_reasons_use_explicit_locator_order_and_scores() -> None:
    packet = "TASK\nDo the task.\nLIKELY FILES\n\nPRIMARY\n\n* src/app.py\n\nStart here.\n"
    control_manifest = _manifest(primary=["src/app.py", "src/other.py"])
    score_manifest = _manifest(primary=["src/app.py", "src/other.py"])
    score_manifest["locator_evidence"]["primary_files"][0]["score"] = 700
    rank_manifest = _manifest(primary=["src/app.py", "src/other.py"])
    rank_manifest["locator_evidence"]["primary_files"].reverse()

    control = build_packet_causality_trace(control_manifest, packet)
    score_change = compare_packet_causality_traces(control, build_packet_causality_trace(score_manifest, packet))
    rank_change = compare_packet_causality_traces(control, build_packet_causality_trace(rank_manifest, packet))

    assert SCORE_CHANGED_RANK_STABLE in score_change["reason_codes"]
    assert RANK_CHANGED_MEMBERSHIP_STABLE in rank_change["reason_codes"]
