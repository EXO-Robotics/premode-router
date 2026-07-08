from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import cli
from premode import pcodex_bootstrap as pcodex


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = ("pcodex", "pcodex-status", "pcodex-dry-run", "pcodex-tune")
ALLOWED_PREFIXES = (".agents/skills/", "plugins/pcodex/", ".agents/plugins/marketplace.json")


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _all_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def test_repo_local_agent_skills_exist_with_valid_frontmatter() -> None:
    for name in SKILL_NAMES:
        path = REPO_ROOT / ".agents" / "skills" / name / "SKILL.md"
        assert path.exists()
        fields = _frontmatter(path)
        assert fields["name"] == name
        assert 20 <= len(fields["description"]) <= 95
        assert "pcodex" in fields["description"].lower()


def test_skill_copies_match_plugin_skill_copies() -> None:
    for name in SKILL_NAMES:
        agent_skill = REPO_ROOT / ".agents" / "skills" / name / "SKILL.md"
        plugin_skill = REPO_ROOT / "plugins" / "pcodex" / "skills" / name / "SKILL.md"
        assert plugin_skill.exists()
        assert plugin_skill.read_text(encoding="utf-8") == agent_skill.read_text(encoding="utf-8")


def test_pcodex_resolver_exists_and_is_packaged() -> None:
    agent_resolver = REPO_ROOT / ".agents" / "skills" / "pcodex" / "bin" / "resolve-pcodex.sh"
    plugin_resolver = REPO_ROOT / "plugins" / "pcodex" / "skills" / "pcodex" / "bin" / "resolve-pcodex.sh"

    assert agent_resolver.exists()
    assert plugin_resolver.exists()
    assert plugin_resolver.read_text(encoding="utf-8") == agent_resolver.read_text(encoding="utf-8")
    assert agent_resolver.stat().st_mode & 0o111
    assert plugin_resolver.stat().st_mode & 0o111

    text = agent_resolver.read_text(encoding="utf-8")
    assert "./.venv/bin/pcodex" in text
    assert "$HOME/.pcodex-alpha/bin/pcodex" in text
    assert "command -v pcodex" in text
    assert "pCodex executable not found" in text


def test_skills_avoid_unsupported_claims() -> None:
    combined = "\n".join(
        (REPO_ROOT / ".agents" / "skills" / name / "SKILL.md").read_text(encoding="utf-8").lower()
        for name in SKILL_NAMES
    )
    assert "slash command" not in combined
    assert "`/pcodex" not in combined
    assert "automatic mcp" not in combined
    assert "automatically invoke" not in combined
    assert "launch live codex" in combined


def test_plugin_manifest_and_marketplace_json_validate() -> None:
    manifest = json.loads((REPO_ROOT / "plugins" / "pcodex" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads((REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "pcodex"
    assert manifest["skills"] == "./skills/"
    assert manifest["policy"]["global_config_mutation"] is False
    assert manifest["policy"]["live_codex_launch"] is False

    assert marketplace["name"] == "local-premode-marketplace"
    for entry in marketplace["plugins"]:
        assert (REPO_ROOT / entry["source"]["path"]).exists()

    pcodex_entries = [item for item in marketplace["plugins"] if item.get("name") == "pcodex"]
    assert len(pcodex_entries) == 1
    source_path = pcodex_entries[0]["source"]["path"]
    assert source_path == "./plugins/pcodex"
    assert (REPO_ROOT / source_path).exists()
    assert pcodex_entries[0]["policy"]["publication"] == "REPO_LOCAL_ONLY"


def test_integrate_codex_dry_run_reports_without_writing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    before = _all_files(repo)

    result = pcodex.integrate_codex_surface(repo, dry_run=True, write=False, with_mcp=False)

    assert result["status"] == "dry_run"
    assert result["codex_launch"] == "not_executed"
    assert ".agents/skills/pcodex/SKILL.md" in result["planned_files"]
    assert ".agents/skills/pcodex/bin/resolve-pcodex.sh" in result["planned_files"]
    assert "plugins/pcodex/.codex-plugin/plugin.json" in result["planned_files"]
    assert _all_files(repo) == before


def test_integrate_codex_write_creates_only_allowlisted_files_and_is_idempotent(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    first = pcodex.integrate_codex_surface(repo, dry_run=False, write=True, with_mcp=True)
    created = _all_files(repo)

    assert first["status"] == "written"
    assert first["mcp"]["global_config_mutation"] is False
    assert "plugins/pcodex/.mcp.json" in created
    assert ".agents/skills/pcodex/bin/resolve-pcodex.sh" in created
    assert "plugins/pcodex/skills/pcodex/bin/resolve-pcodex.sh" in created
    assert (repo / ".agents" / "skills" / "pcodex" / "bin" / "resolve-pcodex.sh").stat().st_mode & 0o111
    assert created
    assert all(any(path.startswith(prefix) or path == prefix for prefix in ALLOWED_PREFIXES) for path in created if path != ".git")

    second = pcodex.integrate_codex_surface(repo, dry_run=False, write=True, with_mcp=True)
    assert second["written_files"] == []
    assert set(second["unchanged_files"]) == created


def test_with_mcp_stays_repo_local_and_does_not_mutate_global_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _make_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    result = pcodex.integrate_codex_surface(repo, dry_run=False, write=True, with_mcp=True)

    assert result["mcp"]["activation"] == "explicit_user_approved"
    assert result["global_config_mutation"] is False
    assert not (home / ".codex" / "config.toml").exists()


def test_plugin_init_local_marketplace_dry_run_and_write(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    before = _all_files(repo)

    dry_run = pcodex.plugin_init_local_marketplace(repo, dry_run=True)
    assert dry_run["status"] == "dry_run"
    assert _all_files(repo) == before

    written = pcodex.plugin_init_local_marketplace(repo, dry_run=False)
    assert written["status"] == "written"
    assert (repo / "plugins" / "pcodex" / ".codex-plugin" / "plugin.json").exists()
    assert (repo / ".agents" / "plugins" / "marketplace.json").exists()


def test_pcodex_ui_works_with_missing_and_partial_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    missing = pcodex.pcodex_ui_payload(repo)
    assert missing["schema_version"] == "pcodex.ui.v1"
    assert missing["configured_mode"] == "on"
    assert missing["codex_launch"] == "not_executed"

    state = repo / ".premode" / "pcodex_state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{not-json", encoding="utf-8")
    partial = pcodex.pcodex_ui_payload(repo)
    assert partial["schema_version"] == "pcodex.ui.v1"
    assert partial["state_status"] in {"invalid_default", "error"}
    assert partial["warnings"]


def test_pcodex_ui_json_emits_stable_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _make_repo(tmp_path)

    assert pcodex.main(["ui", "--json", "--repo-root", str(repo)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "pcodex.ui.v1"
    assert set(
        [
            "configured_mode",
            "effective_mode",
            "algorithm",
            "tuning_status",
            "mcp_status",
            "codex_cli",
            "fallback",
            "local_telemetry_counters",
            "state_path",
            "warnings",
            "next_recommended_action",
        ]
    ).issubset(payload)


def test_new_pcodex_commands_route_to_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("new pcodex commands must stay on bootstrap route"))

    assert cli.pcodex_main(["integrate", "codex", "--dry-run"]) == 0
    assert cli.pcodex_main(["plugin", "init", "--local-marketplace", "--dry-run"]) == 0
    assert cli.pcodex_main(["ui", "--json"]) == 0
    assert calls == [
        ["integrate", "codex", "--dry-run"],
        ["plugin", "init", "--local-marketplace", "--dry-run"],
        ["ui", "--json"],
    ]


def test_model_facing_packet_rendering_constants_unchanged() -> None:
    assert pcodex.PCODEX_PACKET_VERSION == "v5"
    assert pcodex.PCODEX_PACKET_VARIANT == "tool_assisted_anchors_internal"
    assert pcodex.PCODEX_PACKET_STRATEGY == "literal_symbol"
    assert pcodex.PCODEX_FALLBACK_VARIANT == "ranked_paths_plus_anchors"
