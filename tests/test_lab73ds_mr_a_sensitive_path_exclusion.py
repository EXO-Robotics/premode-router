from __future__ import annotations

from pathlib import Path

import pytest

from premode.compiler import compile_prompt
from premode.context_constraints import classify_path_for_routing, is_sensitive_or_secret_path
from premode.fixture import init_project
from premode.ignore import IgnoreMatcher
from premode.indexer import index_project
from premode.profiles import PROFILES
from premode.role_model import (
    INTENT_V2_ROLE_BUCKETS_VARIANT,
    RepoWarmIndex,
    dry_run_selector_candidate,
    rank_intent_v2_paths,
)
from premode.safe_reader import is_secret_name, safe_read


SENSITIVE_PATHS = [
    ".env",
    ".env.local",
    "env.local",
    "env.local.20260218_224442.bak",
    "._backup_codex/env.local.20260218_224442.bak",
    "secrets.json",
    "secret.toml",
    "credentials.json",
    "private.key",
    "service.pem",
    "id_rsa",
    "id_ed25519",
    ".agents/cache.json",
    ".premode/pcodex_state.json",
]

RUNTIME_STATE_PATHS = [
    "state/foo.json",
    "proof/run.json",
    "artifacts/output.json",
    "PROJECT/state/latest.json",
]

GENERATED_PATHS = [
    "node_modules/pkg/index.js",
    ".next/server/app.js",
    "dist/bundle.js",
    "build/output.js",
    "cache/runtime.json",
    ".git/config",
]

USEFUL_SOURCE_PATHS = [
    "drizzle.config.ts",
    "src/app/api/activity/route.ts",
    "src/app/gamebot/page.tsx",
    "src/lib/sse.ts",
    "src/lib/auth.ts",
    "src/app/api/auth/route.ts",
    "src/lib/tokenizer.ts",
    "services/cache/runtime_cache.py",
    "src/state/store.ts",
]

PROMPT = "Fix the runtime activity SSE auth bug and verify the gamebot route."


@pytest.mark.parametrize("path", SENSITIVE_PATHS)
def test_sensitive_or_secret_path_patterns_are_excluded_by_name_only(path: str) -> None:
    assert is_sensitive_or_secret_path(path) is True
    assert is_secret_name(path) is True
    assert classify_path_for_routing(path)["category"] == "secret_state_proof_runtime"


@pytest.mark.parametrize("path", USEFUL_SOURCE_PATHS)
def test_auth_token_source_files_remain_eligible(path: str) -> None:
    assert is_sensitive_or_secret_path(path) is False
    assert is_secret_name(path) is False
    assert classify_path_for_routing(path)["category"] == "editable_source_or_support"


@pytest.mark.parametrize("path", RUNTIME_STATE_PATHS)
def test_runtime_state_paths_are_routing_exclusions_not_secret_names(path: str) -> None:
    assert is_sensitive_or_secret_path(path) is False
    assert classify_path_for_routing(path)["category"] == "secret_state_proof_runtime"


def test_safe_read_blocks_sensitive_paths_before_file_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path
    init_project(repo)
    for rel in SENSITIVE_PATHS:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic placeholder\n", encoding="utf-8")

    original_open = Path.open

    def guard_open(self: Path, *args: object, **kwargs: object):
        try:
            rel = self.relative_to(repo).as_posix()
        except ValueError:
            rel = self.as_posix()
        if rel in SENSITIVE_PATHS:
            raise AssertionError(f"safe_read opened sensitive fixture: {rel}")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard_open)
    ignore = IgnoreMatcher.from_repo(repo)

    for rel in SENSITIVE_PATHS:
        result = safe_read(repo, rel, PROFILES["lite"], ignore)
        assert result.allowed is False
        assert any(term in (result.reason or "").lower() for term in ("secret", "ignored"))


def test_default_fallback_selected_paths_filter_sensitive_entries() -> None:
    result = dry_run_selector_candidate(
        [*SENSITIVE_PATHS, *USEFUL_SOURCE_PATHS],
        PROMPT,
        default_selected_paths=[
            "._backup_codex/env.local.20260218_224442.bak",
            "src/lib/auth.ts",
            ".premode/pcodex_state.json",
        ],
    )

    assert result.candidate_selector_used is False
    assert result.candidate_selector_fallback_reason == "candidate_not_requested"
    assert result.selected_paths == ("src/lib/auth.ts",)
    assert result.default_selected_paths == ("src/lib/auth.ts",)
    assert result.sensitive_path_exclusion_count >= 2


def test_ranked_selected_and_warm_paths_exclude_sensitive_and_generated_entries() -> None:
    paths = [*SENSITIVE_PATHS, *RUNTIME_STATE_PATHS, *GENERATED_PATHS, *USEFUL_SOURCE_PATHS, "tests/test_activity.py"]
    ranked = rank_intent_v2_paths(paths, PROMPT, max_paths=10)
    ranked_paths = {decision.path for decision in ranked}
    cold = dry_run_selector_candidate(
        paths,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        max_paths=10,
    )
    warm_index = RepoWarmIndex.build(paths)
    warm_valid, warm_reason = warm_index.validate_for_paths(paths)
    warm = dry_run_selector_candidate(
        paths,
        PROMPT,
        selector_candidate=INTENT_V2_ROLE_BUCKETS_VARIANT,
        default_selected_paths=["src/lib/auth.ts"],
        max_paths=10,
        warm_index_enabled=True,
        warm_index=warm_index,
    )

    blocked = set(SENSITIVE_PATHS + RUNTIME_STATE_PATHS + GENERATED_PATHS)
    assert ranked_paths.isdisjoint(blocked)
    assert set(cold.selected_paths).isdisjoint(blocked)
    assert set(cold.candidate_paths).isdisjoint(blocked)
    assert set(warm_index.paths).isdisjoint(blocked)
    assert warm_valid is True, warm_reason
    assert warm.selected_paths == cold.selected_paths
    assert warm.candidate_paths == cold.candidate_paths
    assert warm.content_reads == cold.content_reads == warm_index.content_reads == 0
    assert any(path in set(cold.selected_paths) for path in USEFUL_SOURCE_PATHS)
    assert cold.sensitive_path_exclusion_count >= len(SENSITIVE_PATHS)


def test_compiled_packet_excludes_sensitive_and_generated_path_lists(tmp_path: Path) -> None:
    repo = tmp_path
    init_project(repo)
    for rel in USEFUL_SOURCE_PATHS:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("export const value = 1\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_activity.py").write_text("def test_activity(): assert True\n", encoding="utf-8")
    for rel in SENSITIVE_PATHS + RUNTIME_STATE_PATHS + GENERATED_PATHS:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    index_project(repo, "lite")

    result = compile_prompt(
        repo,
        PROMPT,
        "lite",
        use_repo_map=True,
        packet_version="v5",
        record=False,
    )

    blocked = set(SENSITIVE_PATHS + RUNTIME_STATE_PATHS + GENERATED_PATHS)
    packet = str(result["packet"])
    for rel in blocked:
        assert rel not in packet
    for key in [
        "candidate_edit_files",
        "likely_edit_files",
        "support_files",
        "read_only_support_files",
        "verification_files",
        "related_tests",
        "suggested_tests",
    ]:
        paths = {
            str(item.get("path") if isinstance(item, dict) else item)
            for item in (result.get(key) or [])
        }
        assert paths.isdisjoint(blocked)
    tier_paths = {
        str(item.get("path"))
        for tier in (result.get("context_tiers") or {}).values()
        for item in tier
        if isinstance(item, dict) and item.get("path")
    }
    assert tier_paths.isdisjoint(blocked)
    assert "src/lib/auth.ts" in packet or "src/app/api/auth/route.ts" in packet


def test_cache_named_source_directory_remains_packet_visible(tmp_path: Path) -> None:
    repo = tmp_path
    init_project(repo)
    source = repo / "services" / "cache" / "runtime_cache.py"
    source.parent.mkdir(parents=True)
    source.write_text("def cache_key(value):\n    return value\n", encoding="utf-8")
    tests = repo / "tests" / "test_runtime_cache.py"
    tests.parent.mkdir()
    tests.write_text("def test_cache_key(): assert True\n", encoding="utf-8")
    top_level_cache = repo / "cache" / "runtime.json"
    top_level_cache.parent.mkdir()
    top_level_cache.write_text("{}\n", encoding="utf-8")
    index_project(repo, "lite")

    assert classify_path_for_routing("services/cache/runtime_cache.py")["category"] == "editable_source_or_support"
    assert classify_path_for_routing("cache/runtime.json")["category"] == "generated_or_build_output"

    result = compile_prompt(
        repo,
        "Fix services/cache/runtime_cache.py cache key behavior and verify tests.",
        "lite",
        use_repo_map=True,
        packet_version="v5",
        record=False,
    )
    packet = str(result["packet"])

    assert "services/cache/runtime_cache.py" in packet
    assert "cache/runtime.json" not in packet
