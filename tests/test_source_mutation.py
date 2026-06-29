import hashlib
from pathlib import Path

from premode.config import init_project
from premode.indexer import index_project
from premode.compiler import inspect_prompt, compile_prompt
from premode.hook import handle_user_prompt_submit


def _hash_sources(repo):
    out = {}
    for p in repo.rglob("*"):
        if p.is_file() and ".premode" not in p.parts:
            out[p.relative_to(repo).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_inspect_compile_hook_do_not_mutate_sources(repo):
    init_project(repo)
    index_project(repo, "lite")
    before = _hash_sources(repo)
    inspect_prompt(repo, "Fix build", "lite")
    compile_prompt(repo, "Fix build", "lite")
    handle_user_prompt_submit({"cwd": str(repo), "hook_event_name": "UserPromptSubmit", "prompt": "Fix build"}, "augment", repo)
    handle_user_prompt_submit({"cwd": str(repo), "hook_event_name": "UserPromptSubmit", "prompt": "Fix build"}, "strict", repo)
    after = _hash_sources(repo)
    assert before == after
