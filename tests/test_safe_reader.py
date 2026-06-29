from pathlib import Path

from premode.config import init_project
from premode.ignore import IgnoreMatcher
from premode.profiles import PROFILES
from premode.safe_reader import safe_read
from premode.indexer import index_project
from premode.compiler import compile_prompt, inspect_prompt


def test_large_file_truncated(repo):
    init_project(repo)
    p = repo / "src" / "huge.txt"
    p.write_text("A" * 200000, encoding="utf-8")
    res = safe_read(repo, "src/huge.txt", PROFILES["lite"], IgnoreMatcher.from_repo(repo))
    assert res.allowed
    assert res.truncated
    assert res.bytes_read <= PROFILES["lite"].max_file_bytes


def test_large_log_head_tail_truncated(repo):
    init_project(repo)
    (repo / "logs").mkdir()
    p = repo / "logs" / "build.log"
    p.write_text("HEAD\n" + ("middle\n" * 50000) + "TAIL\n", encoding="utf-8")
    res = safe_read(repo, "logs/build.log", PROFILES["lite"], IgnoreMatcher.from_repo(repo))
    assert res.allowed
    assert res.truncated
    assert res.bytes_read <= PROFILES["lite"].max_log_bytes
    assert "HEAD" in res.content


def test_compile_inspect_respect_per_file_cap(repo):
    init_project(repo)
    (repo / "src" / "huge.py").write_text("print('x')\n" * 20000, encoding="utf-8")
    index_project(repo, "lite")
    c = compile_prompt(repo, "fix huge", "lite")
    i = inspect_prompt(repo, "fix huge", "lite")
    assert all(item["bytes_read"] <= item["max_bytes"] for item in c["selected"])
    assert all(item["bytes_read"] <= item["max_bytes"] for item in i["selected"])


def test_premodeignore_blocks_secret_read(repo):
    init_project(repo)
    (repo / ".env").write_text("SECRET=abc", encoding="utf-8")
    res = safe_read(repo, ".env", PROFILES["standard"], IgnoreMatcher.from_repo(repo))
    assert not res.allowed
    assert "ignored" in (res.reason or "") or "secret" in (res.reason or "")
