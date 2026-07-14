#!/usr/bin/env python3
"""Verify, safely extract, and initialize one frozen first-run fixture."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
import zipfile


def restore(
    snapshot: Path,
    expected_sha256: str,
    destination: Path,
    fixture_id: str,
    git_executable: Path,
) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError("fixture destination must be absent or empty")
    if snapshot.is_symlink() or not snapshot.is_file():
        raise RuntimeError("fixture snapshot must be a regular file")
    if snapshot.stat().st_size > 64 * 1024 * 1024:
        raise RuntimeError("fixture snapshot is too large")
    payload = snapshot.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("fixture snapshot checksum mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(infos) > 10_000 or len(names) != len(set(names)):
            raise RuntimeError("fixture archive has too many or duplicate members")
        if len({name.casefold() for name in names}) != len(names):
            raise RuntimeError("fixture archive has case-conflicting members")
        total_size = 0
        for info in infos:
            member = PurePosixPath(info.filename)
            raw_parts = info.filename.split("/")
            unix_type = stat.S_IFMT(info.external_attr >> 16)
            permissions = (info.external_attr >> 16) & 0o777
            total_size += info.file_size
            if (
                not info.filename
                or "\x00" in info.filename
                or "\\" in info.filename
                or any(part in {"", "."} for part in raw_parts)
                or info.filename != member.as_posix()
                or member.is_absolute()
                or ".." in member.parts
                or any(part.casefold() == ".git" for part in member.parts)
                or member.name.casefold() in {".gitattributes", ".gitmodules"}
                or info.is_dir()
                or unix_type not in {0, stat.S_IFREG}
                or permissions != 0o644
                or info.flag_bits & 0x1
                or info.file_size > 32 * 1024 * 1024
                or total_size > 64 * 1024 * 1024
                or info.file_size / max(info.compress_size, 1) > 200.0
            ):
                raise RuntimeError(f"unsafe fixture member: {info.filename}")
        archive.extractall(destination)

    if not git_executable.is_absolute() or git_executable.is_symlink():
        raise RuntimeError("fixture restore requires an absolute Git executable")
    git_executable = git_executable.resolve(strict=True)
    if not git_executable.is_file() or not os.access(git_executable, os.X_OK):
        raise RuntimeError("fixture restore requires an absolute Git executable")
    with tempfile.TemporaryDirectory(
        prefix="pcodex-first-run-git-", dir=destination.parent
    ) as git_temp:
        git_env = {
            "HOME": os.devnull,
            "PATH": os.pathsep.join((str(git_executable.parent), "/usr/bin", "/bin")),
            "TMPDIR": git_temp,
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_DATE": "2026-07-13T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-07-13T00:00:00Z",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": os.devnull,
            "GIT_CONFIG_KEY_1": "core.attributesFile",
            "GIT_CONFIG_VALUE_1": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
        }
        commands = (
            (str(git_executable), "--version"),
            (str(git_executable), "init", "-q", "--initial-branch=main", "--template="),
            (str(git_executable), "config", "user.email", "fixture.invalid"),
            (str(git_executable), "config", "user.name", "pCodex Fixture"),
            (str(git_executable), "add", "--", "."),
            (str(git_executable), "commit", "-q", "-m", "frozen first-run fixture"),
        )
        for command in commands:
            subprocess.run(
                command, cwd=destination, env=git_env, check=True, timeout=30
            )
        inside = subprocess.run(
            (str(git_executable), "rev-parse", "--is-inside-work-tree"),
            cwd=destination,
            env=git_env,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        head = subprocess.run(
            (str(git_executable), "rev-parse", "HEAD"),
            cwd=destination,
            env=git_env,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        if inside != "true" or len(head) != 40:
            raise RuntimeError("fixture Git initialization postcondition failed")
    if fixture_id == "fixture-02":
        (destination / "dirty-untracked.txt").write_text(
            "must remain unrelated\n", encoding="utf-8"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument(
        "--fixture-id",
        choices=[f"fixture-{index:02d}" for index in range(1, 6)],
        required=True,
    )
    args = parser.parse_args()
    restore(
        args.snapshot.resolve(),
        args.sha256,
        args.destination.resolve(),
        args.fixture_id,
        args.git,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
