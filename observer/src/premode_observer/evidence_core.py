"""Versioned evidence primitives for the isolated OBSERVER-A package."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import os
import threading
import time
from typing import Any, Mapping
from uuid import UUID, uuid4


EVENT_SCHEMA_VERSION = "1.0.0"
MEASUREMENT_CLASSES = frozenset(
    {
        "direct_observed",
        "server_reported",
        "agent_reported",
        "pcodex_reported",
        "os_sampled",
        "derived",
        "reconciled",
        "inferred",
        "unavailable",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _uuid_text(value: str, name: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


@dataclass(frozen=True, slots=True)
class RunIdentity:
    run_id: str
    experiment_id: str
    task_id: str
    configuration_id: str
    created_at_utc: str

    @classmethod
    def create(cls, experiment_id: str, task_id: str, configuration_id: str) -> "RunIdentity":
        for name, value in (
            ("experiment_id", experiment_id),
            ("task_id", task_id),
            ("configuration_id", configuration_id),
        ):
            if not value or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        return cls(str(uuid4()), experiment_id, task_id, configuration_id, utc_now())

    def __post_init__(self) -> None:
        _uuid_text(self.run_id, "run_id")


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    schema_version: str
    event_id: str
    run_id: str
    experiment_id: str
    task_id: str
    configuration_id: str
    source: str
    event_type: str
    timestamp_utc: str
    monotonic_ns: int
    process_id: int
    thread_id: int
    sequence: int
    source_sequence: int
    parent_event_id: str | None
    correlation_id: str | None
    measurement_class: str
    payload_schema: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        identity: RunIdentity,
        *,
        source: str,
        event_type: str,
        sequence: int,
        source_sequence: int,
        measurement_class: str,
        payload_schema: str,
        payload: Mapping[str, Any] | None = None,
        parent_event_id: str | None = None,
        correlation_id: str | None = None,
    ) -> "EventEnvelope":
        return cls(
            schema_version=EVENT_SCHEMA_VERSION,
            event_id=str(uuid4()),
            run_id=identity.run_id,
            experiment_id=identity.experiment_id,
            task_id=identity.task_id,
            configuration_id=identity.configuration_id,
            source=source,
            event_type=event_type,
            timestamp_utc=utc_now(),
            monotonic_ns=time.monotonic_ns(),
            process_id=os.getpid(),
            thread_id=threading.get_ident(),
            sequence=sequence,
            source_sequence=source_sequence,
            parent_event_id=parent_event_id,
            correlation_id=correlation_id,
            measurement_class=measurement_class,
            payload_schema=payload_schema,
            payload=dict(payload or {}),
        )

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported event schema version: {self.schema_version}")
        _uuid_text(self.event_id, "event_id")
        _uuid_text(self.run_id, "run_id")
        if self.parent_event_id is not None:
            _uuid_text(self.parent_event_id, "parent_event_id")
        if self.measurement_class not in MEASUREMENT_CLASSES:
            raise ValueError(f"invalid measurement_class: {self.measurement_class}")
        for name in ("experiment_id", "task_id", "configuration_id", "source", "event_type", "payload_schema"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if self.sequence < 0 or self.source_sequence < 0 or self.monotonic_ns < 0:
            raise ValueError("sequence and monotonic values must be non-negative")
        try:
            parsed = datetime.fromisoformat(self.timestamp_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp_utc must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("timestamp_utc must be UTC")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EventEnvelope":
        return cls(**dict(value))


class RunState(str, Enum):
    INITIALIZED = "initialized"
    ACTIVE = "active"
    SEALING = "sealing"
    SEALED = "sealed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.INITIALIZED: frozenset({RunState.ACTIVE, RunState.FAILED}),
    RunState.ACTIVE: frozenset({RunState.SEALING, RunState.INTERRUPTED, RunState.FAILED}),
    RunState.SEALING: frozenset({RunState.SEALED, RunState.INTERRUPTED, RunState.FAILED}),
    RunState.INTERRUPTED: frozenset({RunState.ACTIVE, RunState.SEALING, RunState.FAILED}),
    RunState.SEALED: frozenset(),
    RunState.FAILED: frozenset(),
}


@dataclass(slots=True)
class RunStateMachine:
    state: RunState = RunState.INITIALIZED

    def transition(self, target: RunState) -> RunState:
        if target not in _TRANSITIONS[self.state]:
            raise ValueError(f"invalid run-state transition: {self.state.value} -> {target.value}")
        self.state = target
        return self.state
