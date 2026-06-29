import json

from premode.config import init_project
from premode.indexer import index_project
from premode.hook import handle_user_prompt_submit
from premode.plugin import install_local_plugin
from premode.mcp_server import call_tool


def test_hook_strict_blocks_uncompiled_and_augment_adds_context(repo):
    init_project(repo)
    index_project(repo, "lite")
    payload = {"cwd": str(repo), "hook_event_name": "UserPromptSubmit", "prompt": "Fix build SECRET_SENTINEL_RAW_PROMPT_12345"}
    strict = handle_user_prompt_submit(payload, "strict", repo)
    assert strict["decision"] == "block"
    assert "SECRET_SENTINEL_RAW_PROMPT_12345" not in json.dumps(strict)
    augment = handle_user_prompt_submit(payload, "augment", repo)
    assert "hookSpecificOutput" in augment
    assert "additionalContext" in augment["hookSpecificOutput"]


def test_plugin_manifest_hooks_mcp_parse(repo):
    init_project(repo)
    paths = install_local_plugin(repo, "repo")
    for key in ["marketplace", "manifest", "hooks", "mcp"]:
        data = json.loads(open(paths[key], encoding="utf-8").read())
        assert data
    manifest = json.loads(open(paths["manifest"], encoding="utf-8").read())
    assert manifest["skills"] == "./skills/"
    assert manifest["hooks"] == "./hooks/hooks.json"
    assert manifest["mcpServers"] == "./.mcp.json"


def test_mcp_tools_json_safe_read_only(repo):
    init_project(repo)
    index_project(repo, "lite")
    result = call_tool("premode_read_index", {}, repo)
    json.dumps(result)
    assert result["content"][0]["type"] == "text"
