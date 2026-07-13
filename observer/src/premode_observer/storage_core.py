"""Immutable raw evidence, manifests, recovery, and content-addressed blobs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .evidence_core import EventEnvelope, RunIdentity, RunState, RunStateMachine, utc_now


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, value: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise FileExistsError(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            # A hard-link publication is atomic and fails if another writer won,
            # unlike a check followed by os.replace(), which has a race window.
            os.link(temporary_path, path)
            temporary_path.unlink()
        else:
            os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class BlobRef:
    algorithm: str
    digest: str
    size_bytes: int
    relative_path: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "algorithm": self.algorithm,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "relative_path": self.relative_path,
        }


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def put(self, value: bytes) -> BlobRef:
        digest = sha256_bytes(value)
        relative = Path("sha256") / digest[:2] / digest
        destination = self.root / relative
        if destination.exists():
            if destination.read_bytes() != value:
                raise RuntimeError(f"content-address collision or corruption: {digest}")
        else:
            atomic_write(destination, value, exclusive=True)
        return BlobRef("sha256", digest, len(value), relative.as_posix())

    def read(self, reference: BlobRef) -> bytes:
        value = (self.root / reference.relative_path).read_bytes()
        if len(value) != reference.size_bytes or sha256_bytes(value) != reference.digest:
            raise ValueError(f"blob integrity failure: {reference.digest}")
        return value


class ManifestStore:
    def __init__(self, run_root: Path) -> None:
        self.run_root = Path(run_root)

    def write_once(self, name: str, payload: Mapping[str, Any]) -> tuple[Path, str]:
        if name not in {"manifest.initial", "manifest.final"}:
            raise ValueError("manifest name must be manifest.initial or manifest.final")
        path = self.run_root / f"{name}.json"
        encoded = canonical_json_bytes(dict(payload))
        digest = sha256_bytes(encoded)
        atomic_write(path, encoded, exclusive=True)
        try:
            atomic_write(self.run_root / f"{name}.sha256", f"{digest}  {path.name}\n".encode(), exclusive=True)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path, digest

    def verify(self, name: str) -> bool:
        path = self.run_root / f"{name}.json"
        sidecar = self.run_root / f"{name}.sha256"
        expected = sidecar.read_text(encoding="utf-8").split()[0]
        return sha256_file(path) == expected


class AppendOnlyEventStore:
    """Append raw events to one active segment and immutably seal completed segments."""

    def __init__(self, run_root: Path, run_id: str) -> None:
        self.run_root = Path(run_root)
        assert_run_mutable(self.run_root)
        self.run_id = run_id
        self.active_dir = self.run_root / "raw" / "active"
        self.sealed_dir = self.run_root / "raw" / "sealed"
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.sealed_dir.mkdir(parents=True, exist_ok=True)
        self._segment_number = self._next_segment_number()
        self.active_path = self.active_dir / f"events-{self._segment_number:06d}.jsonl"
        self.active_path.touch(exist_ok=True)
        self._expected_size = self.active_path.stat().st_size
        self._expected_digest = sha256_file(self.active_path)
        paths = sorted(self.sealed_dir.glob("events-*.jsonl")) + [self.active_path]
        self._last_sequence = self._scan_last_sequence(paths)

    def _next_segment_number(self) -> int:
        numbers = []
        for path in (*self.active_dir.glob("events-*.jsonl"), *self.sealed_dir.glob("events-*.jsonl")):
            try:
                numbers.append(int(path.stem.split("-")[1]))
            except (IndexError, ValueError):
                continue
        active_numbers = [
            int(path.stem.split("-")[1])
            for path in self.active_dir.glob("events-*.jsonl")
            if path.stem.split("-")[1].isdigit()
        ]
        if active_numbers:
            return max(active_numbers)
        return max(numbers, default=0) + 1

    @staticmethod
    def _scan_last_sequence(paths: Iterable[Path]) -> int:
        last = -1
        for event in iter_events(paths):
            if event.sequence <= last:
                raise ValueError("event sequence is not strictly increasing")
            last = event.sequence
        return last

    def _verify_active_prefix(self) -> None:
        if self.active_path.stat().st_size != self._expected_size:
            raise RuntimeError("active event segment size changed outside append-only store")
        if sha256_file(self.active_path) != self._expected_digest:
            raise RuntimeError("active event segment content changed outside append-only store")

    def append(self, event: EventEnvelope) -> int:
        assert_run_mutable(self.run_root)
        if read_state(self.run_root) is RunState.INITIALIZED:
            transition_state(self.run_root, RunState.ACTIVE)
        if event.run_id != self.run_id:
            raise ValueError("event run_id does not match event store")
        if event.sequence <= self._last_sequence:
            raise ValueError("event sequence must be strictly increasing")
        self._verify_active_prefix()
        encoded = canonical_json_bytes(event.to_dict())
        with self.active_path.open("ab", buffering=0) as handle:
            handle.write(encoded)
            os.fsync(handle.fileno())
        self._expected_size += len(encoded)
        self._expected_digest = sha256_file(self.active_path)
        self._last_sequence = event.sequence
        return len(encoded)

    def seal(self) -> dict[str, Any]:
        self._verify_active_prefix()
        destination = self.sealed_dir / self.active_path.name
        if destination.exists():
            raise FileExistsError(destination)
        digest = self._expected_digest
        pending_sidecar = self.active_path.with_suffix(".jsonl.sha256.pending")
        atomic_write(pending_sidecar, f"{digest}  {destination.name}\n".encode(), exclusive=True)
        os.replace(self.active_path, destination)
        _fsync_directory(self.sealed_dir)
        os.replace(pending_sidecar, destination.with_suffix(".jsonl.sha256"))
        _fsync_directory(self.sealed_dir)
        result = {
            "path": destination.relative_to(self.run_root).as_posix(),
            "sha256": digest,
            "size_bytes": destination.stat().st_size,
            "last_sequence": self._last_sequence,
        }
        self._segment_number += 1
        self.active_path = self.active_dir / f"events-{self._segment_number:06d}.jsonl"
        self.active_path.touch(exist_ok=False)
        self._expected_size = 0
        self._expected_digest = sha256_file(self.active_path)
        return result

    def verify_sealed(self) -> list[dict[str, Any]]:
        results = []
        last_sequence = -1
        for path in sorted(self.sealed_dir.glob("events-*.jsonl")):
            sidecar = path.with_suffix(".jsonl.sha256")
            expected = None
            actual = sha256_file(path)
            try:
                expected = sidecar.read_text(encoding="utf-8").split()[0]
                valid = expected == actual
                if valid:
                    for event in iter_events([path]):
                        if event.sequence <= last_sequence:
                            valid = False
                            break
                        last_sequence = event.sequence
            except (OSError, IndexError, ValueError):
                valid = False
            results.append({"path": path.name, "valid": valid, "expected_sha256": expected, "actual_sha256": actual})
        return results

    def recover_active(self, blobs: BlobStore) -> dict[str, Any]:
        """Preserve and remove an incomplete tail, then resume after the last valid event."""
        raw = self.active_path.read_bytes()
        complete_length = raw.rfind(b"\n") + 1
        tail = raw[complete_length:]
        events = list(iter_events_bytes(raw[:complete_length]))
        last = self._scan_last_sequence(sorted(self.sealed_dir.glob("events-*.jsonl")))
        for event in events:
            if event.run_id != self.run_id or event.sequence <= last:
                raise ValueError("active segment contains invalid event ordering or run identity")
            last = event.sequence
        tail_ref = None
        if tail:
            tail_ref = blobs.put(tail)
            with self.active_path.open("r+b") as handle:
                handle.truncate(complete_length)
                handle.flush()
                os.fsync(handle.fileno())
        self._expected_size = complete_length
        self._expected_digest = sha256_file(self.active_path)
        self._last_sequence = last
        return {
            "status": "recovered" if tail else "clean",
            "valid_event_count": len(events),
            "last_sequence": last,
            "discarded_tail": tail_ref.to_dict() if tail_ref else None,
        }

    @classmethod
    def recover_orphaned_seals(cls, run_root: Path) -> list[dict[str, Any]]:
        """Complete sidecar publication or return uncertified segments to active."""
        run_root = Path(run_root)
        active_dir = run_root / "raw" / "active"
        sealed_dir = run_root / "raw" / "sealed"
        receipts: list[dict[str, Any]] = []
        for pending in sorted(active_dir.glob("events-*.jsonl.sha256.pending")):
            active = active_dir / pending.name.removesuffix(".sha256.pending")
            if not active.exists():
                continue
            expected = pending.read_text(encoding="utf-8").split()[0]
            actual = sha256_file(active)
            if expected != actual:
                raise RuntimeError(f"stale seal sidecar does not match active segment: {active.name}")
            pending.unlink()
            receipts.append({"segment": active.name, "action": "cleared_prepublication_sidecar", "sha256": actual})
        for sealed in sorted(sealed_dir.glob("events-*.jsonl")):
            sidecar = sealed.with_suffix(".jsonl.sha256")
            if sidecar.exists():
                continue
            pending = active_dir / f"{sealed.name}.sha256.pending"
            actual = sha256_file(sealed)
            if pending.exists():
                try:
                    expected = pending.read_text(encoding="utf-8").split()[0]
                except IndexError:
                    expected = ""
                if expected == actual:
                    os.replace(pending, sidecar)
                    receipts.append({"segment": sealed.name, "action": "completed_sidecar", "sha256": actual})
                    continue
            destination = active_dir / sealed.name
            if destination.exists():
                raise RuntimeError(f"cannot recover orphaned sealed segment; active path exists: {sealed.name}")
            os.replace(sealed, destination)
            pending.unlink(missing_ok=True)
            receipts.append({"segment": sealed.name, "action": "returned_to_active", "sha256": actual})
        return receipts


def iter_events_bytes(value: bytes) -> Iterable[EventEnvelope]:
    for line_number, line in enumerate(value.splitlines(), start=1):
        if not line:
            continue
        try:
            yield EventEnvelope.from_dict(json.loads(line))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid event at line {line_number}") from exc


def iter_events(paths: Iterable[Path]) -> Iterable[EventEnvelope]:
    for path in paths:
        yield from iter_events_bytes(path.read_bytes())


def initialize_run_layout(root: Path, identity: RunIdentity) -> Path:
    run_root = Path(root) / "runs" / identity.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    for relative in (
        "raw/active",
        "raw/sealed",
        "artifacts",
        "blobs",
        "request",
        "response",
        "runtime",
        "agent",
        "normalized",
        "validation",
    ):
        (run_root / relative).mkdir(parents=True, exist_ok=False)
    ManifestStore(run_root).write_once(
        "manifest.initial",
        {
            "schema_version": "1.0.0",
            "identity": {
                "run_id": identity.run_id,
                "experiment_id": identity.experiment_id,
                "task_id": identity.task_id,
                "configuration_id": identity.configuration_id,
                "created_at_utc": identity.created_at_utc,
            },
        },
    )
    write_state(run_root, RunState.INITIALIZED, sequence=0)
    return run_root


def write_state(run_root: Path, state: RunState, *, sequence: int, detail: str | None = None) -> None:
    atomic_write(
        Path(run_root) / "state.json",
        canonical_json_bytes(
            {
                "schema_version": "1.0.0",
                "state": state.value,
                "sequence": sequence,
                "updated_at_utc": utc_now(),
                "detail": detail,
            }
        ),
    )


def read_state(run_root: Path) -> RunState:
    path = Path(run_root) / "state.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    return RunState(json.loads(path.read_text(encoding="utf-8"))["state"])


def assert_run_mutable(run_root: Path) -> None:
    run_root = Path(run_root)
    if (run_root / "manifest.final.json").exists() or (run_root / "manifest.final.sha256").exists():
        raise RuntimeError("sealed run is immutable")
    state_path = run_root / "state.json"
    if state_path.is_file() and read_state(run_root) in {RunState.SEALED, RunState.FAILED}:
        raise RuntimeError("sealed or failed run is immutable")


def transition_state(run_root: Path, target: RunState, *, detail: str | None = None) -> None:
    current = read_state(run_root)
    RunStateMachine(current).transition(target)
    write_state(run_root, target, sequence=_read_state_sequence(run_root) + 1, detail=detail)


def _ensure_active(run_root: Path) -> None:
    if read_state(run_root) is RunState.INITIALIZED:
        transition_state(run_root, RunState.ACTIVE)


def immutable_inventory(run_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Inventory evidence that must not change after finalization."""
    run_root = Path(run_root)

    def entries(paths: Iterable[Path]) -> list[dict[str, Any]]:
        return [
            {
                "path": path.relative_to(run_root).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(paths)
            if path.is_file()
        ]

    evidence_paths: list[Path] = []
    for name in ("request", "response", "runtime", "agent", "artifacts"):
        evidence_paths.extend((run_root / name).rglob("*"))
    blob_paths = list((run_root / "blobs").rglob("*"))
    return {"evidence_files": entries(evidence_paths), "blob_files": entries(blob_paths)}


def _read_state_sequence(run_root: Path) -> int:
    path = Path(run_root) / "state.json"
    if not path.exists():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8")).get("sequence", 0))


def recover_run(run_root: Path, identity: RunIdentity) -> dict[str, Any]:
    """Recover a run and durably record every mutation in raw evidence and artifacts."""
    run_root = Path(run_root)
    assert_run_mutable(run_root)
    orphan_receipts = AppendOnlyEventStore.recover_orphaned_seals(run_root)
    store = AppendOnlyEventStore(run_root, identity.run_id)
    active_receipt = store.recover_active(BlobStore(run_root / "blobs"))
    changed = bool(orphan_receipts) or active_receipt["status"] == "recovered"
    state_sequence = _read_state_sequence(run_root) + 1
    if changed:
        _ensure_active(run_root)
        transition_state(run_root, RunState.INTERRUPTED, detail="recovery_started")
        event = EventEnvelope.create(
            identity,
            source="observer_storage",
            event_type="run.recovered",
            sequence=store._last_sequence + 1,
            source_sequence=0,
            measurement_class="direct_observed",
            payload_schema="run.recovered/1.0.0",
            payload={"orphaned_seals": orphan_receipts, "active_segment": active_receipt},
        )
        store.append(event)
        receipt = {
            "schema_version": "1.0.0",
            "run_id": identity.run_id,
            "recorded_at_utc": utc_now(),
            "event_id": event.event_id,
            "orphaned_seals": orphan_receipts,
            "active_segment": active_receipt,
        }
        receipt_bytes = canonical_json_bytes(receipt)
        receipt_path = run_root / "artifacts" / "recovery" / f"{sha256_bytes(receipt_bytes)}.json"
        atomic_write(receipt_path, receipt_bytes, exclusive=True)
        transition_state(run_root, RunState.ACTIVE, detail="recovery_completed")
        receipt["receipt_path"] = receipt_path.relative_to(run_root).as_posix()
        return receipt
    return {"schema_version": "1.0.0", "run_id": identity.run_id, "status": "clean", "orphaned_seals": []}


def finalize_run(run_root: Path, identity: RunIdentity, *, summary: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Seal remaining raw evidence, write the immutable final manifest, and close state."""
    run_root = Path(run_root)
    if (run_root / "manifest.final.json").exists() or (run_root / "manifest.final.sha256").exists():
        raise FileExistsError(run_root / "manifest.final.json")
    assert_run_mutable(run_root)
    AppendOnlyEventStore.recover_orphaned_seals(run_root)
    store = AppendOnlyEventStore(run_root, identity.run_id)
    _ensure_active(run_root)
    if read_state(run_root) is not RunState.SEALING:
        transition_state(run_root, RunState.SEALING)
    final_event = EventEnvelope.create(
        identity,
        source="observer_storage",
        event_type="run.finalized",
        sequence=store._last_sequence + 1,
        source_sequence=0,
        measurement_class="direct_observed",
        payload_schema="run.finalized/1.0.0",
        payload=dict(summary or {}),
    )
    store.append(final_event)
    segment = store.seal()
    store.active_path.unlink()
    sealed_segments = [
        {
            "path": path.relative_to(run_root).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted((run_root / "raw" / "sealed").glob("events-*.jsonl"))
    ]
    inventory = immutable_inventory(run_root)
    manifest = {
        "schema_version": "1.0.0",
        "run_id": identity.run_id,
        "completed_at_utc": utc_now(),
        "final_event_id": final_event.event_id,
        "sealed_segments": sealed_segments,
        **inventory,
        "summary": dict(summary or {}),
    }
    _, digest = ManifestStore(run_root).write_once("manifest.final", manifest)
    transition_state(run_root, RunState.SEALED)
    return {"manifest_sha256": digest, "final_event_id": final_event.event_id, "last_segment": segment}


def copy_verified(source: Path, destination: Path) -> None:
    """Copy helper used only for recovery/export while detecting short or altered copies."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256_file(source) != sha256_file(destination):
        destination.unlink(missing_ok=True)
        raise IOError("copy integrity verification failed")
