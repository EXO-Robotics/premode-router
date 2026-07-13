from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
from typing import Any

import pytest

from premode import pcodex_bootstrap as pcodex
from premode import managed_state
from premode.compiler import build_compiled_packet, compile_prompt
from premode.managed_state import (
    INSTALL_STATE_SCHEMA_VERSION,
    ManagedStateError,
    apply_uninstall,
    install_managed_file,
    plan_uninstall,
    read_install_state_receipt,
    sha256_bytes,
    validate_install_state_receipt,
)
from premode.production_ranking import (
    PRODUCTION_RANKING_PROVIDER_VERSION,
    ProductionRankingRequestV1,
    ProductionRankingResultV1,
    UnknownProviderVersionError,
    ProductionRankingContractError,
    rank_with_provider,
    ranking_result_from_dict,
)
from premode.production_ranking_incumbent import IncumbentManifestRankingProviderV1
from premode.product_contract import validate_payload_against_schema


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text("def run(): return True\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text("def test_run(): assert True\n", encoding="utf-8")
    return repo


class _StaticProvider:
    provider_version = PRODUCTION_RANKING_PROVIDER_VERSION

    def __init__(self, primary: str) -> None:
        self.primary = primary
        self.seen_task: str | None = None

    def rank(self, request: ProductionRankingRequestV1) -> ProductionRankingResultV1:
        self.seen_task = request.exact_task
        return ProductionRankingResultV1(
            routing_mode="narrow",
            primary_paths=(self.primary, self.primary),
            verify_paths=("tests/test_app.py",),
            support_paths=(),
            abstention_reason=None,
            decision_receipt={
                "schema_version": "pcodex.production-ranking-decision-receipt.v1",
                "exact_task_sha256": hashlib.sha256(request.exact_task.encode("utf-8")).hexdigest(),
                "routing_mode": "narrow",
                "primary_path_count": 1,
                "verify_path_count": 1,
                "support_path_count": 0,
                "source_contract": "test-provider.v1",
            },
        )


def test_provider_interchangeability_determinism_and_exact_task_preservation() -> None:
    exact = "Fix  src/app.py\nKeep this second line byte-for-byte."
    request = ProductionRankingRequestV1(exact, {"repo_root": "."}, {"mode": "test"})
    first_provider = _StaticProvider("src/app.py")
    second_provider = _StaticProvider("src/alternate.py")

    first = rank_with_provider(first_provider, request)
    repeated = rank_with_provider(first_provider, request)
    second = rank_with_provider(second_provider, request)

    assert first_provider.seen_task == exact
    assert first.to_dict() == repeated.to_dict()
    assert first.primary_paths == ("src/app.py",)
    assert first.verify_paths == ("tests/test_app.py",)
    assert second.primary_paths == ("src/alternate.py",)
    assert json.loads(json.dumps(first.to_dict()))["primary_paths"] == ["src/app.py"]


def test_canonical_packet_consumes_swappable_provider_without_legacy_candidate_knowledge(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src" / "alternate.py").write_text("VALUE = 1\n", encoding="utf-8")
    exact = "Update the selected implementation and its test."
    first = compile_prompt(
        repo,
        exact,
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
        canonical_core_packet=True,
        record_artifacts=False,
        production_ranking_provider=_StaticProvider("src/app.py"),
    )
    second = compile_prompt(
        repo,
        exact,
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
        canonical_core_packet=True,
        record_artifacts=False,
        production_ranking_provider=_StaticProvider("src/alternate.py"),
    )
    assert "* src/app.py" in first["packet"]
    assert "* src/alternate.py" in second["packet"]
    assert first["production_ranking"]["primary_paths"] != second["production_ranking"]["primary_paths"]
    assert "routing_decision" not in first


def test_abstention_serialization_and_unknown_versions_fail_safely() -> None:
    result = ProductionRankingResultV1(
        routing_mode="abstain",
        primary_paths=(),
        verify_paths=(),
        support_paths=(),
        abstention_reason="unsupported_task_class",
        decision_receipt={
            "schema_version": "pcodex.production-ranking-decision-receipt.v1",
            "exact_task_sha256": hashlib.sha256(b"task").hexdigest(),
            "routing_mode": "abstain",
            "primary_path_count": 0,
            "verify_path_count": 0,
            "support_path_count": 0,
            "source_contract": "test-provider.v1",
        },
    )
    assert ranking_result_from_dict(result.to_dict()) == result
    payload = result.to_dict()
    payload["provider_version"] = "production-ranking-provider.v2"
    with pytest.raises(UnknownProviderVersionError):
        ranking_result_from_dict(payload)
    leaked = result.to_dict()
    leaked["decision_receipt"]["candidate"] = "D3"
    with pytest.raises(ProductionRankingContractError, match="unsupported fields"):
        ranking_result_from_dict(leaked)
    leaked_source = result.to_dict()
    leaked_source["decision_receipt"]["source_contract"] = "D3-observer-qwen"
    with pytest.raises(ProductionRankingContractError, match="public-safe|non-product"):
        ranking_result_from_dict(leaked_source)
    leaked_reason = result.to_dict()
    leaked_reason["abstention_reason"] = "observer promoted D3"
    with pytest.raises(ProductionRankingContractError, match="public-safe"):
        ranking_result_from_dict(leaked_reason)


def test_incumbent_adapter_and_canonical_packet_hide_experiment_identities(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    exact = "Change src/app.py and update its test."
    compiled = compile_prompt(
        repo,
        exact,
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
        canonical_core_packet=True,
        record_artifacts=False,
    )
    public_result = compiled["production_ranking"]
    public_text = json.dumps(public_result, sort_keys=True)

    assert public_result["provider_version"] == PRODUCTION_RANKING_PROVIDER_VERSION
    assert exact in compiled["packet"]
    assert compiled["packet"].count(exact) == 1
    experiment_identity = re.compile(r"(?i)(?<![A-Za-z0-9])(?:D3|C2|Qwen|observer)(?![A-Za-z0-9])")
    assert experiment_identity.search(public_text) is None
    assert experiment_identity.search(compiled["packet"]) is None

    internal = build_compiled_packet(
        repo,
        exact,
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
        canonical_core_packet=True,
        record=False,
    )
    request = ProductionRankingRequestV1(
        exact,
        {"repo_root": str(repo), "manifest": internal["manifest"]},
        {"canonical_packet_renderer": "canonical_core_v1"},
    )
    result = IncumbentManifestRankingProviderV1().rank(request)
    assert result.to_dict() == public_result
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "production-ranking-provider-v1.schema.json").read_text(encoding="utf-8"))
    validate_payload_against_schema(public_result, schema)


def test_production_provider_interface_has_no_observer_or_experiment_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    interface = (root / "src" / "premode" / "production_ranking.py").read_text(encoding="utf-8")
    for forbidden in ("from .routing_contract", "from .observer", "import premode.observer", "from .lab73", "import premode.lab73"):
        assert forbidden not in interface.casefold()


def test_new_managed_file_repeated_operation_and_safe_reinstall(tmp_path: Path) -> None:
    root = tmp_path / "new-managed" / "pcodex-state"
    receipt = root / ".premode" / "install-state.json"
    first = install_managed_file(root, "plugins/pCodex β/config.json", b"{}\n", receipt_path=receipt)
    target = root / "plugins" / "pCodex β" / "config.json"

    assert first["status"] == "installed"
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "pcodex.install-state.schema.json").read_text(encoding="utf-8"))
    validate_payload_against_schema(first["receipt"], schema)
    assert target.read_bytes() == b"{}\n"
    repeated = install_managed_file(root, "plugins/pCodex β/config.json", b"{}\n", receipt_path=receipt)
    assert repeated["status"] == "already_installed"
    assert repeated["writes_performed"] is False

    applied = apply_uninstall(root, receipt)
    assert applied["removed"] == ["plugins/pCodex β/config.json"]
    assert not target.exists()
    second = apply_uninstall(root, receipt)
    assert second["not_found"] == [{"path": "plugins/pCodex β/config.json", "reason": "already_missing"}]

    reinstall = install_managed_file(root, "plugins/pCodex β/config.json", b"{}\n", receipt_path=receipt, operation_type="reinstall")
    assert reinstall["status"] == "installed"
    assert target.exists()


def test_preexisting_identical_preserved_and_different_conflicts(tmp_path: Path) -> None:
    root = tmp_path / "identical" / "pcodex-state"
    target = root / "config.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"same")
    receipt = root / "receipt.json"

    identical = install_managed_file(root, "config.json", b"same", receipt_path=receipt)
    assert identical["writes_performed"] is True
    assert identical["target_write_performed"] is False
    assert identical["receipt"]["items"][0]["preexisting_state"] == "identical"
    plan = plan_uninstall(root, receipt)
    assert plan["will_remove"] == []
    assert plan["will_preserve"] == [{"path": "config.json", "reason": "preexisting_state"}]

    other_root = tmp_path / "different" / "pcodex-state"
    other_root.mkdir(parents=True)
    (other_root / "config.json").write_bytes(b"user")
    conflict_receipt = other_root / "receipt.json"
    conflict = install_managed_file(other_root, "config.json", b"product", receipt_path=conflict_receipt)
    assert conflict["status"] == "conflict"
    assert not conflict_receipt.exists()
    assert (other_root / "config.json").read_bytes() == b"user"


def test_user_modified_and_unrelated_sibling_state_are_preserved(tmp_path: Path) -> None:
    root = tmp_path / "modified" / "pcodex-state"
    receipt = root / "receipt.json"
    install_managed_file(root, "codex/pcodex.json", b"owned", receipt_path=receipt)
    sibling = root / "codex" / "unrelated.json"
    sibling.write_bytes(b"unrelated")
    (root / "codex" / "pcodex.json").write_bytes(b"user changed")

    plan = plan_uninstall(root, receipt)
    assert plan["will_remove"] == []
    assert plan["will_preserve"] == [{"path": "codex/pcodex.json", "reason": "user_modified"}]
    applied = apply_uninstall(root, receipt)
    assert applied["removed"] == []
    assert sibling.read_bytes() == b"unrelated"
    assert (root / "codex" / "pcodex.json").read_bytes() == b"user changed"


@pytest.mark.parametrize("kind", ["missing", "corrupt", "future"])
def test_missing_corrupt_and_future_receipts_fail_closed(tmp_path: Path, kind: str) -> None:
    root = tmp_path / kind / "pcodex-state"
    root.mkdir(parents=True)
    target = root / "legacy.txt"
    target.write_text("keep", encoding="utf-8")
    receipt = root / "receipt.json"
    if kind == "corrupt":
        receipt.write_text("{", encoding="utf-8")
    elif kind == "future":
        receipt.write_text(json.dumps({"schema_version": "pcodex.install-state.v99"}), encoding="utf-8")

    plan = plan_uninstall(root, receipt)
    assert plan["will_remove"] == []
    assert plan["requires_manual_action"]
    assert target.read_text(encoding="utf-8") == "keep"
    applied = apply_uninstall(root, receipt)
    assert applied["applied"] is False
    assert applied["writes_performed"] is False
    assert applied["status"] == "blocked_unknown_state"
    assert not (root / ".premode" / "uninstall-operation.json").exists()


def test_atomic_receipt_failure_rolls_back_new_file(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "receipt-failure" / "pcodex-state"
    receipt = root / "receipt.json"
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source: str | bytes | os.PathLike[str] | os.PathLike[bytes], destination: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated interrupted receipt replacement")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)
    with pytest.raises(OSError, match="interrupted"):
        install_managed_file(root, "owned/file.txt", b"content", receipt_path=receipt)

    assert not (root / "owned" / "file.txt").exists()
    assert not receipt.exists()
    assert not list(root.rglob("*.tmp"))


def test_atomic_replacement_leaves_no_temporary_files(tmp_path: Path) -> None:
    root = tmp_path / "atomic" / "pcodex-state"
    receipt = root / "receipt.json"
    install_managed_file(root, "path with spaces/ü.txt", b"content", receipt_path=receipt)
    assert read_install_state_receipt(receipt)["status"] == "loaded"
    assert not list(root.rglob("*.tmp"))


def test_operation_receipt_escape_is_rejected_before_removal(tmp_path: Path) -> None:
    root = tmp_path / "receipt-escape" / "pcodex-state"
    receipt = root / "receipt.json"
    install_managed_file(root, "owned.txt", b"content", receipt_path=receipt)
    with pytest.raises(ManagedStateError, match="under the managed root"):
        apply_uninstall(root, receipt, operation_receipt_path=tmp_path / "outside.json")
    assert (root / "owned.txt").exists()


def test_unsafe_and_symlink_managed_roots_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManagedStateError, match="unsafe broad"):
        plan_uninstall(Path("/"), Path("/.premode/install-state.json"))
    shared_root = Path("/") / "Users" / "Shared"
    volume_root = Path("/") / "Volumes" / "Backup"
    with pytest.raises(ManagedStateError, match="unsafe broad"):
        plan_uninstall(shared_root, shared_root / "install-state.json")
    with pytest.raises(ManagedStateError, match="unsafe broad"):
        plan_uninstall(volume_root, volume_root / "install-state.json")
    broad_documents = Path.home() / "Documents"
    with pytest.raises(ManagedStateError, match="not a repository or designated"):
        plan_uninstall(broad_documents, broad_documents / "install-state.json")
    real_root = tmp_path / "real"
    real_root.mkdir()
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(ManagedStateError, match="symlink"):
        plan_uninstall(link_root, link_root / "receipt.json")


def test_missing_owner_marker_blocks_forged_receipt(tmp_path: Path) -> None:
    source = tmp_path / "source" / "pcodex-state"
    source_receipt = source / "receipt.json"
    installed = install_managed_file(source, "owned.txt", b"owned", receipt_path=source_receipt)
    forged_root = tmp_path / "forged" / "pcodex-state"
    forged_root.mkdir(parents=True)
    (forged_root / "owned.txt").write_bytes(b"owned")
    forged = installed["receipt"]
    forged["managed_root_hash"] = sha256_bytes(str(forged_root.resolve()).encode("utf-8"))
    forged_receipt = forged_root / "receipt.json"
    forged_receipt.write_text(json.dumps(forged), encoding="utf-8")
    plan = plan_uninstall(forged_root, forged_receipt)
    assert plan["will_remove"] == []
    assert any(item["reason"] == "ownership_marker_invalid" for item in plan["requires_manual_action"])


def test_operation_receipt_collision_preserves_target(tmp_path: Path) -> None:
    root = tmp_path / "collision" / "pcodex-state"
    receipt = root / "receipt.json"
    install_managed_file(root, "owned.txt", b"owned", receipt_path=receipt)
    unrelated = root / "unrelated.json"
    unrelated.write_text("user content", encoding="utf-8")
    with pytest.raises(ManagedStateError, match="unrelated state"):
        apply_uninstall(root, receipt, operation_receipt_path=unrelated)
    assert (root / "owned.txt").read_bytes() == b"owned"
    assert unrelated.read_text(encoding="utf-8") == "user content"


def test_marker_pins_receipt_path_and_operation_receipt_ownership(tmp_path: Path) -> None:
    root = tmp_path / "authority" / "pcodex-state"
    receipt = root / "receipt.json"
    install_managed_file(root, "owned.txt", b"owned", receipt_path=receipt)
    copied = root / "copied-receipt.json"
    copied.write_bytes(receipt.read_bytes())
    copied_plan = plan_uninstall(root, copied)
    assert copied_plan["will_remove"] == []
    assert {item["reason"] for item in copied_plan["requires_manual_action"]} == {"receipt_path_mismatch"}

    unrelated = root / "operation.json"
    unrelated.write_text(json.dumps({
        "schema_version": managed_state.UNINSTALL_OPERATION_SCHEMA_VERSION,
        "managed_root_hash": sha256_bytes(str(root.resolve()).encode("utf-8")),
    }), encoding="utf-8")
    with pytest.raises(ManagedStateError, match="unrelated state"):
        apply_uninstall(root, receipt, operation_receipt_path=unrelated)
    assert (root / "owned.txt").read_bytes() == b"owned"


def test_apply_rechecks_hash_after_planning(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "recheck" / "pcodex-state"
    receipt = root / "receipt.json"
    target = root / "owned.txt"
    install_managed_file(root, "owned.txt", b"owned", receipt_path=receipt)
    real_plan = managed_state.plan_uninstall

    def mutate_after_plan(managed_root: Path | str, state_receipt: Path | str) -> dict[str, Any]:
        plan = real_plan(managed_root, state_receipt)
        target.write_bytes(b"user changed after preview")
        return plan

    monkeypatch.setattr(managed_state, "plan_uninstall", mutate_after_plan)
    applied = managed_state.apply_uninstall(root, receipt)
    assert applied["status"] == "blocked_conflict"
    assert applied["writes_performed"] is False
    assert target.read_bytes() == b"user changed after preview"


def test_apply_quarantines_before_validation_to_avoid_pathname_swap(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "swap" / "pcodex-state"
    receipt = root / "receipt.json"
    target = root / "owned.txt"
    install_managed_file(root, "owned.txt", b"owned", receipt_path=receipt)
    real_rename = os.rename
    swapped = False

    def swap_before_quarantine(
        source: Any,
        destination: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if source == target.name and src_dir_fd is not None and not swapped:
            swapped = True
            target.write_bytes(b"replacement")
        real_rename(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "rename", swap_before_quarantine)
    applied = apply_uninstall(root, receipt)
    assert applied["status"] == "blocked_conflict"
    assert applied["writes_performed"] is False
    assert target.read_bytes() == b"replacement"


def test_quarantine_read_failure_restores_current_target(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "read-failure" / "pcodex-state"
    receipt = root / "receipt.json"
    target = root / "owned.txt"
    install_managed_file(root, "owned.txt", b"owned", receipt_path=receipt)

    def fail_fstat(_fd: int) -> Any:
        raise OSError("simulated quarantine read failure")

    monkeypatch.setattr(managed_state.os, "fstat", fail_fstat)
    with pytest.raises(OSError, match="quarantine read failure"):
        apply_uninstall(root, receipt)
    assert target.read_bytes() == b"owned"


def test_operation_receipt_failure_restores_removed_target(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "operation-failure" / "pcodex-state"
    receipt = root / "receipt.json"
    target = root / "owned.txt"
    install_managed_file(root, "owned.txt", b"owned", receipt_path=receipt)
    real_write = managed_state._atomic_write_json

    def fail_operation(path: Path, payload: dict[str, Any]) -> None:
        if payload.get("schema_version") == managed_state.UNINSTALL_OPERATION_SCHEMA_VERSION:
            raise OSError("simulated operation receipt failure")
        real_write(path, payload)

    monkeypatch.setattr(managed_state, "_atomic_write_json", fail_operation)
    with pytest.raises(OSError, match="operation receipt failure"):
        apply_uninstall(root, receipt)
    assert target.read_bytes() == b"owned"


def test_post_replace_directory_fsync_failure_keeps_install_consistent(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "install-fsync" / "pcodex-state"
    receipt = root / "receipt.json"
    calls = 0
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls % 2 == 0:
            raise OSError("directory fsync unsupported")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    installed = install_managed_file(root, "owned.txt", b"owned", receipt_path=receipt)
    assert installed["status"] == "installed"
    assert (root / "owned.txt").read_bytes() == b"owned"
    assert read_install_state_receipt(receipt)["status"] == "loaded"


def test_post_replace_directory_fsync_failure_keeps_uninstall_consistent(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "uninstall-fsync" / "pcodex-state"
    receipt = root / "receipt.json"
    target = root / "owned.txt"
    install_managed_file(root, "owned.txt", b"owned", receipt_path=receipt)
    calls = 0
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory fsync unsupported")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    applied = apply_uninstall(root, receipt)
    assert applied["status"] == "applied"
    assert not target.exists()
    operation = Path(applied["operation_receipt"])
    assert json.loads(operation.read_text(encoding="utf-8"))["status"] == "applied"


def test_unknown_receipt_owner_blocks_all_removal(tmp_path: Path) -> None:
    root = tmp_path / "unknown-owner" / "pcodex-state"
    receipt = root / "receipt.json"
    install_managed_file(root, "first.txt", b"first", receipt_path=receipt)
    install_managed_file(root, "second.txt", b"second", receipt_path=receipt)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["items"][0]["owner"] = "unknown_component"
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    applied = apply_uninstall(root, receipt)
    assert applied["status"] == "blocked_unknown_state"
    assert applied["writes_performed"] is False
    assert (root / "first.txt").read_bytes() == b"first"
    assert (root / "second.txt").read_bytes() == b"second"


def test_symlink_escape_path_escape_and_research_ownership_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "escape" / "pcodex-state"
    outside = tmp_path / "outside"
    root.mkdir(parents=True)
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ManagedStateError, match="symlink"):
        install_managed_file(root, "link/file.txt", b"x", receipt_path=root / "receipt.json")
    with pytest.raises(ManagedStateError, match="unsafe managed path"):
        install_managed_file(root, "../escape.txt", b"x", receipt_path=root / "receipt.json")
    with pytest.raises(ManagedStateError, match="unknown product owner"):
        install_managed_file(root, "safe-owner-test.txt", b"x", receipt_path=root / "receipt.json", owner="observer")

    observer_receipt = root / "observer-receipt.json"
    installed = install_managed_file(root, "safe.txt", b"safe", receipt_path=observer_receipt)
    payload = installed["receipt"]
    payload["items"][0]["owned_path"] = "observer.db"
    payload["items"][0]["owner"] = "research_lane"
    observer_receipt.write_text(json.dumps(payload), encoding="utf-8")
    plan = plan_uninstall(root, observer_receipt)
    assert plan["will_remove"] == []
    assert plan["unknown_owner"] == [{"path": "observer.db", "owner": "research_lane"}]


def test_uninstall_cli_preview_is_literal_no_write(tmp_path: Path, capsys: Any) -> None:
    repo = _repo(tmp_path)
    before = sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*"))
    assert pcodex.main(["uninstall", "--dry-run", "--repo-root", str(repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    after = sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*"))

    assert payload["schema_version"] == "pcodex.uninstall-plan.v1"
    assert payload["writes_performed"] is False
    assert payload["codex_launch"] == "not_executed"
    assert payload["requires_manual_action"]
    assert before == after
    assert pcodex.main(["uninstall", "--yes", "--repo-root", str(repo), "--json"]) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["status"] == "blocked_unknown_state"
