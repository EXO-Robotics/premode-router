from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal

from .context_contracts import ContextPacketV1


CoreRole = Literal["primary", "verification", "support"]

DEFAULT_CORE_INSTRUCTION = "Start with these files. Expand only when required by the task."
DEFAULT_FALLBACK_INSTRUCTION = "No likely files met the confidence threshold. Expand only as required by the task."


@dataclass(frozen=True)
class CorePath:
    path: str
    role: CoreRole | None = None
    anchor: str | None = None


def _clean_anchor(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) < 2:
        return None
    return text[:80]


def _normalized_paths(items: Iterable[CorePath]) -> list[CorePath]:
    normalized: list[CorePath] = []
    seen: set[str] = set()
    for item in items:
        path = str(item.path or "").strip()
        key = path.casefold()
        if not path or key in seen:
            continue
        role = item.role if item.role in {"primary", "verification", "support"} else None
        normalized.append(CorePath(path=path, role=role, anchor=_clean_anchor(item.anchor)))
        seen.add(key)
    return normalized


def _path_line(item: CorePath, exact_task: str) -> str:
    # If the entire task is itself the selected path, refer back to the TASK
    # field instead of duplicating the exact prompt bytes.
    path = "(same path as TASK)" if item.path == exact_task else item.path
    anchor = None if item.anchor == exact_task else item.anchor
    return f"* {path} :: {anchor}" if anchor else f"* {path}"


def render_core_packet(
    task: str,
    paths: Iterable[CorePath],
    *,
    instruction: str = DEFAULT_CORE_INSTRUCTION,
    fallback_instruction: str = DEFAULT_FALLBACK_INSTRUCTION,
) -> str:
    """Render the narrow deterministic model-facing pCodex packet."""

    exact_task = str(task)
    items = _normalized_paths(paths)
    lines = ["TASK", exact_task]
    if not items:
        lines.extend(["", fallback_instruction])
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(["LIKELY FILES", ""])
    if all(item.role is None for item in items):
        lines.extend(_path_line(item, exact_task) for item in items)
    else:
        unlabelled = [item for item in items if item.role is None]
        if unlabelled:
            lines.extend(_path_line(item, exact_task) for item in unlabelled)
        headings: tuple[tuple[CoreRole, str], ...] = (
            ("primary", "PRIMARY"),
            ("verification", "VERIFY"),
            ("support", "SUPPORT"),
        )
        for role, heading in headings:
            role_items = [item for item in items if item.role == role]
            if not role_items:
                continue
            if lines[-1] != "":
                lines.append("")
            lines.extend([heading, ""])
            lines.extend(_path_line(item, exact_task) for item in role_items)

    lines.extend(["", instruction])
    return "\n".join(lines).rstrip() + "\n"


def render_context_packet_v1(
    task: str,
    paths: Iterable[CorePath],
    *,
    instruction: str = DEFAULT_CORE_INSTRUCTION,
    fallback_instruction: str = DEFAULT_FALLBACK_INSTRUCTION,
) -> ContextPacketV1:
    """Return the typed logistics contract without changing packet rendering."""

    exact_task = str(task)
    rendered = render_core_packet(
        exact_task,
        paths,
        instruction=instruction,
        fallback_instruction=fallback_instruction,
    )
    return ContextPacketV1.from_task_and_packet(exact_task, rendered)


def core_packet_leakage(task: str, packet: str) -> dict[str, object]:
    generated = packet.replace(str(task), "", 1).casefold()
    forbidden_terms = (
        "audit receipt",
        "benchmark",
        "cache diagnostic",
        "experiment",
        "lab 7",
        "packet strategy",
        "selector",
        "selection_lock_hash",
        "topology",
        "tuning",
    )
    matched = [term for term in forbidden_terms if term in generated]
    return {
        "model_facing_diagnostic_leakage": bool(matched),
        "matched_terms": matched,
    }
