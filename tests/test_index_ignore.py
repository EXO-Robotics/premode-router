from premode.config import init_project
from premode.indexer import index_project
from premode.compiler import compile_prompt


def test_ignored_files_not_indexed_or_selected(repo):
    init_project(repo)
    (repo / "build").mkdir(exist_ok=True)
    (repo / "build" / "generated.swift").write_text("IGNORED_FILE_SENTINEL_12345", encoding="utf-8")
    (repo / ".env").write_text("IGNORED_FILE_SENTINEL_12345", encoding="utf-8")
    idx = index_project(repo, "standard")
    paths = {e["path"] for e in idx["entries"]}
    assert "build/generated.swift" not in paths
    assert ".env" not in paths
    compiled = compile_prompt(repo, "Fix the build. PROMPT_SENTINEL_12345", "standard")
    assert "PROMPT_SENTINEL_12345" in compiled["packet"]
    assert "IGNORED_FILE_SENTINEL_12345" not in compiled["packet"]
