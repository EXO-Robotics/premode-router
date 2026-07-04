from __future__ import annotations

import re
from pathlib import Path

from premode.benchmark import run_benchmark
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


V5_FORBIDDEN_SCAFFOLDING_TERMS = (
    "warning",
    "scope",
    "contract",
    "forbidden",
    "must",
    "do not",
    "verify",
    "verification",
    "review",
    "validation",
    "confidence",
    "decision",
    "policy",
    "command",
    "acceptance",
    "safety",
    "run this",
    "do-not-edit",
)


def _prepare(repo: Path, *, large: bool = False) -> None:
    init_project(repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text(
        "def calculate_total(value):\n"
        "    return value + 1\n\n"
        "def render_total(value):\n"
        "    return f'Total: {calculate_total(value)}'\n",
        encoding="utf-8",
    )
    (repo / "src" / "helpers.py").write_text(
        "def normalize_total(value):\n"
        "    return int(value)\n",
        encoding="utf-8",
    )
    if large:
        (repo / "src" / "large.py").write_text(
            "def target_large_symbol():\n    return 1\n\n" + "\n".join(f"VALUE_{i} = {i}" for i in range(900)),
            encoding="utf-8",
        )
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text(
        "from src.app import calculate_total, render_total\n\n"
        "def test_calculate_total():\n"
        "    assert calculate_total(2) == 3\n\n"
        "def test_render_total():\n"
        "    assert render_total(2) == 'Total: 3'\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Demo\n\nUse calculate_total for totals.\n", encoding="utf-8")
    index_project(repo, "lite")


def _strip_dynamic(packet: str) -> str:
    text = re.sub(r"<TASK>.*?</TASK>", "<TASK></TASK>", packet, flags=re.DOTALL)
    text = re.sub(r"<FILE\b.*?</FILE>", "<FILE></FILE>", text, flags=re.DOTALL)
    for tag in ("PRIMARY_FILES", "RELATED_TESTS", "SUPPORT_FILES", "REPO"):
        text = re.sub(rf"<{tag}>.*?</{tag}>", f"<{tag}></{tag}>", text, flags=re.DOTALL)
    return text.lower()


def test_v5_ranked_paths_packet_contains_ranked_primary_files_and_related_tests(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(repo, "Update calculate_total in src/app.py.", "lite", packet_version="v5", packet_variant="ranked_paths")

    packet = result["packet"]
    assert packet.startswith("PREMODE_CONTEXT_PACKET_V5")
    assert "schema: ranked-context-only" in packet
    assert "<PRIMARY_FILES>\n1. src/app.py" in packet
    assert "<RELATED_TESTS>" in packet
    assert "tests/test_app.py" in packet
    assert "<FILE " not in packet


def test_v5_ranked_snippets_packet_includes_compact_file_blocks(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(repo, "Update calculate_total and test_calculate_total.", "lite", packet_version="v5")

    packet = result["packet"]
    assert result["packet_variant"] == "ranked_snippets"
    assert '<FILE path="src/app.py" role="primary" rank="1">' in packet
    assert '<FILE path="tests/test_app.py" role="related_test" rank="1">' in packet
    assert "def calculate_total" in packet
    assert result["metrics"]["file_block_count"] >= 1
    assert result["metrics"]["snippet_token_count"] > 0


def test_v5_model_facing_scaffolding_has_no_diagnostic_or_behavior_terms(repo: Path) -> None:
    _prepare(repo)
    prompt = "Update src/app.py. Literal task words: warning scope review verification command policy do not."

    result = compile_prompt(repo, prompt, "lite", packet_version="v5", packet_variant="ranked_snippets")

    scaffold = _strip_dynamic(result["packet"])
    for term in V5_FORBIDDEN_SCAFFOLDING_TERMS:
        assert term not in scaffold
    assert result["model_facing_leakage_check"]["model_facing_diagnostic_leakage"] is False
    assert result["metrics"]["model_facing_diagnostic_leakage"] is False


def test_v5_diagnostics_remain_out_of_band(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(repo, "Update calculate_total.", "lite", packet_version="v5", save=True)

    assert result["packet_version"] == "v5"
    assert result["packet_variant"] == "ranked_snippets"
    assert isinstance(result["likely_files"], list)
    assert isinstance(result["related_tests"], list)
    assert isinstance(result["support_files"], list)
    assert "warnings" in result
    assert "confidence" in result
    assert result["decision_ledger"]
    assert result["scope_contract"]
    assert result["review_metadata"]["model_facing"] is False
    assert result["verification_suggestions"] is not None
    assert result["packet_hashes"]["packet_sha256"] == result["compiled_packet_sha256"]
    assert result["token_estimates"]["packet_variant"] == "ranked_snippets"


def test_v5_rank_ordering_is_deterministic(repo: Path) -> None:
    _prepare(repo)

    first = compile_prompt(repo, "Update calculate_total.", "lite", packet_version="v5", record_artifacts=False)
    second = compile_prompt(repo, "Update calculate_total.", "lite", packet_version="v5", record_artifacts=False)

    assert first["packet"] == second["packet"]
    assert first["compiled_packet_sha256"] == second["compiled_packet_sha256"]


def test_v5_support_cap_is_enforced(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(repo, "Update totals across app helper readme surfaces.", "lite", packet_version="v5")

    assert result["metrics"]["support_count"] <= 2
    support_body = re.search(r"<SUPPORT_FILES>(.*?)</SUPPORT_FILES>", result["packet"], flags=re.DOTALL)
    assert support_body is not None
    ranked = [line for line in support_body.group(1).splitlines() if line.strip()]
    assert len(ranked) <= 2


def test_v5_primary_tests_only_omits_support_files(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(repo, "Update calculate_total.", "lite", packet_version="v5", packet_variant="primary_tests_only")

    assert result["metrics"]["support_count"] == 0
    assert "<SUPPORT_FILES>\n</SUPPORT_FILES>" in result["packet"]
    assert 'role="support"' not in result["packet"]


def test_v5_top1_plus_tests_includes_only_top_primary_and_related_tests(repo: Path) -> None:
    _prepare(repo)

    result = compile_prompt(repo, "Update calculate_total and render_total.", "lite", packet_version="v5", packet_variant="top1_plus_tests")

    primary_body = re.search(r"<PRIMARY_FILES>(.*?)</PRIMARY_FILES>", result["packet"], flags=re.DOTALL)
    assert primary_body is not None
    primary_lines = [line for line in primary_body.group(1).splitlines() if line.strip()]
    assert len(primary_lines) == 1
    assert "<SUPPORT_FILES>" not in result["packet"]
    assert result["metrics"]["ranked_primary_count"] == 1
    assert result["metrics"]["related_test_count"] <= 3


def test_v5_snippets_do_not_dump_large_files_by_default(repo: Path) -> None:
    _prepare(repo, large=True)

    result = compile_prompt(repo, "Update target_large_symbol in src/large.py.", "lite", packet_version="v5")

    assert "VALUE_899" not in result["packet"]
    assert result["metrics"]["snippet_token_count"] < 300


def test_existing_v3_and_v4_packet_modes_remain_unchanged(repo: Path) -> None:
    _prepare(repo)

    v3 = compile_prompt(repo, "Update calculate_total.", "lite", cache_optimized=True)
    v4 = compile_prompt(repo, "Update calculate_total.", "lite", packet_version="v4")

    assert v3["packet"].startswith("PREMODE_COMPILED_PACKET_V3")
    assert "## 2. Stable agent contract" in v3["packet"]
    assert v4["packet"].startswith("PREMODE_CONTEXT_PACKET_V4")
    assert "schema: context-only" in v4["packet"]


def test_local_benchmark_passes_for_default_and_v5(repo: Path) -> None:
    _prepare(repo)

    default = run_benchmark(repo, profile="lite")
    v5 = run_benchmark(repo, profile="lite", packet_version="v5", packet_variant="ranked_snippets")

    assert default["benchmark_status"] in {"pass", "warning"}
    assert v5["benchmark_status"] in {"pass", "warning"}


def test_compile_mode_comparison_includes_v5_lanes(repo: Path) -> None:
    _prepare(repo)

    result = run_benchmark(repo, profile="lite", compile_modes=True)

    modes = {item["mode"] for item in result["cases"][0]["compile_mode_comparison"]}
    assert "v5_ranked_paths" in modes
    assert "v5_ranked_snippets" in modes
    assert "v5_primary_tests_only" in modes
    assert "v5_top1_plus_tests" in modes
