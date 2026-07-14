from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from premode.algorithm_handoff import (
    production_behavior_freeze,
    validate_algorithm_handoff_files,
    validate_installed_algorithm_handoff,
)
from scripts.build_release_artifacts import validate_required_algorithm_handoff
from scripts.validate_algorithm_handoff import validate


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "release/algorithm-handoff.v1.json"
SCHEMA = ROOT / "schemas/pcodex.algorithm-handoff.v1.schema.json"
MANIFEST = ROOT / "premode.product.json"


def test_sanitized_handoff_and_behavior_freeze_validate() -> None:
    result = validate_algorithm_handoff_files(HANDOFF, SCHEMA, MANIFEST)
    assert result == {
        "status": "valid",
        "schema_version": "pcodex.algorithm-handoff.v1",
        "promotion_decision": "no_candidate_promoted",
        "provider_version": "production-ranking-provider.v1",
        "freeze_sha256": "f4499af2b068a8802d3abaadbd360e804facebf4afc5dc6f461ee3fd12e2714c",
        "freeze_case_count": 9,
    }
    freeze = production_behavior_freeze()
    assert freeze["routing_modes"] == [
        "narrow",
        "broad",
        "broad",
        "abstain",
        "abstain",
        "abstain",
        "abstain",
        "abstain",
        "fallback",
    ]
    assert freeze["abstention_case_count"] == 5
    assert freeze["fallback_case_count"] == 1
    assert freeze["all_exact_tasks_once"] is True


def test_source_handoff_binds_real_ancestor_and_tree() -> None:
    result = validate(ROOT)
    assert result["baseline_is_ancestor"] is True
    assert result["private_evidence_opened"] is False
    assert result["baseline_commit"] == "b9aede455c8d49217ef0a67e8dec0c8cf2c565a6"
    assert result["baseline_tree"] == "8120490deb23457d19299b09d5291783753f2066"


def test_handoff_contains_only_hashes_for_private_evidence() -> None:
    payload = json.loads(HANDOFF.read_text(encoding="utf-8"))
    assert payload["private_evidence_included"] is False
    assert payload["native_evidence"]["complete_receipt_count"] == 36
    assert payload["native_evidence"]["excluded_receipt_count"] == 6
    for item in payload["evidence_integrity"]:
        assert set(item) == {"id", "sha256", "disclosure"}
        assert len(item["sha256"]) == 64
    serialized = json.dumps(payload, sort_keys=True).casefold()
    for forbidden in ("transcript", "raw_prompt", "expected_patch", "private/tmp"):
        assert forbidden not in serialized


def test_product_manifest_binds_handoff_decision_and_freeze() -> None:
    payload = json.loads(HANDOFF.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    authority = manifest["production_ranking_authority"]["algorithm_handoff"]
    assert authority["receipt"] == "release/algorithm-handoff.v1.json"
    assert authority["schema"] == "schemas/pcodex.algorithm-handoff.v1.schema.json"
    assert authority["decision"] == payload["promotion_decision"]
    assert authority["freeze_sha256"] == payload["production_provider"]["freeze_sha256"]


def test_changed_provider_freeze_fails_closed(tmp_path: Path) -> None:
    changed = json.loads(HANDOFF.read_text(encoding="utf-8"))
    changed["production_provider"]["freeze_sha256"] = "0" * 64
    changed_path = tmp_path / "handoff.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="behavior freeze differs"):
        validate_algorithm_handoff_files(changed_path, SCHEMA, MANIFEST)


def test_fabricated_evidence_or_claim_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(HANDOFF.read_text(encoding="utf-8"))
    payload["evidence_integrity"][0]["sha256"] = "0" * 64
    changed_path = tmp_path / "bad-evidence.json"
    changed_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence authority differs"):
        validate_algorithm_handoff_files(changed_path, SCHEMA, MANIFEST)

    payload = json.loads(HANDOFF.read_text(encoding="utf-8"))
    payload["supported_claims"][0] = "general token savings"
    changed_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="supported claims differ"):
        validate_algorithm_handoff_files(changed_path, SCHEMA, MANIFEST)


def test_promotion_dimensions_and_counts_are_explicit_and_reconciled() -> None:
    payload = json.loads(HANDOFF.read_text(encoding="utf-8"))
    results = payload["qualification_results"]
    assert set(results) == {
        "recommendation_safety",
        "packet_quality",
        "agent_quality",
        "complete_task_cost",
        "transfer_evidence",
    }
    assert results["recommendation_safety"]["counted_receipts"] == 36
    assert payload["native_evidence"] == {
        "complete_receipt_count": 36,
        "excluded_receipt_count": 6,
        "scope": "bounded native complete receipts from strategy recovery and incumbent hardening; not the final held-out corpus",
    }
    assert results["transfer_evidence"]["executed_tasks"] == 0


def test_installed_handoff_resolves_outside_source_checkout(tmp_path: Path) -> None:
    share = tmp_path / "share/premode-router"
    (share / "release").mkdir(parents=True)
    (share / "schemas").mkdir()
    shutil.copy2(HANDOFF, share / "release/algorithm-handoff.v1.json")
    shutil.copy2(SCHEMA, share / "schemas/pcodex.algorithm-handoff.v1.schema.json")
    shutil.copy2(MANIFEST, share / "premode.product.json")
    assert validate_installed_algorithm_handoff(tmp_path)["status"] == "valid"


def test_wheel_and_sdist_require_the_sanitized_handoff() -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    wheel = [
        "premode_router-0.3.0b1.data/data/share/premode-router/release/algorithm-handoff.v1.json"
    ]
    sdist = ["premode_router-0.3.0b1/release/algorithm-handoff.v1.json"]
    assert (
        validate_required_algorithm_handoff(wheel, policy, archive_kind="wheel") == []
    )
    assert (
        validate_required_algorithm_handoff(sdist, policy, archive_kind="sdist") == []
    )
    assert validate_required_algorithm_handoff([], policy, archive_kind="wheel") == [
        "missing_algorithm_handoff:algorithm-handoff.v1.json"
    ]
