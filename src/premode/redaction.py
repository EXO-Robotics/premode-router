from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.MULTILINE,
)
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key_block", PRIVATE_KEY_RE),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{12,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("assignment_secret", re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret|client_secret|signing[_-]?key)\b\s*[:=]\s*[^\s'\"`]+")),
    ("sentinel_secret", re.compile(r"SECRET[_A-Z0-9-]{8,}")),
]
HIGH_ENTROPY_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{48,}\b")
PATH_LIKE_RE = re.compile(
    r"\b(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+\."
    r"(?:swift|py|md|json|toml|yaml|yml|log|trace|txt|ts|tsx|js|jsx|go|rs|java|kt|c|cpp|h|hpp|plist)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {ch: s.count(ch) for ch in set(s)}
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def redact_text(text: str) -> RedactionResult:
    counts: dict[str, int] = {}
    out = text
    for name, pattern in SECRET_PATTERNS:
        out, n = pattern.subn(f"[REDACTED:{name}]", out)
        if n:
            counts[name] = counts.get(name, 0) + n

    # Preserve source/log path-shaped strings before entropy redaction. Long Swift
    # and app paths can look high-entropy, but they are needed for path extraction
    # and are not secrets merely because they are long.
    preserved_paths: dict[str, str] = {}

    def preserve_path(match: re.Match[str]) -> str:
        key = f"§PREMODE_PATH_{len(preserved_paths)}§"
        preserved_paths[key] = match.group(0)
        return key

    out = PATH_LIKE_RE.sub(preserve_path, out)

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        # Do not redact harmless repeated filler strings like AAAAA... used in truncation tests.
        if len(set(token)) <= 4:
            return token
        if _entropy(token) >= 4.2:
            counts["high_entropy"] = counts.get("high_entropy", 0) + 1
            return "[REDACTED:high_entropy]"
        return token

    out = HIGH_ENTROPY_RE.sub(repl, out)
    for key, value in preserved_paths.items():
        out = out.replace(key, value)
    return RedactionResult(out, counts)


def merge_redaction_counts(items: Iterable[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        for k, v in item.items():
            merged[k] = merged.get(k, 0) + int(v)
    return merged
