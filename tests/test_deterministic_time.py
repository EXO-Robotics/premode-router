from premode.config import init_project
from premode.indexer import index_project
from premode.compiler import compile_prompt


def test_deterministic_audit_filename(monkeypatch, repo):
    monkeypatch.setenv("PREMODE_TEST_FIXED_TIME", "2026-01-01T00:00:00Z")
    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, "Fix deterministic", "lite")
    assert "20260101T000000Z" in result["audit_path"]
    text = next((repo / ".premode" / "audit").glob("*.json")).read_text(encoding="utf-8")
    assert "2026-01-01T00:00:00Z" in text
