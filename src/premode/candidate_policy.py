from __future__ import annotations

"""Authoritative, content-free candidate admissibility policy.

The policy deliberately answers only whether a repository path may enter routing.
It does not score candidates and none of its audit fields are model-facing.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from .context_constraints import is_sensitive_or_secret_path
from .ignore import IgnoreMatcher
from .safe_reader import is_secret_name


class CandidateClassification(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_IF_EXPLICIT = "ALLOW_IF_EXPLICIT"
    SUPPORT_ONLY = "SUPPORT_ONLY"
    GENERATED_EXCEPTION = "GENERATED_EXCEPTION"
    DENY_RUNTIME = "DENY_RUNTIME"
    DENY_SECRET = "DENY_SECRET"
    DENY_IGNORED = "DENY_IGNORED"
    DENY_OUTSIDE_ROOT = "DENY_OUTSIDE_ROOT"
    DENY_SYMLINK_ESCAPE = "DENY_SYMLINK_ESCAPE"


HARD_DENIALS = frozenset(
    {
        CandidateClassification.DENY_OUTSIDE_ROOT,
        CandidateClassification.DENY_SYMLINK_ESCAPE,
        CandidateClassification.DENY_SECRET,
        CandidateClassification.DENY_RUNTIME,
    }
)

RUNTIME_ROOT_SEGMENTS = frozenset(
    {
        ".git",
        ".pcodex",
        ".premode",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "__pycache__",
        "_claw_output",
        "premode_labs",
        "observer_evidence",
        "observer-runs",
        "pcodex_audit",
        "pcodex_receipts",
    }
)
RUNTIME_PROVENANCE = frozenset(
    {
        "audit_ledger",
        "benchmark_artifact",
        "observer_run",
        "package_build_output",
        "runtime_packet_receipt",
        "temporary_packet",
        "tool_cache",
    }
)
RUNTIME_FILE_NAMES = frozenset(
    {
        "pcodex_state.json",
        "cache_manifest.json",
        "lcc.lock.json",
        "packet_receipt.json",
        "runtime_packet.json",
    }
)
GENERATED_SEGMENTS = frozenset(
    {
        "build",
        "dist",
        "generated",
        "__generated__",
        "gen",
        "node_modules",
        "out",
        "target",
        "vendor",
        "vendors",
        "third_party",
        "deriveddata",
    }
)


@dataclass(frozen=True)
class CandidateAdmissibility:
    normalized_path: str
    original_path: str
    provenance_source: str
    provenance_chain: tuple[str, ...]
    classification: CandidateClassification
    policy_rules_evaluated: tuple[str, ...]
    explicit_path: bool
    generated_intent: bool
    support_only: bool
    final_disposition: str

    @property
    def candidate_id(self) -> str:
        return hashlib.sha256(f"candidate_policy.v1\0{self.normalized_path.casefold()}".encode("utf-8")).hexdigest()

    @property
    def final_admissibility(self) -> str | None:
        if self.classification == CandidateClassification.ALLOW:
            return "ALLOW"
        if self.classification == CandidateClassification.ALLOW_IF_EXPLICIT and self.explicit_path:
            return "ALLOW_IF_EXPLICIT_SATISFIED"
        if self.classification == CandidateClassification.SUPPORT_ONLY and self.support_only:
            return "SUPPORT_ONLY_QUALIFIED"
        if self.classification == CandidateClassification.GENERATED_EXCEPTION and self.generated_intent:
            return "GENERATED_EXCEPTION_QUALIFIED"
        return None

    @property
    def final_policy_receipt(self) -> dict[str, object]:
        payload = {
            "policy_version": "candidate_policy.v1",
            "candidate_id": self.candidate_id,
            "normalized_path": self.normalized_path,
            "classification": self.classification.value,
            "final_admissibility": self.final_admissibility,
            "rules_evaluated": list(self.policy_rules_evaluated),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {**payload, "receipt_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}

    @property
    def admitted(self) -> bool:
        return self.final_admissibility is not None

    def to_metadata(self) -> dict[str, object]:
        return {
            "normalized_path": self.normalized_path,
            "original_path": self.original_path,
            "candidate_id": self.candidate_id,
            "provenance_source": self.provenance_source,
            "provenance_sources": list(self.provenance_chain),
            "provenance_chain": list(self.provenance_chain),
            "admissibility_classification": self.classification.value,
            "policy_rules_evaluated": list(self.policy_rules_evaluated),
            "explicit_path": self.explicit_path,
            "generated_intent": self.generated_intent,
            "support_only": self.support_only,
            "final_disposition": self.final_disposition,
            "final_admissibility": self.final_admissibility,
            "final_policy_receipt": self.final_policy_receipt,
        }


def _chain(provenance: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(provenance, str):
        values = (provenance,)
    else:
        values = tuple(str(value) for value in provenance)
    return tuple(dict.fromkeys(value for value in values if value)) or ("legacy_adapter",)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _host_normalized_relative(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return os.path.normcase(relative).replace("\\", "/")


def _explicit_paths(task_context: Mapping[str, object] | None) -> tuple[str, ...]:
    if not task_context:
        return ()
    raw = task_context.get("explicit_paths") or ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(item) for item in raw if str(item))


def _looks_generated(rel_path: str) -> bool:
    parts = tuple(part.lower() for part in PurePosixPath(rel_path).parts)
    name = parts[-1] if parts else ""
    return bool(
        set(parts) & GENERATED_SEGMENTS
        or ".generated." in name
        or ".gen." in name
    )


def _looks_runtime(rel_path: str, provenance_chain: tuple[str, ...]) -> bool:
    parts = tuple(part.lower() for part in PurePosixPath(rel_path).parts)
    name = parts[-1] if parts else ""
    if set(parts) & RUNTIME_ROOT_SEGMENTS:
        return True
    if set(provenance_chain) & RUNTIME_PROVENANCE:
        return True
    return name in RUNTIME_FILE_NAMES and any(part in {"tmp", "audit", "receipts", "runtime"} for part in parts[:-1])


def evaluate_candidate(
    repository_root: Path,
    candidate_path: str | Path,
    provenance: str | Sequence[str],
    task_context: Mapping[str, object] | None = None,
    repository_state: Mapping[str, object] | None = None,
) -> CandidateAdmissibility:
    """Classify one path using the frozen precedence lattice.

    ``repository_state`` may supply an ``ignore_matcher``. All other inputs are
    ordinary immutable values, making repeated evaluations deterministic for a
    fixed filesystem state.
    """

    root = Path(repository_root).resolve(strict=False)
    original = str(candidate_path)
    chain = _chain(provenance)
    source = chain[0]
    explicit_hint = "explicit_prompt_path" in chain or original in _explicit_paths(task_context)
    generated_hint = bool((task_context or {}).get("generated_intent"))
    support_hint = bool((task_context or {}).get("support_only")) or "support_relation" in chain
    rules: list[str] = ["normalize", "root_boundary"]

    raw = Path(candidate_path)
    lexical = Path(os.path.abspath(os.path.normpath(str(raw if raw.is_absolute() else root / raw))))
    normalized_path = original.replace("\\", "/")
    if not _is_within(lexical, root):
        return CandidateAdmissibility(
            normalized_path=normalized_path,
            original_path=original,
            provenance_source=source,
            provenance_chain=chain,
            classification=CandidateClassification.DENY_OUTSIDE_ROOT,
            policy_rules_evaluated=tuple(rules),
            explicit_path=explicit_hint,
            generated_intent=generated_hint,
            support_only=support_hint,
            final_disposition="REJECT",
        )

    normalized_path = _host_normalized_relative(lexical, root)
    resolved = lexical.resolve(strict=False)
    rules.append("symlink_boundary")
    if not _is_within(resolved, root):
        return CandidateAdmissibility(
            normalized_path=normalized_path,
            original_path=original,
            provenance_source=source,
            provenance_chain=chain,
            classification=CandidateClassification.DENY_SYMLINK_ESCAPE,
            policy_rules_evaluated=tuple(rules),
            explicit_path=explicit_hint,
            generated_intent=generated_hint,
            support_only=support_hint,
            final_disposition="REJECT",
        )

    explicit = explicit_hint
    for value in _explicit_paths(task_context):
        if str(value) == original:
            explicit = True
            break
        explicit_raw = Path(value)
        explicit_lexical = Path(os.path.abspath(os.path.normpath(str(explicit_raw if explicit_raw.is_absolute() else root / explicit_raw))))
        if _is_within(explicit_lexical, root) and _host_normalized_relative(explicit_lexical, root) == normalized_path:
            explicit = True
            break
    generated_intent = generated_hint
    support_only = support_hint

    rules.append("secret")
    first_segment = PurePosixPath(normalized_path).parts[0].lower() if normalized_path else ""
    secret_check_path = PurePosixPath(normalized_path).name if first_segment in {".agents", ".codex"} else normalized_path
    secret = is_secret_name(secret_check_path) or is_sensitive_or_secret_path(secret_check_path)
    rules.append("runtime")
    runtime = _looks_runtime(normalized_path, chain)
    # Normative precedence is secret before runtime when a path matches both.
    if secret:
        classification = CandidateClassification.DENY_SECRET
    elif runtime:
        classification = CandidateClassification.DENY_RUNTIME
    else:
        matcher = (repository_state or {}).get("ignore_matcher")
        if not isinstance(matcher, IgnoreMatcher):
            matcher = IgnoreMatcher.from_repo(root)
        rules.append("ignore")
        ignored = matcher.is_ignored(normalized_path)
        generated = _looks_generated(normalized_path)
        if generated and not generated_intent:
            classification = CandidateClassification.DENY_IGNORED
        elif ignored and not explicit and not (generated and generated_intent):
            classification = CandidateClassification.DENY_IGNORED
        elif ignored and explicit and not generated:
            classification = CandidateClassification.ALLOW_IF_EXPLICIT
        else:
            rules.append("generated_exception")
            if generated:
                classification = (
                    CandidateClassification.GENERATED_EXCEPTION
                    if generated_intent
                    else CandidateClassification.DENY_IGNORED
                )
            else:
                rules.append("support_only")
                classification = CandidateClassification.SUPPORT_ONLY if support_only else CandidateClassification.ALLOW

    if classification in HARD_DENIALS or classification == CandidateClassification.DENY_IGNORED:
        disposition = "REJECT"
    elif classification == CandidateClassification.SUPPORT_ONLY:
        disposition = "ADMIT_SUPPORT"
    else:
        disposition = "ADMIT_PRIMARY"
    return CandidateAdmissibility(
        normalized_path=normalized_path,
        original_path=original,
        provenance_source=source,
        provenance_chain=chain,
        classification=classification,
        policy_rules_evaluated=tuple(rules),
        explicit_path=explicit,
        generated_intent=generated_intent,
        support_only=support_only,
        final_disposition=disposition,
    )


def assert_final_admissibility(result: CandidateAdmissibility, *, selected_role: str) -> None:
    allowed = {
        "ALLOW",
        "ALLOW_IF_EXPLICIT_SATISFIED",
        "SUPPORT_ONLY_QUALIFIED",
        "GENERATED_EXCEPTION_QUALIFIED",
    }
    if result.final_admissibility not in allowed:
        raise ValueError(f"candidate is not finally admissible: {result.normalized_path}")
    if result.final_admissibility == "SUPPORT_ONLY_QUALIFIED" and selected_role != "support":
        raise ValueError(f"support-only candidate cannot be selected as {selected_role}: {result.normalized_path}")
