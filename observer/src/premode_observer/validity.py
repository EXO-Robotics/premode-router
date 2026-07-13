"""Independent, dimensional validity accounting."""

from __future__ import annotations

from dataclasses import dataclass, field

from .evidence_core import MEASUREMENT_CLASSES


VALIDITY_DIMENSIONS = (
    "capture_complete",
    "request_capture_valid",
    "response_capture_valid",
    "token_valid",
    "timing_valid",
    "model_identity_valid",
    "agent_trace_valid",
    "tool_trace_valid",
    "repository_valid",
    "storage_valid",
    "replay_valid",
    "overhead_valid",
    "overall_measurement_valid",
)
VALIDITY_STATUSES = frozenset({"valid", "invalid", "partial", "unavailable", "not_applicable", "pending"})


@dataclass(frozen=True, slots=True)
class ValidityResult:
    status: str
    measurement_class: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in VALIDITY_STATUSES:
            raise ValueError(f"invalid validity status: {self.status}")
        if self.measurement_class not in MEASUREMENT_CLASSES:
            raise ValueError(f"invalid measurement class: {self.measurement_class}")


@dataclass(slots=True)
class DimensionalValidity:
    dimensions: dict[str, ValidityResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = set(self.dimensions).difference(VALIDITY_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown validity dimensions: {sorted(unknown)}")
        for name in VALIDITY_DIMENSIONS:
            self.dimensions.setdefault(name, ValidityResult("pending", "direct_observed"))

    @classmethod
    def pending(cls) -> "DimensionalValidity":
        return cls(
            {
                name: ValidityResult("pending", "direct_observed")
                for name in VALIDITY_DIMENSIONS
            }
        )

    def set(self, dimension: str, status: str, measurement_class: str, reason: str | None = None) -> None:
        if dimension not in VALIDITY_DIMENSIONS:
            raise ValueError(f"unknown validity dimension: {dimension}")
        self.dimensions[dimension] = ValidityResult(status, measurement_class, reason)

    def calculate_overall(self) -> ValidityResult:
        inputs = [result for name, result in self.dimensions.items() if name != "overall_measurement_valid"]
        if any(result.status == "invalid" for result in inputs):
            overall = ValidityResult("invalid", "derived", "one or more validity dimensions are invalid")
        elif any(result.status in {"partial", "unavailable", "pending"} for result in inputs):
            overall = ValidityResult("partial", "derived", "one or more validity dimensions are incomplete")
        else:
            overall = ValidityResult("valid", "derived")
        self.dimensions["overall_measurement_valid"] = overall
        return overall

    def to_dict(self) -> dict[str, dict[str, str | None]]:
        return {
            name: {
                "status": result.status,
                "measurement_class": result.measurement_class,
                "reason": result.reason,
            }
            for name, result in self.dimensions.items()
        }
