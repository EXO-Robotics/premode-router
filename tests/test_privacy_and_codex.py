import json
from pathlib import Path

from premode.config import init_project
from premode.indexer import index_project
from premode.codex_exec import CodexOptions, build_codex_args, codex_capabilities_from_help, run_codex
from premode.compiler import compile_prompt

SENTINEL_PROMPT = "Fix the build. SECRET_SENTINEL_RAW_PROMPT_12345"
CODEX_HELP = """
Usage: codex exec [OPTIONS] -
  -C <DIR>
  --sandbox <MODE>
  --approval-mode <MODE>
  --ephemeral
  --json
  --output-last-message <FILE>
"""


def test_codex_command_shape_and_no_raw_prompt(repo):
    init_project(repo)
    caps = codex_capabilities_from_help(CODEX_HELP)
    args = build_codex_args(repo, CodexOptions(json=True, output_last_message=".premode/out/final.md"), caps)
    assert args[-1] == "-"
    assert args.count("-") == 1
    assert "--json" in args
    assert "--output-last-message" in args


def test_secret_sentinel_privacy_dry_run(repo):
    init_project(repo)
    index_project(repo, "lite")
    dry = run_codex(repo, SENTINEL_PROMPT, "lite", CodexOptions(dry_run=True))
    text = json.dumps(dry)
    assert "SECRET_SENTINEL_RAW_PROMPT_12345" not in text
    assert dry["command"][-1] == "-"
    assert SENTINEL_PROMPT not in dry["command"]
    audit_text = "\n".join(p.read_text(encoding="utf-8") for p in (repo / ".premode" / "audit").glob("*.json"))
    metrics_text = (repo / ".premode" / "metrics" / "usage_ledger.jsonl").read_text(encoding="utf-8")
    assert "SECRET_SENTINEL_RAW_PROMPT_12345" not in audit_text
    assert "SECRET_SENTINEL_RAW_PROMPT_12345" not in metrics_text
    assert "raw_prompt_sha256" in audit_text


def test_compile_packet_sanitizes_sentinel(repo):
    init_project(repo)
    index_project(repo, "lite")
    compiled = compile_prompt(repo, SENTINEL_PROMPT, "lite")
    assert "SECRET_SENTINEL_RAW_PROMPT_12345" not in compiled["packet"]
    assert "[REDACTED" in compiled["packet"]


def test_execute_uses_compiled_packet_stdin(monkeypatch, repo):
    init_project(repo)
    index_project(repo, "lite")
    captured = {}
    caps = codex_capabilities_from_help(CODEX_HELP)
    monkeypatch.setattr("premode.codex_exec.detect_codex_capabilities", lambda: caps)
    class Result:
        returncode = 0
        stdout = '{"usage":{"input_tokens":1,"output_tokens":1}}\n'
        stderr = ""
    def fake_run(args, input, text, capture_output, check, cwd=None):
        captured["args"] = args
        captured["input"] = input
        captured["cwd"] = cwd
        return Result()
    monkeypatch.setattr("subprocess.run", fake_run)
    run_codex(repo, SENTINEL_PROMPT, "lite", CodexOptions(json=True))
    assert captured["args"][-1] == "-"
    assert SENTINEL_PROMPT not in captured["args"]
    assert captured["input"] != SENTINEL_PROMPT
    assert "SECRET_SENTINEL_RAW_PROMPT_12345" not in captured["input"]
    assert "PREMODE_COMPILED_PACKET_V3" in captured["input"]
