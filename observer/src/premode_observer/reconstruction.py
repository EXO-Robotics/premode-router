"""Non-destructive reconstruction of legacy observer safety receipts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .measurement import OBSERVER_RECEIPT_SCHEMA, build_observer_receipt


MAX_RECEIPT_BYTES = 2 * 1024 * 1024
RECONSTRUCTION_SCHEMA = "observer-reconstruction.v1"


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _contains_false(value: Any) -> bool:
    return isinstance(value, Mapping) and any(item is False for item in value.values())


def reconstruct_legacy_receipt(source: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    """Return a corrected receipt without copying model-visible or personal text."""
    schema = source.get("schema_version")
    if schema is not None:
        raise ValueError("INCOMPATIBLE_SCHEMA")
    if not isinstance(source.get("run_id"), str) or not isinstance(source.get("validation"), Mapping):
        raise ValueError("INCOMPATIBLE_SCHEMA")
    run_value = source.get("run") if isinstance(source.get("run"), Mapping) else source
    validation = source.get("validation") if isinstance(source.get("validation"), Mapping) else None
    selected = run_value.get("selected_paths") if isinstance(run_value.get("selected_paths"), list) else None
    packet_hash = run_value.get("packet_sha256") or run_value.get("packet_hash")
    projection_hash = _canonical_hash(selected) if selected is not None else None
    validation_unsafe = validation.get("unsafe") if isinstance(validation, Mapping) else None
    top_level_unsafe = source.get("unsafe")
    authoritative_legacy_violation = isinstance(validation, Mapping) and (
        validation.get("outcome_class") == "unsafe"
        or _contains_false(validation.get("forbidden_paths_avoided"))
        or _contains_false(validation.get("forbidden_paths_unchanged"))
    )
    if isinstance(validation_unsafe, bool):
        legacy_unsafe = validation_unsafe
    elif isinstance(source.get("experiment_family"), str):
        legacy_unsafe = True if authoritative_legacy_violation else top_level_unsafe if isinstance(top_level_unsafe, bool) else None
    elif isinstance(top_level_unsafe, bool):
        legacy_unsafe = top_level_unsafe
    else:
        legacy_unsafe = True if authoritative_legacy_violation else None
    receipt = build_observer_receipt(
        repo_root,
        packet_paths=selected,
        packet_hash=str(packet_hash) if packet_hash else None,
        packet_projection_hash=projection_hash,
        run=run_value,
        validation=validation,
        # Legacy field presence is not proof of the original model-visible bytes
        # or execution-time filesystem snapshot. Reconstruction therefore fails
        # closed until a future frozen-evidence format permits recomputation.
        packet_hash_verified=False,
        packet_changed=run_value.get("packet_changed"),
        baseline_same_behavior=run_value.get("baseline_same_behavior"),
        action_order_complete=bool(run_value.get("action_order_complete")),
        legacy_unsafe=legacy_unsafe,
        source_receipt_hashes=(_canonical_hash(source),),
        reconstruction_status="reconstructed_from_bounded_legacy_fields",
    )
    return {"schema_version": RECONSTRUCTION_SCHEMA, "source_preserved": True, "source_hash": _canonical_hash(source), "corrected_receipt": receipt.to_dict()}


def reconstruct_file(source_path: Path, repo_root: Path, output_path: Path) -> dict[str, Any]:
    source_path = Path(source_path)
    output_path = Path(output_path)
    if source_path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError("SOURCE_RECEIPT_TOO_LARGE")
    source_bytes = source_path.read_bytes()
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    resolved_source = source_path.resolve(strict=True)
    resolved_output = output_path.parent.resolve(strict=True) / output_path.name
    if resolved_output == resolved_source or output_path.exists() or output_path.is_symlink():
        raise ValueError("OUTPUT_PATH_MUST_BE_NEW_AND_DISTINCT")
    source = json.loads(source_bytes.decode("utf-8"))
    if not isinstance(source, dict):
        raise ValueError("SOURCE_RECEIPT_NOT_OBJECT")
    corrected = reconstruct_legacy_receipt(source, repo_root)
    payload = (json.dumps(corrected, sort_keys=True, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(output_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_digest:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("SOURCE_RECEIPT_MUTATED")
    return corrected


def public_summary(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in receipts:
        corrected = item.get("corrected_receipt") if isinstance(item.get("corrected_receipt"), Mapping) else {}
        status = corrected.get("measurement_status") if isinstance(corrected.get("measurement_status"), Mapping) else {}
        raw = status.get("status")
        key = str(raw) if raw in {"COMPLETE", "INDETERMINATE", "CONTRADICTORY", "CORRUPT", "INCOMPATIBLE_SCHEMA", "INVALID"} else "INCOMPATIBLE_SCHEMA"
        counts[key] = counts.get(key, 0) + 1
    return {"schema_version": "observer-reconstruction-summary.v1", "receipt_count": len(receipts), "measurement_status_counts": dict(sorted(counts.items())), "content_included": False}
