"""Generic, lazy policy dispatch for explicitly selected agent adapters."""

from __future__ import annotations

from typing import Any


def adapter_policy_from_detection(detection: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve adapter policy only after project detection selects an adapter."""
    active = detection.get("active_project", {}) if isinstance(detection, dict) else {}
    adapter = active.get("adapter")
    if adapter == "openclaw_control_plane":
        from .openclaw_adapter import openclaw_policy_from_detection

        return openclaw_policy_from_detection(detection)
    return None
