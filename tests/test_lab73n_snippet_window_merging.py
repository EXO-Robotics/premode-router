from __future__ import annotations

from pathlib import Path

from premode.evidence_snippets import estimate_tokens, extract_evidence_snippets
from premode.locator import LocatedFile


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _located(path: str, signals: list[str]) -> LocatedFile:
    return LocatedFile(path=path, score=100, role="primary", confidence="high", matched_signals=signals)


def test_one_line_shift_windows_merge_and_preserve_signal_attribution(repo: Path) -> None:
    lines = [f"line {line_number}" for line_number in range(1, 61)]
    lines[45] = "line 46 MergeAlpha"
    lines[46] = "line 47 MergeBeta"
    _write_lines(repo / "src" / "window.py", lines)

    packet = extract_evidence_snippets(
        repo,
        "MergeAlpha MergeBeta",
        primary_files=[
            _located(
                "src/window.py",
                ["symbol:MergeAlpha", "symbol:MergeBeta"],
            )
        ],
        snippet_budget_tokens=1000,
    )

    assert len(packet["snippets"]) == 1
    snippet = packet["snippets"][0]
    assert snippet["start_line"] == 43
    assert snippet["end_line"] == 50
    assert {"symbol:MergeAlpha", "symbol:MergeBeta"} <= set(snippet["matched_signals"])
    assert "MergeAlpha" in snippet["text"]
    assert "MergeBeta" in snippet["text"]

    duplicate_cost = estimate_tokens("\n".join(lines[42:49])) + estimate_tokens("\n".join(lines[43:50]))
    assert packet["model_facing_evidence_tokens"] < duplicate_cost


def test_far_apart_windows_remain_separate(repo: Path) -> None:
    lines = [f"line {line_number}" for line_number in range(1, 61)]
    lines[9] = "line 10 FarAlpha"
    lines[39] = "line 40 FarBeta"
    _write_lines(repo / "src" / "far.py", lines)

    packet = extract_evidence_snippets(
        repo,
        "FarAlpha FarBeta",
        primary_files=[_located("src/far.py", ["symbol:FarAlpha", "symbol:FarBeta"])],
        snippet_budget_tokens=1000,
    )

    ranges = [(snippet["start_line"], snippet["end_line"]) for snippet in packet["snippets"]]
    assert ranges == [(7, 13), (37, 43)]


def test_nearby_windows_merge_when_budget_permits(repo: Path) -> None:
    lines = [f"line {line_number}" for line_number in range(1, 61)]
    lines[0] = "line 1 NearAlpha"
    lines[7] = "line 8 NearBeta"
    _write_lines(repo / "src" / "near.py", lines)

    packet = extract_evidence_snippets(
        repo,
        "NearAlpha NearBeta",
        primary_files=[_located("src/near.py", ["symbol:NearAlpha", "symbol:NearBeta"])],
        snippet_budget_tokens=1000,
    )

    assert [(snippet["start_line"], snippet["end_line"]) for snippet in packet["snippets"]] == [(1, 11)]
