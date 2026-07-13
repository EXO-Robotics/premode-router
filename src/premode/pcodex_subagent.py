from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import re
import tempfile
from typing import Any

from . import pcodex_bootstrap as pcodex
from .candidate_policy import CandidateIntent, classify_candidate, is_generated_candidate_path
from .core_packet import CorePath, render_core_packet
from .production_ranking import ProductionRankingContractError, ranking_result_from_dict


CompileRunner = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class SubagentTransformResult:
    prompt: str
    enabled: bool
    algorithm: str = pcodex.PCODEX_PACKET_STRATEGY
    mode: str | None = None
    effective_mode: str | None = None
    transform_applied: bool = False
    tuning_profile: str | None = None
    packet_path: str | None = None
    used_fallback: bool = False
    error: str | None = None
    route: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _write_packet(packet: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="pcodex_subagent_packet_", suffix=".md", delete=False)
    with handle:
        handle.write(packet)
    return handle.name


def compose_transformed_prompt(subagent_prompt: str, packet: str) -> str:
    if packet.startswith("TASK\n"):
        return packet.rstrip() + "\n"
    return f"{subagent_prompt.rstrip()}\n\n---\n\n{packet.strip()}\n"


def _validated_decision_and_packet(
    project_root: Path,
    prompt: str,
    compiled: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    product_raw = compiled.get("production_ranking")
    if isinstance(product_raw, Mapping):
        try:
            product = ranking_result_from_dict(product_raw)
        except ProductionRankingContractError:
            return None, None
        roles = (("primary_paths", "primary"), ("verify_paths", "verification"), ("support_paths", "support"))
        items: list[CorePath] = []
        seen: set[str] = set()
        explicit_paths = {
            path.casefold()
            for path in re.findall(r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+(?![\w.-])", prompt)
        }
        generated_intent = bool(re.search(r"(?i)\b(generated|vendor|dist|build output|generated code)\b", prompt))
        for key, role in roles:
            for value in getattr(product, key):
                explicit = value.casefold() in explicit_paths
                policy = classify_candidate(
                    project_root,
                    value,
                    intent=CandidateIntent(
                        explicit=explicit,
                        generated_required=explicit and (generated_intent or is_generated_candidate_path(value)),
                        support_only=role == "support",
                    ),
                    provenance=("production_ranking_provider",),
                )
                if not policy.admitted or not policy.normalized_path or policy.normalized_path.casefold() in seen:
                    return None, None
                seen.add(policy.normalized_path.casefold())
                items.append(CorePath(path=policy.normalized_path, role=role))  # type: ignore[arg-type]
        expected = prompt if product.routing_mode == "abstain" else render_core_packet(prompt, items)
        if compiled.get("packet") != expected:
            return None, None
        return product.to_dict(), expected
    raw = compiled.get("routing_decision")
    if not isinstance(raw, dict) or raw.get("schema_version") != "routing-decision.v1":
        return None, None
    mode = raw.get("mode")
    confidence = raw.get("confidence")
    if mode not in {"narrow", "broad", "abstain"} or confidence not in {"low", "medium", "high"}:
        return None, None
    roles = (("primary_paths", "primary"), ("verification_paths", "verification"), ("support_paths", "support"))
    explicit_paths = {
        path.casefold()
        for path in re.findall(r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+(?![\w.-])", prompt)
    }
    generated_intent = bool(re.search(r"(?i)\b(generated|vendor|dist|build output|generated code)\b", prompt))

    def intent_for(path: str, role: str) -> CandidateIntent:
        explicit = path.casefold() in explicit_paths
        return CandidateIntent(
            explicit=explicit,
            generated_required=explicit and (generated_intent or is_generated_candidate_path(path)),
            support_only=role == "support",
        )
    normalized: dict[str, list[str]] = {}
    seen: set[str] = set()
    for key, role in roles:
        values = raw.get(key)
        if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) for value in values):
            return None, None
        normalized[key] = []
        for value in values:
            policy = classify_candidate(
                project_root,
                value,
                intent=intent_for(value, role),
                provenance=("subagent_routing_decision",),
            )
            if not policy.admitted or not policy.normalized_path or policy.normalized_path.casefold() in seen:
                return None, None
            seen.add(policy.normalized_path.casefold())
            normalized[key].append(policy.normalized_path)
    evidence = raw.get("candidate_provenance")
    if not isinstance(evidence, (list, tuple)) or any(not isinstance(item, dict) for item in evidence):
        return None, None
    evidence_paths: set[tuple[str, str]] = set()
    ranks: set[int] = set()
    support_relations = ("import_", "imported_by:", "source_test_", "shared_", "option_", "symbol:")
    for item in evidence:
        role = item.get("role")
        path = item.get("path")
        signals = item.get("matched_signals")
        provenance = item.get("provenance")
        rank = item.get("rank")
        score = item.get("score")
        if (
            item.get("schema_version") != "candidate-evidence.v1"
            or role not in {"primary", "verification", "support"}
            or not isinstance(path, str)
            or not isinstance(rank, int) or isinstance(rank, bool) or rank < 0 or rank in ranks
            or not isinstance(score, int) or isinstance(score, bool)
            or item.get("confidence") not in {"low", "medium", "high"}
            or not isinstance(signals, (list, tuple)) or any(not isinstance(value, str) for value in signals)
            or not isinstance(provenance, (list, tuple)) or any(not isinstance(value, str) for value in provenance)
        ):
            return None, None
        policy = classify_candidate(
            project_root,
            path,
            intent=intent_for(path, str(role)),
            provenance=("subagent_candidate_evidence",),
        )
        if not policy.admitted or not policy.normalized_path:
            return None, None
        key = (str(role), policy.normalized_path.casefold())
        if key in evidence_paths or (role == "support" and not any(signal.startswith(support_relations) for signal in signals)):
            return None, None
        ranks.add(rank)
        evidence_paths.add(key)
    if mode == "abstain":
        if any(normalized.values()):
            return None, None
        return {**raw, **normalized}, ""
    budget = 2 if mode == "narrow" else 4
    selected_evidence = {
        (role, path.casefold())
        for key, role in roles
        for path in normalized[key]
    }
    if (
        not normalized["primary_paths"]
        or (mode == "narrow" and len(normalized["primary_paths"]) > 2)
        or len(normalized["support_paths"]) > budget
        or not selected_evidence.issubset(evidence_paths)
    ):
        return None, None
    items = [
        CorePath(path=path, role=role)  # type: ignore[arg-type]
        for key, role in roles
        for path in normalized[key]
    ]
    expected = render_core_packet(prompt, items)
    if compiled.get("packet") != expected:
        return None, None
    return {**raw, **normalized}, expected


def transform_subagent_prompt(
    subagent_prompt: str,
    project_root: Path,
    *,
    parent_prompt: str | None = None,
    spawn_metadata: Mapping[str, str] | None = None,
    dry_run: bool = False,
    compile_runner: CompileRunner | None = None,
    profile: str | None = "lite",
    no_write: bool = False,
) -> SubagentTransformResult:
    mode_state = pcodex.resolve_mode_state(project_root, validate_tuned=True, require_runnable=False)
    mode = str(mode_state.get("configured_mode") or mode_state.get("mode") or "on")
    effective_mode = str(mode_state.get("effective_mode") or mode)
    tuning_profile = str(mode_state["effective_tuning_profile"]) if effective_mode == "tuned" and mode_state.get("effective_tuning_profile") else None
    fallback = mode_state.get("fallback") if isinstance(mode_state.get("fallback"), dict) else {}
    fallback_reason = str(fallback.get("last_reason")) if fallback.get("active") and fallback.get("last_reason") else None
    base_metadata: dict[str, Any] = {
        "parent_prompt_present": parent_prompt is not None,
        "spawn_metadata_keys": sorted((spawn_metadata or {}).keys()),
        "dry_run": dry_run,
        "config_source": "pcodex_state",
        "state_status": mode_state.get("state_status"),
        "state_error": mode_state.get("state_error"),
        "mode": mode,
        "configured_mode": mode,
        "effective_mode": effective_mode,
        "transform_applied": False,
        "tuning_profile": tuning_profile,
        "tuning": mode_state.get("tuning"),
        "fallback": fallback,
    }
    if mode_state.get("state_status") == "invalid_default":
        error = str(mode_state.get("state_error") or "Invalid pCodex mode state")
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=False,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            error=error,
            metadata={**base_metadata, "status": "invalid_state_raw_prompt", "error": error},
        )
    tuning = mode_state.get("tuning") if isinstance(mode_state.get("tuning"), dict) else {}
    if mode == "tuned" and not tuning.get("profile_valid"):
        error = str(tuning.get("profile_error") or "Invalid pCodex tuning profile")
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            error=error,
            metadata={**base_metadata, "status": "tuned_profile_invalid_raw_prompt", "error": error},
        )
    if effective_mode == "off":
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=False,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=None,
            metadata={**base_metadata, "status": "disabled_raw_prompt"},
        )

    if compile_runner is None and no_write:
        def runner(root: Path, prompt: str, selected_profile: str | None, **kwargs: Any) -> dict[str, Any]:
            return pcodex.compile_pcodex_packet(
                root,
                prompt,
                selected_profile,
                tuning_profile=kwargs.get("tuning_profile"),
                write_policy="advisory",
            )
    else:
        runner = compile_runner or pcodex.compile_pcodex_packet
    try:
        compiled = pcodex.run_compile_runner(runner, project_root, subagent_prompt, profile, tuning_profile=tuning_profile)
    except Exception as exc:
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            error="compile_failed",
            metadata={**base_metadata, "status": "compile_failed_raw_prompt", "error_type": type(exc).__name__},
        )

    routing_decision, packet = _validated_decision_and_packet(project_root, subagent_prompt, compiled)
    if routing_decision is None:
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            error="invalid_routing_decision",
            metadata={**base_metadata, "status": "invalid_routing_decision_raw_prompt"},
        )
    routing_mode = routing_decision.get("routing_mode") or routing_decision.get("mode")
    public_ranking = (
        routing_decision
        if "routing_mode" in routing_decision
        else {
            "routing_mode": routing_mode,
            "primary_paths": list(routing_decision.get("primary_paths") or []),
            "verify_paths": list(routing_decision.get("verification_paths") or []),
            "support_paths": list(routing_decision.get("support_paths") or []),
        }
    )
    if routing_mode == "abstain":
        return SubagentTransformResult(
            prompt=subagent_prompt,
            enabled=True,
            mode=mode,
            effective_mode=effective_mode,
            transform_applied=False,
            tuning_profile=tuning_profile,
            route="abstain",
            metadata={**base_metadata, "status": "abstained_raw_prompt", "production_ranking": public_ranking},
        )
    assert packet is not None
    telemetry = (
        {"telemetry": {"status": "not_recorded", "reason": "no_write"}}
        if no_write
        else pcodex.record_runtime_telemetry(
            project_root,
            configured_mode=mode,
            effective_mode=effective_mode,
            fallback_reason=fallback_reason,
        )
    )
    packet_path = None if dry_run or no_write else _write_packet(packet)
    route = str(compiled.get("route") or "")
    transformed = compose_transformed_prompt(subagent_prompt, packet)
    return SubagentTransformResult(
        prompt=transformed,
        enabled=True,
        mode=mode,
        effective_mode=effective_mode,
        transform_applied=True,
        tuning_profile=tuning_profile,
        packet_path=packet_path,
        used_fallback=route == "explicit_fallback",
        route=route or None,
        metadata={
            **base_metadata,
            "status": "transformed",
            "transform_applied": True,
            "premode_command": compiled.get("premode_command"),
            "packet_sha256": compiled.get("packet_sha256"),
            "model_facing_sections": compiled.get("model_facing_sections"),
            "production_ranking": public_ranking,
            "telemetry": telemetry.get("telemetry"),
        },
    )
