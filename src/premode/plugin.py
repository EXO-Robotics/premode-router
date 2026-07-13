"""Deprecated compatibility entrypoint for canonical pCodex integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .codex_plugin import apply_integration


def install_local_plugin(repo_root: Path, scope: str = "repo") -> dict[str, Any]:
    """Install the canonical plugin without recreating the legacy plugin tree."""
    if scope != "repo":
        raise ValueError("beta supports repo scope only; use --scope repo")
    result = apply_integration(repo_root)
    return {
        **result,
        "deprecated_entrypoint": "premode plugin install-local",
        "canonical_command": "pcodex integrate codex --write",
        "plugin_root": str(repo_root / "plugins" / "pcodex"),
        "marketplace": str(repo_root / ".agents" / "plugins" / "marketplace.json"),
    }
