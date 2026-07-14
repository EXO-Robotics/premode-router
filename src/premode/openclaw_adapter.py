"""OpenClaw-specific authority policy isolated from general repository routing."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any


OPENCLAW_AUTHORITY_MARKERS: tuple[str, ...] = (
    "AGENTS.md",
    "WORKFLOW.md",
    "PROJECT/tasks.json",
    "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    "PROJECT/state/worker_start/WORKER_STARTER_CONTEXT_V1.json",
    "PROJECT/state/task_queue_normalized_latest.json",
    "PROJECT/state/path_authority_latest.json",
    "PROJECT/state/artifact_authority_latest.json",
    "PROJECT/AI/OUTPUT_HYGIENE_GUARDRAILS.md",
    "ARTIFACT_STORAGE.md",
    "EXTERNAL_ARTIFACTS_INDEX.md",
)

OPENCLAW_EVIDENCE_ONLY_PATTERNS: tuple[str, ...] = (
    "_claw_output/",
    "PROJECT/state/history/",
    "PROJECT/state/archive/",
    "PROJECT/artifacts/generated/",
    "logs/",
    "proof/",
    "proofs/",
)

OPENCLAW_DANGEROUS_MUTATION_ZONES: tuple[str, ...] = (
    "PROJECT/tasks.json",
    "PROJECT/state/task_queue_normalized_latest.json",
    "PROJECT/state/path_authority_latest.json",
    "PROJECT/state/artifact_authority_latest.json",
    "_claw_output/",
    "Content/",
    "*.uasset",
    "*.umap",
    "*.blend",
)

OPENCLAW_PROOF_POLICY: dict[str, bool] = {
    "do_not_claim_runtime_from_static_or_browser_evidence": True,
    "do_not_claim_collision_or_input_proof_without_same_run_evidence": True,
    "do_not_mutate_bridge_unreal_or_blender_without_authorization": True,
    "do_not_mutate_project_task_queue_without_authorization": True,
    "do_not_treat_historical_proof_as_current_truth": True,
    "human_review_required_for_public_synthesis": True,
}

OPENCLAW_GOVERNANCE_MARKERS = ("AGENTS.md", "WORKFLOW.md")
OPENCLAW_CURRENT_AUTHORITY_MARKERS = (
    "PROJECT/tasks.json",
    "PROJECT/state/task_queue_normalized_latest.json",
    "PROJECT/state/path_authority_latest.json",
    "PROJECT/state/artifact_authority_latest.json",
)
OPENCLAW_WORKER_MARKERS = (
    "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    "PROJECT/state/worker_start/WORKER_STARTER_CONTEXT_V1.json",
    "PROJECT/AI/tools/gamebot/task_queue.py",
    "tools/gamebot/task_queue.py",
)
OPENCLAW_SECRET_PATTERNS = (
    ".env",
    ".env.",
    "secrets/",
    "credentials/",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".key",
)


class OpenClawAdapterError(ValueError):
    """OpenClaw policy cannot safely project the provider result."""


@dataclass(frozen=True)
class OpenClawWorkspaceQualification:
    qualified: bool
    reason: str
    governance_markers: tuple[str, ...]
    current_authority_markers: tuple[str, ...]
    worker_markers: tuple[str, ...]


@dataclass(frozen=True)
class OpenClawPathPolicy:
    path: str
    authority_class: str
    surface: str
    mutation_policy: str
    explicitly_task_named: bool
    reason_codes: tuple[str, ...]
    include: bool = True


def _present_markers(root: Path, markers: tuple[str, ...]) -> tuple[str, ...]:
    present: list[str] = []
    for marker in markers:
        candidate = root / marker
        try:
            info = candidate.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise OpenClawAdapterError(
                "cannot inspect OpenClaw workspace marker safely"
            ) from exc
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            continue
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
        except OSError:
            continue
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                continue
        finally:
            os.close(descriptor)
        present.append(marker)
    return tuple(present)


def qualify_openclaw_workspace(root: Path) -> OpenClawWorkspaceQualification:
    """Require three independent marker families at the immutable bound root."""

    resolved = root.resolve(strict=True)
    if resolved != root or not root.is_dir():
        raise OpenClawAdapterError("OpenClaw workspace must be a resolved directory")
    governance = _present_markers(root, OPENCLAW_GOVERNANCE_MARKERS)
    authority = _present_markers(root, OPENCLAW_CURRENT_AUTHORITY_MARKERS)
    workers = _present_markers(root, OPENCLAW_WORKER_MARKERS)
    missing = [
        name
        for name, values in (
            ("governance", governance),
            ("current_authority", authority),
            ("worker_surface", workers),
        )
        if not values
    ]
    return OpenClawWorkspaceQualification(
        qualified=not missing,
        reason="qualified" if not missing else "missing_" + "_and_".join(missing),
        governance_markers=governance,
        current_authority_markers=authority,
        worker_markers=workers,
    )


def _normalized_relative_path(root: Path, value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(
            (ord(character) < 32 and character not in "\t") or ord(character) == 127
            for character in value
        )
    ):
        raise OpenClawAdapterError("provider returned an invalid path")
    normalized = value.strip().replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts or normalized.startswith("//"):
        raise OpenClawAdapterError("provider path escapes the bound workspace")
    path = pure.as_posix()
    if path in {"", "."} or re.match(r"^[A-Za-z]:", path):
        raise OpenClawAdapterError("provider path is not repository-relative")
    candidate = root / path
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError, RuntimeError) as exc:
        raise OpenClawAdapterError("provider path escapes through a symlink") from exc
    return path


def _task_names_exact_path(exact_task: str, path: str) -> bool:
    normalized_task = exact_task.replace("\\", "/")
    return (
        re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(path)}(?![A-Za-z0-9_.-])",
            normalized_task,
        )
        is not None
    )


def classify_openclaw_path(
    root: Path, exact_task: str, value: str
) -> OpenClawPathPolicy:
    path = _normalized_relative_path(root, value)
    lower = path.casefold()
    named = _task_names_exact_path(exact_task, path)
    reasons: list[str] = []

    if any(
        lower == pattern
        or lower.startswith(pattern)
        or (pattern.startswith(".") and lower.endswith(pattern))
        for pattern in OPENCLAW_SECRET_PATTERNS
    ):
        return OpenClawPathPolicy(
            path, "unknown", "general", "forbidden", named, ("sensitive_path",), False
        )
    if any(
        part in {"node_modules", ".git", "saved", "intermediate", "binaries"}
        for part in PurePosixPath(lower).parts
    ):
        return OpenClawPathPolicy(
            path,
            "generated_evidence",
            "nested_executor",
            "forbidden",
            named,
            ("generated_or_dependency_tree",),
            False,
        )

    historical = lower.startswith(("project/state/history/", "project/state/archive/"))
    generated = lower.startswith(
        ("_claw_output/", "project/artifacts/generated/", "logs/", "proof/", "proofs/")
    )
    if historical or generated:
        authority = "historical_evidence" if historical else "generated_evidence"
        reasons.append(
            "explicit_task_named_evidence"
            if named
            else "unmentioned_noncurrent_evidence"
        )
        return OpenClawPathPolicy(
            path,
            authority,
            "control_plane",
            "read_only" if named else "forbidden",
            named,
            tuple(reasons),
            named,
        )

    suffix = PurePosixPath(lower).suffix
    if suffix in {".uasset", ".umap"} or lower.startswith("content/"):
        return OpenClawPathPolicy(
            path,
            "unknown",
            "unreal_asset",
            "explicit_authorization_required",
            named,
            ("binary_unreal_asset",),
            named,
        )
    if suffix == ".blend":
        return OpenClawPathPolicy(
            path,
            "unknown",
            "blender_asset",
            "explicit_authorization_required",
            named,
            ("binary_blender_asset",),
            named,
        )
    if lower in {marker.casefold() for marker in OPENCLAW_CURRENT_AUTHORITY_MARKERS}:
        return OpenClawPathPolicy(
            path,
            "current_authority",
            "state_authority",
            "explicit_authorization_required",
            named,
            ("current_control_plane_authority",),
            True,
        )
    if lower in {marker.casefold() for marker in OPENCLAW_GOVERNANCE_MARKERS}:
        return OpenClawPathPolicy(
            path,
            "current_authority",
            "control_plane",
            "read_only",
            named,
            ("governance_authority",),
            True,
        )

    if lower.startswith("source/") or suffix in {".cpp", ".h", ".cs", ".uproject"}:
        surface = "unreal_source"
    elif "blender" in lower and suffix in {".py", ".toml", ".json"}:
        surface = "blender_pipeline"
    elif any(
        part in {"web", "node", "executor", "bridge"}
        for part in PurePosixPath(lower).parts
    ):
        surface = (
            "bridge" if "bridge" in PurePosixPath(lower).parts else "nested_executor"
        )
    elif "task_queue" in lower:
        surface = "task_queue"
    else:
        surface = "general"
    validation = any(
        part in {"test", "tests", "spec", "specs", "schemas", "workflows"}
        for part in PurePosixPath(lower).parts
    ) or PurePosixPath(lower).name.startswith("test_")
    return OpenClawPathPolicy(
        path,
        "validation_surface" if validation else "authored_source",
        surface,
        "eligible",
        named,
        ("validation_surface" if validation else "authored_source",),
        True,
    )


def dangerous_mutation_zones() -> tuple[dict[str, str], ...]:
    return (
        {
            "path_pattern": "PROJECT/tasks.json",
            "surface": "task_queue",
            "mutation_policy": "explicit_authorization_required",
            "reason_code": "current_control_plane_authority",
        },
        {
            "path_pattern": "PROJECT/state/*_latest.json",
            "surface": "state_authority",
            "mutation_policy": "explicit_authorization_required",
            "reason_code": "current_control_plane_authority",
        },
        {
            "path_pattern": "_claw_output/**",
            "surface": "control_plane",
            "mutation_policy": "forbidden",
            "reason_code": "generated_evidence",
        },
        {
            "path_pattern": "**/*.uasset",
            "surface": "unreal_asset",
            "mutation_policy": "explicit_authorization_required",
            "reason_code": "binary_unreal_asset",
        },
        {
            "path_pattern": "**/*.umap",
            "surface": "unreal_asset",
            "mutation_policy": "explicit_authorization_required",
            "reason_code": "binary_unreal_asset",
        },
        {
            "path_pattern": "**/*.blend",
            "surface": "blender_asset",
            "mutation_policy": "explicit_authorization_required",
            "reason_code": "binary_blender_asset",
        },
        {
            "path_pattern": "**/node_modules/**",
            "surface": "nested_executor",
            "mutation_policy": "forbidden",
            "reason_code": "dependency_tree",
        },
        {
            "path_pattern": "**/.env*",
            "surface": "general",
            "mutation_policy": "forbidden",
            "reason_code": "sensitive_path",
        },
    )


def is_openclaw_authority_path(path: str) -> bool:
    lower = path.strip("/").lower()
    return any(lower == marker.lower() for marker in OPENCLAW_AUTHORITY_MARKERS)


def is_openclaw_evidence_only_path(path: str) -> bool:
    lower = path.strip("/").lower()
    return any(
        lower.startswith(pattern.lower())
        or (pattern.startswith("*") and lower.endswith(pattern[1:].lower()))
        for pattern in OPENCLAW_EVIDENCE_ONLY_PATTERNS
    )


def openclaw_policy_from_detection(detection: dict[str, Any]) -> dict[str, Any] | None:
    """Return policy only when the OpenClaw adapter was explicitly selected."""
    active = detection.get("active_project", {}) if isinstance(detection, dict) else {}
    if active.get("adapter") != "openclaw_control_plane":
        return None
    return {
        "authority_model": "proof_governed_control_plane",
        "authority_surfaces": list(OPENCLAW_AUTHORITY_MARKERS),
        "evidence_only_patterns": list(OPENCLAW_EVIDENCE_ONLY_PATTERNS),
        "dangerous_mutation_zones": list(OPENCLAW_DANGEROUS_MUTATION_ZONES),
        "proof_policy": dict(OPENCLAW_PROOF_POLICY),
        "notes": [
            "Current authority surfaces outrank historical/generated proof artifacts.",
            "Generated proof/log folders are evidence-only unless explicitly task-named.",
            "Bridge, Unreal, Blender, and task-queue mutation require explicit authorization.",
        ],
    }
