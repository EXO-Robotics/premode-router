from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any, Iterable

from .ignore import IgnoreMatcher
from .locator import LocatedFile, is_scaffold_meta_term
from .safe_reader import safe_read


DEFAULT_SNIPPET_BUDGET_TOKENS = 2000
MAX_SNIPPET_BUDGET_TOKENS = 4000
TOKEN_BYTES = 4
NEARBY_WINDOW_MERGE_THRESHOLD_LINES = 2
MAX_MERGED_SNIPPET_LINES = 11
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
OPTION_RE = re.compile(r"--[A-Za-z0-9][A-Za-z0-9_-]*")
SYMBOL_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]{2,}\b|\b[a-zA-Z_][a-zA-Z0-9_]+(?:[_-][a-zA-Z0-9_]+)+\b")
PATH_RE = re.compile(r"(?<![A-Za-z0-9_./-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+")
QUOTED_RE = re.compile(r'"([^"\n]{2,120})"|\'([^\'\n]{2,120})\'')
NO_INTERPRETATION_RE = re.compile(r"\b(?:this means|correct behavior|should be|should edit|risky|risk)\b", re.IGNORECASE)


@dataclass
class EvidenceSnippet:
    path: str
    start_line: int
    end_line: int
    matched_signals: list[str]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "matched_signals": list(self.matched_signals),
            "text": self.text,
        }


def estimate_tokens(text: str) -> int:
    return max(1, len(text.encode("utf-8", errors="replace")) // TOKEN_BYTES)


def clamp_snippet_budget(value: int | None) -> int:
    if value is None:
        return DEFAULT_SNIPPET_BUDGET_TOKENS
    return max(0, min(MAX_SNIPPET_BUDGET_TOKENS, int(value)))


def _path_of(item: LocatedFile | dict[str, Any] | str) -> str:
    if isinstance(item, LocatedFile):
        return item.path
    if isinstance(item, dict):
        return str(item.get("path") or "")
    return str(item or "")


def _signals_of(item: LocatedFile | dict[str, Any] | str) -> list[str]:
    if isinstance(item, LocatedFile):
        return list(item.matched_signals or [])
    if isinstance(item, dict):
        signals = item.get("matched_signals") or item.get("evidence_flags") or []
        return [str(signal) for signal in signals]
    return []


def _signal_terms(signals: Iterable[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for signal in signals:
        text = str(signal)
        if ":" not in text:
            continue
        kind, raw = text.split(":", 1)
        if kind in {"quoted_literal", "symbol", "symbol_term", "content", "path", "option_flag", "option_decl", "option_use", "option_default", "option_choices", "option_value_evidence", "behavior_source", "artifact_terms", "content_cluster"}:
            for value in re.split(r"[,|]", raw.strip().strip("\"'")):
                clean = value.strip().strip("\"'")
                if len(clean) >= 2 and not is_scaffold_meta_term(clean):
                    pairs.append((f"{kind}:{clean}", clean))
    return pairs


def _prompt_terms(prompt: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for path in PATH_RE.findall(prompt or ""):
        if not is_scaffold_meta_term(path):
            pairs.append((f"path:{path}", path))
    for flag in OPTION_RE.findall(prompt or ""):
        pairs.append((f"option_flag:{flag}", flag))
    for quoted in [a or b for a, b in QUOTED_RE.findall(prompt or "")]:
        clean = quoted.strip()
        if clean and not is_scaffold_meta_term(clean):
            pairs.append((f"quoted_literal:{clean}", clean))
    for symbol in SYMBOL_RE.findall(prompt or ""):
        if not is_scaffold_meta_term(symbol):
            pairs.append((f"symbol:{symbol}", symbol))
    return _dedupe_pairs(pairs)


def _dedupe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for signal, term in pairs:
        key = (signal.lower(), term.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((signal, term))
    return out


def _term_priority(pair: tuple[str, str]) -> tuple[int, str]:
    signal, term = pair
    if signal.startswith(("option_flag:", "option_decl:", "option_use:", "option_default:", "option_choices:", "option_value_evidence:")):
        return (0, term.lower())
    if signal.startswith(("quoted_literal:", "literal:", "symbol:", "symbol_term:")):
        return (1, term.lower())
    if signal.startswith(("behavior_source:", "artifact_terms:", "content_cluster:")):
        return (2, term.lower())
    return (3, term.lower())


def _line_matches(line: str, term: str) -> bool:
    if not term:
        return False
    if _is_code_like_match_term(term):
        return term in line
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", line, re.IGNORECASE))


def _is_code_like_match_term(term: str) -> bool:
    if term.startswith("--") or "/" in term or "\\" in term:
        return True
    if "." in term or "::" in term:
        return True
    if "_" in term or "-" in term:
        return True
    return bool(re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", term))


def _snippet_window(lines: list[str], line_index: int, *, radius: int = 3) -> tuple[int, int, str]:
    start = max(0, line_index - radius)
    end = min(len(lines), line_index + radius + 1)
    text = "\n".join(lines[start:end]).strip("\n")
    return start + 1, end, text


def _line_gap(left: EvidenceSnippet, right: EvidenceSnippet) -> int:
    if left.path != right.path:
        return 10**9
    if right.start_line > left.end_line:
        return right.start_line - left.end_line - 1
    if left.start_line > right.end_line:
        return left.start_line - right.end_line - 1
    return 0


def _merged_snippet(left: EvidenceSnippet, right: EvidenceSnippet, lines: list[str]) -> EvidenceSnippet:
    start = min(left.start_line, right.start_line)
    end = max(left.end_line, right.end_line)
    text = "\n".join(lines[start - 1 : end]).strip("\n")
    return EvidenceSnippet(
        path=left.path,
        start_line=start,
        end_line=end,
        matched_signals=_dedupe([*left.matched_signals, *right.matched_signals])[:12],
        text=text,
    )


def _merge_snippet_windows(
    snippets: list[EvidenceSnippet],
    lines_by_path: dict[str, list[str]],
    *,
    budget_tokens: int | None,
) -> list[EvidenceSnippet]:
    if len(snippets) < 2:
        return snippets

    budget = clamp_snippet_budget(budget_tokens)
    ordered = sorted(snippets, key=lambda snippet: (snippet.path, snippet.start_line, snippet.end_line))
    merged: list[EvidenceSnippet] = []
    current = ordered[0]
    for snippet in ordered[1:]:
        lines = lines_by_path.get(current.path)
        gap = _line_gap(current, snippet)
        can_consider = lines is not None and current.path == snippet.path and gap <= NEARBY_WINDOW_MERGE_THRESHOLD_LINES
        if not can_consider:
            merged.append(current)
            current = snippet
            continue

        candidate = _merged_snippet(current, snippet, lines)
        candidate_cost = estimate_tokens(candidate.text)
        compact_enough = candidate.end_line - candidate.start_line + 1 <= MAX_MERGED_SNIPPET_LINES
        overlaps = snippet.start_line <= current.end_line and current.start_line <= snippet.end_line
        budget_permits = budget > 0 and candidate_cost <= budget
        if compact_enough and (overlaps or budget_permits):
            current = candidate
            continue

        merged.append(current)
        current = snippet

    merged.append(current)
    return merged


def _snippets_for_file(
    repo_root: Path,
    file: LocatedFile | dict[str, Any] | str,
    *,
    prompt: str,
    max_snippets: int,
    ignore: IgnoreMatcher,
    merge_budget_tokens: int | None = None,
) -> list[EvidenceSnippet]:
    path = _path_of(file)
    if not path:
        return []
    read = safe_read(repo_root, path, caps=None, ignore=ignore, max_bytes=32_000, purpose="evidence_snippet")
    if not read.allowed or not read.content:
        return []
    lines = read.content.splitlines()
    signals = _signals_of(file)
    terms = sorted(_dedupe_pairs(_signal_terms(signals) + _prompt_terms(prompt)), key=_term_priority)
    snippets: list[EvidenceSnippet] = []
    seen_windows: set[tuple[int, int]] = set()
    candidate_limit = max(max_snippets * 8, max_snippets)
    for signal, term in terms:
        for idx, line in enumerate(lines):
            if not _line_matches(line, term):
                continue
            start, end, text = _snippet_window(lines, idx)
            if not text or (start, end) in seen_windows:
                continue
            seen_windows.add((start, end))
            matched = [signal]
            for other_signal, other_term in terms:
                if other_signal != signal and other_term and any(_line_matches(snippet_line, other_term) for snippet_line in text.splitlines()):
                    matched.append(other_signal)
            snippets.append(EvidenceSnippet(path=path, start_line=start, end_line=end, matched_signals=_dedupe(matched)[:12], text=text))
            if len(snippets) >= candidate_limit:
                return _merge_snippet_windows(snippets, {path: lines}, budget_tokens=merge_budget_tokens)[:max_snippets]
    return _merge_snippet_windows(snippets, {path: lines}, budget_tokens=merge_budget_tokens)[:max_snippets]


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def _budgeted(snippets: list[EvidenceSnippet], budget_tokens: int) -> tuple[list[EvidenceSnippet], int]:
    budget = clamp_snippet_budget(budget_tokens)
    if budget <= 0:
        return [], 0
    kept: list[EvidenceSnippet] = []
    used = 0
    for snippet in snippets:
        token_cost = estimate_tokens(snippet.text)
        if used + token_cost > budget:
            continue
        kept.append(snippet)
        used += token_cost
    return kept, used


def attach_snippets_to_files(
    repo_root: Path,
    files: list[LocatedFile],
    *,
    prompt: str,
    snippet_budget_tokens: int = DEFAULT_SNIPPET_BUDGET_TOKENS,
    max_files: int | None = None,
    max_snippets_per_file: int = 3,
) -> tuple[list[dict[str, Any]], int]:
    ignore = IgnoreMatcher.from_repo(repo_root)
    all_snippets: list[EvidenceSnippet] = []
    selected_files = files[: max_files or len(files)]
    for file in selected_files:
        all_snippets.extend(
            _snippets_for_file(
                repo_root,
                file,
                prompt=prompt,
                max_snippets=max_snippets_per_file,
                ignore=ignore,
                merge_budget_tokens=snippet_budget_tokens,
            )
        )
    budgeted, used_tokens = _budgeted(all_snippets, snippet_budget_tokens)
    by_path: dict[str, list[dict[str, Any]]] = {}
    for snippet in budgeted:
        by_path.setdefault(snippet.path, []).append(snippet.to_dict())
    out: list[dict[str, Any]] = []
    for file in files:
        path = file.path
        out.append(
            {
                "path": path,
                "score": file.score,
                "confidence": file.confidence,
                "matched_signals": list(file.matched_signals),
                "snippets": by_path.get(path, []),
            }
        )
    return out, used_tokens


def extract_evidence_snippets(
    repo_root: Path,
    prompt: str,
    *,
    primary_files: list[LocatedFile] | None = None,
    support_files: list[LocatedFile] | None = None,
    verification_files: list[LocatedFile] | None = None,
    snippet_budget_tokens: int = DEFAULT_SNIPPET_BUDGET_TOKENS,
) -> dict[str, Any]:
    ordered: list[tuple[str, LocatedFile]] = []
    for bucket, files in (
        ("candidate_primary", primary_files or []),
        ("support", support_files or []),
        ("verification", verification_files or []),
    ):
        for file in files:
            ordered.append((bucket, file))
    ignore = IgnoreMatcher.from_repo(repo_root)
    snippets: list[tuple[str, EvidenceSnippet]] = []
    for bucket, file in ordered:
        per_file = 3 if bucket == "candidate_primary" else 1
        for snippet in _snippets_for_file(repo_root, file, prompt=prompt, max_snippets=per_file, ignore=ignore, merge_budget_tokens=snippet_budget_tokens):
            snippets.append((bucket, snippet))

    priority = {"candidate_primary": 0, "support": 3, "verification": 4}
    snippets.sort(key=lambda item: (priority.get(item[0], 9), item[1].path, item[1].start_line))
    kept, used_tokens = _budgeted([snippet for _, snippet in snippets], snippet_budget_tokens)
    return {
        "snippets": [snippet.to_dict() for snippet in kept],
        "model_facing_evidence_tokens": used_tokens,
        "snippet_budget_tokens": clamp_snippet_budget(snippet_budget_tokens),
        "omitted_snippet_count": max(0, len(snippets) - len(kept)),
        "policy": "factual_retrieved_evidence_only",
    }


def has_interpretive_snippet_text(snippets: Iterable[dict[str, Any]]) -> bool:
    return any(NO_INTERPRETATION_RE.search(str(snippet.get("text") or "")) for snippet in snippets)
