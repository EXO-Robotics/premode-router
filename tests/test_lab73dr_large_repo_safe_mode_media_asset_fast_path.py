from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from premode import compiler
from premode import locator
from premode import pcodex_bootstrap as pcodex
from premode.compiler import compile_prompt
from premode.locator import (
    _build_import_suffix_lookup,
    _resolve_import_ref,
    locate_files,
    locate_media_files,
)


LITERAL_SYMBOL_KWARGS = {
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
}


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def _many_files(repo: Path, count: int, *, suffix: str = ".txt", directory: str = "bulk") -> None:
    for index in range(count):
        _write(repo / directory / f"file_{index:04d}{suffix}", f"item {index}\n")


def test_asset_media_prompt_triggers_metadata_only_fast_path(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(repo / "Assets" / "Palm" / "latest_palm.png", b"\x89PNG\r\n")
    _write(repo / "src" / "asset_lookup.py", "def asset_lookup(): return True\n")

    def fail(*_args, **_kwargs):
        raise AssertionError("media fast path must not use content locator reads")

    monkeypatch.setattr(locator, "_read_bounded", fail)
    monkeypatch.setattr(locator, "_file_evidence", fail)

    result = compile_prompt(
        repo,
        "Find the latest palm PNG asset. Do not modify files.",
        "lite",
        record_artifacts=False,
        **LITERAL_SYMBOL_KWARGS,
    )

    assert result["context_selection_mode"] == "asset_media_fast_path"
    assert result["asset_media_fast_path"]["content_reads"] == 0
    assert result["asset_media_fast_path"]["asset_selected_count"] == 1
    assert "Assets/Palm/latest_palm.png" in json.dumps(result["locator_evidence"])
    assert "Assets/Palm/latest_palm.png" in result["packet"]


def test_latest_palm_png_wins_by_mtime_after_path_term_filter(repo: Path) -> None:
    old_palm = repo / "Assets" / "Palm" / "palm_old.png"
    new_palm = repo / "Assets" / "Palm" / "palm_new.png"
    unrelated_new = repo / "Assets" / "Trees" / "oak_new.png"
    for path in (old_palm, new_palm, unrelated_new):
        _write(path, b"\x89PNG\r\n")
    now = time.time()
    os.utime(old_palm, (now - 200, now - 200))
    os.utime(new_palm, (now - 50, now - 50))
    os.utime(unrelated_new, (now, now))

    result = locate_media_files(
        repo,
        "Find the latest palm PNG asset. Do not modify files.",
        inventory_paths=[
            "Assets/Palm/palm_old.png",
            "Assets/Palm/palm_new.png",
            "Assets/Trees/oak_new.png",
        ],
        max_files=1,
    )

    assert [file.path for file in result.primary_files] == ["Assets/Palm/palm_new.png"]
    assert result.metadata["asset_stat_calls"] == 2


def test_asset_fast_path_does_not_read_file_contents(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(repo / "assets" / "palm.png", b"\x89PNG\r\nbinary payload")

    def fail(*_args, **_kwargs):
        raise AssertionError("content reader/tokenizer should not run")

    monkeypatch.setattr(locator, "_read_bounded", fail)
    monkeypatch.setattr(locator, "_file_evidence", fail)

    result = locate_media_files(repo, "Locate the palm png asset. Do not modify files.", inventory_paths=["assets/palm.png"])

    assert result.primary_files[0].path == "assets/palm.png"
    assert result.metadata["content_reads"] == 0


def test_large_messy_repo_dry_run_completes_under_timeout(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(compiler, "_LARGE_REPO_PATH_THRESHOLD", 100)
    monkeypatch.setattr(compiler, "_ASSET_HEAVY_MEDIA_THRESHOLD", 10)
    _write(repo / "assets" / "palms" / "palm_latest.png", b"\x89PNG\r\n")
    for index in range(30):
        _write(repo / "assets" / "textures" / f"texture_{index:03d}.png", b"\x89PNG\r\n")
    _many_files(repo, 180)
    pcodex.set_enabled(repo, True)

    started = time.perf_counter()
    result = pcodex.run_dry_run(repo, "Find the latest palm PNG asset. Do not modify files.")
    elapsed = time.perf_counter() - started

    assert elapsed < 10
    assert result["codex_launch"] == "not_executed"
    assert result["context_selection_mode"] == "asset_media_fast_path"
    assert result["asset_media_fast_path"]["content_reads"] == 0
    assert "assets/palms/palm_latest.png" in result["selected_paths"]


def test_nested_repo_archive_generated_dirs_are_pruned_or_capped(repo: Path) -> None:
    paths = [
        "assets/palm.png",
        "archive/assets/palm_old.png",
        "generated/assets/palm_generated.png",
        "_claw_output/assets/palm_runtime.png",
        "snapshots/assets/palm_snapshot.png",
    ]
    for rel in paths:
        _write(repo / rel, b"\x89PNG\r\n")

    result = locate_media_files(repo, "List palm PNG assets. Do not modify files.", inventory_paths=paths, max_files=8)
    selected = [file.path for file in result.primary_files]

    assert selected == ["assets/palm.png"]
    assert result.metadata["asset_candidate_pruned_count"] == 4


def test_code_edit_prompt_stays_on_normal_locator_for_small_repo(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(repo / "src" / "math.py", "def add(a, b): return a + b\n")
    calls = {"count": 0}
    original = compiler.locate_files

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(compiler, "locate_files", wrapped)

    result = compile_prompt(repo, "Fix the add function for negative inputs.", "lite", record_artifacts=False)

    assert calls["count"] == 1
    assert result["context_selection_mode"] == "normal_locator"
    assert result["compile_degraded"] is False


def test_large_code_repo_relation_building_caps_instead_of_hanging(repo: Path) -> None:
    for index in range(1_230):
        _write(repo / "src" / f"module_{index:04d}.py", f"def helper_{index}(): return {index}\n")
    _write(repo / "tests" / "test_module_0001.py", "from src.module_0001 import helper_0001\n")

    result = locate_files(repo, "Fix module 0001 helper behavior.")

    assert "relation_file_count_cap" in result.relation_degraded_reasons
    assert result.metadata["relation_degraded_reasons"]


def test_resolve_import_ref_uses_bounded_lookup_not_full_suffix_scan() -> None:
    class NoIterLargePathIndex(set[str]):
        def __len__(self) -> int:
            return locator.MAX_IMPORT_SUFFIX_SCAN_PATHS + 1

        def __contains__(self, item: object) -> bool:
            return False

        def __iter__(self):
            raise AssertionError("full suffix scan should not iterate a large path index")

    assert _resolve_import_ref("tests/test_foo.py", "pkg/foo", NoIterLargePathIndex()) is None

    path_index = {"src/pkg/foo.py"}
    suffix_lookup = _build_import_suffix_lookup(path_index)
    assert _resolve_import_ref("tests/test_foo.py", "pkg/foo", path_index, suffix_lookup=suffix_lookup) == "src/pkg/foo.py"


def test_structured_degrade_fields_are_json_only(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "_LARGE_REPO_BROAD_DEGRADE_THRESHOLD", 50)
    _many_files(repo, 80)

    result = compile_prompt(repo, "Inspect this repository and summarize the relevant surfaces.", "lite", record_artifacts=False)

    assert result["status"] == "compile_degraded"
    assert result["compile_degraded"] is True
    assert result["compile_degraded_reason"] == "large_repo_budget_exceeded"
    assert result["large_repo_safety"]["fallback_strategy"] == "json_only_structured_degrade"
    assert "large_repo_budget_exceeded" not in result["packet"]
    assert "large_repo_safety" not in result["packet"]


def test_pcodex_dry_run_reports_codex_launch_not_executed_when_degraded(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "_LARGE_REPO_BROAD_DEGRADE_THRESHOLD", 50)
    _many_files(repo, 80)
    pcodex.set_enabled(repo, True)

    result = pcodex.run_dry_run(repo, "Inspect this repository and summarize the relevant surfaces.")

    assert result["status"] == "dry_run_degraded"
    assert result["codex_launch"] == "not_executed"
    assert result["compile_degraded_reason"] == "large_repo_budget_exceeded"
    assert result["large_repo_safety"]["content_reads"] == 0


def test_small_repo_literal_symbol_packet_stays_compatible(repo: Path) -> None:
    _write(repo / "src" / "calc.py", "def add(a, b): return a + b\n")

    result = compile_prompt(
        repo,
        "Fix the add function for negative inputs.",
        "lite",
        record_artifacts=False,
        **LITERAL_SYMBOL_KWARGS,
    )

    assert result["context_selection_mode"] == "normal_locator"
    assert result["compile_degraded"] is False
    assert "PREMODE_CONTEXT_PACKET_V5" in result["packet"]
    assert "<TASK>" in result["packet"]
    assert "<PRIMARY_FILES>" in result["packet"]
    assert "<RELATED_TESTS>" in result["packet"]
    assert "Fix the add function for negative inputs." in result["packet"]
    assert "asset_media_fast_path" not in result["packet"]
    assert "large_repo_budget_exceeded" not in result["packet"]
