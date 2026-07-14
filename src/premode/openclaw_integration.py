"""OpenClaw integration authority shared by lifecycle and no-write evidence.

This module mirrors the path and runtime-dotenv contract of the explicitly
supported OpenClaw 2026.4.14 runtime without launching OpenClaw or reading its
configuration payload.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Mapping


OPENCLAW_CONFIG_FILENAME = "openclaw.json"
OPENCLAW_LEGACY_CONFIG_FILENAME = "clawdbot.json"
OPENCLAW_STATE_DIRNAME = ".openclaw"
OPENCLAW_LEGACY_STATE_DIRNAME = ".clawdbot"
_PATH_AUTHORITY_KEYS = frozenset(
    {
        "HOME",
        "USERPROFILE",
        "OPENCLAW_HOME",
        "OPENCLAW_STATE_DIR",
        "OPENCLAW_CONFIG_PATH",
        "OPENCLAW_TEST_FAST",
    }
)
_DOTENV_LINE = re.compile(
    r"^[\s\ufeff]*(?:export[\s\ufeff]+)?([A-Za-z0-9_.-]+)"
    r"(?:[\s\ufeff]*=[\s\ufeff]*?|:[\s\ufeff]+?)"
    r"([\s\ufeff]*'(?:\\'|[^'])*'|"
    r"[\s\ufeff]*\"(?:\\\"|[^\"])*\"|"
    r"[\s\ufeff]*`(?:\\`|[^`])*`|[^#\r\n]+)?"
    r"[\s\ufeff]*(?:#.*)?$",
    re.MULTILINE,
)


class OpenClawAuthorityError(ValueError):
    """OpenClaw path authority could not be established without ambiguity."""


@dataclass(frozen=True)
class OpenClawConfigAuthority:
    """Active config plus every path capable of changing that authority."""

    config_path: Path
    state_dir: Path
    source: str
    config_candidates: tuple[Path, ...]
    state_candidates: tuple[Path, ...]
    dotenv_paths: tuple[Path, ...]
    config_target_candidates: tuple[Path, ...]
    state_target_candidates: tuple[Path, ...]
    dotenv_target_paths: tuple[Path, ...]
    nested_state_target_candidates: tuple[Path, ...]


def _home_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value in {"undefined", "null"}:
        return None
    return value


def _path_override(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _absolute(path: Path, *, cwd: Path) -> Path:
    """Match Node path.resolve: lexical absolute normalization, no realpath."""

    candidate = path if path.is_absolute() else cwd / path
    return Path(os.path.abspath(os.fspath(candidate)))


def _distinct_resolved_targets(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    targets: list[Path] = []
    for path in paths:
        try:
            target = path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise OpenClawAuthorityError(
                "cannot resolve OpenClaw authority symlink target"
            ) from exc
        if target != path and target not in targets:
            targets.append(target)
    return tuple(targets)


def _nested_symlink_targets(
    roots: tuple[Path, ...], *, max_entries: int = 100_000
) -> tuple[Path, ...]:
    """Return the bounded transitive targets of symlinks below state roots."""

    targets: list[Path] = []
    pending = list(roots)
    visited_directories: set[tuple[int, int]] = set()
    entries_seen = 0
    while pending:
        path = pending.pop()
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise OpenClawAuthorityError(
                "cannot inspect OpenClaw state symlink authority"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            try:
                target = path.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                raise OpenClawAuthorityError(
                    "cannot resolve OpenClaw state symlink authority"
                ) from exc
            if target not in targets:
                targets.append(target)
                pending.append(target)
            continue
        if not stat.S_ISDIR(info.st_mode):
            continue
        identity = (info.st_dev, info.st_ino)
        if identity in visited_directories:
            continue
        visited_directories.add(identity)
        try:
            with os.scandir(path) as iterator:
                children = [Path(item.path) for item in iterator]
        except OSError as exc:
            raise OpenClawAuthorityError(
                "cannot inspect OpenClaw state directory authority"
            ) from exc
        entries_seen += len(children)
        if entries_seen > max_entries:
            raise OpenClawAuthorityError(
                "OpenClaw state symlink authority exceeds the safe inspection bound"
            )
        pending.extend(children)
    return tuple(targets)


def _expand_openclaw_path(value: str, *, effective_home: Path, cwd: Path) -> Path:
    if value == "~":
        return effective_home
    if value.startswith(("~/", "~\\")):
        value = str(effective_home) + value[1:]
    return _absolute(Path(value), cwd=cwd)


def _effective_home(env: Mapping[str, str], *, home: Path | None, cwd: Path) -> Path:
    raw_os_home = _home_value(env.get("HOME")) or _home_value(env.get("USERPROFILE"))
    os_home = Path(raw_os_home) if raw_os_home else (home or Path.home())
    os_home = _absolute(os_home, cwd=cwd)
    override = _home_value(env.get("OPENCLAW_HOME"))
    if override is None:
        return os_home
    return _expand_openclaw_path(override, effective_home=os_home, cwd=cwd)


def _state_dir(
    env: Mapping[str, str], *, effective_home: Path, cwd: Path
) -> tuple[Path, str]:
    new_state_dir = effective_home / OPENCLAW_STATE_DIRNAME
    legacy_state_dir = effective_home / OPENCLAW_LEGACY_STATE_DIRNAME
    override = _path_override(env.get("OPENCLAW_STATE_DIR"))
    if override is not None:
        return (
            _expand_openclaw_path(override, effective_home=effective_home, cwd=cwd),
            "explicit_state_dir",
        )
    if env.get("OPENCLAW_TEST_FAST") == "1" or new_state_dir.exists():
        return new_state_dir, "new_state_dir"
    if legacy_state_dir.exists():
        return legacy_state_dir, "legacy_state_dir"
    return new_state_dir, "new_state_dir"


def _dotenv_value(raw: str | None) -> str:
    value = re.sub(r"^[\s\ufeff]+|[\s\ufeff]+$", "", raw or "")
    quote = value[:1]
    if len(value) >= 2 and quote in {"'", '"', "`"} and value[-1] == quote:
        value = value[1:-1]
    if quote == '"':
        value = value.replace("\\n", "\n").replace("\\r", "\r")
    return value


def _read_runtime_dotenv(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as exc:
        raise OpenClawAuthorityError(
            f"cannot read OpenClaw runtime dotenv {path.name}"
        ) from exc

    values: dict[str, str] = {}
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for match in _DOTENV_LINE.finditer(normalized):
        key = match.group(1)
        if key not in _PATH_AUTHORITY_KEYS:
            continue
        values[key] = _dotenv_value(match.group(2))
    return values


def _load_runtime_path_environment(
    env: Mapping[str, str], *, home: Path | None, cwd: Path
) -> tuple[dict[str, str], tuple[Path, ...], Path]:
    effective = dict(env)
    initial_home = _effective_home(effective, home=home, cwd=cwd)
    initial_state, _ = _state_dir(effective, effective_home=initial_home, cwd=cwd)
    state_env_path = initial_state / ".env"
    default_state_env_path = initial_home / OPENCLAW_STATE_DIRNAME / ".env"
    dotenv_paths = [state_env_path]
    explicit_state_present = "OPENCLAW_STATE_DIR" in effective
    if not (
        explicit_state_present
        and _absolute(state_env_path, cwd=cwd)
        != _absolute(default_state_env_path, cwd=cwd)
    ):
        dotenv_paths.append(initial_home / ".config/openclaw/gateway.env")

    preexisting = set(effective)
    first_seen: set[str] = set()
    for dotenv_path in dotenv_paths:
        for key, value in _read_runtime_dotenv(dotenv_path).items():
            if key in preexisting or key in first_seen:
                continue
            effective[key] = value
            first_seen.add(key)
    return effective, tuple(dict.fromkeys(dotenv_paths)), initial_state


def resolve_openclaw_config_authority(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    cwd: Path | None = None,
) -> OpenClawConfigAuthority:
    """Resolve OpenClaw 2026.4.14 path authority without process execution."""

    supplied_env = os.environ if environ is None else environ
    working_directory = _absolute(cwd or Path.cwd(), cwd=Path.cwd())
    env, dotenv_paths, initial_state = _load_runtime_path_environment(
        supplied_env, home=home, cwd=working_directory
    )
    effective_home = _effective_home(env, home=home, cwd=working_directory)
    state_dir, state_source = _state_dir(
        env, effective_home=effective_home, cwd=working_directory
    )
    explicit_config = _path_override(env.get("OPENCLAW_CONFIG_PATH"))
    new_state_dir = effective_home / OPENCLAW_STATE_DIRNAME
    legacy_state_dir = effective_home / OPENCLAW_LEGACY_STATE_DIRNAME

    config_candidates: tuple[Path, ...]
    if explicit_config is not None:
        config_candidates = (
            _expand_openclaw_path(
                explicit_config,
                effective_home=effective_home,
                cwd=working_directory,
            ),
        )
    elif env.get("OPENCLAW_TEST_FAST") == "1":
        config_candidates = (state_dir / OPENCLAW_CONFIG_FILENAME,)
    elif _path_override(env.get("OPENCLAW_STATE_DIR")) is not None:
        config_candidates = (
            state_dir / OPENCLAW_CONFIG_FILENAME,
            state_dir / OPENCLAW_LEGACY_CONFIG_FILENAME,
        )
    else:
        config_candidates = (
            new_state_dir / OPENCLAW_CONFIG_FILENAME,
            new_state_dir / OPENCLAW_LEGACY_CONFIG_FILENAME,
            legacy_state_dir / OPENCLAW_CONFIG_FILENAME,
            legacy_state_dir / OPENCLAW_LEGACY_CONFIG_FILENAME,
        )

    existing = next(
        (candidate for candidate in config_candidates if candidate.exists()), None
    )
    config_path = existing or (
        config_candidates[0]
        if explicit_config is not None or env.get("OPENCLAW_TEST_FAST") == "1"
        else state_dir / OPENCLAW_CONFIG_FILENAME
    )
    if explicit_config is not None:
        source = "explicit_config_path"
    elif env.get("OPENCLAW_TEST_FAST") == "1":
        source = "test_fast_canonical"
    elif existing is None:
        source = f"{state_source}_canonical_default"
    else:
        filename_label = (
            "canonical" if existing.name == OPENCLAW_CONFIG_FILENAME else "legacy"
        )
        if _path_override(env.get("OPENCLAW_STATE_DIR")) is not None:
            source = f"explicit_state_dir_{filename_label}_existing"
        elif existing.parent == new_state_dir:
            source = f"new_state_dir_{filename_label}_existing"
        else:
            source = f"default_legacy_{filename_label}_existing"

    state_candidates = tuple(
        dict.fromkeys(
            (
                state_dir,
                initial_state,
                new_state_dir,
                legacy_state_dir,
            )
        )
    )
    state_targets = _distinct_resolved_targets(state_candidates)
    return OpenClawConfigAuthority(
        config_path=config_path,
        state_dir=state_dir,
        source=source,
        config_candidates=config_candidates,
        state_candidates=state_candidates,
        dotenv_paths=dotenv_paths,
        config_target_candidates=_distinct_resolved_targets(config_candidates),
        state_target_candidates=state_targets,
        dotenv_target_paths=_distinct_resolved_targets(dotenv_paths),
        nested_state_target_candidates=tuple(
            target
            for target in _nested_symlink_targets(state_candidates)
            if target not in state_targets
        ),
    )
