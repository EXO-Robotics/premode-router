"""Strict, content-free wire contracts for the bounded OpenClaw preflight tool.

This module defines logistics contracts only.  It does not detect repositories,
rank paths, execute validation, or select an OpenClaw workspace.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
import re
import unicodedata
from typing import AbstractSet, Any, Mapping, Sequence


OPENCLAW_PREFLIGHT_REQUEST_SCHEMA_VERSION = "pcodex.openclaw-preflight-request.v1"
OPENCLAW_PREFLIGHT_RESULT_SCHEMA_VERSION = "pcodex.openclaw-preflight-result.v1"
OPENCLAW_PREFLIGHT_RECEIPT_SCHEMA_VERSION = "pcodex.openclaw-preflight-receipt.v1"
OPENCLAW_PREFLIGHT_SOURCE_CONTRACT = "pcodex.openclaw-preflight.v1"
OPENCLAW_CLASSIFICATION_POLICY_VERSION = "pcodex.openclaw-authority-policy.v1"
PRODUCTION_RANKING_PROVIDER_VERSION = "production-ranking-provider.v1"
SENSITIVE_PRIVATE = "sensitive_private"
PRIVATE_METADATA = "private_metadata"

MAX_EXACT_TASK_LENGTH = 32_768
MAX_PATH_LENGTH = 4_096
MAX_LIKELY_PATHS = 20
MAX_DANGEROUS_ZONES = 32
MAX_VALIDATION_SURFACES = 12
MAX_REASON_CODES = 8

ROUTING_MODES = frozenset({"narrow", "broad", "fallback", "abstain"})
ABSTENTION_REASONS = frozenset(
    {
        "conservative_safety_boundary",
        "insufficient_path_evidence",
        "provider_declined",
        "unsupported_task_class",
    }
)
SELECTION_ROLES = frozenset({"primary", "verify", "support"})
AUTHORITY_CLASSES = frozenset(
    {
        "current_authority",
        "authored_source",
        "validation_surface",
        "configuration",
        "historical_evidence",
        "generated_evidence",
        "unknown",
    }
)
SURFACES = frozenset(
    {
        "control_plane",
        "task_queue",
        "state_authority",
        "bridge",
        "unreal_source",
        "unreal_asset",
        "blender_pipeline",
        "blender_asset",
        "nested_executor",
        "general",
    }
)
MUTATION_POLICIES = frozenset(
    {"eligible", "read_only", "explicit_authorization_required", "forbidden"}
)
DANGEROUS_MUTATION_POLICIES = frozenset(
    {"explicit_authorization_required", "forbidden"}
)
VALIDATION_KINDS = frozenset({"test", "schema", "build", "workflow", "proof"})

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WORKSPACE_BINDING_ID = re.compile(r"^ocwb_[0-9a-f]{32}$")
_RECEIPT_ID = re.compile(r"^ocpr_[0-9a-f]{64}$")
_PUBLIC_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_FORBIDDEN_PUBLIC_IDENTITY_TERMS = (
    "candidate",
    "experiment",
    "observer",
    "qwen",
    "d3",
    "c2",
)
_RECEIPT_ID_DOMAIN = b"pcodex.openclaw-preflight-receipt-id.v1\0"


class OpenClawPreflightContractError(ValueError):
    """A versioned OpenClaw preflight payload failed closed."""


def canonical_json_bytes(value: Mapping[str, Any] | Sequence[Any]) -> bytes:
    """Return deterministic UTF-8 JSON without accepting non-finite values."""

    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise OpenClawPreflightContractError(
            "contract payload is not canonical JSON"
        ) from exc
    return rendered.encode("utf-8")


def canonical_sha256(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _strict_fields(
    payload: Mapping[str, Any],
    *,
    required: set[str],
    optional: AbstractSet[str] = frozenset(),
    label: str,
) -> None:
    if not isinstance(payload, Mapping):
        raise OpenClawPreflightContractError(f"{label} must be an object")
    actual = set(payload)
    if not required.issubset(actual) or actual - required - optional:
        raise OpenClawPreflightContractError(
            f"{label} contains missing or unsupported fields"
        )


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise OpenClawPreflightContractError(f"{field} must be a string")
    return value


def _require_sha256(value: object, field: str) -> str:
    text = _require_string(value, field)
    if _SHA256.fullmatch(text) is None:
        raise OpenClawPreflightContractError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return text


def _require_enum(value: object, allowed: frozenset[str], field: str) -> str:
    text = _require_string(value, field)
    if text not in allowed:
        raise OpenClawPreflightContractError(f"{field} is unsupported")
    return text


def _require_count(value: object, field: str, *, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > maximum
    ):
        raise OpenClawPreflightContractError(
            f"{field} must be an integer from 0 through {maximum}"
        )
    return value


def _validate_public_identifier(value: object, field: str) -> str:
    text = _require_string(value, field)
    lowered = text.casefold()
    if _PUBLIC_IDENTIFIER.fullmatch(text) is None or any(
        term in lowered for term in _FORBIDDEN_PUBLIC_IDENTITY_TERMS
    ):
        raise OpenClawPreflightContractError(
            f"{field} must be a bounded public-safe identifier"
        )
    return text


def _validate_relative_path(value: object, field: str, *, pattern: bool = False) -> str:
    path = _require_string(value, field)
    if (
        not path
        or len(path) > MAX_PATH_LENGTH
        or len(path.encode("utf-8")) > MAX_PATH_LENGTH
        or unicodedata.normalize("NFC", path) != path
        or path != path.strip()
        or "\x00" in path
        or "\\" in path
        or path.startswith("/")
        or path.endswith("/")
        or path == "~"
        or path.startswith("~/")
        or _WINDOWS_DRIVE.match(path) is not None
    ):
        raise OpenClawPreflightContractError(
            f"{field} must be a normalized repository-relative POSIX path"
        )
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise OpenClawPreflightContractError(
            f"{field} must be a normalized repository-relative POSIX path"
        )
    if not pattern and any(character in path for character in "*?[]"):
        raise OpenClawPreflightContractError(f"{field} cannot contain glob syntax")
    return path


def _unique_strings(
    values: object,
    field: str,
    *,
    maximum: int,
    public_identifiers: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise OpenClawPreflightContractError(f"{field} must be an ordered array")
    if len(values) > maximum:
        raise OpenClawPreflightContractError(
            f"{field} cannot contain more than {maximum} entries"
        )
    result: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        text = (
            _validate_public_identifier(value, f"{field}[{index}]")
            if public_identifiers
            else _require_string(value, f"{field}[{index}]")
        )
        identity = unicodedata.normalize("NFC", text).casefold()
        if identity in seen:
            raise OpenClawPreflightContractError(f"{field} contains duplicates")
        seen.add(identity)
        result.append(text)
    return tuple(result)


def _unique_path_objects(
    values: Sequence[object], field: str, *, maximum: int
) -> tuple[object, ...]:
    if len(values) > maximum:
        raise OpenClawPreflightContractError(
            f"{field} cannot contain more than {maximum} entries"
        )
    seen: set[str] = set()
    result: list[object] = []
    for value in values:
        path = getattr(value, "path", getattr(value, "path_pattern", None))
        if not isinstance(path, str):
            raise OpenClawPreflightContractError(f"{field} entries are invalid")
        identity = unicodedata.normalize("NFC", path).casefold()
        if identity in seen:
            raise OpenClawPreflightContractError(f"{field} contains duplicate paths")
        seen.add(identity)
        result.append(value)
    return tuple(result)


@dataclass(frozen=True)
class OpenClawPreflightRequestV1:
    exact_task: str
    profile: str = "openclaw"
    schema_version: str = OPENCLAW_PREFLIGHT_REQUEST_SCHEMA_VERSION
    sensitivity_classification: str = SENSITIVE_PRIVATE

    def __post_init__(self) -> None:
        if self.schema_version != OPENCLAW_PREFLIGHT_REQUEST_SCHEMA_VERSION:
            raise OpenClawPreflightContractError(
                f"unsupported OpenClaw preflight request schema_version: {self.schema_version}"
            )
        if self.profile != "openclaw":
            raise OpenClawPreflightContractError(
                "unsupported OpenClaw preflight profile"
            )
        if self.sensitivity_classification != SENSITIVE_PRIVATE:
            raise OpenClawPreflightContractError(
                "OpenClaw preflight requests must remain sensitive/private"
            )
        if not isinstance(self.exact_task, str) or not self.exact_task:
            raise OpenClawPreflightContractError(
                "exact_task must be a non-empty string"
            )
        if (
            len(self.exact_task) > MAX_EXACT_TASK_LENGTH
            or len(self.exact_task.encode("utf-8")) > MAX_EXACT_TASK_LENGTH
        ):
            raise OpenClawPreflightContractError(
                "exact_task exceeds the 32768-character or UTF-8-byte bound"
            )

    @property
    def exact_task_sha256(self) -> str:
        return hashlib.sha256(self.exact_task.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "exact_task": self.exact_task,
            "profile": self.profile,
            "sensitivity_classification": self.sensitivity_classification,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True)
class OpenClawLikelyPathV1:
    path: str
    selection_role: str
    authority_class: str
    surface: str
    mutation_policy: str
    explicitly_task_named: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _validate_relative_path(self.path, "path"))
        _require_enum(self.selection_role, SELECTION_ROLES, "selection_role")
        _require_enum(self.authority_class, AUTHORITY_CLASSES, "authority_class")
        _require_enum(self.surface, SURFACES, "surface")
        _require_enum(self.mutation_policy, MUTATION_POLICIES, "mutation_policy")
        if not isinstance(self.explicitly_task_named, bool):
            raise OpenClawPreflightContractError(
                "explicitly_task_named must be a boolean"
            )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(
                self.reason_codes,
                "reason_codes",
                maximum=MAX_REASON_CODES,
                public_identifiers=True,
            ),
        )
        if self.authority_class in {"historical_evidence", "generated_evidence"}:
            if self.mutation_policy != "read_only":
                raise OpenClawPreflightContractError(
                    "historical and generated evidence must remain read_only"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True)
class OpenClawDangerousMutationZoneV1:
    path_pattern: str
    surface: str
    mutation_policy: str
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "path_pattern",
            _validate_relative_path(self.path_pattern, "path_pattern", pattern=True),
        )
        _require_enum(self.surface, SURFACES, "surface")
        _require_enum(
            self.mutation_policy,
            DANGEROUS_MUTATION_POLICIES,
            "mutation_policy",
        )
        _validate_public_identifier(self.reason_code, "reason_code")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpenClawValidationSurfaceV1:
    path: str
    kind: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _validate_relative_path(self.path, "path"))
        _require_enum(self.kind, VALIDATION_KINDS, "kind")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _section_hash(items: Sequence[object]) -> str:
    payload: list[dict[str, Any]] = []
    for item in items:
        to_dict = getattr(item, "to_dict", None)
        if not callable(to_dict):
            raise OpenClawPreflightContractError(
                "receipt section contains invalid items"
            )
        payload.append(to_dict())
    return canonical_sha256(payload)


def derive_openclaw_preflight_receipt_id(
    *,
    exact_task_sha256: str,
    workspace_binding_id: str,
    provider_decision_sha256: str,
    routing_mode: str,
    path_count: int,
    dangerous_zone_count: int,
    validation_surface_count: int,
    ordered_paths_sha256: str,
    dangerous_zones_sha256: str,
    validation_surfaces_sha256: str,
    provider_version: str = PRODUCTION_RANKING_PROVIDER_VERSION,
    classification_policy_version: str = OPENCLAW_CLASSIFICATION_POLICY_VERSION,
    source_contract: str = OPENCLAW_PREFLIGHT_SOURCE_CONTRACT,
) -> str:
    """Derive an opaque ID from the complete content-free receipt core."""

    _require_sha256(exact_task_sha256, "exact_task_sha256")
    if _WORKSPACE_BINDING_ID.fullmatch(workspace_binding_id) is None:
        raise OpenClawPreflightContractError("workspace_binding_id is invalid")
    _require_sha256(provider_decision_sha256, "provider_decision_sha256")
    _require_enum(routing_mode, ROUTING_MODES, "routing_mode")
    _require_count(path_count, "path_count", maximum=MAX_LIKELY_PATHS)
    _require_count(
        dangerous_zone_count,
        "dangerous_zone_count",
        maximum=MAX_DANGEROUS_ZONES,
    )
    _require_count(
        validation_surface_count,
        "validation_surface_count",
        maximum=MAX_VALIDATION_SURFACES,
    )
    if provider_version != PRODUCTION_RANKING_PROVIDER_VERSION:
        raise OpenClawPreflightContractError("unsupported provider_version")
    if classification_policy_version != OPENCLAW_CLASSIFICATION_POLICY_VERSION:
        raise OpenClawPreflightContractError(
            "unsupported classification_policy_version"
        )
    if source_contract != OPENCLAW_PREFLIGHT_SOURCE_CONTRACT:
        raise OpenClawPreflightContractError("unsupported source_contract")
    for name, value in (
        ("ordered_paths_sha256", ordered_paths_sha256),
        ("dangerous_zones_sha256", dangerous_zones_sha256),
        ("validation_surfaces_sha256", validation_surfaces_sha256),
    ):
        _require_sha256(value, name)
    identity = {
        "classification_policy_version": classification_policy_version,
        "dangerous_zone_count": dangerous_zone_count,
        "dangerous_zones_sha256": dangerous_zones_sha256,
        "exact_task_sha256": exact_task_sha256,
        "ordered_paths_sha256": ordered_paths_sha256,
        "path_count": path_count,
        "provider_decision_sha256": provider_decision_sha256,
        "provider_version": provider_version,
        "routing_mode": routing_mode,
        "schema_version": OPENCLAW_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
        "sensitivity_classification": PRIVATE_METADATA,
        "source_contract": source_contract,
        "validation_surface_count": validation_surface_count,
        "validation_surfaces_sha256": validation_surfaces_sha256,
        "workspace_binding_id": workspace_binding_id,
    }
    digest = hashlib.sha256(
        _RECEIPT_ID_DOMAIN + canonical_json_bytes(identity)
    ).hexdigest()
    return f"ocpr_{digest}"


@dataclass(frozen=True)
class OpenClawPreflightResultV1:
    routing_mode: str
    abstention_reason: str | None
    exact_task_sha256: str
    workspace_binding_id: str
    ordered_likely_paths: tuple[OpenClawLikelyPathV1, ...]
    dangerous_mutation_zones: tuple[OpenClawDangerousMutationZoneV1, ...]
    expected_validation_surfaces: tuple[OpenClawValidationSurfaceV1, ...]
    receipt_id: str
    profile: str = "openclaw"
    schema_version: str = OPENCLAW_PREFLIGHT_RESULT_SCHEMA_VERSION
    sensitivity_classification: str = PRIVATE_METADATA

    def __post_init__(self) -> None:
        if self.schema_version != OPENCLAW_PREFLIGHT_RESULT_SCHEMA_VERSION:
            raise OpenClawPreflightContractError(
                f"unsupported OpenClaw preflight result schema_version: {self.schema_version}"
            )
        if self.profile != "openclaw":
            raise OpenClawPreflightContractError(
                "unsupported OpenClaw preflight profile"
            )
        if self.sensitivity_classification != PRIVATE_METADATA:
            raise OpenClawPreflightContractError(
                "OpenClaw preflight results must remain private metadata"
            )
        _require_enum(self.routing_mode, ROUTING_MODES, "routing_mode")
        _require_sha256(self.exact_task_sha256, "exact_task_sha256")
        if _WORKSPACE_BINDING_ID.fullmatch(self.workspace_binding_id) is None:
            raise OpenClawPreflightContractError("workspace_binding_id is invalid")
        if not isinstance(self.ordered_likely_paths, (list, tuple)):
            raise OpenClawPreflightContractError(
                "ordered_likely_paths must be an ordered array"
            )
        if not isinstance(self.dangerous_mutation_zones, (list, tuple)):
            raise OpenClawPreflightContractError(
                "dangerous_mutation_zones must be an ordered array"
            )
        if not isinstance(self.expected_validation_surfaces, (list, tuple)):
            raise OpenClawPreflightContractError(
                "expected_validation_surfaces must be an ordered array"
            )
        for path_item in self.ordered_likely_paths:
            if not isinstance(path_item, OpenClawLikelyPathV1):
                raise OpenClawPreflightContractError(
                    "ordered_likely_paths entries are invalid"
                )
        for zone_item in self.dangerous_mutation_zones:
            if not isinstance(zone_item, OpenClawDangerousMutationZoneV1):
                raise OpenClawPreflightContractError(
                    "dangerous_mutation_zones entries are invalid"
                )
        for validation_item in self.expected_validation_surfaces:
            if not isinstance(validation_item, OpenClawValidationSurfaceV1):
                raise OpenClawPreflightContractError(
                    "expected_validation_surfaces entries are invalid"
                )
        object.__setattr__(
            self,
            "ordered_likely_paths",
            _unique_path_objects(
                self.ordered_likely_paths,
                "ordered_likely_paths",
                maximum=MAX_LIKELY_PATHS,
            ),
        )
        object.__setattr__(
            self,
            "dangerous_mutation_zones",
            _unique_path_objects(
                self.dangerous_mutation_zones,
                "dangerous_mutation_zones",
                maximum=MAX_DANGEROUS_ZONES,
            ),
        )
        object.__setattr__(
            self,
            "expected_validation_surfaces",
            _unique_path_objects(
                self.expected_validation_surfaces,
                "expected_validation_surfaces",
                maximum=MAX_VALIDATION_SURFACES,
            ),
        )
        if self.routing_mode == "abstain":
            if self.abstention_reason not in ABSTENTION_REASONS:
                raise OpenClawPreflightContractError(
                    "abstain results require a supported abstention_reason"
                )
        elif self.abstention_reason is not None:
            raise OpenClawPreflightContractError(
                "abstention_reason is valid only for abstain results"
            )
        if self.routing_mode in {"fallback", "abstain"} and self.ordered_likely_paths:
            raise OpenClawPreflightContractError(
                "fallback and abstain results cannot contain likely path guidance"
            )
        if _RECEIPT_ID.fullmatch(self.receipt_id) is None:
            raise OpenClawPreflightContractError(
                "receipt_id must be an opaque domain-separated receipt identifier"
            )

    @property
    def ordered_paths_sha256(self) -> str:
        return _section_hash(self.ordered_likely_paths)

    @property
    def dangerous_zones_sha256(self) -> str:
        return _section_hash(self.dangerous_mutation_zones)

    @property
    def validation_surfaces_sha256(self) -> str:
        return _section_hash(self.expected_validation_surfaces)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "routing_mode": self.routing_mode,
            "abstention_reason": self.abstention_reason,
            "exact_task_sha256": self.exact_task_sha256,
            "workspace_binding_id": self.workspace_binding_id,
            "ordered_likely_paths": [
                item.to_dict() for item in self.ordered_likely_paths
            ],
            "dangerous_mutation_zones": [
                item.to_dict() for item in self.dangerous_mutation_zones
            ],
            "expected_validation_surfaces": [
                item.to_dict() for item in self.expected_validation_surfaces
            ],
            "receipt_id": self.receipt_id,
            "sensitivity_classification": self.sensitivity_classification,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True)
class OpenClawPreflightReceiptV1:
    receipt_id: str
    exact_task_sha256: str
    workspace_binding_id: str
    provider_decision_sha256: str
    routing_mode: str
    path_count: int
    dangerous_zone_count: int
    validation_surface_count: int
    ordered_paths_sha256: str
    dangerous_zones_sha256: str
    validation_surfaces_sha256: str
    provider_version: str = PRODUCTION_RANKING_PROVIDER_VERSION
    classification_policy_version: str = OPENCLAW_CLASSIFICATION_POLICY_VERSION
    source_contract: str = OPENCLAW_PREFLIGHT_SOURCE_CONTRACT
    schema_version: str = OPENCLAW_PREFLIGHT_RECEIPT_SCHEMA_VERSION
    sensitivity_classification: str = PRIVATE_METADATA

    def __post_init__(self) -> None:
        if self.schema_version != OPENCLAW_PREFLIGHT_RECEIPT_SCHEMA_VERSION:
            raise OpenClawPreflightContractError(
                f"unsupported OpenClaw preflight receipt schema_version: {self.schema_version}"
            )
        if self.sensitivity_classification != PRIVATE_METADATA:
            raise OpenClawPreflightContractError(
                "OpenClaw preflight receipts must remain private metadata"
            )
        if self.provider_version != PRODUCTION_RANKING_PROVIDER_VERSION:
            raise OpenClawPreflightContractError("unsupported provider_version")
        if self.classification_policy_version != OPENCLAW_CLASSIFICATION_POLICY_VERSION:
            raise OpenClawPreflightContractError(
                "unsupported classification_policy_version"
            )
        if self.source_contract != OPENCLAW_PREFLIGHT_SOURCE_CONTRACT:
            raise OpenClawPreflightContractError("unsupported source_contract")
        if _WORKSPACE_BINDING_ID.fullmatch(self.workspace_binding_id) is None:
            raise OpenClawPreflightContractError("workspace_binding_id is invalid")
        _require_enum(self.routing_mode, ROUTING_MODES, "routing_mode")
        for name, value in (
            ("exact_task_sha256", self.exact_task_sha256),
            ("provider_decision_sha256", self.provider_decision_sha256),
            ("ordered_paths_sha256", self.ordered_paths_sha256),
            ("dangerous_zones_sha256", self.dangerous_zones_sha256),
            ("validation_surfaces_sha256", self.validation_surfaces_sha256),
        ):
            _require_sha256(value, name)
        _require_count(self.path_count, "path_count", maximum=MAX_LIKELY_PATHS)
        _require_count(
            self.dangerous_zone_count,
            "dangerous_zone_count",
            maximum=MAX_DANGEROUS_ZONES,
        )
        _require_count(
            self.validation_surface_count,
            "validation_surface_count",
            maximum=MAX_VALIDATION_SURFACES,
        )
        expected = derive_openclaw_preflight_receipt_id(
            exact_task_sha256=self.exact_task_sha256,
            workspace_binding_id=self.workspace_binding_id,
            provider_decision_sha256=self.provider_decision_sha256,
            routing_mode=self.routing_mode,
            path_count=self.path_count,
            dangerous_zone_count=self.dangerous_zone_count,
            validation_surface_count=self.validation_surface_count,
            ordered_paths_sha256=self.ordered_paths_sha256,
            dangerous_zones_sha256=self.dangerous_zones_sha256,
            validation_surfaces_sha256=self.validation_surfaces_sha256,
            provider_version=self.provider_version,
            classification_policy_version=self.classification_policy_version,
            source_contract=self.source_contract,
        )
        if (
            self.receipt_id != expected
            or _RECEIPT_ID.fullmatch(self.receipt_id) is None
        ):
            raise OpenClawPreflightContractError(
                "receipt_id does not match the domain-separated receipt identity"
            )

    @classmethod
    def from_result(
        cls,
        result: OpenClawPreflightResultV1,
        *,
        provider_decision_sha256: str,
    ) -> OpenClawPreflightReceiptV1:
        if not isinstance(result, OpenClawPreflightResultV1):
            raise OpenClawPreflightContractError(
                "result must be OpenClawPreflightResultV1"
            )
        return cls(
            receipt_id=result.receipt_id,
            exact_task_sha256=result.exact_task_sha256,
            workspace_binding_id=result.workspace_binding_id,
            provider_decision_sha256=provider_decision_sha256,
            routing_mode=result.routing_mode,
            path_count=len(result.ordered_likely_paths),
            dangerous_zone_count=len(result.dangerous_mutation_zones),
            validation_surface_count=len(result.expected_validation_surfaces),
            ordered_paths_sha256=result.ordered_paths_sha256,
            dangerous_zones_sha256=result.dangerous_zones_sha256,
            validation_surfaces_sha256=result.validation_surfaces_sha256,
        )

    def validate_against_result(self, result: OpenClawPreflightResultV1) -> None:
        expected = OpenClawPreflightReceiptV1.from_result(
            result,
            provider_decision_sha256=self.provider_decision_sha256,
        )
        if self != expected:
            raise OpenClawPreflightContractError(
                "OpenClaw preflight receipt does not bind the supplied result"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "exact_task_sha256": self.exact_task_sha256,
            "workspace_binding_id": self.workspace_binding_id,
            "provider_version": self.provider_version,
            "provider_decision_sha256": self.provider_decision_sha256,
            "classification_policy_version": self.classification_policy_version,
            "routing_mode": self.routing_mode,
            "path_count": self.path_count,
            "dangerous_zone_count": self.dangerous_zone_count,
            "validation_surface_count": self.validation_surface_count,
            "ordered_paths_sha256": self.ordered_paths_sha256,
            "dangerous_zones_sha256": self.dangerous_zones_sha256,
            "validation_surfaces_sha256": self.validation_surfaces_sha256,
            "source_contract": self.source_contract,
            "sensitivity_classification": self.sensitivity_classification,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def openclaw_preflight_request_from_dict(
    payload: Mapping[str, Any],
) -> OpenClawPreflightRequestV1:
    required = {"schema_version", "exact_task", "sensitivity_classification"}
    _strict_fields(payload, required=required, optional={"profile"}, label="request")
    return OpenClawPreflightRequestV1(
        schema_version=payload["schema_version"],  # type: ignore[arg-type]
        exact_task=payload["exact_task"],  # type: ignore[arg-type]
        profile=payload.get("profile", "openclaw"),  # type: ignore[arg-type]
        sensitivity_classification=payload["sensitivity_classification"],  # type: ignore[arg-type]
    )


def _likely_path_from_dict(payload: Mapping[str, Any]) -> OpenClawLikelyPathV1:
    expected = {field.name for field in fields(OpenClawLikelyPathV1)}
    _strict_fields(payload, required=expected, label="likely path")
    return OpenClawLikelyPathV1(
        path=payload["path"],  # type: ignore[arg-type]
        selection_role=payload["selection_role"],  # type: ignore[arg-type]
        authority_class=payload["authority_class"],  # type: ignore[arg-type]
        surface=payload["surface"],  # type: ignore[arg-type]
        mutation_policy=payload["mutation_policy"],  # type: ignore[arg-type]
        explicitly_task_named=payload["explicitly_task_named"],  # type: ignore[arg-type]
        reason_codes=payload["reason_codes"],  # type: ignore[arg-type]
    )


def _dangerous_zone_from_dict(
    payload: Mapping[str, Any],
) -> OpenClawDangerousMutationZoneV1:
    expected = {field.name for field in fields(OpenClawDangerousMutationZoneV1)}
    _strict_fields(payload, required=expected, label="dangerous mutation zone")
    return OpenClawDangerousMutationZoneV1(
        path_pattern=payload["path_pattern"],  # type: ignore[arg-type]
        surface=payload["surface"],  # type: ignore[arg-type]
        mutation_policy=payload["mutation_policy"],  # type: ignore[arg-type]
        reason_code=payload["reason_code"],  # type: ignore[arg-type]
    )


def _validation_surface_from_dict(
    payload: Mapping[str, Any],
) -> OpenClawValidationSurfaceV1:
    expected = {field.name for field in fields(OpenClawValidationSurfaceV1)}
    _strict_fields(payload, required=expected, label="validation surface")
    return OpenClawValidationSurfaceV1(
        path=payload["path"],  # type: ignore[arg-type]
        kind=payload["kind"],  # type: ignore[arg-type]
    )


def _mapping_array(value: object, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise OpenClawPreflightContractError(f"{field} must be an ordered array")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise OpenClawPreflightContractError(f"{field} entries must be objects")
        result.append(item)
    return result


def openclaw_preflight_result_from_dict(
    payload: Mapping[str, Any],
) -> OpenClawPreflightResultV1:
    expected = {field.name for field in fields(OpenClawPreflightResultV1)}
    _strict_fields(payload, required=expected, label="result")
    likely = _mapping_array(payload["ordered_likely_paths"], "ordered_likely_paths")
    zones = _mapping_array(
        payload["dangerous_mutation_zones"], "dangerous_mutation_zones"
    )
    validation = _mapping_array(
        payload["expected_validation_surfaces"], "expected_validation_surfaces"
    )
    return OpenClawPreflightResultV1(
        schema_version=payload["schema_version"],  # type: ignore[arg-type]
        profile=payload["profile"],  # type: ignore[arg-type]
        routing_mode=payload["routing_mode"],  # type: ignore[arg-type]
        abstention_reason=payload["abstention_reason"],  # type: ignore[arg-type]
        exact_task_sha256=payload["exact_task_sha256"],  # type: ignore[arg-type]
        workspace_binding_id=payload["workspace_binding_id"],  # type: ignore[arg-type]
        ordered_likely_paths=tuple(_likely_path_from_dict(item) for item in likely),
        dangerous_mutation_zones=tuple(
            _dangerous_zone_from_dict(item) for item in zones
        ),
        expected_validation_surfaces=tuple(
            _validation_surface_from_dict(item) for item in validation
        ),
        receipt_id=payload["receipt_id"],  # type: ignore[arg-type]
        sensitivity_classification=payload["sensitivity_classification"],  # type: ignore[arg-type]
    )


def openclaw_preflight_receipt_from_dict(
    payload: Mapping[str, Any],
) -> OpenClawPreflightReceiptV1:
    expected = {field.name for field in fields(OpenClawPreflightReceiptV1)}
    _strict_fields(payload, required=expected, label="receipt")
    return OpenClawPreflightReceiptV1(
        schema_version=payload["schema_version"],  # type: ignore[arg-type]
        receipt_id=payload["receipt_id"],  # type: ignore[arg-type]
        exact_task_sha256=payload["exact_task_sha256"],  # type: ignore[arg-type]
        workspace_binding_id=payload["workspace_binding_id"],  # type: ignore[arg-type]
        provider_version=payload["provider_version"],  # type: ignore[arg-type]
        provider_decision_sha256=payload["provider_decision_sha256"],  # type: ignore[arg-type]
        classification_policy_version=payload["classification_policy_version"],  # type: ignore[arg-type]
        routing_mode=payload["routing_mode"],  # type: ignore[arg-type]
        path_count=payload["path_count"],  # type: ignore[arg-type]
        dangerous_zone_count=payload["dangerous_zone_count"],  # type: ignore[arg-type]
        validation_surface_count=payload["validation_surface_count"],  # type: ignore[arg-type]
        ordered_paths_sha256=payload["ordered_paths_sha256"],  # type: ignore[arg-type]
        dangerous_zones_sha256=payload["dangerous_zones_sha256"],  # type: ignore[arg-type]
        validation_surfaces_sha256=payload["validation_surfaces_sha256"],  # type: ignore[arg-type]
        source_contract=payload["source_contract"],  # type: ignore[arg-type]
        sensitivity_classification=payload["sensitivity_classification"],  # type: ignore[arg-type]
    )
