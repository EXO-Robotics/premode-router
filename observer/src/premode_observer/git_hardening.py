"""Sanitized, bounded Git execution for observer measurements."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Sequence


GIT_HARDENING_VERSION = "observer-git-environment.v1"
ALLOWED_SUBCOMMANDS = frozenset({
    "add", "branch", "commit", "config", "diff", "init", "ls-files",
    "merge-base", "rev-parse", "status",
})
EXECUTION_CONFIG_PATTERN = re.compile(
    r"(?im)^\s*(?:include|includeif|fsmonitor|hookspath|pager|textconv|external|command|clean|smudge|process|helper|sshcommand|editor|gpgsign|program)\s*="
)
ATTRIBUTE_EXECUTION_PATTERN = re.compile(r"(?i)(?:^|\s)(?:filter|diff)=[^\s]+")
INCLUDE_SECTION_PATTERN = re.compile(r"(?im)^\s*\[\s*include(?:if\s+[^]]+)?\s*\]")
MAX_ATTRIBUTE_FILES = 1024
MAX_CONTROL_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class GitResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    environment_version: str
    repository_control_status: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.repository_control_status == "safe"


def audit_repository_control(root: Path) -> tuple[str, tuple[str, ...]]:
    """Inspect execution-bearing repository metadata without invoking Git."""
    root = Path(root).resolve(strict=True)
    findings: list[str] = []
    dotgit = root / ".git"
    config_path: Path | None = None
    try:
        if dotgit.is_symlink():
            return "unsafe", ("SYMLINKED_GIT_METADATA",)
    except OSError:
        return "indeterminate", ("UNREADABLE_GIT_METADATA",)
    if dotgit.is_file():
        try:
            line = dotgit.read_text(encoding="utf-8", errors="strict").strip()
        except (OSError, UnicodeError):
            return "indeterminate", ("UNREADABLE_GIT_REDIRECT",)
        if not line.casefold().startswith("gitdir:"):
            return "unsafe", ("MALFORMED_GIT_REDIRECT",)
        target = Path(line.split(":", 1)[1].strip())
        target = target if target.is_absolute() else root / target
        try:
            resolved = target.resolve(strict=True)
        except OSError:
            return "unsafe", ("BROKEN_GIT_REDIRECT",)
        if root != resolved and root not in resolved.parents:
            return "unsafe", ("OUTSIDE_ROOT_GIT_REDIRECT",)
        config_path = resolved / "config"
    elif dotgit.is_dir():
        config_path = dotgit / "config"
    config_paths = [config_path] if config_path is not None else []
    if dotgit.is_dir():
        config_paths.append(dotgit / "config.worktree")
    for config_path in config_paths:
        if config_path is None or (not config_path.exists() and not config_path.is_symlink()):
            continue
        try:
            config_resolved = config_path.resolve(strict=True)
            config_resolved.relative_to(root)
            config_stat = config_resolved.stat()
        except (OSError, ValueError):
            return "unsafe", ("OUTSIDE_OR_UNSAFE_GIT_CONFIG",)
        if config_path.is_symlink() or not config_resolved.is_file() or config_stat.st_nlink > 1:
            return "unsafe", ("OUTSIDE_OR_UNSAFE_GIT_CONFIG",)
        try:
            text = config_path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError):
            return "indeterminate", ("UNREADABLE_LOCAL_GIT_CONFIG",)
        if EXECUTION_CONFIG_PATTERN.search(text) or INCLUDE_SECTION_PATTERN.search(text):
            findings.append("REPOSITORY_EXECUTION_CONFIG")
    attribute_paths: list[Path] = []
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = [name for name in names if name != ".git" and not (Path(directory) / name).is_symlink()]
        if ".gitattributes" in files:
            attribute_paths.append(Path(directory) / ".gitattributes")
            if len(attribute_paths) > MAX_ATTRIBUTE_FILES:
                return "indeterminate", ("TOO_MANY_GIT_ATTRIBUTES",)
    if dotgit.is_dir():
        attribute_paths.append(dotgit / "info" / "attributes")
    total_control_bytes = 0
    for attributes in attribute_paths:
        if attributes is None:
            continue
        if attributes.is_symlink() and not attributes.exists():
            return "unsafe", ("UNSAFE_GIT_ATTRIBUTES_SURFACE",)
        if not attributes.exists():
            continue
        try:
            attributes_resolved = attributes.resolve(strict=True)
            attributes_resolved.relative_to(root)
            attributes_stat = attributes_resolved.stat()
        except (OSError, ValueError):
            return "unsafe", ("UNSAFE_GIT_ATTRIBUTES_SURFACE",)
        if attributes.is_symlink() or not attributes_resolved.is_file() or attributes_stat.st_nlink > 1:
            return "unsafe", ("UNSAFE_GIT_ATTRIBUTES_SURFACE",)
        try:
            total_control_bytes += attributes.stat().st_size
            if total_control_bytes > MAX_CONTROL_BYTES:
                return "indeterminate", ("GIT_ATTRIBUTES_TOO_LARGE",)
            text = attributes.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError):
            return "indeterminate", ("UNREADABLE_GIT_ATTRIBUTES",)
        if ATTRIBUTE_EXECUTION_PATTERN.search(text):
            findings.append("ATTRIBUTE_EXECUTION_DRIVER")
    return ("unsafe", tuple(sorted(set(findings)))) if findings else ("safe", ())


def run_git(
    root: Path,
    args: Sequence[str],
    *,
    check: bool = False,
    timeout: float = 10.0,
    audit_repository: bool = True,
) -> GitResult:
    """Run one fixed Git builtin with sanitized configuration and environment."""
    root = Path(root).resolve(strict=True)
    if not args or args[0] not in ALLOWED_SUBCOMMANDS:
        raise ValueError("Git subcommand is not in the observer allow-list")
    if args[0] == "branch" and tuple(args[1:]) != ("--show-current",):
        raise ValueError("Git branch is limited to --show-current")
    if args[0] == "init" and tuple(args[1:]) not in {(), ("-q",), ("--quiet",)}:
        raise ValueError("Git init arguments are not in the observer allow-list")
    if args[0] == "config" and tuple(args[1:]) not in {
        ("user.email", "observer@example.invalid"),
        ("user.name", "Observer"),
    }:
        raise ValueError("Git config arguments are not in the observer allow-list")
    if args[0] == "add" and tuple(args[1:]) != (".",):
        raise ValueError("Git add arguments are not in the observer allow-list")
    if args[0] == "commit" and tuple(args[1:]) != ("-qm", "fixture"):
        raise ValueError("Git commit arguments are not in the observer allow-list")
    git_path = next((path for path in (Path("/usr/bin/git"), Path("/opt/homebrew/bin/git")) if path.is_file()), None)
    if git_path is None:
        raise FileNotFoundError("trusted Git executable not found")
    git_stat = git_path.stat()
    if git_stat.st_uid != 0 or git_stat.st_mode & 0o022:
        raise PermissionError("Git executable is not on a trusted immutable surface")
    git = str(git_path.resolve(strict=True))
    control_status, findings = audit_repository_control(root) if audit_repository else ("safe", ())
    if control_status != "safe":
        result = GitResult(
            argv=(git, *args),
            returncode=125,
            stdout="",
            stderr=",".join(findings) or "repository control evidence incomplete",
            environment_version=GIT_HARDENING_VERSION,
            repository_control_status=control_status,
        )
        if check:
            raise subprocess.CalledProcessError(result.returncode, result.argv, output=result.stdout, stderr=result.stderr)
        return result
    with tempfile.TemporaryDirectory(prefix="premode-observer-git-") as temp_value:
        temp = Path(temp_value)
        empty_config = temp / "global.gitconfig"
        empty_config.touch(mode=0o600)
        hooks = temp / "hooks"
        hooks.mkdir(mode=0o700)
        home = temp / "home"
        home.mkdir(mode=0o700)
        xdg = temp / "xdg"
        xdg.mkdir(mode=0o700)
        askpass = temp / "askpass"
        askpass.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        askpass.chmod(0o700)
        env = {
            "PATH": f"{Path(git).parent}:/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": str(askpass),
            "SSH_ASKPASS": str(askpass),
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GIT_EDITOR": "true",
            "GIT_SEQUENCE_EDITOR": "true",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        command = [
            git,
            "--no-pager",
            "-c", f"core.hooksPath={hooks}",
            "-c", "core.fsmonitor=false",
            "-c", "core.attributesFile=/dev/null",
            "-c", "core.excludesFile=/dev/null",
            "-c", "diff.external=",
            "-c", "credential.helper=",
            "-c", "commit.gpgSign=false",
            "-c", "tag.gpgSign=false",
            *args,
        ]
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    stdout = completed.stdout[:1_000_000]
    stderr = completed.stderr[:64_000]
    result = GitResult(
        argv=tuple(command),
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        environment_version=GIT_HARDENING_VERSION,
        repository_control_status=control_status,
    )
    if check and not result.ok:
        raise subprocess.CalledProcessError(result.returncode, result.argv, output=stdout, stderr=stderr)
    return result
