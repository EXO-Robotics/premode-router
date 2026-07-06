from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any

from .codex_exec import CodexOptions, build_codex_invocation, run_codex
from .compiler import compile_prompt
from .plugins import PluginAliasError, available_plugin_aliases, resolve_packet_plugin

PCODEX_PLUGIN_ALIAS = "literal_symbol"
PCODEX_PACKET_VERSION = "v5"
PCODEX_PACKET_VARIANT = "tool_assisted_anchors_internal"
PCODEX_PACKET_STRATEGY = "literal_symbol"
PCODEX_FALLBACK_VARIANT = "ranked_paths_plus_anchors"
CONFIG_ENV = "PCODEX_ENABLED"
CONFIG_PATH_ENV = "PCODEX_CONFIG"
CONFIG_PATH_ALIAS_ENV = "PCODEX_CONFIG_PATH"
ALGORITHM_ENV = "PCODEX_ALGORITHM"
PROJECT_ROOT_ENV = "PCODEX_PROJECT_ROOT"
PACKET_STRATEGY_ENV = "PCODEX_PACKET_STRATEGY"


@dataclass(frozen=True)
class PcodexConfig:
    enabled: bool = False
    source: str = "default"
    path: str | None = None
    algorithm: str = PCODEX_PACKET_STRATEGY


def _repo_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def _repo_config_path(repo_root: Path) -> Path:
    return repo_root / ".pcodex" / "config.toml"


def _user_config_path() -> Path:
    return Path.home() / ".pcodex" / "config.toml"


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _parse_algorithm(value: Any) -> str | None:
    if value is None:
        return PCODEX_PACKET_STRATEGY
    text = str(value).strip()
    return text if text == PCODEX_PACKET_STRATEGY else None


def _read_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    pcodex = data.get("pcodex")
    return pcodex if isinstance(pcodex, dict) else data


def resolve_config(cwd: Path | None = None, env: dict[str, str] | None = None) -> PcodexConfig:
    env = dict(os.environ if env is None else env)
    cwd = Path.cwd() if cwd is None else cwd
    env_algorithm = _parse_algorithm(env.get(ALGORITHM_ENV))
    if env_algorithm is None:
        return PcodexConfig(enabled=False, source=f"{ALGORITHM_ENV}:invalid", path=None)

    env_raw_value = env.get(CONFIG_ENV)
    env_value = _parse_bool(env_raw_value)
    if env_raw_value is not None and env_value is None:
        return PcodexConfig(enabled=False, source=f"{CONFIG_ENV}:invalid", path=None, algorithm=env_algorithm)
    if env_value is not None:
        return PcodexConfig(enabled=env_value, source=CONFIG_ENV, path=None, algorithm=env_algorithm)

    paths: list[tuple[str, Path]] = []
    config_path_value = env.get(CONFIG_PATH_ENV) or env.get(CONFIG_PATH_ALIAS_ENV)
    if config_path_value:
        source = CONFIG_PATH_ENV if env.get(CONFIG_PATH_ENV) else CONFIG_PATH_ALIAS_ENV
        paths.append((source, Path(config_path_value).expanduser()))
    repo_root = _repo_root(cwd)
    paths.extend([("repo", _repo_config_path(repo_root)), ("user", _user_config_path())])
    for source, path in paths:
        data = _read_config(path)
        enabled = _parse_bool(data.get("enabled"))
        algorithm = _parse_algorithm(data.get("algorithm"))
        if algorithm is None:
            return PcodexConfig(enabled=False, source=f"{source}:invalid", path=str(path))
        if enabled is not None:
            return PcodexConfig(
                enabled=enabled,
                source=source,
                path=str(path),
                algorithm=algorithm,
            )
        if path.exists():
            return PcodexConfig(enabled=False, source=f"{source}:invalid", path=str(path))
    return PcodexConfig()


def write_repo_config(cwd: Path, *, enabled: bool) -> Path:
    repo_root = _repo_root(cwd)
    path = _repo_config_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[pcodex]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        f"algorithm = \"{PCODEX_PACKET_STRATEGY}\"\n",
        encoding="utf-8",
    )
    return path


def _command_available(name: str) -> bool:
    if shutil.which(name) is not None:
        return True
    sibling = Path(sys.executable).with_name(name)
    return sibling.exists() and os.access(sibling, os.X_OK)


def plugin_alias_available() -> bool:
    try:
        resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
    except PluginAliasError:
        return False
    return True


def _literal_symbol_kwargs() -> dict[str, str]:
    return {
        "packet_version": PCODEX_PACKET_VERSION,
        "packet_variant": PCODEX_PACKET_VARIANT,
        "packet_strategy": PCODEX_PACKET_STRATEGY,
    }


def _premode_alias_command(prompt: str, repo_root: Path, profile: str | None) -> list[str]:
    cmd = ["premode", "compile", prompt, "--repo", str(repo_root), "--plugin", PCODEX_PLUGIN_ALIAS]
    if profile:
        cmd.extend(["--profile", profile])
    return cmd


def _premode_explicit_command(prompt: str, repo_root: Path, profile: str | None) -> list[str]:
    cmd = [
        "premode",
        "compile",
        prompt,
        "--repo",
        str(repo_root),
        "--packet-version",
        PCODEX_PACKET_VERSION,
        "--packet-variant",
        PCODEX_PACKET_VARIANT,
        "--packet-strategy",
        PCODEX_PACKET_STRATEGY,
    ]
    if profile:
        cmd.extend(["--profile", profile])
    return cmd


def compile_pcodex_packet(repo_root: Path, prompt: str, profile: str | None = "lite") -> dict[str, Any]:
    try:
        resolved = resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
        route = "plugin_alias"
        command = _premode_alias_command(prompt, repo_root, profile)
        kwargs = resolved.as_compile_kwargs()
        plugin_resolution = resolved.as_dict()
    except PluginAliasError as exc:
        route = "explicit_fallback"
        command = _premode_explicit_command(prompt, repo_root, profile)
        kwargs = _literal_symbol_kwargs()
        plugin_resolution = None
        fallback_reason = str(exc)
    else:
        fallback_reason = None
    compiled = compile_prompt(
        repo_root,
        prompt,
        profile,
        use_repo_map=True,
        cache_optimized=True,
        save=False,
        record_artifacts=False,
        **kwargs,
    )
    return {
        "status": "compiled",
        "route": route,
        "premode_command": command,
        "plugin_alias_resolution": plugin_resolution,
        "fallback_reason": fallback_reason,
        "packet": compiled["packet"],
        "packet_sha256": compiled.get("compiled_packet_sha256"),
        "packet_version": compiled.get("packet_version"),
        "packet_variant": compiled.get("packet_variant"),
        "packet_strategy": compiled.get("strategy_selected") or kwargs.get("packet_strategy"),
        "model_facing_sections": ["TASK", "PRIMARY_FILES", "RELATED_TESTS", "END_PREMODE_CONTEXT_PACKET_V5"],
    }


def redact_text(text: str, limit: int = 800) -> str:
    redacted = re.sub(r"\b\S*(?:SECRET|TOKEN|PASSWORD|API[_-]?KEY)\S*\b", "<redacted>", text, flags=re.IGNORECASE)
    return redacted[:limit] + ("..." if len(redacted) > limit else "")


def compose_final_prompt(raw_task: str, packet: str | None) -> str:
    if packet:
        return packet
    return raw_task


def doctor(cwd: Path | None = None) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    config = resolve_config(cwd)
    return {
        "status": "ok",
        "repo_root": str(repo_root),
        "premode_executable_available": _command_available("premode"),
        "codex_executable_available": _command_available("codex"),
        "plugin_alias_available": plugin_alias_available(),
        "available_plugin_aliases": available_plugin_aliases(),
        "fallback_explicit_literal_symbol_available": True,
        "git_repo": (repo_root / ".git").exists(),
        "config": config.__dict__,
        "algorithm": PCODEX_PACKET_STRATEGY,
        "secrets_printed": False,
    }


def status(cwd: Path | None = None) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    config = resolve_config(cwd)
    return {
        "enabled": config.enabled,
        "config_source": config.source,
        "config_path": config.path,
        "algorithm": PCODEX_PACKET_STRATEGY,
        "premode_available": _command_available("premode"),
        "codex_available": _command_available("codex"),
        "plugin_alias_available": plugin_alias_available(),
    }


def child_env_for(repo_root: Path, config: PcodexConfig | None = None) -> dict[str, str]:
    config = resolve_config(repo_root) if config is None else config
    env = {
        CONFIG_ENV: "1" if config.enabled else "0",
        ALGORITHM_ENV: PCODEX_PACKET_STRATEGY,
        PACKET_STRATEGY_ENV: PCODEX_PACKET_STRATEGY,
        PROJECT_ROOT_ENV: str(repo_root.resolve()),
    }
    if config.path and config.source in {"repo", CONFIG_PATH_ENV, CONFIG_PATH_ALIAS_ENV}:
        env[CONFIG_PATH_ENV] = config.path
        env[CONFIG_PATH_ALIAS_ENV] = config.path
    return env


def install(cwd: Path | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    repo_root = _repo_root(cwd)
    path = _repo_config_path(repo_root)
    result = {
        "status": "dry_run" if dry_run else "installed",
        "repo_root": str(repo_root),
        "config_path": str(path),
        "would_write": not path.exists(),
        "doctor": doctor(cwd),
    }
    if not dry_run and not path.exists():
        write_repo_config(cwd, enabled=False)
        result["written"] = True
    else:
        result["written"] = False
    return result


def set_enabled(cwd: Path | None, enabled: bool) -> dict[str, Any]:
    cwd = Path.cwd() if cwd is None else cwd
    path = write_repo_config(cwd, enabled=enabled)
    return {"status": "enabled" if enabled else "disabled", "enabled": enabled, "config_path": str(path), "algorithm": PCODEX_PACKET_STRATEGY}


def _write_temp_packet(packet: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="pcodex_packet_", suffix=".md", delete=False)
    with handle:
        handle.write(packet)
    return handle.name


def run_dry_run(repo_root: Path, prompt: str, profile: str | None = "lite") -> dict[str, Any]:
    config = resolve_config(repo_root)
    child_env = child_env_for(repo_root, config)
    base = {
        "status": "dry_run",
        "enabled": config.enabled,
        "config_source": config.source,
        "algorithm": PCODEX_PACKET_STRATEGY,
        "child_env": child_env,
        "child_env_keys": sorted(child_env),
        "raw_task_preview": redact_text(prompt),
        "codex_launch": "not_executed",
    }
    if config.enabled:
        compiled = compile_pcodex_packet(repo_root, prompt, profile)
        packet_path = _write_temp_packet(compiled["packet"])
        final_prompt = compose_final_prompt(prompt, compiled["packet"])
        invocation = build_codex_invocation(repo_root, CodexOptions(dry_run=True))
        return {
            **base,
            "premode_command": compiled["premode_command"],
            "codex_command": invocation.args,
            "packet_path": packet_path,
            "final_prompt_preview": redact_text(final_prompt),
            "packet_sha256": compiled["packet_sha256"],
            "route": compiled["route"],
        }
    invocation = build_codex_invocation(repo_root, CodexOptions(dry_run=True))
    return {
        **base,
        "premode_command": None,
        "codex_command": invocation.args,
        "packet_path": None,
        "final_prompt_preview": redact_text(prompt),
    }


def run_enabled(repo_root: Path, prompt: str, profile: str | None = "lite") -> dict[str, Any]:
    config = resolve_config(repo_root)
    child_env = child_env_for(repo_root, config)
    return run_codex(
        repo_root,
        prompt,
        profile,
        CodexOptions(
            dry_run=False,
            execute=True,
            packet_version=PCODEX_PACKET_VERSION,
            packet_variant=PCODEX_PACKET_VARIANT,
            packet_strategy=PCODEX_PACKET_STRATEGY,
            lane="pcodex",
            child_env=child_env,
        ),
    )


def run_disabled(repo_root: Path, prompt: str) -> dict[str, Any]:
    child_env = child_env_for(repo_root, resolve_config(repo_root))
    completed = subprocess.run(["codex", "exec", "-"], input=prompt, text=True, capture_output=True, check=False, cwd=repo_root, env={**os.environ, **child_env})
    return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "enabled": False, "child_env": child_env}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcodex")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--apply", action="store_true", help="Write repo-local pCodex config. Default is dry-run.")
    sub.add_parser("status")
    sub.add_parser("on")
    sub.add_parser("off")
    tune = sub.add_parser("tune")
    tune_group = tune.add_mutually_exclusive_group()
    tune_group.add_argument("--static-only", action="store_true", help="Generate static local tuning artifacts. This is the default.")
    tune_group.add_argument("--validate", action="store_true", help="Validate existing .premode/tuning artifacts without regenerating them.")
    tune.add_argument("--repo-root", default=None, help="Repository root to tune. Defaults to the current repo.")
    tune.add_argument("--out-dir", default=None, help="Artifact directory. Must remain under .premode/tuning/.")
    sub.add_parser("mcp-server")
    comp = sub.add_parser("compile")
    comp.add_argument("prompt")
    comp.add_argument("--repo", default=None)
    comp.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    comp.add_argument("--dry-run", action="store_true")
    comp.add_argument("--json", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("prompt")
    run.add_argument("--repo", default=None)
    run.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    cwd = Path.cwd()
    repo_arg = getattr(args, "repo", None) or getattr(args, "repo_root", None)
    repo_root = _repo_root(Path(repo_arg).resolve() if repo_arg else cwd)
    if args.command == "doctor":
        print(json.dumps(doctor(repo_root), indent=2, sort_keys=True))
        return 0
    if args.command == "install":
        print(json.dumps(install(repo_root, dry_run=not args.apply), indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        print(json.dumps(status(repo_root), indent=2, sort_keys=True))
        return 0
    if args.command == "on":
        print(json.dumps(set_enabled(repo_root, True), indent=2, sort_keys=True))
        return 0
    if args.command == "off":
        print(json.dumps(set_enabled(repo_root, False), indent=2, sort_keys=True))
        return 0
    if args.command == "tune":
        from .tuning import validate_tuning_artifacts, write_tuning_artifacts

        try:
            if args.validate:
                result = validate_tuning_artifacts(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result.get("status") == "pass" else 1
            result = write_tuning_artifacts(repo_root, out_dir=Path(args.out_dir) if args.out_dir else None)
        except ValueError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2, sort_keys=True))
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("validation_status") == "pass" else 1
    if args.command == "mcp-server":
        from . import pcodex_mcp_server

        return pcodex_mcp_server.serve()
    if args.command == "compile":
        if args.dry_run:
            try:
                resolve_packet_plugin(PCODEX_PLUGIN_ALIAS)
                command = _premode_alias_command(args.prompt, repo_root, args.profile)
                route = "plugin_alias"
            except PluginAliasError as exc:
                command = _premode_explicit_command(args.prompt, repo_root, args.profile)
                route = "explicit_fallback"
                fallback_reason = str(exc)
            else:
                fallback_reason = None
            print(json.dumps({"status": "dry_run", "route": route, "premode_command": command, "fallback_reason": fallback_reason}, indent=2, sort_keys=True))
            return 0
        compiled = compile_pcodex_packet(repo_root, args.prompt, args.profile)
        if args.json:
            payload = {key: value for key, value in compiled.items() if key != "packet"}
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(compiled["packet"])
        return 0
    if args.command == "run":
        if args.dry_run:
            print(json.dumps(run_dry_run(repo_root, args.prompt, args.profile), indent=2, sort_keys=True))
            return 0
        if resolve_config(repo_root).enabled:
            result = run_enabled(repo_root, args.prompt, args.profile)
        else:
            result = run_disabled(repo_root, args.prompt)
        print(json.dumps(result, indent=2, sort_keys=True))
        return int(result.get("returncode", 0) or 0)
    return 2
