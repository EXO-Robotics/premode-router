import os
from pathlib import Path

from premode.paths import normalize_for_manifest
from premode.config import init_project
from premode.profiles import PROFILES
from premode.ignore import IgnoreMatcher
from premode.safe_reader import safe_read


def test_cross_platform_path_normalization(repo):
    cases = [
        (str(repo / "src" / "App.swift"), "src/App.swift"),
        (f"C:\\{repo.name}\\src\\App.swift", "src/App.swift"),
        (f"{repo.name}\\src\\App.swift", "src/App.swift"),
        ("src\\App.swift", "src/App.swift"),
        ("src/App.swift", "src/App.swift"),
    ]
    for raw, expected in cases:
        norm = normalize_for_manifest(raw, repo)
        assert norm.ok, raw
        assert norm.rel_path == expected


def test_symlink_escape_blocked(repo, tmp_path):
    init_project(repo)
    outside_dir = repo.parent / "outside-area"
    outside_dir.mkdir(exist_ok=True)
    outside = outside_dir / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = repo / "src" / "escape.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        return
    res = safe_read(repo, "src/escape.txt", PROFILES["lite"], IgnoreMatcher.from_repo(repo))
    assert not res.allowed
    assert "escapes" in (res.reason or "")
