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


PROMPT = "Fix the runtime activity SSE auth bug and verify the gamebot route."

SENSITIVE_PATHS = [
    ".env",
    ".env.local",
    "._backup_codex/env.local.20260218_224442.bak",
    ".premode/pcodex_state.json",
    "private.key",
    "id_rsa",
]

RUNTIME_AND_GENERATED_PATHS = [
    "state/foo.json",
    "proof/run.json",
    "artifacts/output.json",
    "node_modules/pkg/index.js",
    ".next/server/app.js",
    "dist/bundle.js",
    "cache/runtime.json",
]

NORMAL_SOURCE_PATHS = [
    "src/lib/auth.ts",
    "src/app/api/auth/route.ts",
    "src/lib/tokenizer.ts",
    "services/cache/runtime_cache.py",
    "src/state/store.ts",
]

PATHS = [
    *SENSITIVE_PATHS,
    *RUNTIME_AND_GENERATED_PATHS,
    *NORMAL_SOURCE_PATHS,
    "tests/test_activity.py",
    "README.md",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "docs/private-beta.md",
    "assets/logo.png",
]


def _score_order_hash(result) -> str:
    payload = {
        "selected_paths": list(result.selected_paths),
        "role_buckets": dict(result.role_bucket_summary),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _warm_serial(paths: list[str] | None = None, prompt: str = PROMPT, *, max_paths: int | None = 10, warm_index=None):
    paths = PATHS if paths is None else paths
    index = RepoWarmIndex.build(paths) if warm_index is None else warm_index
    return dry_run_selector_candidate(
        paths,
        prompt,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        max_paths=max_paths,
        warm_index_enabled=True,
        warm_index=index,
    )


def _warm_features(paths: list[str] | None = None, prompt: str = PROMPT, *, max_paths: int | None = 10, warm_index=None):
    paths = PATHS if paths is None else paths
    index = RepoWarmIndex.build(paths) if warm_index is None else warm_index
    return dry_run_selector_candidate(
        paths,
        prompt,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        max_paths=max_paths,
        warm_index_enabled=True,
        warm_index=index,
        warm_features_enabled=True,
    )


def test_warm_features_remain_opt_in_internal_and_default_behavior_unchanged() -> None:
    default = dry_run_selector_candidate(PATHS, PROMPT, default_selected_paths=["README.md"])
    warm_only = _warm_serial()
    feature = _warm_features()

    assert default.candidate_selector_used is False
    assert default.candidate_selector_fallback_reason == "candidate_not_requested"
    assert default.warm_index_enabled is False
    assert default.warm_features_enabled is False
    assert default.parallel_scoring_enabled is False
    assert default.adaptive_parallel_enabled is False

    assert warm_only.warm_index_enabled is True
    assert warm_only.warm_features_enabled is False
    assert feature.warm_features_enabled is True
    assert feature.warm_features_schema_version == WARM_SCORING_FEATURE_SCHEMA_VERSION


def test_warm_feature_output_equals_current_warm_index_serial_output() -> None:
    current = _warm_serial()
    feature = _warm_features()

    assert feature.selected_paths == current.selected_paths
    assert len(feature.candidate_paths) == len(current.candidate_paths)
    assert feature.role_bucket_summary == current.role_bucket_summary
    assert _score_order_hash(feature) == _score_order_hash(current)
    assert feature.selection_lock_hash == current.selection_lock_hash
    assert feature.content_reads == current.content_reads == 0
    assert feature.warm_features_reused_count == feature.warm_features_candidate_count
    assert feature.feature_reuse_hit_rate == 1.0
    assert feature.warm_features_fallback_reason is None


def test_repeated_warm_feature_runs_are_deterministic() -> None:
    first = _warm_features()
    second = _warm_features()

    assert second.selected_paths == first.selected_paths
    assert second.role_bucket_summary == first.role_bucket_summary
    assert second.selection_lock_hash == first.selection_lock_hash
    assert _score_order_hash(second) == _score_order_hash(first)


def test_feature_schema_version_mismatch_falls_back_safely() -> None:
    index = replace(RepoWarmIndex.build(PATHS), warm_feature_schema_version="future-feature-schema")
    baseline = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        max_paths=10,
    )
    feature = _warm_features(warm_index=index)

    assert feature.warm_index_fallback_reason == "warm_feature_schema_version_changed"
    assert feature.warm_features_fallback_reason == "warm_features_require_valid_warm_index"
    assert feature.selected_paths == baseline.selected_paths
    assert feature.selection_lock_hash == baseline.selection_lock_hash


def test_missing_and_corrupt_warm_feature_records_fall_back_safely() -> None:
    index = RepoWarmIndex.build(PATHS)
    missing_metadata = replace(index.path_metadata[0], scoring_features=None)
    missing_index = replace(index, path_metadata=(missing_metadata, *index.path_metadata[1:]))
    corrupt_feature = replace(index.path_metadata[0].scoring_features, path="src/other.py")
    corrupt_metadata = replace(index.path_metadata[0], scoring_features=corrupt_feature)
    corrupt_index = replace(index, path_metadata=(corrupt_metadata, *index.path_metadata[1:]))
    current = _warm_serial(warm_index=index)

    missing = _warm_features(warm_index=missing_index)
    corrupt = _warm_features(warm_index=corrupt_index)

    assert missing.warm_features_fallback_reason == "missing_warm_feature_record"
    assert corrupt.warm_features_fallback_reason == "corrupt_warm_feature_record"
    assert missing.selected_paths == current.selected_paths
    assert corrupt.selected_paths == current.selected_paths
    assert missing.selection_lock_hash == current.selection_lock_hash
    assert corrupt.selection_lock_hash == current.selection_lock_hash


def test_content_reads_remain_zero_and_no_prompts_packets_or_source_are_cached() -> None:
    index = RepoWarmIndex.build(PATHS)
    feature = _warm_features(warm_index=index)
    payload = json.dumps(index.to_dict(include_paths=True), sort_keys=True).lower()
    result_payload = json.dumps(feature.to_dict(include_paths=True), sort_keys=True).lower()

    assert index.content_reads == feature.content_reads == 0
    assert "source_text" not in payload
    assert "source_snippet" not in payload
    assert "file_content" not in payload
    assert "raw_prompt" not in payload
    assert "packet" not in payload
    assert PROMPT.lower() not in payload
    assert "packet" not in result_payload
    assert "model_facing_output" not in result_payload


def test_mr_a_sensitive_paths_remain_excluded_and_normal_sources_remain_eligible() -> None:
    for path in SENSITIVE_PATHS:
        assert is_sensitive_or_secret_path(path) is True
        assert is_secret_name(path) is True
        assert classify_path_for_routing(path)["category"] == "secret_state_proof_runtime"
    for path in NORMAL_SOURCE_PATHS:
        assert is_sensitive_or_secret_path(path) is False
        assert is_secret_name(path) is False
        assert classify_path_for_routing(path)["category"] == "editable_source_or_support"

    feature = _warm_features()
    blocked = set(SENSITIVE_PATHS + RUNTIME_AND_GENERATED_PATHS)

    assert set(feature.selected_paths).isdisjoint(blocked)
    assert set(feature.candidate_paths).isdisjoint(blocked)
    assert any(path in set(feature.selected_paths) for path in NORMAL_SOURCE_PATHS)
    assert feature.sensitive_path_exclusion_count >= len(SENSITIVE_PATHS)
    assert feature.sensitive_excluded_count == feature.sensitive_path_exclusion_count


def test_adaptive_warm_index_and_intent_v2_remain_opt_in_internal() -> None:
    no_candidate = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        default_selected_paths=["src/lib/auth.ts"],
        warm_index_enabled=True,
        warm_index=RepoWarmIndex.build(PATHS),
        warm_features_enabled=True,
    )
    no_warm = dry_run_selector_candidate(
        PATHS,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        parallel_scoring_enabled=True,
        parallel_scoring_mode="adaptive",
        warm_features_enabled=True,
    )

    assert no_candidate.candidate_selector_used is False
    assert no_candidate.candidate_selector_fallback_reason == "candidate_not_requested"
    assert no_candidate.warm_features_enabled is True
    assert no_candidate.adaptive_parallel_enabled is False
    assert no_warm.parallel_score_fallback_reason == "parallel_requires_valid_warm_index"
    assert no_warm.adaptive_parallel_enabled is False


def test_setup_install_package_live_routing_surfaces_untouched() -> None:
    payload = _warm_features().to_dict()

    assert "setup" not in payload
    assert "install" not in payload
    assert "package" not in payload
    assert "live_routing" not in payload
