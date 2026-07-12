from __future__ import annotations

import json

from premode.locator import FileRelation, LocateResult, LocatedFile
from premode.routing_decision import (
    BROAD_PRIMARY_BUDGET,
    BROAD_SUPPORT_BUDGET,
    BROAD_VERIFICATION_BUDGET,
    NARROW_PRIMARY_BUDGET,
    NARROW_SUPPORT_BUDGET,
    NARROW_VERIFICATION_BUDGET,
    RoutingMode,
    SupportConfidence,
    decide_routing,
    metadata_paths_equal_projection,
    render_model_request,
    routing_decision_metadata,
    validate_packet_projection,
    routing_input_from_ranked,
)
from premode.ranker_protocol import RankedCandidate, RankedCandidates, B0_ROUTING_BASE_V1


def _file(path: str, score: int, role: str = "source", *signals: str) -> LocatedFile:
    return LocatedFile(
        path=path,
        score=score,
        role=role,
        confidence="high" if score >= 320 else "medium",
        matched_signals=list(signals),
    )


def _result(
    *,
    primary=(),
    verification=(),
    support=(),
    confidence="high",
    ambiguity=(),
    uncovered=(),
    relations=(),
) -> LocateResult:
    all_files = [*primary, *verification, *support]
    records = [
        {
            "normalized_path": item.path,
            "final_admissibility": "ALLOW",
            "final_policy_receipt": {"receipt_sha256": f"test:{item.path}"},
        }
        for item in all_files
    ]
    result = LocateResult(
        primary_files=list(primary),
        verification_files=list(verification),
        support_files=list(support),
        confidence=confidence,
        covered_prompt_terms=["auth"],
        uncovered_prompt_terms=list(uncovered),
        ambiguity_reasons=list(ambiguity),
        dependency_relations=list(relations),
        metadata={"candidate_provenance": ("inventory", "symbol_match"), "candidate_policy": {"records": records}},
    )
    ranked = RankedCandidates(
        B0_ROUTING_BASE_V1.configuration_hash,
        tuple(RankedCandidate(item.path, item.path, item.score, index, f"evidence:{item.path}", ()) for index, item in enumerate(sorted(all_files, key=lambda value: (-value.score, value.path)), start=1)),
    )
    return routing_input_from_ranked(result, ranked)


def test_concentrated_high_confidence_evidence_routes_narrow_deterministically() -> None:
    located = _result(primary=[_file("src/auth.py", 500, "source", "symbol:authenticate")])

    first = decide_routing(located, "Fix authenticate.")
    second = decide_routing(located, "Fix authenticate.")

    assert first == second
    assert first.mode is RoutingMode.NARROW
    assert first.primary_paths == ("src/auth.py",)
    assert first.candidate_provenance == ("inventory", "symbol_match")
    assert validate_packet_projection(first, render_model_request(first))


def test_weak_margin_or_distributed_evidence_routes_broad() -> None:
    located = _result(
        primary=[
            _file("src/auth.py", 400, "source", "symbol:authenticate"),
            _file("src/session.py", 330, "source", "content:session"),
        ],
        ambiguity=["top_score_gap_small"],
    )

    decision = decide_routing(located, "Update auth and session behavior.")

    assert decision.mode is RoutingMode.BROAD
    assert "rank_margin_below_narrow_threshold" in decision.reasons


def test_insufficient_or_severe_evidence_abstains_with_exact_raw_task() -> None:
    exact_task = "Investigate this broadly.\nPreserve these bytes exactly."
    weak = decide_routing(
        _result(primary=[_file("README.md", 80, "docs", "role:docs")], confidence="low"),
        exact_task,
    )
    severe = decide_routing(
        _result(
            primary=[_file("src/app.py", 500, "source", "content:app")],
            ambiguity=["no_transportable_evidence"],
        ),
        exact_task,
    )

    for decision in (weak, severe):
        assert decision.mode is RoutingMode.ABSTAIN
        assert decision.primary_paths == ()
        assert decision.verification_paths == ()
        assert decision.support_paths == ()
        assert render_model_request(decision) == exact_task
        assert validate_packet_projection(decision, exact_task)


def test_narrow_emits_at_most_one_strong_support_and_omits_qualified_or_weak() -> None:
    primary = _file("pkg/src/auth.py", 600, "source", "symbol:authenticate")
    strong_a = _file("pkg/pyproject.toml", 300, "config", "content:auth")
    strong_b = _file("pkg/build.toml", 290, "config", "content:build")
    qualified = _file("pkg/config/settings.toml", 220, "config", "role:config")
    weak = _file("pyproject.toml", 200, "config", "role:config")
    relations = [
        FileRelation(primary.path, strong_a.path, "package_manifest", 90),
        FileRelation(primary.path, strong_b.path, "build_config", 85),
    ]
    decision = decide_routing(
        _result(primary=[primary], support=[qualified, weak, strong_b, strong_a], relations=relations),
        "Fix authenticate.",
    )

    assert decision.mode is RoutingMode.NARROW
    assert NARROW_SUPPORT_BUDGET == 1
    assert decision.support_paths == (strong_a.path,)
    by_path = {item.path: item for item in decision.support_decisions}
    assert by_path[strong_a.path].confidence is SupportConfidence.STRONG
    assert by_path[strong_a.path].emitted is True
    assert by_path[strong_b.path].confidence is SupportConfidence.STRONG
    assert by_path[strong_b.path].emitted is False
    assert by_path[qualified.path].confidence is SupportConfidence.WEAK
    assert by_path[weak.path].confidence is SupportConfidence.WEAK


def test_broad_emits_strong_and_qualified_support_with_independent_budget() -> None:
    primary = _file("pkg/src/auth.py", 400, "source", "symbol:authenticate")
    candidates = [
        _file("pkg/build.toml", 310, "config", "content:build"),
        _file("pkg/config/a.toml", 260, "config", "role:config"),
        _file("pkg/config/b.toml", 250, "config", "role:config"),
        _file("pkg/config/c.toml", 240, "config", "role:config"),
        _file("pyproject.toml", 500, "config", "role:config"),
    ]
    decision = decide_routing(
        _result(
            primary=[primary],
            support=candidates,
            confidence="medium",
            relations=[FileRelation(primary.path, candidates[0].path, "build_config", 90)],
        ),
        "Update authentication build configuration.",
    )

    assert decision.mode is RoutingMode.BROAD
    assert BROAD_SUPPORT_BUDGET == 3
    assert decision.support_paths == ("pkg/build.toml",)
    assert "pyproject.toml" not in decision.support_paths


def test_packet_contains_only_projection_and_metadata_paths_must_match() -> None:
    primary = _file("src/auth.py", 500, "source", "symbol:authenticate")
    verification = _file("tests/test_auth.py", 300, "test", "adjacent_test:src/auth.py")
    support = _file("pkg/pyproject.toml", 280, "config", "explicit_path:pkg/pyproject.toml")
    decision = decide_routing(
        _result(primary=[primary], verification=[verification], support=[support], relations=[FileRelation(primary.path, support.path, "package_manifest", 90)]),
        "Fix authentication and its test.",
    )
    packet = render_model_request(decision)

    assert packet.count("Fix authentication and its test.") == 1
    assert "\nPRIMARY\n\n* src/auth.py" in packet
    assert "\nVERIFY\n\n* tests/test_auth.py" in packet
    assert "\nSUPPORT\n\n* pkg/pyproject.toml" in packet
    assert "NARROW" not in packet
    assert "confidence" not in packet.casefold()
    assert "symbol:authenticate" not in packet
    assert metadata_paths_equal_projection(
        decision,
        primary_paths=["src/auth.py"],
        verification_paths=["tests/test_auth.py"],
        support_paths=["pkg/pyproject.toml"],
    )
    assert not metadata_paths_equal_projection(
        decision,
        primary_paths=["src/auth.py"],
        verification_paths=["tests/test_auth.py"],
        support_paths=[],
    )
    assert validate_packet_projection(decision, packet)
    assert not validate_packet_projection(decision, packet + "hidden metadata")


def test_primary_and_verification_budgets_are_independent_and_preserve_order() -> None:
    narrow = decide_routing(
        _result(
            primary=[_file("src/a.py", 600, "source", "symbol:Target")],
            verification=[
                _file("tests/test_a.py", 310, "test", "content:a"),
                _file("tests/test_b.py", 300, "test", "content:b"),
                _file("tests/test_c.py", 290, "test", "content:c"),
            ],
        ),
        "Fix Target.",
    )
    broad_primaries = [
        _file(f"src/p{index}.py", 500 - index, "source", f"content:p{index}")
        for index in range(7)
    ]
    broad_verification = [
        _file(f"tests/test_p{index}.py", 300 - index, "test", f"content:p{index}")
        for index in range(5)
    ]
    broad = decide_routing(
        _result(primary=broad_primaries, verification=broad_verification),
        "Update the distributed package behavior.",
    )

    assert (NARROW_PRIMARY_BUDGET, NARROW_VERIFICATION_BUDGET) == (2, 2)
    assert narrow.mode is RoutingMode.NARROW
    assert narrow.verification_paths == ("tests/test_a.py", "tests/test_b.py")
    assert (BROAD_PRIMARY_BUDGET, BROAD_VERIFICATION_BUDGET) == (5, 3)
    assert broad.mode is RoutingMode.BROAD
    assert broad.primary_paths == tuple(f"src/p{index}.py" for index in range(5))
    assert broad.verification_paths == tuple(f"tests/test_p{index}.py" for index in range(3))


def test_observer_metadata_is_json_safe_and_kept_out_of_model_bytes() -> None:
    decision = decide_routing(
        _result(primary=[_file("src/auth.py", 500, "source", "symbol:authenticate")]),
        "Fix authenticate.",
    )
    metadata = routing_decision_metadata(decision)
    packet = render_model_request(decision)

    assert metadata["mode"] == "NARROW"
    assert metadata["candidate_provenance"] == ["inventory", "symbol_match"]
    assert metadata["packet_projection"]["primary_paths"] == ["src/auth.py"]
    assert json.loads(json.dumps(metadata)) == metadata
    assert "candidate_provenance" not in packet
