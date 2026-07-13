from __future__ import annotations

from copy import deepcopy
import json

from premode.compiler import compile_prompt

from premode.packet_causality import (
    AMBIGUITY_CHANGED_MODE_UNCHANGED,
    CONFIDENCE_CHANGED_MODE_UNCHANGED,
    LOCATOR_ROLE_CHANGED_PROJECTION_STABLE,
    PACKET_BYTES_CHANGED,
    PACKET_PROJECTION_CHANGED,
    RANK_CHANGED_MEMBERSHIP_STABLE,
    RANK_MEMBERSHIP_CHANGED_PROJECTION_STABLE,
    ROLE_CHANGED_PROJECTION_STABLE,
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
    assert first["schema_version"] == "packet-causality-trace.v2"
    rendered = json.dumps(first, sort_keys=True)
    assert "private task bytes" not in rendered
    assert packet not in rendered


def test_trace_redacts_ambiguity_payload_and_bounds_roles() -> None:
    manifest = _manifest(ambiguity=["uncovered_core_terms:private_term"])
    manifest["routing_decision"]["candidate_provenance"] = [
        {"path": f"src/file_{index}.py", "role": "primary"} for index in range(100)
    ]
    trace = build_packet_causality_trace(manifest, "TASK\nDo it.\n")
    rendered = json.dumps(trace, sort_keys=True)

    assert "private_term" not in rendered
    assert trace["routing_summary"]["ambiguity"]["categories"] == ["uncovered_core_terms"]
    assert trace["routing_summary"]["role_count"] == 100
    assert len(trace["routing_summary"]["roles"]) == 32


def test_unknown_ambiguity_category_is_hashed_not_emitted() -> None:
    private_category = "private_customer_" + "x" * 5000
    trace = build_packet_causality_trace(
        _manifest(ambiguity=[private_category]), "TASK\nDo it.\n"
    )
    rendered = json.dumps(trace, sort_keys=True)

    assert "private_customer" not in rendered
    assert trace["routing_summary"]["ambiguity"]["categories"] == []
    assert trace["routing_summary"]["ambiguity"]["unknown_category_count"] == 1


def test_trace_rejects_absolute_and_traversal_paths_and_preserves_case() -> None:
    manifest = _manifest(primary=[
        "src/Config.py",
        "src/config.py",
        "/private/file.py",
        "C:/" + "local/account/file.py",
        "../escape.py",
    ])
    trace = build_packet_causality_trace(manifest, "TASK\nDo it.\n")
    paths = trace["routing_summary"]["primary"]

    assert paths == ["src/Config.py", "src/config.py"]


def test_case_only_replacement_is_not_stable_rank_membership() -> None:
    packet = "TASK\nDo it.\n"
    control = build_packet_causality_trace(_manifest(primary=["src/Config.py"]), packet)
    candidate = build_packet_causality_trace(_manifest(primary=["src/config.py"]), packet)
    comparison = compare_packet_causality_traces(control, candidate)

    assert RANK_CHANGED_MEMBERSHIP_STABLE not in comparison["reason_codes"]


def test_rank_membership_change_is_not_metadata_only() -> None:
    packet = "TASK\nDo it.\n"
    control_manifest = _manifest(primary=["src/a.py", "src/b.py"])
    candidate_manifest = deepcopy(control_manifest)
    candidate_manifest["locator_evidence"]["primary_files"][1]["path"] = "src/c.py"
    control = build_packet_causality_trace(control_manifest, packet)
    candidate = build_packet_causality_trace(candidate_manifest, packet)
    comparison = compare_packet_causality_traces(control, candidate)

    assert RANK_MEMBERSHIP_CHANGED_PROJECTION_STABLE in comparison["reason_codes"]


def test_role_change_beyond_display_bound_uses_full_hash() -> None:
    packet = "TASK\nDo it.\n"
    control_manifest = _manifest()
    candidate_manifest = _manifest()
    control_manifest["routing_decision"]["candidate_provenance"] = [
        {"path": f"src/file_{index:03d}.py", "role": "primary"} for index in range(33)
    ]
    candidate_manifest["routing_decision"]["candidate_provenance"] = [
        *control_manifest["routing_decision"]["candidate_provenance"][:32],
        {"path": "src/file_032.py", "role": "verification"},
    ]
    comparison = compare_packet_causality_traces(
        build_packet_causality_trace(control_manifest, packet),
        build_packet_causality_trace(candidate_manifest, packet),
    )

    assert ROLE_CHANGED_PROJECTION_STABLE in comparison["reason_codes"]


def test_rank_membership_change_beyond_display_bound_uses_full_hash() -> None:
    packet = "TASK\nDo it.\n"
    paths = [f"src/file_{index:03d}.py" for index in range(33)]
    control_manifest = _manifest(primary=paths)
    candidate_manifest = deepcopy(control_manifest)
    candidate_manifest["locator_evidence"]["primary_files"][32]["path"] = "src/replacement.py"
    comparison = compare_packet_causality_traces(
        build_packet_causality_trace(control_manifest, packet),
        build_packet_causality_trace(candidate_manifest, packet),
    )

    assert RANK_MEMBERSHIP_CHANGED_PROJECTION_STABLE in comparison["reason_codes"]
    assert SCORE_CHANGED_RANK_STABLE not in comparison["reason_codes"]


def test_locator_role_change_is_not_mislabeled_as_score_change() -> None:
    packet = "TASK\nDo it.\n"
    control_manifest = _manifest(primary=["src/a.py"])
    candidate_manifest = deepcopy(control_manifest)
    candidate_manifest["locator_evidence"]["primary_files"] = []
    candidate_manifest["locator_evidence"]["verification_files"] = [
        {"path": "src/a.py", "score": 800, "confidence": "medium", "matched_signals": ["symbol:app"]}
    ]
    comparison = compare_packet_causality_traces(
        build_packet_causality_trace(control_manifest, packet),
        build_packet_causality_trace(candidate_manifest, packet),
    )

    assert LOCATOR_ROLE_CHANGED_PROJECTION_STABLE in comparison["reason_codes"]
    assert SCORE_CHANGED_RANK_STABLE not in comparison["reason_codes"]


def test_rank_order_change_is_not_mislabeled_as_role_change() -> None:
    packet = "TASK\nDo it.\n"
    control_manifest = _manifest(primary=["src/a.py", "src/b.py"])
    candidate_manifest = deepcopy(control_manifest)
    candidate_manifest["locator_evidence"]["primary_files"].reverse()
    comparison = compare_packet_causality_traces(
        build_packet_causality_trace(control_manifest, packet),
        build_packet_causality_trace(candidate_manifest, packet),
    )

    assert RANK_CHANGED_MEMBERSHIP_STABLE in comparison["reason_codes"]
    assert LOCATOR_ROLE_CHANGED_PROJECTION_STABLE not in comparison["reason_codes"]


def test_compiler_trace_is_diagnostic_only_and_packet_identical(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    kwargs = {
        "record_artifacts": False,
        "canonical_core_packet": True,
        "packet_version": "v5",
        "packet_variant": "tool_assisted_anchors_internal",
        "packet_strategy": "literal_symbol",
    }
    normal = compile_prompt(tmp_path, "Change src/app.py.", **kwargs)
    traced = compile_prompt(tmp_path, "Change src/app.py.", include_packet_causality_trace=True, **kwargs)

    assert "packet_causality_trace" not in normal
    assert traced["packet_causality_trace"]["schema_version"] == "packet-causality-trace.v2"
    assert normal["packet"] == traced["packet"]


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
