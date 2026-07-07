from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WritePolicy:
    name: str
    can_write_lockfile: bool
    can_write_cache_manifest: bool
    can_write_inventory: bool
    can_write_topology: bool
    can_write_telemetry: bool
    can_write_runtime_state: bool
    can_write_install_manifest: bool
    can_register_mcp: bool
    can_run_codex: bool
    can_delete_local_state: bool
    can_write_temp_packet: bool
    can_write_audit: bool
    can_write_metrics: bool


NORMAL = WritePolicy(
    name="normal",
    can_write_lockfile=True,
    can_write_cache_manifest=True,
    can_write_inventory=True,
    can_write_topology=True,
    can_write_telemetry=True,
    can_write_runtime_state=True,
    can_write_install_manifest=True,
    can_register_mcp=True,
    can_run_codex=True,
    can_delete_local_state=True,
    can_write_temp_packet=True,
    can_write_audit=True,
    can_write_metrics=True,
)

NO_RECORD = WritePolicy(
    name="no_record",
    can_write_lockfile=False,
    can_write_cache_manifest=False,
    can_write_inventory=False,
    can_write_topology=False,
    can_write_telemetry=False,
    can_write_runtime_state=False,
    can_write_install_manifest=True,
    can_register_mcp=False,
    can_run_codex=False,
    can_delete_local_state=False,
    can_write_temp_packet=False,
    can_write_audit=False,
    can_write_metrics=False,
)

ADVISORY = WritePolicy(
    name="advisory",
    can_write_lockfile=False,
    can_write_cache_manifest=False,
    can_write_inventory=False,
    can_write_topology=False,
    can_write_telemetry=False,
    can_write_runtime_state=False,
    can_write_install_manifest=False,
    can_register_mcp=False,
    can_run_codex=False,
    can_delete_local_state=False,
    can_write_temp_packet=False,
    can_write_audit=False,
    can_write_metrics=False,
)


def resolve_write_policy(policy: WritePolicy | str | None = None) -> WritePolicy:
    if isinstance(policy, WritePolicy):
        return policy
    if policy is None:
        return NORMAL
    normalized = str(policy).strip().lower().replace("-", "_")
    if normalized == "normal":
        return NORMAL
    if normalized in {"no_record", "norecord"}:
        return NO_RECORD
    if normalized == "advisory":
        return ADVISORY
    raise ValueError(f"Unknown write policy: {policy}")
