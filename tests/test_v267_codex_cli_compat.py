import json

from premode.codex_exec import (
    CodexOptions,
    build_codex_invocation,
    codex_capabilities_from_help,
    run_codex,
)
from premode.config import init_project
from premode.indexer import index_project


def _caps(help_text: str):
    return codex_capabilities_from_help(help_text)


def _help_with(*flags: str) -> str:
    return "Usage: codex exec [OPTIONS] -\n" + "\n".join(f"  {flag}" for flag in flags)


def test_codex_help_with_approval_mode_uses_new_flag(repo):
    caps = _caps(_help_with("-C <DIR>", "--sandbox <MODE>", "--approval-mode <MODE>", "--ephemeral"))
    invocation = build_codex_invocation(repo, CodexOptions(), caps)
    assert "--approval-mode" in invocation.args
    assert "--ask-for-approval" not in invocation.args
    assert invocation.capabilities["approval_strategy"] == "--approval-mode"
    assert invocation.args[-1] == "-"


def test_codex_help_with_ask_for_approval_uses_legacy_flag(repo):
    caps = _caps(_help_with("-C <DIR>", "--sandbox <MODE>", "--ask-for-approval <MODE>", "--ephemeral"))
    invocation = build_codex_invocation(repo, CodexOptions(), caps)
    assert "--ask-for-approval" in invocation.args
    assert "--approval-mode" not in invocation.args
    assert invocation.capabilities["approval_strategy"] == "--ask-for-approval"
    assert invocation.args[-1] == "-"


def test_codex_help_without_approval_flag_omits_approval_and_warns(repo):
    caps = _caps(_help_with("-C <DIR>", "--sandbox <MODE>", "--ephemeral"))
    invocation = build_codex_invocation(repo, CodexOptions(), caps)
    assert "--approval-mode" not in invocation.args
    assert "--ask-for-approval" not in invocation.args
    assert invocation.capabilities["approval_strategy"] == "omitted"
    assert any("approval mode omitted" in warning for warning in invocation.warnings)
    assert invocation.args[-1] == "-"


def test_unsupported_output_last_message_is_omitted_and_warns(repo):
    caps = _caps(_help_with("-C <DIR>", "--sandbox <MODE>", "--approval-mode <MODE>", "--ephemeral"))
    invocation = build_codex_invocation(repo, CodexOptions(output_last_message=".premode/out/final.md"), caps)
    assert "--output-last-message" not in invocation.args
    assert ".premode/out/final.md" not in invocation.args
    assert any("--output-last-message" in warning for warning in invocation.warnings)
    assert invocation.args[-1] == "-"


def test_unsupported_short_cd_falls_back_to_long_cd(repo):
    caps = _caps(_help_with("--cd <DIR>", "--sandbox <MODE>", "--approval-mode <MODE>", "--ephemeral"))
    invocation = build_codex_invocation(repo, CodexOptions(), caps)
    assert "-C" not in invocation.args
    assert "--cd" in invocation.args
    assert invocation.cwd is None
    assert invocation.capabilities["cd_strategy"] == "--cd"
    assert invocation.args[-1] == "-"


def test_missing_cd_flags_falls_back_to_subprocess_cwd(repo):
    caps = _caps(_help_with("--sandbox <MODE>", "--approval-mode <MODE>", "--ephemeral"))
    invocation = build_codex_invocation(repo, CodexOptions(), caps)
    assert "-C" not in invocation.args
    assert "--cd" not in invocation.args
    assert invocation.cwd == repo.resolve()
    assert invocation.capabilities["cd_strategy"] == "subprocess_cwd"
    assert invocation.args[-1] == "-"


def test_dry_run_contains_capabilities_warnings_and_no_raw_prompt(monkeypatch, repo):
    init_project(repo)
    index_project(repo, "lite")
    caps = _caps(_help_with("-C <DIR>", "--sandbox <MODE>", "--ephemeral"))
    monkeypatch.setattr("premode.codex_exec.detect_codex_capabilities", lambda: caps)
    raw_prompt = "Fix worker SECRET_SENTINEL_RAW_PROMPT_12345"
    dry = run_codex(repo, raw_prompt, "lite", CodexOptions(dry_run=True, output_last_message=".premode/out/final.md"))
    assert "codex_capabilities" in dry
    assert "codex_warnings" in dry
    assert dry["command"][-1] == "-"
    assert raw_prompt not in dry["command"]
    assert "SECRET_SENTINEL_RAW_PROMPT_12345" not in json.dumps(dry)
    assert "--ask-for-approval" not in dry["command"]
    assert "--approval-mode" not in dry["command"]
    assert any("approval mode omitted" in warning for warning in dry["codex_warnings"])


def test_local_unsupported_ask_for_approval_shape_prefers_supported_flag(repo):
    caps = _caps(_help_with("-C <DIR>", "--sandbox <MODE>", "--approval-mode <MODE>", "--ephemeral", "--output-last-message <FILE>"))
    invocation = build_codex_invocation(repo, CodexOptions(output_last_message=".premode/out/final.md"), caps)
    assert "--ask-for-approval" not in invocation.args
    assert "--approval-mode" in invocation.args
    assert "--output-last-message" in invocation.args
    assert invocation.args[-1] == "-"
