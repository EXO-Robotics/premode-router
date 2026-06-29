from __future__ import annotations

from datetime import datetime, timezone
import os


def now_utc() -> datetime:
    fixed = os.environ.get("PREMODE_TEST_FIXED_TIME")
    if fixed:
        text = fixed.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def timestamp_slug() -> str:
    return now_utc().strftime("%Y%m%dT%H%M%SZ")


def timestamp_iso() -> str:
    return now_utc().isoformat().replace("+00:00", "Z")
