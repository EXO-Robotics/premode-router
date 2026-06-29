from __future__ import annotations

from dataclasses import dataclass, asdict
import os
import platform
import subprocess
from typing import Literal

ProfileName = Literal["lite", "standard", "pro", "auto"]


@dataclass(frozen=True)
class ResourceCaps:
    name: str
    max_index_files: int
    max_file_bytes: int
    max_log_bytes: int
    max_total_selected_context_bytes: int
    max_git_diff_bytes: int
    hard_packet_token_budget: int
    hard_full_text_file_count: int
    hard_summary_count: int
    hard_manifest_count: int
    hard_log_line_count: int
    max_full_text_file_tokens: int = 5000

    def to_dict(self) -> dict:
        return asdict(self)


PROFILES: dict[str, ResourceCaps] = {
    "lite": ResourceCaps(
        name="lite",
        max_index_files=5000,
        max_file_bytes=65536,
        max_log_bytes=131072,
        max_total_selected_context_bytes=750000,
        max_git_diff_bytes=200000,
        hard_packet_token_budget=12000,
        hard_full_text_file_count=8,
        hard_summary_count=20,
        hard_manifest_count=60,
        hard_log_line_count=80,
        max_full_text_file_tokens=5000,
    ),
    "standard": ResourceCaps(
        name="standard",
        max_index_files=20000,
        max_file_bytes=131072,
        max_log_bytes=524288,
        max_total_selected_context_bytes=2000000,
        max_git_diff_bytes=500000,
        hard_packet_token_budget=20000,
        hard_full_text_file_count=14,
        hard_summary_count=40,
        hard_manifest_count=120,
        hard_log_line_count=80,
        max_full_text_file_tokens=8000,
    ),
    "pro": ResourceCaps(
        name="pro",
        max_index_files=100000,
        max_file_bytes=262144,
        max_log_bytes=2097152,
        max_total_selected_context_bytes=6000000,
        max_git_diff_bytes=1500000,
        hard_packet_token_budget=40000,
        hard_full_text_file_count=24,
        hard_summary_count=80,
        hard_manifest_count=240,
        hard_log_line_count=120,
        max_full_text_file_tokens=12000,
    ),
}


def detect_available_memory_mb() -> int | None:
    """Best-effort available RAM detection without third-party dependencies."""
    meminfo = "/proc/meminfo"
    if os.path.exists(meminfo):
        try:
            values: dict[str, int] = {}
            with open(meminfo, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        values[parts[0].rstrip(":")] = int(parts[1])
            if "MemAvailable" in values:
                return values["MemAvailable"] // 1024
            if "MemTotal" in values:
                return values["MemTotal"] // 1024
        except OSError:
            pass

    if platform.system() == "Darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return int(out) // (1024 * 1024)
        except Exception:
            return None

    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size // (1024 * 1024))
    except Exception:
        return None


def choose_auto_profile(available_mb: int | None = None) -> str:
    if available_mb is None:
        available_mb = detect_available_memory_mb()
    if available_mb is None:
        return "standard"
    if available_mb < 12 * 1024:
        return "lite"
    if available_mb < 28 * 1024:
        return "standard"
    return "pro"


def resolve_profile(name: str | None, config: dict | None = None) -> ResourceCaps:
    selected = name or (config or {}).get("resource_profile") or "auto"
    if selected == "auto":
        selected = choose_auto_profile()
    if selected not in PROFILES:
        raise ValueError(f"Unknown resource profile: {selected}")
    base = PROFILES[selected]
    overrides = ((config or {}).get("profile_overrides") or {}).get(selected, {})
    if not overrides:
        return base
    data = base.to_dict()
    data.update({k: int(v) for k, v in overrides.items() if k in data and k != "name"})
    return ResourceCaps(**data)


def recommend_profile() -> dict:
    available = detect_available_memory_mb()
    selected = choose_auto_profile(available)
    return {
        "available_memory_mb": available,
        "recommended_profile": selected,
        "profile": selected,
        "caps": PROFILES[selected].to_dict(),
    }
