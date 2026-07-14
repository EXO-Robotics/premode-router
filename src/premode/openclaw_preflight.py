"""No-write OpenClaw projection over the frozen production ranking provider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable, Mapping

from .openclaw_adapter import (
    OpenClawPathPolicy,
    classify_openclaw_path,
    dangerous_mutation_zones,
    qualify_openclaw_workspace,
)
from .openclaw_contracts import (
    OpenClawDangerousMutationZoneV1,
    OpenClawLikelyPathV1,
    OpenClawPreflightReceiptV1,
    OpenClawPreflightRequestV1,
    OpenClawPreflightResultV1,
    OpenClawValidationSurfaceV1,
    canonical_sha256,
    derive_openclaw_preflight_receipt_id,
)
from .openclaw_lifecycle import ready_workspace_binding
from .production_ranking import (
    ProductionRankingResultV1,
    ranking_result_from_dict,
)
from .write_policy import ADVISORY, WritePolicy


CompileRunner = Callable[..., Mapping[str, Any]]
_MUTATION_VERBS = re.compile(
    r"\b(?:change|edit|fix|modify|mutate|repair|replace|update|write)\b",
    re.IGNORECASE,
)


class OpenClawPreflightError(RuntimeError):
    """The bound adapter cannot produce safe preflight guidance."""


@dataclass(frozen=True)
class OpenClawPreflightExecution:
    result: OpenClawPreflightResultV1
    receipt: OpenClawPreflightReceiptV1


def _default_compile_runner(
    workspace: Path,
    exact_task: str,
    profile: str,
    *,
    write_policy: WritePolicy,
) -> Mapping[str, Any]:
    from .pcodex_bootstrap import compile_pcodex_packet

    return compile_pcodex_packet(
        workspace,
        exact_task,
        profile,
        write_policy=write_policy,
    )


def _provider_result(
    workspace: Path,
    request: OpenClawPreflightRequestV1,
    *,
    compile_runner: CompileRunner,
) -> ProductionRankingResultV1:
    compiled = compile_runner(
        workspace,
        request.exact_task,
        "lite",
        write_policy=ADVISORY,
    )
    if not isinstance(compiled, Mapping):
        raise OpenClawPreflightError("production compile result is invalid")
    payload = compiled.get("production_ranking")
    if not isinstance(payload, Mapping):
        raise OpenClawPreflightError("production ranking result is unavailable")
    try:
        return ranking_result_from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise OpenClawPreflightError("production ranking result is invalid") from exc


def _validation_kind(path: str) -> str:
    lower = path.casefold()
    parts = PurePosixPath(lower).parts
    suffix = PurePosixPath(lower).suffix
    if "workflows" in parts or lower.endswith((".yml", ".yaml")):
        return "workflow"
    if "schema" in lower or suffix in {".schema", ".xsd"}:
        return "schema"
    if "proof" in lower:
        return "proof"
    if any(part in {"test", "tests", "spec", "specs"} for part in parts):
        return "test"
    return "build"


def _policy_item(policy: OpenClawPathPolicy, role: str) -> OpenClawLikelyPathV1:
    return OpenClawLikelyPathV1(
        path=policy.path,
        selection_role=role,
        authority_class=policy.authority_class,
        surface=policy.surface,
        mutation_policy=policy.mutation_policy,
        explicitly_task_named=policy.explicitly_task_named,
        reason_codes=policy.reason_codes,
    )


def _danger_zones() -> tuple[OpenClawDangerousMutationZoneV1, ...]:
    return tuple(
        OpenClawDangerousMutationZoneV1(**zone) for zone in dangerous_mutation_zones()
    )


def _direct_binary_mutation(
    exact_task: str, policies: tuple[OpenClawPathPolicy, ...]
) -> bool:
    return _MUTATION_VERBS.search(exact_task) is not None and any(
        policy.explicitly_task_named
        and policy.surface in {"unreal_asset", "blender_asset"}
        for policy in policies
    )


def _sections_from_provider(
    workspace: Path,
    request: OpenClawPreflightRequestV1,
    provider: ProductionRankingResultV1,
) -> tuple[
    str,
    str | None,
    tuple[OpenClawLikelyPathV1, ...],
    tuple[OpenClawValidationSurfaceV1, ...],
]:
    if provider.routing_mode in {"fallback", "abstain"}:
        return provider.routing_mode, provider.abstention_reason, (), ()
    selected: list[tuple[OpenClawPathPolicy, str]] = []
    policies: list[OpenClawPathPolicy] = []
    seen: set[str] = set()
    for role, values in (
        ("primary", provider.primary_paths),
        ("verify", provider.verify_paths),
        ("support", provider.support_paths),
    ):
        for path in values:
            policy = classify_openclaw_path(workspace, request.exact_task, path)
            policies.append(policy)
            identity = policy.path.casefold()
            if not policy.include or identity in seen:
                continue
            seen.add(identity)
            selected.append((policy, role))
            if len(selected) == 20:
                break
        if len(selected) == 20:
            break
    policy_tuple = tuple(policies)
    if _direct_binary_mutation(request.exact_task, policy_tuple):
        return "abstain", "conservative_safety_boundary", (), ()
    ordered = [_policy_item(policy, role) for policy, role in selected]
    if not ordered:
        return "fallback", None, (), ()
    validation: list[OpenClawValidationSurfaceV1] = []
    for item in ordered:
        if item.selection_role != "verify":
            continue
        validation.append(
            OpenClawValidationSurfaceV1(
                path=item.path, kind=_validation_kind(item.path)
            )
        )
        if len(validation) == 12:
            break
    return provider.routing_mode, None, tuple(ordered), tuple(validation)


def _build_execution(
    request: OpenClawPreflightRequestV1,
    *,
    workspace_binding_id: str,
    provider_decision: Mapping[str, Any],
    routing_mode: str,
    abstention_reason: str | None,
    paths: tuple[OpenClawLikelyPathV1, ...],
    validation: tuple[OpenClawValidationSurfaceV1, ...],
) -> OpenClawPreflightExecution:
    zones = _danger_zones()
    provider_decision_sha256 = canonical_sha256(provider_decision)
    ordered_paths_sha256 = canonical_sha256([item.to_dict() for item in paths])
    dangerous_zones_sha256 = canonical_sha256([item.to_dict() for item in zones])
    validation_surfaces_sha256 = canonical_sha256(
        [item.to_dict() for item in validation]
    )
    receipt_id = derive_openclaw_preflight_receipt_id(
        exact_task_sha256=request.exact_task_sha256,
        workspace_binding_id=workspace_binding_id,
        provider_decision_sha256=provider_decision_sha256,
        routing_mode=routing_mode,
        path_count=len(paths),
        dangerous_zone_count=len(zones),
        validation_surface_count=len(validation),
        ordered_paths_sha256=ordered_paths_sha256,
        dangerous_zones_sha256=dangerous_zones_sha256,
        validation_surfaces_sha256=validation_surfaces_sha256,
    )
    result = OpenClawPreflightResultV1(
        routing_mode=routing_mode,
        abstention_reason=abstention_reason,
        exact_task_sha256=request.exact_task_sha256,
        workspace_binding_id=workspace_binding_id,
        ordered_likely_paths=paths,
        dangerous_mutation_zones=zones,
        expected_validation_surfaces=validation,
        receipt_id=receipt_id,
    )
    receipt = OpenClawPreflightReceiptV1.from_result(
        result,
        provider_decision_sha256=provider_decision_sha256,
    )
    receipt.validate_against_result(result)
    return OpenClawPreflightExecution(result=result, receipt=receipt)


def run_openclaw_preflight(
    workspace: Path,
    request: OpenClawPreflightRequestV1,
    *,
    compile_runner: CompileRunner | None = None,
    environ: Mapping[str, str] | None = None,
) -> OpenClawPreflightExecution:
    root = workspace.resolve(strict=True)
    if root != workspace:
        raise OpenClawPreflightError("workspace binding changed")
    workspace_binding_id = ready_workspace_binding(root, environ=environ)
    qualification = qualify_openclaw_workspace(root)
    if not qualification.qualified:
        return _build_execution(
            request,
            workspace_binding_id=workspace_binding_id,
            provider_decision={
                "adapter_gate": "unsupported_task_class",
                "provider_version": "production-ranking-provider.v1",
            },
            routing_mode="abstain",
            abstention_reason="unsupported_task_class",
            paths=(),
            validation=(),
        )
    provider = _provider_result(
        root,
        request,
        compile_runner=compile_runner or _default_compile_runner,
    )
    routing_mode, reason, paths, validation = _sections_from_provider(
        root, request, provider
    )
    return _build_execution(
        request,
        workspace_binding_id=workspace_binding_id,
        provider_decision=provider.to_dict(),
        routing_mode=routing_mode,
        abstention_reason=reason,
        paths=paths,
        validation=validation,
    )


def openclaw_preflight_backend(
    workspace: Path, task: str, profile: str | None
) -> Mapping[str, Any]:
    """Picklable transport backend exposing only bounded public-safe fields."""

    request = OpenClawPreflightRequestV1(
        exact_task=task,
        profile=profile or "openclaw",
    )
    execution = run_openclaw_preflight(workspace, request)
    result = execution.result
    class_map = {
        "current_authority": "current_authority",
        "authored_source": "implementation",
        "validation_surface": "verification",
        "configuration": "support",
        "historical_evidence": "historical_or_generated_evidence",
        "generated_evidence": "historical_or_generated_evidence",
        "unknown": "support",
    }
    return {
        "status": (
            "abstained"
            if result.routing_mode == "abstain"
            else "fallback"
            if result.routing_mode == "fallback"
            else "ready"
        ),
        "routing_mode": result.routing_mode,
        "likely_paths": [item.path for item in result.ordered_likely_paths],
        "authority_classifications": [
            {"path": item.path, "classification": class_map[item.authority_class]}
            for item in result.ordered_likely_paths
        ],
        "dangerous_mutation_zones": [
            item.path_pattern for item in result.dangerous_mutation_zones
        ],
        "expected_validation_surfaces": [
            item.path for item in result.expected_validation_surfaces
        ],
        "receipt_id": result.receipt_id,
    }
