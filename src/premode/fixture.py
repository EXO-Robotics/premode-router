from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from .config import init_project
from .indexer import index_project
from .compiler import inspect_prompt, compile_prompt
from .codex_exec import run_codex, CodexOptions


def run_fixture() -> dict:
    temp = Path(tempfile.mkdtemp(prefix="premode-fixture-"))
    subprocess.run(["git", "init"], cwd=temp, check=True, capture_output=True, text=True)
    (temp / "src").mkdir()
    (temp / "docs").mkdir()
    (temp / "logs").mkdir()
    (temp / "build").mkdir()
    (temp / "README.md").write_text("# Fixture\n\nA tiny project for Pre-mode.\n", encoding="utf-8")
    (temp / "AGENTS.md").write_text("Stay minimal. Run tests before reporting done.\n", encoding="utf-8")
    (temp / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (temp / "docs" / "plan.md").write_text("The build fix should not expand scope.\n", encoding="utf-8")
    (temp / "logs" / "build.log").write_text(("error: sample failure\n" * 2000), encoding="utf-8")
    (temp / ".env").write_text("API_KEY=SECRET_SENTINEL_RAW_PROMPT_12345\n", encoding="utf-8")
    (temp / "secret.pem").write_text("-----BEGIN SECRET-----\n", encoding="utf-8")
    (temp / "build" / "generated.txt").write_text("ignored build artifact", encoding="utf-8")

    paths = init_project(temp)
    idx = index_project(temp)
    inspected = inspect_prompt(temp, "Fix the build. SECRET_SENTINEL_RAW_PROMPT_12345", "lite")
    compiled = compile_prompt(temp, "Fix the build. SECRET_SENTINEL_RAW_PROMPT_12345", "lite", out_path=temp / ".premode" / "out" / "fixture.md", json_out_path=temp / ".premode" / "out" / "fixture.json")
    dry = run_codex(temp, "Fix the build. SECRET_SENTINEL_RAW_PROMPT_12345", "lite", CodexOptions(dry_run=True))
    return {
        "fixture_repo": str(temp),
        "generated_paths": paths,
        "index_entries": idx["entry_count"],
        "inspect_audit": inspected["audit_path"],
        "compiled_packet": str(temp / ".premode" / "out" / "fixture.md"),
        "compiled_json": str(temp / ".premode" / "out" / "fixture.json"),
        "dry_run": dry,
    }
