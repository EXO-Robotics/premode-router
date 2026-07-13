from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from premode import cli
from premode import pcodex_bootstrap as pcodex
from premode import __version__
from premode import codex_native, codex_plugin
from premode.codex_native import STATE_RELATIVE as NATIVE_STATE_RELATIVE
from premode.codex_plugin import (
    JOURNAL_RELATIVE,
    STATE_RELATIVE,
    apply_integration,
    canonical_files,
    canonical_manifest,
    canonical_source_root,
    disable_integration,
    integration_preview,
    marketplace_entry,
    plugin_status,
    repair_integration,
    uninstall_integration,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = ("pcodex", "pcodex-status", "pcodex-dry-run", "pcodex-tune")


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            stat_result = path.stat()
            result[path.relative_to(root).as_posix()] = (stat_result.st_mtime_ns, path.read_bytes().hex())
    return result


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return dict(line.split(":", 1) for line in text[4:end].splitlines())


def test_one_canonical_source_tree_and_valid_skills() -> None:
    root = canonical_source_root()
    assert root == REPO_ROOT / "plugins" / "pcodex"
    legacy_root = REPO_ROOT / ".agents" / "plugins" / "plugins" / "premode-router"
    assert not any(path.is_file() for path in legacy_root.rglob("*"))
    assert not any(path.is_file() for root in (REPO_ROOT / ".agents" / "skills").glob("pcodex*") for path in root.rglob("*"))
    assert not any(path.is_file() for root in (REPO_ROOT / "templates" / "codex" / "skills").glob("pcodex*") for path in root.rglob("*"))
    for name in SKILL_NAMES:
        fields = _frontmatter(root / "skills" / name / "SKILL.md")
        assert fields["name"].strip() == name
        assert "pcodex" in fields["description"].lower()


def test_manifest_uses_product_version_and_supported_shape() -> None:
    checked_in = json.loads((canonical_source_root() / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert checked_in == canonical_manifest()
    assert __version__ == "0.3.0b1"
    assert checked_in["version"] == "0.3.0-beta.1"
    assert checked_in["skills"] == "./skills/"
    assert "mcpServers" not in checked_in
    assert "hooks" not in checked_in
    assert len(checked_in["interface"]["defaultPrompt"]) == 3
    assert all(len(prompt) <= 128 for prompt in checked_in["interface"]["defaultPrompt"])


def test_resolver_is_installed_artifact_safe() -> None:
    resolver = canonical_source_root() / "skills" / "pcodex" / "bin" / "resolve-pcodex.sh"
    text = resolver.read_text(encoding="utf-8")
    assert resolver.stat().st_mode & 0o111
    assert "command -v pcodex" in text
    assert "./.venv" not in text
    assert ".pcodex-alpha" not in text
    assert "/Users/" not in text


@pytest.mark.parametrize("name", ["path with spaces", "Unicode β"])
def test_preview_is_literal_no_write_for_path_variants(tmp_path: Path, name: str) -> None:
    repo = _make_repo(tmp_path, name)
    before = _snapshot(repo)
    result = integration_preview(repo)
    assert result["status"] == "dry_run"
    assert result["writes_performed"] is False
    assert result["conflicts"] == []
    assert _snapshot(repo) == before
    assert not (repo / STATE_RELATIVE).exists()
    assert not (repo / JOURNAL_RELATIVE).exists()


def test_missing_codex_installs_repo_state_but_defers_native_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(codex_plugin.shutil, "which", lambda _name: None)
    preview = integration_preview(repo, native=True)
    assert preview["codex_compatibility"]["reason"] == "codex_missing"
    assert preview["conflicts"] == []
    result = apply_integration(repo, native=True)
    assert result["status"] == "installed_needs_codex"
    assert result["native_registration"]["status"] == "deferred"
    assert (repo / STATE_RELATIVE).exists()
    assert not (repo / NATIVE_STATE_RELATIVE).exists()


def test_unsupported_codex_version_blocks_before_any_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setenv("PCODEX_TEST_CODEX_VERSION", "0.144.0")
    before = _snapshot(repo)
    preview = integration_preview(repo, native=True)
    assert {item.get("reason") for item in preview["conflicts"]} == {"unsupported_codex_version"}
    assert apply_integration(repo, native=True)["status"] == "blocked"
    assert _snapshot(repo) == before


def test_apply_status_disable_reenable_uninstall_reinstall(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    installed = apply_integration(repo)
    assert installed["status"] == "installed"
    assert plugin_status(repo)["readiness"] == "READY"

    repeated = apply_integration(repo)
    assert repeated["status"] == "unchanged"
    assert repeated["writes_performed"] is False

    disabled = disable_integration(repo)
    assert disabled["status"] == "disabled"
    disabled_status = plugin_status(repo)
    assert disabled_status["readiness"] == "NEEDS_ACTION"
    assert disabled_status["reason"] == "disabled"

    repaired = repair_integration(repo)
    assert repaired["status"] == "repaired"
    assert plugin_status(repo)["readiness"] == "READY"

    removed = uninstall_integration(repo)
    assert removed["status"] == "uninstalled"
    assert not (repo / "plugins" / "pcodex").exists()
    assert not (repo / ".agents" / "plugins" / "marketplace.json").exists()
    assert plugin_status(repo)["reason"] == "plugin_absent"
    assert apply_integration(repo)["status"] == "installed"


def test_exact_registration_receipt_preserves_unrelated_order_and_values(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    marketplace = repo / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    original = (
        '{\n  "name" : "personal",\n  "unknown": {"keep":true},\n  "plugins" : [\n'
        '    {"name":"first","source":{"source":"local","path":"./plugins/first"}}\n'
        '  ]\n}\n'
    )
    marketplace.write_text(original, encoding="utf-8")
    apply_integration(repo)
    mutated = marketplace.read_text(encoding="utf-8")
    assert mutated.startswith(original[: original.index("\n  ]")])
    after = json.loads(marketplace.read_text(encoding="utf-8"))
    assert list(after) == ["name", "unknown", "plugins"]
    assert after["unknown"] == {"keep": True}
    assert [item["name"] for item in after["plugins"]] == ["first", "pcodex"]
    receipt = json.loads((repo / STATE_RELATIVE).read_text(encoding="utf-8"))
    registration = receipt["registrations"]["marketplace"]
    assert registration["managed_fields"] == ["plugins[name=pcodex]"]
    assert registration["preexisting_value_hash"] is None
    assert registration["ownership_id"] == receipt["ownership_id"]
    assert uninstall_integration(repo)["status"] == "uninstalled"
    assert marketplace.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "content",
    ["{not-json", "[]", '{"plugins":"bad"}', '{"schema_version":"codex.marketplace.v99","plugins":[]}'],
)
def test_malformed_or_future_marketplace_fails_closed_without_write(tmp_path: Path, content: str) -> None:
    repo = _make_repo(tmp_path)
    path = repo / ".agents" / "plugins" / "marketplace.json"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    before = _snapshot(repo)
    preview = integration_preview(repo)
    assert preview["conflicts"]
    assert _snapshot(repo) == before
    blocked = apply_integration(repo)
    assert blocked["status"] == "blocked"
    assert _snapshot(repo) == before


def test_existing_same_name_without_receipt_is_not_claimed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo / ".agents" / "plugins" / "marketplace.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"name": "personal", "plugins": [marketplace_entry()]}) + "\n", encoding="utf-8")
    before = _snapshot(repo)
    preview = integration_preview(repo)
    assert {item.get("reason") for item in preview["conflicts"]} == {"unknown_owner"}
    assert apply_integration(repo)["status"] == "blocked"
    assert _snapshot(repo) == before


def test_modified_owned_file_and_registration_are_preserved(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    apply_integration(repo)
    skill = repo / "plugins" / "pcodex" / "skills" / "pcodex" / "SKILL.md"
    skill.write_text("user modified\n", encoding="utf-8")
    assert plugin_status(repo)["readiness"] == "BLOCKED"
    assert repair_integration(repo)["reason"] == "user_modified"
    assert uninstall_integration(repo)["status"] == "blocked"
    assert skill.read_text(encoding="utf-8") == "user modified\n"


def test_malformed_optional_mcp_authority_reports_blocked(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "malformed-mcp-authority")
    assert apply_integration(repo, with_mcp=True)["status"] == "installed"
    state_path = repo / STATE_RELATIVE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["registrations"]["mcp"] = None
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = plugin_status(repo)
    assert result["readiness"] == "BLOCKED"
    assert result["reason"] == "corrupt_or_future_authority"


def test_missing_owned_file_is_repaired(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    apply_integration(repo)
    helper = repo / "plugins" / "pcodex" / "skills" / "pcodex" / "bin" / "resolve-pcodex.sh"
    helper.unlink()
    assert plugin_status(repo)["readiness"] == "NEEDS_ACTION"
    result = repair_integration(repo)
    assert result["status"] == "repaired"
    assert helper.exists() and helper.stat().st_mode & 0o111


def test_symlink_and_hardlink_replacements_block_cleanup(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    apply_integration(repo)
    helper = repo / "plugins" / "pcodex" / "skills" / "pcodex" / "bin" / "resolve-pcodex.sh"
    outside = tmp_path / "outside"
    outside.write_text(helper.read_text(encoding="utf-8"), encoding="utf-8")
    helper.unlink()
    helper.symlink_to(outside)
    assert plugin_status(repo)["readiness"] == "BLOCKED"
    assert uninstall_integration(repo)["status"] == "blocked"
    helper.unlink()
    os.link(outside, helper)
    assert uninstall_integration(repo)["status"] == "blocked"


def test_legacy_migration_preserves_unknown_legacy_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    legacy = repo / ".agents" / "plugins" / "plugins" / "premode-router"
    legacy.mkdir(parents=True)
    (legacy / "user.txt").write_text("keep", encoding="utf-8")
    preview = integration_preview(repo, migration=True)
    assert preview["migration"]["requires_manual_action"] is True
    migrated = apply_integration(repo, migration=True)
    assert migrated["status"] == "installed"
    assert migrated["legacy_preserved"]
    assert (legacy / "user.txt").read_text(encoding="utf-8") == "keep"
    status = plugin_status(repo)
    assert status["readiness"] == "NEEDS_ACTION"
    assert status["reason"] == "legacy_preserved_manual_action"


def test_exact_historical_legacy_fingerprints_match_starting_commit() -> None:
    start = "99ebc95c9db7f40333c661743920485e0d45c134"
    for relative, expected in codex_plugin.LEGACY_PLUGIN_FINGERPRINT.items():
        content = subprocess.check_output(
            ["git", "show", f"{start}:.agents/plugins/plugins/premode-router/{relative}"],
            cwd=REPO_ROOT,
        )
        assert hashlib.sha256(content).hexdigest() == expected
    for relative, expected in codex_plugin.LEGACY_SKILL_FINGERPRINT.items():
        content = subprocess.check_output(["git", "show", f"{start}:.agents/skills/{relative}"], cwd=REPO_ROOT)
        assert hashlib.sha256(content).hexdigest() == expected


def test_exact_supported_legacy_migration_removes_only_fingerprinted_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    plugin_root = repo / ".agents/plugins/plugins/premode-router"
    skills_root = repo / ".agents/skills"
    plugin_files = {
        ".codex-plugin/plugin.json": b"legacy plugin\n",
        "skills/premode-router/SKILL.md": b"legacy skill\n",
    }
    skill_files = {"pcodex/SKILL.md": b"legacy pcodex\n", "pcodex-status/SKILL.md": b"legacy status\n"}
    for relative, content in plugin_files.items():
        path = plugin_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for relative, content in skill_files.items():
        path = skills_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    monkeypatch.setattr(codex_plugin, "LEGACY_PLUGIN_FINGERPRINT", {key: hashlib.sha256(value).hexdigest() for key, value in plugin_files.items()})
    monkeypatch.setattr(codex_plugin, "LEGACY_SKILL_FINGERPRINT", {key: hashlib.sha256(value).hexdigest() for key, value in skill_files.items()})
    marketplace = repo / ".agents/plugins/marketplace.json"
    marketplace.parent.mkdir(parents=True, exist_ok=True)
    marketplace.write_text(json.dumps({
        "name": "personal", "plugins": [{
            "name": "premode-router",
            "source": {"source": "local", "path": "./.agents/plugins/plugins/premode-router"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }],
    }) + "\n", encoding="utf-8")
    preview = integration_preview(repo, migration=True)
    assert preview["migration"]["will_remove_legacy"] is True
    result = apply_integration(repo, migration=True)
    assert result["status"] == "installed"
    assert not plugin_root.exists()
    assert not any((skills_root / name).exists() for name in ("pcodex", "pcodex-status"))
    assert plugin_status(repo)["readiness"] == "READY"


def test_exact_migration_remains_reachable_after_canonical_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    assert apply_integration(repo)["status"] == "installed"
    legacy = repo / ".agents/plugins/plugins/premode-router"
    content = b"historical\n"
    path = legacy / ".codex-plugin/plugin.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    monkeypatch.setattr(codex_plugin, "LEGACY_PLUGIN_FINGERPRINT", {
        ".codex-plugin/plugin.json": hashlib.sha256(content).hexdigest(),
    })
    monkeypatch.setattr(codex_plugin, "LEGACY_SKILL_FINGERPRINT", {})
    preview = integration_preview(repo, migration=True)
    assert preview["migration"]["will_remove_legacy"] is True
    migrated = apply_integration(repo, migration=True)
    assert migrated["status"] == "unchanged"
    assert migrated["writes_performed"] is True
    assert not legacy.exists()


@pytest.mark.parametrize("stage", ["marketplace_entry_update", "receipt_update"])
def test_interrupted_install_preserves_preexisting_marketplace_file(
    tmp_path: Path, stage: str,
) -> None:
    repo = _make_repo(tmp_path)
    marketplace = repo / ".agents/plugins/marketplace.json"
    marketplace.parent.mkdir(parents=True)
    original = '{"name":"personal","extra":{"keep":true},"plugins":[]}\n'
    marketplace.write_text(original, encoding="utf-8")

    def stop(current: str) -> None:
        if current == stage:
            raise RuntimeError("interrupt marketplace ownership")

    with pytest.raises(RuntimeError, match="interrupt marketplace ownership"):
        apply_integration(repo, inject=stop)
    recovered = repair_integration(repo)
    assert recovered["status"] == "recovered"
    state = json.loads((repo / STATE_RELATIVE).read_text(encoding="utf-8"))
    assert state["registrations"]["marketplace"]["registration_type"] == "marketplace_entry"
    assert uninstall_integration(repo)["status"] == "uninstalled"
    assert marketplace.read_text(encoding="utf-8") == original


def test_optional_mcp_absent_by_default_and_explicit_when_authorized(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    default = apply_integration(repo)
    assert default["status"] == "installed"
    assert not (repo / "plugins" / "pcodex" / ".mcp.json").exists()
    manifest = json.loads((repo / "plugins" / "pcodex" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "mcpServers" not in manifest
    uninstall_integration(repo)
    preview = integration_preview(repo, with_mcp=True)
    assert preview["optional_mcp"]["would_register"] is True
    explicit = apply_integration(repo, with_mcp=True)
    assert "mcp" in explicit["registration_receipts"]
    mcp = json.loads((repo / "plugins" / "pcodex" / ".mcp.json").read_text(encoding="utf-8"))
    entry = mcp["mcpServers"]["pcodex"]
    assert entry["command"] == os.sys.executable
    assert entry["env"]["PCODEX_WORKSPACE"] == str(repo.resolve())


def test_interruption_leaves_journal_and_never_reports_ready(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    def stop(stage: str) -> None:
        if stage == "plugin_directory_commit":
            raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        apply_integration(repo, inject=stop)
    status = plugin_status(repo)
    assert status["readiness"] == "BLOCKED"
    assert status["reason"] == "interrupted_operation"
    assert not (repo / STATE_RELATIVE).exists()
    assert (repo / JOURNAL_RELATIVE).exists()
    recovered = repair_integration(repo)
    assert recovered["status"] == "recovered"
    assert plugin_status(repo)["readiness"] == "READY"


@pytest.mark.skipif(shutil.which("codex") is None, reason="local Codex CLI unavailable")
def test_native_codex_registration_lifecycle_and_unrelated_config_preservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path, "native path β")
    home = tmp_path / "codex home"
    home.mkdir()
    config = home / "config.toml"
    unrelated = '# preserve exact bytes\nmodel = "fixture-model"\n\n[features]\nfixture = true\n'
    config.write_text(unrelated, encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("PCODEX_TEST_CODEX_VERSION", "0.143.0")
    before = _snapshot(tmp_path)
    plan = integration_preview(repo, native=True)
    assert plan["native_registration"]["writes_performed"] is False
    assert _snapshot(tmp_path) == before
    installed = apply_integration(repo, native=True)
    assert installed["native_registration"]["status"] == "registered"
    assert config.read_text(encoding="utf-8").startswith(unrelated)
    state = json.loads((repo / NATIVE_STATE_RELATIVE).read_text(encoding="utf-8"))
    assert set(state["registrations"]) == {"codex_marketplace", "codex_plugin_enable"}
    assert plugin_status(repo, native=True)["readiness"] == "READY"
    assert disable_integration(repo, native=True)["status"] == "disabled"
    assert plugin_status(repo, native=True)["reason"] == "disabled"
    assert repair_integration(repo, native=True)["status"] == "repaired"
    assert plugin_status(repo, native=True)["readiness"] == "READY"
    assert uninstall_integration(repo, native=True)["status"] == "uninstalled"
    assert config.read_text(encoding="utf-8") == unrelated
    assert not (repo / NATIVE_STATE_RELATIVE).exists()


@pytest.mark.skipif(shutil.which("codex") is None, reason="local Codex CLI unavailable")
def test_native_optional_mcp_and_interruption_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _make_repo(tmp_path, "native-mcp")
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("PCODEX_TEST_CODEX_VERSION", "0.143.0")

    def stop_install(stage: str) -> None:
        if stage == "codex_configuration_update":
            raise RuntimeError("interrupt native install")

    with pytest.raises(RuntimeError, match="interrupt native install"):
        apply_integration(repo, with_mcp=True, native=True, inject=stop_install)
    assert plugin_status(repo, native=True)["reason"] in {"interrupted_operation", "interrupted_native_operation"}
    assert repair_integration(repo, native=True)["native_registration"]["status"] == "recovered"
    state = json.loads((repo / NATIVE_STATE_RELATIVE).read_text(encoding="utf-8"))
    assert set(state["registrations"]) == {"codex_marketplace", "codex_plugin_enable", "codex_mcp"}
    assert plugin_status(repo, native=True)["readiness"] == "READY"

    def stop_disable(stage: str) -> None:
        if stage == "codex_disable_update":
            raise RuntimeError("interrupt native disable")

    with pytest.raises(RuntimeError, match="interrupt native disable"):
        disable_integration(repo, native=True, inject=stop_disable)
    assert plugin_status(repo, native=True)["reason"] == "interrupted_native_operation"
    assert repair_integration(repo, native=True)["native_registration"]["status"] == "recovered"

    def stop_uninstall(stage: str) -> None:
        if stage == "codex_uninstall_plugin_update":
            raise RuntimeError("interrupt native uninstall")

    with pytest.raises(RuntimeError, match="interrupt native uninstall"):
        uninstall_integration(repo, native=True, inject=stop_uninstall)
    assert plugin_status(repo, native=True)["reason"] in {"interrupted_operation", "interrupted_native_operation"}
    assert repair_integration(repo, native=True)["native_registration"]["status"] == "recovered"
    assert plugin_status(repo, native=True)["readiness"] == "READY"
    assert uninstall_integration(repo, native=True)["status"] == "uninstalled"


@pytest.mark.skipif(shutil.which("codex") is None, reason="local Codex CLI unavailable")
def test_missing_native_cache_is_exactly_repaired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _make_repo(tmp_path, "native-cache-repair")
    home = tmp_path / "codex-home-cache"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("PCODEX_TEST_CODEX_VERSION", "0.143.0")
    assert apply_integration(repo, native=True)["native_registration"]["status"] == "registered"
    state = json.loads((repo / NATIVE_STATE_RELATIVE).read_text(encoding="utf-8"))
    cache = Path(state["cache"]["path"])
    shutil.rmtree(cache)
    status = plugin_status(repo, native=True)
    assert status["readiness"] == "NEEDS_ACTION"
    assert {item["reason"] for item in status["native_registration"]["conflicts"]} == {"missing"}
    repaired = repair_integration(repo, native=True)
    assert repaired["native_registration"]["status"] == "repaired"
    assert plugin_status(repo, native=True)["readiness"] == "READY"
    assert uninstall_integration(repo, native=True)["status"] == "uninstalled"


def test_native_journal_and_config_shapes_fail_closed_without_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path, "native-forged")
    home = tmp_path / "codex-forged"
    home.mkdir()
    config = home / "config.toml"
    config.write_text('plugins = "wrong-shape"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    before = _snapshot(tmp_path)
    plan = codex_native.preview(marketplace_root=repo, with_mcp=False)
    assert plan["readiness"] == "BLOCKED"
    assert _snapshot(tmp_path) == before

    config.write_text("", encoding="utf-8")
    journal = {
        "schema_version": codex_native.JOURNAL_SCHEMA,
        "operation": "install",
        "ownership_id": "0" * 36,
        "plugin_version": __version__,
        "with_mcp": False,
        "workspace": str(repo.resolve()),
        "marketplace_root": str((tmp_path / "other").resolve()),
        "codex_home": str(home.resolve()),
        "config_path": str(config.resolve()),
        "config_preexisting_hash": None,
        "unrelated_value_hash": hashlib.sha256(b"{}").hexdigest(),
        "phase": "started",
    }
    journal_path = repo / codex_native.JOURNAL_RELATIVE
    journal_path.parent.mkdir()
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before = _snapshot(tmp_path)
    status = codex_native.status(repo)
    assert status["readiness"] == "BLOCKED"
    assert status["reason"] == "corrupt_or_future_native_authority"
    assert _snapshot(tmp_path) == before


def test_native_authority_write_rejects_symlinked_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / ".pcodex").symlink_to(outside, target_is_directory=True)
    with pytest.raises(codex_native.NativeCodexError):
        codex_native._atomic_json(workspace / codex_native.STATE_RELATIVE, {"sentinel": True})
    assert list(outside.iterdir()) == []


def test_malformed_native_registration_authority_reports_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path, "native-malformed-state")
    home = tmp_path / "codex-malformed-state"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    state = {
        "schema_version": codex_native.STATE_SCHEMA,
        "ownership_id": "0" * 36,
        "plugin_version": __version__,
        "codex_home": str(home.resolve()),
        "config_path": str((home / "config.toml").resolve()),
        "config_preexisting_hash": None,
        "with_mcp": False,
        "workspace": str(repo.resolve()),
        "registrations": None,
        "cache": {},
    }
    state_path = repo / NATIVE_STATE_RELATIVE
    state_path.parent.mkdir()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = codex_native.status(repo)
    assert result["readiness"] == "BLOCKED"
    assert result["reason"] == "corrupt_or_future_native_authority"


@pytest.mark.skipif(shutil.which("codex") is None, reason="local Codex CLI unavailable")
def test_stale_native_mutation_journal_cannot_replace_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path, "native-stale-journal")
    home = tmp_path / "codex-stale"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("PCODEX_TEST_CODEX_VERSION", "0.143.0")
    assert apply_integration(repo, native=True)["native_registration"]["status"] == "registered"
    state = json.loads((repo / NATIVE_STATE_RELATIVE).read_text(encoding="utf-8"))
    config = home / "config.toml"
    config_payload, config_bytes = codex_native._read_config()
    journal = {
        "schema_version": codex_native.JOURNAL_SCHEMA,
        "operation": "uninstall",
        "ownership_id": "f" * 36,
        "plugin_version": __version__,
        "with_mcp": state["with_mcp"],
        "workspace": str(repo.resolve()),
        "marketplace_root": str(repo.resolve()),
        "codex_home": str(home.resolve()),
        "config_path": str(config.resolve()),
        "config_preexisting_hash": state["config_preexisting_hash"],
        "unrelated_value_hash": codex_native._hash_json(codex_native._without_targets(config_payload)),
        "phase": "started",
    }
    journal_path = repo / codex_native.JOURNAL_RELATIVE
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before_config = config_bytes
    repaired = codex_native.repair(repo)
    assert repaired["status"] == "blocked"
    assert "does not match" in repaired["reason"]
    assert config.read_bytes() == before_config
    assert json.loads((repo / NATIVE_STATE_RELATIVE).read_text(encoding="utf-8"))["ownership_id"] == state["ownership_id"]


def test_pcodex_ui_works_with_missing_and_partial_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    missing = pcodex.pcodex_ui_payload(repo)
    assert missing["schema_version"] == "pcodex.ui.v1"
    state = repo / ".premode" / "pcodex_state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{not-json", encoding="utf-8")
    assert pcodex.pcodex_ui_payload(repo)["warnings"]


def test_new_pcodex_commands_route_to_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("new pcodex commands must stay on bootstrap route"))
    assert cli.pcodex_main(["integrate", "codex", "--dry-run"]) == 0
    assert cli.pcodex_main(["integrate", "codex", "--status"]) == 0
    assert calls == [["integrate", "codex", "--dry-run"], ["integrate", "codex", "--status"]]


def test_model_facing_packet_rendering_constants_unchanged() -> None:
    assert pcodex.PCODEX_PACKET_VERSION == "v5"
    assert pcodex.PCODEX_PACKET_VARIANT == "tool_assisted_anchors_internal"
    assert pcodex.PCODEX_PACKET_STRATEGY == "literal_symbol"
    assert pcodex.PCODEX_FALLBACK_VARIANT == "ranked_paths_plus_anchors"
