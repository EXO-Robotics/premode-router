"""Rebuildable SQLite operational index for observer raw evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable

from .evidence_core import EventEnvelope
from .storage_core import iter_events
from .measurement import validate_receipt_schema


SQLITE_SCHEMA_VERSION = 2
MAX_INLINE_PAYLOAD_BYTES = 64 * 1024
MIGRATION_APPLIED_AT_UTC = "2026-07-10T00:00:00Z"


MIGRATION_DIRECTORY = Path(__file__).with_name("migrations")
MIGRATION_PATH = MIGRATION_DIRECTORY / "0001_initial.sql"  # compatibility seam for v1 rollback tests
MIGRATION_TIMESTAMPS = {1: "2026-07-10T00:00:00Z", 2: "2026-07-13T00:00:00Z"}
SQLITE_APPLICATION_ID = 0x504D4F42  # PMOB


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if application_id not in {0, SQLITE_APPLICATION_ID} or user_version > SQLITE_SCHEMA_VERSION:
        raise RuntimeError("database identity or schema is newer than supported")
    existing = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if existing:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
        version = versions[-1] if versions else 0
        if versions != list(range(1, version + 1)):
            raise RuntimeError("noncontiguous SQLite migration history")
        if user_version not in {0, version}:
            raise RuntimeError("SQLite user_version disagrees with migration history")
        if version > SQLITE_SCHEMA_VERSION:
            raise RuntimeError(f"database schema {version} is newer than supported {SQLITE_SCHEMA_VERSION}")
        if version == SQLITE_SCHEMA_VERSION:
            return
    else:
        version = 0
    for target_version in range(version + 1, SQLITE_SCHEMA_VERSION + 1):
        migration_path = MIGRATION_PATH if target_version == 1 else MIGRATION_DIRECTORY / f"{target_version:04d}_measurement_receipts.sql"
        if not migration_path.is_file():
            raise RuntimeError(f"no migration path from schema {target_version - 1}")
        _apply_migration(connection, migration_path, target_version)


def _apply_migration(connection: sqlite3.Connection, migration_path: Path, version: int) -> None:
    migration_sql = migration_path.read_text(encoding="utf-8")
    statements: list[str] = []
    buffer = ""
    for line in migration_sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer)
            buffer = ""
    if buffer.strip():
        raise RuntimeError("incomplete SQLite migration statement")
    connection.execute("BEGIN IMMEDIATE")
    try:
        for statement in statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at_utc) VALUES (?, ?)",
            (version, MIGRATION_TIMESTAMPS[version]),
        )
        connection.execute(f"PRAGMA application_id = {SQLITE_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _ingest_typed_event(connection: sqlite3.Connection, event: EventEnvelope) -> None:
    payload = event.payload
    event_type = event.event_type
    if event_type in {"run.state.changed", "run.recovered", "run.finalized"}:
        state = payload.get("state") or ({"run.recovered": "active", "run.finalized": "sealed"}.get(event_type))
        if state:
            connection.execute(
                "INSERT INTO run_states(run_id, state, timestamp_utc) VALUES (?, ?, ?)",
                (event.run_id, str(state), event.timestamp_utc),
            )
    if event_type in {"model.requested", "agent.model.requested"}:
        connection.execute("INSERT OR IGNORE INTO model_requests(event_id, request_hash) VALUES (?, ?)", (event.event_id, payload.get("request_hash")))
    if event_type == "model.stream.delta":
        connection.execute("INSERT OR IGNORE INTO model_stream_events(event_id, chunk_index) VALUES (?, ?)", (event.event_id, payload.get("chunk_index")))
    if event_type == "model.usage":
        connection.execute(
            "INSERT OR IGNORE INTO model_usage(event_id, prompt_tokens, completion_tokens) VALUES (?, ?, ?)",
            (event.event_id, payload.get("prompt_tokens"), payload.get("completion_tokens")),
        )
    if event_type == "model.timing":
        connection.execute(
            "INSERT OR IGNORE INTO model_timings(event_id, timing_name, original_value, original_unit, normalized_value) VALUES (?, ?, ?, ?, ?)",
            (event.event_id, payload.get("name"), payload.get("original_value"), payload.get("original_unit"), payload.get("normalized_value")),
        )
    if event_type == "agent.session.started":
        connection.execute("INSERT INTO agent_sessions(run_id, session_id) VALUES (?, ?)", (event.run_id, payload.get("session_id")))
    if event_type == "agent.turn.started":
        connection.execute("INSERT INTO agent_turns(run_id, turn_id) VALUES (?, ?)", (event.run_id, payload.get("turn_id")))
    if event_type == "agent.tool.requested":
        connection.execute("INSERT INTO tool_calls(run_id, tool_call_id) VALUES (?, ?)", (event.run_id, payload.get("tool_call_id")))
    if event_type == "validity.dimension":
        connection.execute(
            "INSERT OR REPLACE INTO validity_dimensions(run_id, dimension, status, measurement_class) VALUES (?, ?, ?, ?)",
            (event.run_id, payload.get("dimension"), payload.get("status"), event.measurement_class),
        )
    if event_type == "observer.measurement.receipt":
        receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else payload
        validate_receipt_schema(receipt)
        measurement = receipt.get("measurement_status") if isinstance(receipt.get("measurement_status"), dict) else {}
        recommendation = receipt.get("recommendation_safety") if isinstance(receipt.get("recommendation_safety"), dict) else {}
        quality = receipt.get("packet_quality") if isinstance(receipt.get("packet_quality"), dict) else {}
        attribution = receipt.get("safety_attribution") if isinstance(receipt.get("safety_attribution"), dict) else {}
        required = (receipt.get("schema_version"), receipt.get("derivation_version"), recommendation.get("status"), quality.get("status"), attribution.get("status"), measurement.get("status"))
        if not all(isinstance(value, str) and value for value in required):
            raise ValueError("measurement receipt is incomplete")
        connection.execute(
            """INSERT OR REPLACE INTO observer_measurement_receipts(
                run_id, receipt_schema, derivation_version, recommendation_status,
                packet_quality_status, attribution_status, measurement_status,
                legacy_unsafe, legacy_superseded, source_hash, receipt_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event.run_id, *required, receipt.get("legacy_unsafe"), int(receipt.get("legacy_unsafe_superseded") is True), payload.get("source_hash"), json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
        )


def ingest_events(connection: sqlite3.Connection, events: Iterable[EventEnvelope]) -> int:
    count = 0
    with connection:
        for event in events:
            payload_json = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if len(payload_json.encode("utf-8")) > MAX_INLINE_PAYLOAD_BYTES:
                raise ValueError("large event payload must be stored as a content-addressed blob")
            connection.execute("INSERT OR IGNORE INTO experiments VALUES (?)", (event.experiment_id,))
            connection.execute("INSERT OR IGNORE INTO tasks VALUES (?)", (event.task_id,))
            connection.execute("INSERT OR IGNORE INTO configurations VALUES (?)", (event.configuration_id,))
            connection.execute(
                "INSERT OR IGNORE INTO runs(run_id, experiment_id, task_id, configuration_id) VALUES (?, ?, ?, ?)",
                (event.run_id, event.experiment_id, event.task_id, event.configuration_id),
            )
            connection.execute("INSERT OR IGNORE INTO event_sources VALUES (?)", (event.source,))
            cursor = connection.execute(
                """INSERT INTO events(
                    event_id, run_id, source, event_type, sequence, source_sequence,
                    timestamp_utc, monotonic_ns, measurement_class, payload_schema, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.run_id,
                    event.source,
                    event.event_type,
                    event.sequence,
                    event.source_sequence,
                    event.timestamp_utc,
                    event.monotonic_ns,
                    event.measurement_class,
                    event.payload_schema,
                    payload_json,
                ),
            )
            _ingest_typed_event(connection, event)
            count += cursor.rowcount
    return count


def rebuild_database(database_path: Path, event_paths: Iterable[Path]) -> int:
    """Build a fresh database beside the destination and atomically replace it."""
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{database_path.name}.", dir=database_path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        connection = connect(temporary_path)
        try:
            migrate(connection)
            count = ingest_events(connection, iter_events(event_paths))
            failures = connection.execute("PRAGMA foreign_key_check").fetchall()
            if failures:
                raise RuntimeError(f"foreign key integrity failures: {failures}")
        finally:
            connection.close()
        os.replace(temporary_path, database_path)
        return count
    finally:
        temporary_path.unlink(missing_ok=True)
