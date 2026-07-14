"""Public-safe production ranking freeze and handoff validation.

The fixtures in this module are synthetic contract probes.  They contain no
evaluation task, expected patch, model transcript, or private evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

from .product_contract import validate_payload_against_schema


ALGORITHM_HANDOFF_SCHEMA_VERSION = "pcodex.algorithm-handoff.v1"
ALGORITHM_HANDOFF_RELATIVE_PATH = Path("release/algorithm-handoff.v1.json")
ALGORITHM_HANDOFF_SCHEMA_RELATIVE_PATH = Path(
    "schemas/pcodex.algorithm-handoff.v1.schema.json"
)
EXPECTED_EVIDENCE_AUTHORITY = {
    "strategy-promotion-decision": (
        "9c8575289a4dfc088f80add13cb7145bd4e507fb6e6f7f8794ba1a056c196ef8",
        "public_safe_source",
    ),
    "strategy-manifest": (
        "d2dd983c074eb8a172352f1c976acac4a158c554d28e6d8524d8fbaa875db82a",
        "private_hash_only",
    ),
    "strategy-native-receipt-index": (
        "fab25b104a929415d88140e4af4a1d87bef1462ca8f4ae2d791dba564bfbefbc",
        "private_hash_only",
    ),
    "strategy-run-manifest": (
        "2ac9ec59783482e5946c51b53a8303bfd3dc15a367361eca7577c9982ba574e1",
        "private_hash_only",
    ),
    "incumbent-retention-decision": (
        "10c7c4f64c29664e561b54dee5e46b4f21af985b3b9477f80c2bce45335598b8",
        "public_safe_source",
    ),
    "incumbent-supported-classes": (
        "212039fdea316eae2f738640c9e83c7b4c60ec624df9ae7190474bbb87418165",
        "public_safe_source",
    ),
    "incumbent-abstention-classes": (
        "5399c881dc193b86d96b0b96d537595bbe88bb4a0d0ae0f83ed661b735a0d4e0",
        "public_safe_source",
    ),
    "incumbent-native-receipt-index": (
        "7f8e2e3627dba43a3a2ecfa7d7473c1cef2f0e8298701f64321f15caa84ae8b6",
        "private_hash_only",
    ),
    "incumbent-run-manifest": (
        "3657a3e46e82433c537263e8218e0b2f08e5803f504e8681bdeb2214b9ddad51",
        "private_hash_only",
    ),
    "incumbent-cost-decomposition": (
        "aea37a3eec6f967f26472569cc771767c8afa12764179028caf77580bf07f84c",
        "private_hash_only",
    ),
    "transfer-evidence-neutral-handoff": (
        "fa315f139e18c80c41a3c9e4fcf91687bc015c77fbb7f1746d783f588fa39883",
        "public_safe_source",
    ),
}
EXPECTED_SUPPORTED_TASK_CLASSES = (
    "package-qualified explicit source routing",
    "package-qualified explicit source and related-test routing",
    "ordinary explicit duplicate-boundary controls",
)
EXPECTED_ABSTENTION_CLASSES = (
    "same basename without authority evidence",
    "multiple equally plausible duplicates",
    "near-duplicate conflicting content",
    "generated mirror ambiguity",
    "vendor and archive duplicate ambiguity",
)
EXPECTED_FALLBACK_CLASSES = (
    "an explicitly returned versioned fallback result is contract-compatible",
    "insufficient confidence preserves the exact raw task through abstention",
)
EXPECTED_SUPPORTED_CLAIMS = (
    "The incumbent production ranking provider is frozen behind ProductionRankingProviderV1.",
    "The product accepts versioned narrow, broad, abstention, and explicit provider-returned fallback results.",
    "No new algorithm candidate was promoted into the production package.",
)
EXPECTED_PROHIBITED_CLAIMS = (
    "general token savings",
    "cross-model qualification",
    "universal repository support",
    "final held-out release qualification",
)
EXPECTED_NATIVE_EVIDENCE = {
    "complete_receipt_count": 36,
    "excluded_receipt_count": 6,
    "scope": "bounded native complete receipts from strategy recovery and incumbent hardening; not the final held-out corpus",
}
EXPECTED_QUALIFICATION_RESULTS = {
    "recommendation_safety": {
        "status": "passed_on_counted_native_receipts",
        "counted_receipts": 36,
        "unsafe_recommendations": 0,
        "scope": "counted native complete receipts only",
    },
    "packet_quality": {
        "status": "qualified_with_retained_negatives",
        "deterministic_packet_tasks": 12,
        "known_negative_count": 2,
        "scope": "one irrelevant cross-package verification path and one omitted configuration-support cell are retained",
    },
    "agent_quality": {
        "status": "no_alternative_noninferiority_demonstrated",
        "diagnostic_repetitions": 3,
        "incumbent_exact_successes": 0,
        "evaluated_variant_exact_successes": 3,
        "standard_exact_successes": 3,
        "scope": "one frozen diagnostic cell; not a general quality estimate",
    },
    "complete_task_cost": {
        "status": "evaluated_variant_rejected_for_cost",
        "diagnostic_repetitions": 3,
        "incumbent_mean_input_tokens": 5895,
        "evaluated_variant_mean_input_tokens": 13077,
        "standard_mean_input_tokens": 8040,
        "scope": "complete runtime input tokens on the same frozen diagnostic cell",
    },
    "transfer_evidence": {
        "status": "not_executed_evidence_neutral",
        "executed_tasks": 0,
        "scope": "later multi-model attempt did not execute a task and cannot qualify or disqualify the incumbent",
    },
}
EXPECTED_KNOWN_LIMITATIONS = (
    "The evidence is bounded and does not replace the frozen 10-repository and 100-task release evaluation.",
    "One irrelevant cross-package verification-path defect and one omitted configuration-support cell were retained as negative evidence.",
    "The later multi-model attempt executed no tasks and is evidence-neutral.",
    "Provider execution failures fail closed; automatic raw-task fallback is not implemented.",
    "Synthetic freeze cases prove safe outcomes on representative fixture shapes; they do not isolate every ambiguity mechanism causally.",
    "No broad token-savings, cross-model, or universal task-quality claim is supported.",
)


def _synthetic_cases(root: Path) -> list[tuple[str, str]]:
    files = {
        "narrow/src/app.py": "VALUE = 1\n",
        "source/src/app.py": "VALUE = 1\n",
        "source/tests/test_app.py": "def test_value(): pass\n",
        "broad/packages/a/config.py": "VALUE = 'a'\n",
        "broad/packages/b/config.py": "VALUE = 'b'\n",
        "abstain/packages/a/config.py": "VALUE = 'a'\n",
        "abstain/packages/b/config.py": "VALUE = 'b'\n",
        "equal/packages/a/settings.py": "VALUE = 1\n",
        "equal/packages/b/settings.py": "VALUE = 1\n",
        "near/services/a/config.py": "MODE = 'a'\n",
        "near/services/b/config.py": "MODE = 'b'\n",
        "generated/generated/schema.py": "VALUE = 1\n",
        "generated/build/schema.py": "VALUE = 1\n",
        "vendor/src/client.py": "VALUE = 1\n",
        "vendor/vendor/client.py": "VALUE = 1\n",
        "vendor/archive/client.py": "VALUE = 0\n",
        "fallback/README.md": "Synthetic fallback contract fixture.\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return [
        ("narrow_explicit_symbol_source", "Change VALUE in src/app.py."),
        ("source_explicit_test_pair", "Update src/app.py and tests/test_app.py."),
        (
            "broad_explicit_duplicate_boundary",
            "Reconcile packages/a/config.py with packages/b/config.py.",
        ),
        ("abstain_ambiguous_duplicate", "Fix the ambiguous config.py implementation."),
        ("equal_equally_plausible_duplicates", "Fix settings.py."),
        ("near_conflicting_near_duplicates", "Fix the conflicting config.py."),
        ("generated_mirror_ambiguity", "Fix schema.py."),
        ("vendor_archive_duplicate_ambiguity", "Fix client.py."),
    ]


def production_behavior_freeze() -> dict[str, Any]:
    """Return a deterministic freeze of real compile and provider boundaries."""

    from .compiler import compile_prompt
    from .production_ranking import (
        PRODUCTION_RANKING_PROVIDER_VERSION,
        ProductionRankingDecisionReceiptV1,
        ProductionRankingRequestV1,
        ProductionRankingResultV1,
    )

    class ExplicitFallbackProvider:
        provider_version = PRODUCTION_RANKING_PROVIDER_VERSION

        def rank(
            self, request: ProductionRankingRequestV1
        ) -> ProductionRankingResultV1:
            return ProductionRankingResultV1(
                routing_mode="fallback",
                primary_paths=(),
                verify_paths=(),
                support_paths=(),
                abstention_reason=None,
                decision_receipt=ProductionRankingDecisionReceiptV1(
                    exact_task_sha256=hashlib.sha256(
                        request.exact_task.encode("utf-8")
                    ).hexdigest(),
                    routing_mode="fallback",
                    primary_path_count=0,
                    verify_path_count=0,
                    support_path_count=0,
                    source_contract="routing-decision.v1",
                ),
            )

    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="pcodex-algorithm-freeze-") as raw_root:
        root = Path(raw_root)
        for case_id, task in _synthetic_cases(root):
            case_root = root / case_id.split("_", 1)[0]
            compiled = compile_prompt(
                case_root,
                task,
                "lite",
                packet_version="v5",
                packet_variant="tool_assisted_anchors_internal",
                packet_strategy="literal_symbol",
                canonical_core_packet=True,
                record_artifacts=False,
            )
            result = compiled["production_ranking"]
            packet = str(compiled["packet"])
            rows.append(
                {
                    "case_id": case_id,
                    "routing_mode": result["routing_mode"],
                    "primary_paths": result["primary_paths"],
                    "verify_paths": result["verify_paths"],
                    "support_paths": result["support_paths"],
                    "abstention_reason": result["abstention_reason"],
                    "provider_version": result["provider_version"],
                    "source_contract": result["decision_receipt"]["source_contract"],
                    "packet_sha256": hashlib.sha256(packet.encode("utf-8")).hexdigest(),
                    "exact_task_occurrences": packet.count(task),
                }
            )
        fallback_task = "Inspect the repository without path guidance."
        compiled = compile_prompt(
            root / "fallback",
            fallback_task,
            "lite",
            packet_version="v5",
            packet_variant="tool_assisted_anchors_internal",
            packet_strategy="literal_symbol",
            canonical_core_packet=True,
            record_artifacts=False,
            production_ranking_provider=ExplicitFallbackProvider(),
        )
        result = compiled["production_ranking"]
        packet = str(compiled["packet"])
        rows.append(
            {
                "case_id": "fallback_explicit_provider_result",
                "routing_mode": result["routing_mode"],
                "primary_paths": result["primary_paths"],
                "verify_paths": result["verify_paths"],
                "support_paths": result["support_paths"],
                "abstention_reason": result["abstention_reason"],
                "provider_version": result["provider_version"],
                "source_contract": result["decision_receipt"]["source_contract"],
                "packet_sha256": hashlib.sha256(packet.encode("utf-8")).hexdigest(),
                "exact_task_occurrences": packet.count(fallback_task),
            }
        )
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "pcodex.production-behavior-freeze.v1",
        "case_count": len(rows),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "routing_modes": [row["routing_mode"] for row in rows],
        "abstention_case_count": sum(row["routing_mode"] == "abstain" for row in rows),
        "fallback_case_count": sum(row["routing_mode"] == "fallback" for row in rows),
        "all_exact_tasks_once": all(row["exact_task_occurrences"] == 1 for row in rows),
    }


def installed_algorithm_handoff_paths(
    prefix: Path | str | None = None,
) -> tuple[Path, Path, Path]:
    root = Path(sys.prefix if prefix is None else prefix) / "share" / "premode-router"
    return (
        root / ALGORITHM_HANDOFF_RELATIVE_PATH,
        root / ALGORITHM_HANDOFF_SCHEMA_RELATIVE_PATH,
        root / "premode.product.json",
    )


def validate_algorithm_handoff_files(
    handoff_path: Path,
    schema_path: Path,
    product_manifest_path: Path,
) -> dict[str, Any]:
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads(product_manifest_path.read_text(encoding="utf-8"))
    validate_payload_against_schema(handoff, schema)
    freeze = production_behavior_freeze()
    authority = manifest["production_ranking_authority"]
    declared = authority["algorithm_handoff"]
    provider = handoff["production_provider"]
    baseline = handoff["algorithm_baseline"]
    if handoff["approved_algorithm_commit"] != baseline["commit_sha"]:
        raise ValueError("approved algorithm commit differs from retained baseline")
    if handoff["product_version"] != manifest["release_target"]:
        raise ValueError(
            "algorithm handoff product version differs from product authority"
        )
    if declared["receipt"] != ALGORITHM_HANDOFF_RELATIVE_PATH.as_posix():
        raise ValueError("product manifest points to a different algorithm handoff")
    if declared["decision"] != handoff["promotion_decision"]:
        raise ValueError("product manifest and handoff decisions differ")
    if declared["freeze_sha256"] != freeze["sha256"]:
        raise ValueError("product manifest behavior freeze differs from runtime")
    if provider["freeze_sha256"] != freeze["sha256"]:
        raise ValueError("algorithm handoff behavior freeze differs from runtime")
    if provider["freeze_case_count"] != freeze["case_count"]:
        raise ValueError("algorithm handoff behavior freeze case count differs")
    if provider["abstention_case_count"] != freeze["abstention_case_count"]:
        raise ValueError(
            "algorithm handoff abstention coverage differs from runtime freeze"
        )
    if provider["fallback_case_count"] != freeze["fallback_case_count"]:
        raise ValueError(
            "algorithm handoff fallback coverage differs from runtime freeze"
        )
    if provider["all_exact_tasks_once"] != freeze["all_exact_tasks_once"]:
        raise ValueError(
            "algorithm handoff exact-task coverage differs from runtime freeze"
        )
    if set(provider["routing_modes"]) != set(freeze["routing_modes"]):
        raise ValueError("algorithm handoff routing modes differ from runtime freeze")
    if provider["provider_version"] != authority["provider_version"]:
        raise ValueError(
            "algorithm handoff provider version differs from product authority"
        )
    if provider["implementation"] != authority["compatibility_provider"]:
        raise ValueError(
            "algorithm handoff implementation differs from product authority"
        )
    evidence = {
        item["id"]: (item["sha256"], item["disclosure"])
        for item in handoff["evidence_integrity"]
    }
    if len(evidence) != len(handoff["evidence_integrity"]):
        raise ValueError("algorithm handoff evidence IDs are not unique")
    if evidence != EXPECTED_EVIDENCE_AUTHORITY:
        raise ValueError(
            "algorithm handoff evidence authority differs from the frozen hashes"
        )
    if tuple(handoff["supported_task_classes"]) != EXPECTED_SUPPORTED_TASK_CLASSES:
        raise ValueError(
            "algorithm handoff supported task classes differ from authority"
        )
    if tuple(handoff["abstention_classes"]) != EXPECTED_ABSTENTION_CLASSES:
        raise ValueError("algorithm handoff abstention classes differ from authority")
    if tuple(handoff["fallback_classes"]) != EXPECTED_FALLBACK_CLASSES:
        raise ValueError("algorithm handoff fallback classes differ from authority")
    if tuple(handoff["supported_claims"]) != EXPECTED_SUPPORTED_CLAIMS:
        raise ValueError("algorithm handoff supported claims differ from authority")
    if tuple(handoff["prohibited_claims"]) != EXPECTED_PROHIBITED_CLAIMS:
        raise ValueError("algorithm handoff prohibited claims differ from authority")
    native = handoff["native_evidence"]
    results = handoff["qualification_results"]
    if native != EXPECTED_NATIVE_EVIDENCE:
        raise ValueError("algorithm handoff native evidence differs from authority")
    if results != EXPECTED_QUALIFICATION_RESULTS:
        raise ValueError(
            "algorithm handoff qualification results differ from authority"
        )
    if tuple(handoff["known_limitations"]) != EXPECTED_KNOWN_LIMITATIONS:
        raise ValueError("algorithm handoff known limitations differ from authority")
    if (
        native["complete_receipt_count"]
        != results["recommendation_safety"]["counted_receipts"]
    ):
        raise ValueError("algorithm handoff native receipt counts do not reconcile")
    if (
        results["agent_quality"]["diagnostic_repetitions"]
        != results["complete_task_cost"]["diagnostic_repetitions"]
    ):
        raise ValueError(
            "algorithm handoff diagnostic repetition counts do not reconcile"
        )
    if results["transfer_evidence"]["executed_tasks"] != 0:
        raise ValueError(
            "evidence-neutral transfer attempt cannot contain executed tasks"
        )
    return {
        "status": "valid",
        "schema_version": handoff["schema_version"],
        "promotion_decision": handoff["promotion_decision"],
        "provider_version": provider["provider_version"],
        "freeze_sha256": freeze["sha256"],
        "freeze_case_count": freeze["case_count"],
    }


def validate_installed_algorithm_handoff(
    prefix: Path | str | None = None,
) -> dict[str, Any]:
    return validate_algorithm_handoff_files(*installed_algorithm_handoff_paths(prefix))
