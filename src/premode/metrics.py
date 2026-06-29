from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import premode_dir
from .timeutil import timestamp_iso


def ledger_path(repo_root: Path) -> Path:
    return premode_dir(repo_root) / "metrics" / "usage_ledger.jsonl"


def append_metric(repo_root: Path, record: dict[str, Any]) -> Path:
    path = ledger_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {"timestamp": timestamp_iso(), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(out, sort_keys=True) + "\n")
    return path


def read_metrics(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in [ledger_path(repo_root), premode_dir(repo_root) / "metrics" / "metrics.jsonl"]:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def last_metric(repo_root: Path) -> dict[str, Any]:
    rows = read_metrics(repo_root)
    return rows[-1] if rows else {"runs": 0, "ledger": str(ledger_path(repo_root))}


def summarize_savings(repo_root: Path, limit: int = 30) -> dict[str, Any]:
    rows = read_metrics(repo_root)[-limit:]
    eligible = sum(int(r.get("eligible_readable_repo_tokens") or r.get("estimated_raw_candidate_tokens") or r.get("raw_candidate_tokens") or 0) for r in rows)
    packet = sum(int(r.get("packet_total_tokens") or r.get("estimated_compiled_tokens") or r.get("estimated_tokens") or 0) for r in rows)
    full_text_tokens = sum(int(r.get("full_text_tokens") or 0) for r in rows)
    summary_tokens = sum(int(r.get("summary_tokens") or 0) for r in rows)
    manifest_tokens = sum(int(r.get("manifest_tokens") or 0) for r in rows)
    redactions = sum(int(r.get("redaction_count") or 0) for r in rows)
    actual_input = sum(int((r.get("actual_usage") or {}).get("input_tokens") or r.get("actual_input_tokens") or 0) for r in rows)
    actual_cached = sum(int((r.get("actual_usage") or {}).get("cached_input_tokens") or r.get("actual_cached_input_tokens") or 0) for r in rows)
    actual_output = sum(int((r.get("actual_usage") or {}).get("output_tokens") or r.get("actual_output_tokens") or 0) for r in rows)
    intents: dict[str, int] = {}
    for r in rows:
        name = str(r.get("primary_intent") or "unknown")
        intents[name] = intents.get(name, 0) + 1
    savings = None
    if eligible and packet:
        savings = round(max(0.0, (eligible - packet) / eligible) * 100, 4)
    return {
        "runs": len(rows),
        "eligible_readable_repo_tokens": eligible,
        "packet_total_tokens": packet,
        "estimated_savings_vs_eligible_repo_percent": savings,
        "full_text_tokens": full_text_tokens,
        "summary_tokens": summary_tokens,
        "manifest_tokens": manifest_tokens,
        "actual_input_tokens": actual_input or None,
        "actual_cached_input_tokens": actual_cached or None,
        "actual_output_tokens": actual_output or None,
        "redaction_count": redactions,
        "most_common_intent": max(intents.items(), key=lambda kv: kv[1])[0] if intents else None,
        "ledger": str(ledger_path(repo_root)),
        "note": "Aggregated savings compare packet tokens against eligible readable repository tokens. Use `premode stats --last` for the cleanest per-run view.",
    }
