from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile

import pytest

from premode.no_write import (
    GovernedRoot,
    GovernedRootSet,
    SnapshotPolicy,
    compare_snapshots,
    evidence_receipt,
    governed_roots_from_product,
    snapshot_roots,
    verify_no_write,
    write_evidence_receipts,
)
from premode.product_contract import validate_payload_against_schema


def _authoritative_roots(tmp_path: Path) -> list[GovernedRoot]:
    repo = tmp_path / "repository"
    home = tmp_path / "home"
    temp = tmp_path / "controlled-temp"
    for path in (repo, home, temp):
        path.mkdir(exist_ok=True)
    env = {
        "HOME": str(home),
        "CODEX_HOME": str(home / "codex-home"),
        "XDG_CONFIG_HOME": str(home / "xdg-config"),
        "XDG_CACHE_HOME": str(home / "xdg-cache"),
        "TMPDIR": str(temp),
    }
    return governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)


def _complete_snapshot_verification(tmp_path: Path, operation=lambda: None) -> dict[str, object]:
    verification = verify_no_write(operation, roots=_authoritative_roots(tmp_path), monitor_processes=False)
    verification["process_observation"] = "complete"
    verification["filesystem_observation"] = "complete"
    return verification


def test_snapshot_detects_content_metadata_membership_and_missing_roots(tmp_path: Path) -> None:
    root = tmp_path / "repository with spaces β"
    root.mkdir()
    regular = root / "regular.bin"
    regular.write_bytes(b"alpha")
    missing = tmp_path / "missing"
    before = snapshot_roots([GovernedRoot("repo", root), GovernedRoot("missing", missing)])

    regular.write_bytes(b"bravo")
    (root / "new.txt").write_text("new", encoding="utf-8")
    after = snapshot_roots([GovernedRoot("repo", root), GovernedRoot("missing", missing)])
    comparison = compare_snapshots(before, after)

    assert comparison["unchanged"] is False
    assert {item["path"] for item in comparison["changes"]} >= {"regular.bin", "new.txt"}
    assert next(item for item in before["roots"] if item["root_id"] == "missing")["exists"] is False


def test_snapshot_does_not_follow_symlinks_and_records_hardlinks_and_special_files() -> None:
    with tempfile.TemporaryDirectory(prefix="pcnw-", dir="/private/tmp") as temporary:
        base = Path(temporary)
        root = base / "root"
        outside = base / "outside"
        root.mkdir()
        outside.mkdir()
        secret = outside / "not-enumerated.txt"
        secret.write_text("outside", encoding="utf-8")
        original = root / "original"
        original.write_text("same inode", encoding="utf-8")
        os.link(original, root / "hard-link")
        os.symlink(outside, root / "escape")
        os.symlink(root / "does-not-exist", root / "broken")
        fifo = root / "pipe"
        os.mkfifo(fifo)
        socket_path = root / "sock"
        server = socket.socket(socket.AF_UNIX)
        socket_supported = False
        try:
            try:
                server.bind(str(socket_path))
                socket_supported = True
            except PermissionError:
                pass
            snapshot = snapshot_roots([GovernedRoot("repo", root)])
        finally:
            server.close()

        entries = {item["path"]: item for item in snapshot["roots"][0]["entries"]}
        assert "escape/not-enumerated.txt" not in entries
        assert entries["escape"]["entry_type"] == "symlink"
        assert entries["broken"]["entry_type"] == "symlink"
        assert entries["original"]["inode"] == entries["hard-link"]["inode"]
        assert entries["original"]["hard_link_count"] == 2
        assert entries["pipe"]["entry_type"] == "fifo"
        if socket_supported:
            assert entries["sock"]["entry_type"] == "socket"


def test_large_file_uses_bounded_sampling_and_detects_sampled_change(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"a" * 1024)
    roots = [GovernedRoot("repo", tmp_path)]
    policy = SnapshotPolicy(full_hash_limit=128, sample_size=32)
    before = snapshot_roots(roots, policy=policy)
    with path.open("r+b") as handle:
        handle.seek(512)
        handle.write(b"changed")
    after = snapshot_roots(roots, policy=policy)
    entry = next(item for item in before["roots"][0]["entries"] if item["path"] == "large.bin")
    assert entry["hash_strategy"] == "sha256_size_and_three_samples"
    assert entry["bytes_hashed"] <= 96
    assert compare_snapshots(before, after)["unchanged"] is False


def test_verify_and_sanitized_receipt_are_output_separated(tmp_path: Path) -> None:
    roots = _authoritative_roots(tmp_path)
    governed = next(root.path for root in roots if root.root_id == "repository")
    (governed / "state").write_text("fixed", encoding="utf-8")
    verification = verify_no_write(lambda: "ok", roots=roots, monitor_processes=False)
    verification["process_observation"] = "complete"
    verification["filesystem_observation"] = "complete"
    receipt = evidence_receipt(
        verification,
        product_version="0.3.0b1",
        commit_sha="a" * 40,
        command="pcodex run --dry-run",
        arguments=["--dry-run", "private task text"],
        scenario_id="clean",
        timestamp="2026-07-13T00:00:00Z",
    )
    assert receipt["result"] == "pass"
    assert str(governed) not in json.dumps(receipt)
    assert "private task text" not in json.dumps(receipt)

    output = tmp_path / "evidence-output"
    private_path, public_path = write_evidence_receipts(
        output,
        verification,
        product_version="0.3.0b1",
        commit_sha="a" * 40,
        command="pcodex run --dry-run",
        arguments=["--dry-run", "private task text"],
        scenario_id="clean",
        timestamp="2026-07-13T00:00:00Z",
    )
    assert private_path.exists() and public_path.exists()
    assert compare_snapshots(verification["before"], verification["after"])["unchanged"] is True


def test_evidence_schema_accepts_sanitized_receipt(tmp_path: Path) -> None:
    verification = _complete_snapshot_verification(tmp_path)
    receipt = evidence_receipt(
        verification,
        product_version="0.3.0b1",
        commit_sha="b" * 40,
        command="pcodex status --advisory",
        arguments=["status", "--advisory"],
        scenario_id="missing-state",
        timestamp="2026-07-13T00:00:00Z",
    )
    schema = json.loads((Path(__file__).parents[2] / "schemas" / "pcodex.no-write-evidence.schema.json").read_text(encoding="utf-8"))
    validate_payload_against_schema(receipt, schema)


def test_public_schema_rejects_private_field_content(tmp_path: Path) -> None:
    verification = _complete_snapshot_verification(tmp_path)
    receipt = evidence_receipt(
        verification,
        product_version="0.3.0b1",
        commit_sha="b" * 40,
        command="pcodex.status.advisory",
        arguments=["status", "--advisory"],
        scenario_id="privacy-schema",
        timestamp="2026-07-13T00:00:00Z",
    )
    schema = json.loads((Path(__file__).parents[2] / "schemas" / "pcodex.no-write-evidence.schema.json").read_text(encoding="utf-8"))
    for field, value in (
        ("arguments", ["RAW PRIVATE TASK /" + "Users/alice/private"]),
        ("exceptions", ["secret=plaintext"]),
        ("network_attempted_if_measurable", "/" + "Users/alice/network.log"),
    ):
        mutated = {**receipt, field: value}
        with pytest.raises(ValueError):
            validate_payload_against_schema(mutated, schema)


def test_private_receipt_has_registered_strict_schema(tmp_path: Path) -> None:
    verification = _complete_snapshot_verification(tmp_path)
    receipt = evidence_receipt(
        verification,
        product_version="0.3.0b1",
        commit_sha="e" * 40,
        command="pcodex status --advisory",
        arguments=["status", "--advisory"],
        scenario_id="private-schema",
        timestamp="2026-07-13T00:00:00Z",
        sanitized=False,
    )
    schema = json.loads((Path(__file__).parents[2] / "schemas" / "pcodex.no-write-evidence.private.schema.json").read_text(encoding="utf-8"))
    validate_payload_against_schema(receipt, schema)


def test_empty_and_incomplete_observation_fails_closed(tmp_path: Path) -> None:
    empty = verify_no_write(lambda: None, roots=[], monitor_processes=False)
    assert empty["passed"] is False
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    (unreadable / "file").write_text("data", encoding="utf-8")
    unreadable.chmod(0)
    try:
        verification = verify_no_write(lambda: None, roots=[GovernedRoot("repo", unreadable)], monitor_processes=False)
    finally:
        unreadable.chmod(0o700)
    if verification["before"]["complete"] is False:
        assert verification["passed"] is False


def test_receipt_writer_rejects_governed_output(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    verification = verify_no_write(lambda: None, roots=[GovernedRoot("repo", repo)], monitor_processes=False)
    with pytest.raises(ValueError, match="overlaps governed root"):
        write_evidence_receipts(
            repo / "receipts",
            verification,
            product_version="0.3.0b1",
            commit_sha="a" * 40,
            command="pcodex status --advisory",
            arguments=["status", "--advisory"],
            scenario_id="overlap",
            timestamp="2026-07-13T00:00:00Z",
        )


def test_operation_exception_and_external_config_change_are_evidenced(tmp_path: Path) -> None:
    roots = _authoritative_roots(tmp_path)
    external = next(root.path for root in roots if root.root_id == "codex_plugins")
    external.mkdir(parents=True)

    def fail_after_write() -> None:
        (external / "changed").write_text("mutation", encoding="utf-8")
        raise RuntimeError("synthetic")

    verification = verify_no_write(
        fail_after_write,
        roots=roots,
        monitor_processes=True,
        monitor_filesystem=True,
    )
    receipt = evidence_receipt(
        verification,
        product_version="0.3.0b1",
        commit_sha="c" * 40,
        command="failure-path",
        arguments=["--dry-run"],
        scenario_id="exception",
        timestamp="2026-07-13T00:00:00Z",
    )
    assert verification["exceptions"] == ["RuntimeError"]
    assert receipt["external_config_unchanged"] is False
    assert "RuntimeError" in receipt["exceptions"]
    assert receipt["result"] == "fail"


def test_base_exception_is_snapshotted_and_evidenced(tmp_path: Path) -> None:
    verification = verify_no_write(
        lambda: (_ for _ in ()).throw(SystemExit(7)),
        roots=_authoritative_roots(tmp_path),
        monitor_processes=False,
    )
    assert verification["exceptions"] == ["SystemExit"]
    assert verification["passed"] is False


def test_receipt_fails_closed_for_fake_categories_and_disabled_observation(tmp_path: Path) -> None:
    fake = verify_no_write(
        lambda: None,
        roots=[
            GovernedRoot("fake-repo", tmp_path / "repo", "repository"),
            GovernedRoot("fake-external", tmp_path / "config", "external_config"),
            GovernedRoot("fake-temp", tmp_path / "temp", "temporary_state"),
        ],
        monitor_processes=False,
        monitor_filesystem=False,
    )
    receipt = evidence_receipt(
        fake,
        product_version="0.3.0b1",
        commit_sha="d" * 40,
        command="pcodex.status.advisory",
        arguments=["--token", "-secretvalue", "--repo", "-/" + "Users/alice/private"],
        scenario_id="fake-coverage",
        timestamp="2026-07-13T00:00:00Z",
    )
    encoded = json.dumps(receipt)
    assert receipt["coverage_complete"] is False
    assert receipt["result"] == "fail"
    assert "incomplete_process_observation" in receipt["exceptions"]
    assert "incomplete_filesystem_observation" in receipt["exceptions"]
    assert "secretvalue" not in encoded
    assert "/" + "Users/alice" not in encoded


def test_governed_root_authority_cannot_be_forged_or_mutated(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="must be created"):
        GovernedRootSet([GovernedRoot("repository", tmp_path, "repository")])
    roots = _authoritative_roots(tmp_path)
    with pytest.raises(TypeError):
        roots[0] = GovernedRoot("repository", tmp_path / "fake", "repository")  # type: ignore[index]


@pytest.mark.skipif(not hasattr(__import__("select"), "kqueue"), reason="kqueue vnode evidence is macOS-specific")
def test_transient_create_delete_is_detected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def transient_write() -> None:
        path = repo / "transient"
        path.write_text("temporary", encoding="utf-8")
        path.unlink()

    verification = verify_no_write(
        transient_write,
        roots=[GovernedRoot("repo", repo)],
        monitor_processes=False,
        monitor_filesystem=True,
    )
    assert verification["transient_filesystem_events"]
    assert verification["passed"] is False
