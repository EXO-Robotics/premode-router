from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import premode_dir
from .timeutil import timestamp_iso, timestamp_slug


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_audit(repo_root: Path, event: str, raw_prompt_hash: str | None, record: dict[str, Any]) -> Path:
    audit_dir = premode_dir(repo_root) / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    prefix = (raw_prompt_hash or sha256_text(event))[:12]
    path = audit_dir / f"{timestamp_slug()}_{prefix}_{event}.json"
    safe_record = {
        "timestamp": timestamp_iso(),
        "event": event,
        "raw_prompt_sha256": raw_prompt_hash,
        **record,
    }
    path.write_text(json.dumps(safe_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
