from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from premode.no_write import governed_roots_from_product, verify_no_write
from premode.openclaw_integration import (
    OpenClawAuthorityError,
    resolve_openclaw_config_authority,
)


def _write(path: Path, value: str = "{}\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def test_explicit_config_path_outranks_state_and_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "working"
    home.mkdir()
    cwd.mkdir()
    authority = resolve_openclaw_config_authority(
        environ={
            "HOME": str(home),
            "OPENCLAW_HOME": "~/openclaw-home",
            "OPENCLAW_STATE_DIR": str(tmp_path / "ignored-state"),
            "OPENCLAW_CONFIG_PATH": "relative/config.json",
        },
        home=home,
        cwd=cwd,
    )

    assert authority.config_path == cwd / "relative/config.json"
    assert authority.state_dir == tmp_path / "ignored-state"
    assert authority.source == "explicit_config_path"
    assert authority.config_candidates == (authority.config_path,)


def test_explicit_state_dir_prefers_canonical_then_legacy_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    home.mkdir()
    legacy = _write(state / "clawdbot.json")
    env = {"HOME": str(home), "OPENCLAW_STATE_DIR": str(state)}

    authority = resolve_openclaw_config_authority(environ=env, home=home)
    assert authority.config_path == legacy
    assert authority.source == "explicit_state_dir_legacy_existing"

    canonical = _write(state / "openclaw.json")
    authority = resolve_openclaw_config_authority(environ=env, home=home)
    assert authority.config_path == canonical
    assert authority.source == "explicit_state_dir_canonical_existing"


def test_explicit_state_dir_defaults_to_canonical_without_creating_it(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    state = tmp_path / "missing-state"
    home.mkdir()

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home), "OPENCLAW_STATE_DIR": str(state)},
        home=home,
    )

    assert authority.config_path == state / "openclaw.json"
    assert authority.source == "explicit_state_dir_canonical_default"
    assert not state.exists()


def test_default_candidates_preserve_supported_existing_precedence(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    new_state = home / ".openclaw"
    legacy_state = home / ".clawdbot"
    new_state.mkdir(parents=True)
    legacy = _write(legacy_state / "openclaw.json")

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home)}, home=home
    )
    assert authority.config_path == legacy
    assert authority.source == "default_legacy_canonical_existing"

    new_legacy = _write(new_state / "clawdbot.json")
    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home)}, home=home
    )
    assert authority.config_path == new_legacy
    assert authority.source == "new_state_dir_legacy_existing"

    new_canonical = _write(new_state / "openclaw.json")
    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home)}, home=home
    )
    assert authority.config_path == new_canonical
    assert authority.source == "new_state_dir_canonical_existing"


def test_existing_legacy_state_dir_is_canonical_fallback_when_new_dir_absent(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    legacy_state = home / ".clawdbot"
    legacy_state.mkdir(parents=True)

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home)}, home=home
    )

    assert authority.state_dir == legacy_state
    assert authority.config_path == legacy_state / "openclaw.json"
    assert authority.source == "legacy_state_dir_canonical_default"


def test_openclaw_home_and_test_fast_match_supported_runtime_contract(
    tmp_path: Path,
) -> None:
    os_home = tmp_path / "os-home"
    os_home.mkdir()
    env = {
        "HOME": str(os_home),
        "OPENCLAW_HOME": "~/isolated",
        "OPENCLAW_TEST_FAST": "1",
    }

    authority = resolve_openclaw_config_authority(environ=env, home=os_home)

    assert authority.state_dir == os_home / "isolated/.openclaw"
    assert authority.config_path == authority.state_dir / "openclaw.json"
    assert authority.source == "test_fast_canonical"


def test_no_write_root_always_tracks_exact_active_openclaw_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    for path in (home, repo, temp):
        path.mkdir()
    active = _write(home / ".openclaw/openclaw.json")
    env = {"HOME": str(home), "TMPDIR": str(temp)}

    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)
    openclaw_root = next(root for root in roots if root.root_id == "openclaw_config")

    assert openclaw_root.path == active
    assert openclaw_root.category == "external_config"

    verification = verify_no_write(
        lambda: active.write_text('{"changed":true}\n', encoding="utf-8"),
        roots=roots,
        monitor_processes=False,
    )
    assert verification["passed"] is False
    assert any(
        change["root_id"] == "openclaw_config"
        for change in verification["comparison"]["changes"]
    )


def test_openclaw_config_resolution_is_read_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home)}, home=home
    )

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert before == after
    assert authority.config_path == home / ".openclaw/openclaw.json"


def test_environment_home_outranks_supplied_homedir_fallback(tmp_path: Path) -> None:
    env_home = tmp_path / "environment-home"
    fallback_home = tmp_path / "fallback-home"
    env_home.mkdir()
    fallback_home.mkdir()

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(env_home)}, home=fallback_home
    )

    assert authority.state_dir == env_home / ".openclaw"


@pytest.mark.parametrize(
    ("variable", "literal", "expected_name"),
    [
        ("OPENCLAW_CONFIG_PATH", "null", "null"),
        ("OPENCLAW_STATE_DIR", "undefined", "undefined/openclaw.json"),
    ],
)
def test_config_and_state_overrides_treat_nullish_literals_as_paths(
    tmp_path: Path, variable: str, literal: str, expected_name: str
) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home), variable: literal}, home=home, cwd=cwd
    )

    assert authority.config_path == cwd / expected_name


def test_runtime_state_dotenv_matches_openclaw_config_override_precedence(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    custom = tmp_path / "custom/active.json"
    home.mkdir()
    _write(
        state / ".env",
        f"openclaw_config_path={tmp_path / 'ignored-lowercase.json'}\n"
        f"OPENCLAW_CONFIG_PATH={custom}\n",
    )

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home), "OPENCLAW_STATE_DIR": str(state)},
        home=home,
    )

    assert authority.config_path == custom
    assert authority.state_dir == state
    assert authority.dotenv_paths == (state / ".env",)


def test_runtime_gateway_dotenv_is_loaded_only_for_default_state(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    custom = tmp_path / "gateway-config.json"
    home.mkdir()
    _write(
        home / ".config/openclaw/gateway.env",
        f"OPENCLAW_CONFIG_PATH='{custom}'\n",
    )

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home)}, home=home
    )

    assert authority.config_path == custom
    assert home / ".config/openclaw/gateway.env" in authority.dotenv_paths


def test_preexisting_environment_outranks_runtime_dotenv(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    environment_config = tmp_path / "from-environment.json"
    home.mkdir()
    _write(
        state / ".env",
        f"OPENCLAW_CONFIG_PATH={tmp_path / 'from-dotenv.json'}\n",
    )

    authority = resolve_openclaw_config_authority(
        environ={
            "HOME": str(home),
            "OPENCLAW_STATE_DIR": str(state),
            "OPENCLAW_CONFIG_PATH": str(environment_config),
        },
        home=home,
    )

    assert authority.config_path == environment_config


def test_runtime_dotenv_grammar_matches_supported_dotenv_forms(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    custom = tmp_path / "custom/config.json"
    home.mkdir()
    env = {"HOME": str(home), "OPENCLAW_STATE_DIR": str(state)}
    cases = (
        (f"OPENCLAW_CONFIG_PATH={custom}#comment\n", custom),
        (f"OPENCLAW_CONFIG_PATH='{custom}' # trailing\n", custom),
        (f"OPENCLAW_CONFIG_PATH=`{custom}`\n", custom),
        (
            f'OPENCLAW_CONFIG_PATH="{custom}\\ncontinued"\n',
            Path(f"{custom}\ncontinued"),
        ),
        (
            f'OPENCLAW_CONFIG_PATH="{custom}\ncontinued"\n',
            Path(f"{custom}\ncontinued"),
        ),
    )

    for dotenv, expected in cases:
        _write(state / ".env", dotenv)
        authority = resolve_openclaw_config_authority(environ=env, home=home)
        assert authority.config_path == expected


def test_config_path_resolution_is_lexical_and_preserves_symlink_inode(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    target = tmp_path / "target.json"
    link = cwd / "config-link.json"
    home.mkdir()
    cwd.mkdir()
    _write(target)
    link.symlink_to(target)

    authority = resolve_openclaw_config_authority(
        environ={"HOME": str(home), "OPENCLAW_CONFIG_PATH": "config-link.json"},
        home=home,
        cwd=cwd,
    )

    assert authority.config_path == link
    assert authority.config_path != target


def test_no_write_detects_higher_priority_config_candidate_creation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    for path in (home, repo, temp):
        path.mkdir()
    legacy = _write(home / ".clawdbot/openclaw.json")
    promoted = home / ".openclaw/openclaw.json"
    env = {"HOME": str(home), "TMPDIR": str(temp)}
    before = resolve_openclaw_config_authority(environ=env, home=home)
    assert before.config_path == legacy
    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)

    verification = verify_no_write(
        lambda: _write(promoted), roots=roots, monitor_processes=False
    )

    assert verification["passed"] is False
    assert any(
        change["root_id"].startswith("openclaw_")
        for change in verification["comparison"]["changes"]
    )


def test_no_write_detects_explicit_config_symlink_replacement(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    config = tmp_path / "config-link.json"
    target = _write(tmp_path / "target.json")
    for path in (home, repo, temp):
        path.mkdir()
    config.symlink_to(target)
    env = {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "OPENCLAW_CONFIG_PATH": str(config),
    }
    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)

    def replace_symlink() -> None:
        config.unlink()
        config.write_text('{"replacement":true}\n', encoding="utf-8")

    verification = verify_no_write(
        replace_symlink, roots=roots, monitor_processes=False
    )

    assert verification["passed"] is False
    assert any(
        change["root_id"] == "openclaw_config"
        for change in verification["comparison"]["changes"]
    )


def test_no_write_detects_explicit_config_symlink_target_mutation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    config = tmp_path / "config-link.json"
    target = _write(tmp_path / "outside/target.json")
    for path in (home, repo, temp):
        path.mkdir()
    config.symlink_to(target)
    env = {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "OPENCLAW_CONFIG_PATH": str(config),
    }
    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)

    verification = verify_no_write(
        lambda: target.write_text('{"changed":true}\n', encoding="utf-8"),
        roots=roots,
        monitor_processes=False,
    )

    assert verification["passed"] is False
    assert any(
        change["root_id"].startswith("openclaw_config_target_")
        for change in verification["comparison"]["changes"]
    )


def test_no_write_detects_runtime_dotenv_unquoted_comment_target(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    state = tmp_path / "state"
    active = _write(tmp_path / "outside/active")
    for path in (home, repo, temp):
        path.mkdir()
    _write(state / ".env", f"OPENCLAW_CONFIG_PATH={active}#comment\n")
    env = {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "OPENCLAW_STATE_DIR": str(state),
    }
    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)

    verification = verify_no_write(
        lambda: active.write_text('{"changed":true}\n', encoding="utf-8"),
        roots=roots,
        monitor_processes=False,
    )

    assert verification["passed"] is False
    assert any(
        change["root_id"] == "openclaw_config"
        for change in verification["comparison"]["changes"]
    )


def test_no_write_detects_symlinked_state_directory_target_mutation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    state_target = tmp_path / "outside/state"
    state_link = tmp_path / "state-link"
    for path in (home, repo, temp, state_target):
        path.mkdir(parents=True)
    state_link.symlink_to(state_target, target_is_directory=True)
    env = {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "OPENCLAW_STATE_DIR": str(state_link),
    }
    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)

    verification = verify_no_write(
        lambda: _write(state_target / "sessions/new-state.json"),
        roots=roots,
        monitor_processes=False,
    )

    assert verification["passed"] is False
    assert any(
        change["root_id"].startswith("openclaw_state_target_")
        for change in verification["comparison"]["changes"]
    )


def test_no_write_detects_nested_state_symlink_target_mutation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    state = tmp_path / "state"
    outside = tmp_path / "outside/sessions"
    for path in (home, repo, temp, state, outside):
        path.mkdir(parents=True)
    (state / "sessions").symlink_to(outside, target_is_directory=True)
    env = {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "OPENCLAW_STATE_DIR": str(state),
    }
    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)

    verification = verify_no_write(
        lambda: _write(state / "sessions/new.json"),
        roots=roots,
        monitor_processes=False,
    )

    assert verification["passed"] is False
    assert any(
        change["root_id"].startswith("openclaw_nested_state_target_")
        for change in verification["comparison"]["changes"]
    )


def test_no_write_detects_bom_prefixed_runtime_dotenv_target(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    state = tmp_path / "state"
    active = _write(tmp_path / "outside/active.json")
    for path in (home, repo, temp):
        path.mkdir()
    _write(state / ".env", f"\ufeffOPENCLAW_CONFIG_PATH={active}\n")
    env = {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "OPENCLAW_STATE_DIR": str(state),
    }
    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)

    verification = verify_no_write(
        lambda: active.write_text('{"changed":true}\n', encoding="utf-8"),
        roots=roots,
        monitor_processes=False,
    )

    assert verification["passed"] is False
    assert any(
        change["root_id"] == "openclaw_config"
        for change in verification["comparison"]["changes"]
    )


def test_no_write_detects_broken_config_symlink_target_creation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repository"
    temp = tmp_path / "temp"
    config = tmp_path / "broken-config-link.json"
    target = tmp_path / "outside/future.json"
    for path in (home, repo, temp):
        path.mkdir()
    config.symlink_to(target)
    env = {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "OPENCLAW_CONFIG_PATH": str(config),
    }
    roots = governed_roots_from_product(repo, home=home, temp_root=temp, environ=env)

    verification = verify_no_write(
        lambda: _write(target), roots=roots, monitor_processes=False
    )

    assert verification["passed"] is False
    assert any(
        change["root_id"].startswith("openclaw_config_target_")
        for change in verification["comparison"]["changes"]
    )


def test_config_symlink_cycle_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    home.mkdir()
    first.symlink_to(second)
    second.symlink_to(first)

    with pytest.raises(OpenClawAuthorityError):
        resolve_openclaw_config_authority(
            environ={
                "HOME": str(home),
                "OPENCLAW_CONFIG_PATH": str(first),
            },
            home=home,
        )


def test_config_parent_symlink_cycle_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = tmp_path / "first"
    second = tmp_path / "second"
    home.mkdir()
    first.symlink_to(second)
    second.symlink_to(first)

    with pytest.raises(OpenClawAuthorityError):
        resolve_openclaw_config_authority(
            environ={
                "HOME": str(home),
                "OPENCLAW_CONFIG_PATH": str(first / "openclaw.json"),
            },
            home=home,
        )


def test_acyclic_target_below_repeated_symlink_prefix_is_supported(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    actual = tmp_path / "actual"
    prefix = tmp_path / "prefix"
    home.mkdir()
    actual.mkdir()
    prefix.symlink_to(actual, target_is_directory=True)
    target = prefix / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    link = actual / "link.json"
    link.symlink_to(target)

    authority = resolve_openclaw_config_authority(
        environ={
            "HOME": str(home),
            "OPENCLAW_CONFIG_PATH": str(prefix / "link.json"),
        },
        home=home,
    )

    assert actual / "target.json" in authority.config_target_candidates


def test_live_openclaw_2026_4_14_runtime_dotenv_path_parity(tmp_path: Path) -> None:
    executable = shutil.which("openclaw")
    if executable is None and Path("/opt/homebrew/bin/openclaw").is_file():
        executable = "/opt/homebrew/bin/openclaw"
    if executable is None:
        pytest.skip("OpenClaw runtime is unavailable")
    version = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if "2026.4.14" not in version:
        pytest.skip(f"OpenClaw 2026.4.14 required; found {version}")

    home = tmp_path / "home"
    state = tmp_path / "state"
    custom = tmp_path / "custom/active.json"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "OPENCLAW_STATE_DIR": str(state),
    }
    env.pop("OPENCLAW_CONFIG_PATH", None)
    cases = (
        (
            f"openclaw_config_path={tmp_path / 'ignored-lowercase.json'}\n"
            f"OPENCLAW_CONFIG_PATH={custom}#comment\n",
            custom,
        ),
        (f"OPENCLAW_CONFIG_PATH='{custom}' # trailing\n", custom),
        (f"OPENCLAW_CONFIG_PATH=`{custom}`\n", custom),
        (
            f'OPENCLAW_CONFIG_PATH="{custom}\\ncontinued"\n',
            Path(f"{custom}\ncontinued"),
        ),
        (
            f'OPENCLAW_CONFIG_PATH="{custom}\ncontinued"\n',
            Path(f"{custom}\ncontinued"),
        ),
        (f"\ufeffOPENCLAW_CONFIG_PATH={custom}\n", custom),
    )
    for dotenv, expected in cases:
        _write(state / ".env", dotenv)
        authority = resolve_openclaw_config_authority(environ=env, home=home)
        live = subprocess.run(
            [executable, "config", "file"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()

        assert Path(live) == authority.config_path == expected
