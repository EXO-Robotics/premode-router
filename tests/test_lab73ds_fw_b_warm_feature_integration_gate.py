from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from premode.context_constraints import classify_path_for_routing, is_sensitive_or_secret_path
from premode.role_model import (
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    WARM_SCORING_FEATURE_SCHEMA_VERSION,
    RepoWarmIndex,
    dry_run_selector_candidate,
)
from premode.safe_reader import is_secret_name


PROMPT = "Fix the runtime auth token cache bug and verify the regression route."

SENSITIVE_PATHS = [
    ".env",
    ".env.local",
    "._backup_codex/env.local.20260218_224442.bak",
    ".premode/pcodex_state.json",
    ".agents/plugins/local.json",
    ".git/config",
]

RUNTIME_AND_VENDOR_PATHS = [
    ".next/server/app.js",
    "node_modules/pkg/index.js",
    "cache/runtime.json",
    "state/foo.json",
    "proof/run.json",
]

NORMAL_SOURCE_PATHS = [
    "src/lib/auth.ts",
    "src/app/api/auth/route.ts",
    "src/lib/tokenizer.ts",
    "services/cache/runtime_cache.py",
]

PATHS = [
    *SENSITIVE_PATHS,
    *RUNTIME_AND_VENDOR_PATHS,
    *NORMAL_SOURCE_PATHS,
    "tests/test_activity.py",
    "README.md",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "docs/private-beta.md",
]


def _score_order_hash(result) -> str:
    payload = {
        "selected_paths": list(result.selected_paths),
        "role_buckets": dict(result.role_bucket_summary),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _warm_serial(index: RepoWarmIndex | None = None):
    warm_index = RepoWarmIndex.build(PATHS) if index is None else index
    return dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        max_paths=10,
        warm_index_enabled=True,
        warm_index=warm_index,
    )


def _warm_features(index: RepoWarmIndex | None = None):
    warm_index = RepoWarmIndex.build(PATHS) if index is None else index
    return dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        max_paths=10,
        warm_index_enabled=True,
        warm_index=warm_index,
        warm_features_enabled=True,
    )


def test_warm_feature_reuse_stays_opt_in_internal_and_default_safe() -> None:
    default = dry_run_selector_candidate(PATHS, PROMPT, default_selected_paths=["README.md"])
    requested_without_candidate = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        default_selected_paths=["README.md"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(PATHS),
        warm_features_enabled=True,
    )

    assert default.candidate_selector_used is False
    assert default.warm_index_enabled is False
    assert default.warm_features_enabled is False
    assert default.parallel_scoring_enabled is False
    assert default.adaptive_parallel_enabled is False
    assert requested_without_candidate.candidate_selector_used is False
    assert requested_without_candidate.candidate_selector_fallback_reason == "candidate_not_requested"
    assert requested_without_candidate.selected_paths == ("README.md",)


def test_warm_feature_output_matches_warm_index_serial_gate() -> None:
    serial = _warm_serial()
    feature = _warm_features()

    assert feature.selected_paths == serial.selected_paths
    assert feature.candidate_paths == serial.candidate_paths
    assert feature.role_bucket_summary == serial.role_bucket_summary
    assert _score_order_hash(feature) == _score_order_hash(serial)
    assert feature.selection_lock_hash == serial.selection_lock_hash
    assert feature.content_reads == serial.content_reads == 0
    assert feature.warm_features_enabled is True
    assert feature.warm_features_schema_version == WARM_SCORING_FEATURE_SCHEMA_VERSION
    assert feature.warm_features_fallback_reason is None
    assert feature.warm_features_reused_count == feature.warm_features_candidate_count
    assert feature.feature_reuse_hit_rate == 1.0


def test_schema_mismatched_warm_features_fall_back_without_selector_drift() -> None:
    index = replace(RepoWarmIndex.build(PATHS), warm_feature_schema_version="future-feature-schema")
    cold = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        max_paths=10,
    )
    feature = _warm_features(index)

    assert feature.warm_index_fallback_reason == "warm_feature_schema_version_changed"
    assert feature.warm_features_fallback_reason == "warm_features_require_valid_warm_index"
    assert feature.selected_paths == cold.selected_paths
    assert feature.candidate_paths == cold.candidate_paths
    assert feature.selection_lock_hash == cold.selection_lock_hash


def test_mr_a_sensitive_paths_stay_excluded_and_normal_sources_stay_eligible() -> None:
    for path in SENSITIVE_PATHS:
        assert is_sensitive_or_secret_path(path) is True
        assert is_secret_name(path) is True
        assert classify_path_for_routing(path)["category"] == "secret_state_proof_runtime"
    for path in NORMAL_SOURCE_PATHS:
        assert is_sensitive_or_secret_path(path) is False
        assert is_secret_name(path) is False
        assert classify_path_for_routing(path)["category"] == "editable_source_or_support"

    feature = _warm_features()
    blocked = set(SENSITIVE_PATHS + RUNTIME_AND_VENDOR_PATHS)

    assert set(feature.selected_paths).isdisjoint(blocked)
    assert set(feature.candidate_paths).isdisjoint(blocked)
    assert set(feature.selected_paths).intersection(NORMAL_SOURCE_PATHS)
    assert feature.sensitive_excluded_count == feature.sensitive_path_exclusion_count
    assert feature.sensitive_path_exclusion_count >= len(SENSITIVE_PATHS)
