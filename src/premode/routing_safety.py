from __future__ import annotations

"""Compatibility shim for legacy imports.

The implementation lives in context_constraints.py. Legacy result fields still
use names such as safety_blocked_files for schema compatibility.
"""

from .context_constraints import *  # noqa: F403
