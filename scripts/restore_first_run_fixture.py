#!/usr/bin/env python3
"""Verify, safely extract, and initialize one frozen first-run fixture."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


def restore(
    snapshot: Path, expected_sha256: str, destination: Path, fixture_id: str
) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError("fixture destination must be absent or empty")
    payload = snapshot.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("fixture snapshot checksum mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(snapshot) as archive:
        for info in archive.infolist():
            member = PurePosixPath(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if member.is_absolute() or ".." in member.parts or mode == 0o120000:
                raise RuntimeError(f"unsafe fixture member: {info.filename}")
        archive.extractall(destination)

    git_env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_DATE": "2026-07-13T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-07-13T00:00:00Z",
    }
    commands = (
        ("git", "init", "-q", "--initial-branch=main"),
        ("git", "config", "user.email", "fixture.invalid"),
        ("git", "config", "user.name", "pCodex Fixture"),
        ("git", "add", "."),
        ("git", "commit", "-q", "-m", "frozen first-run fixture"),
    )
    for command in commands:
        subprocess.run(command, cwd=destination, env=git_env, check=True, timeout=30)
    if fixture_id == "fixture-02":
        (destination / "dirty-untracked.txt").write_text(
            "must remain unrelated\n", encoding="utf-8"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
