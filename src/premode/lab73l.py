from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .audit import sha256_text
from .compiler import compile_prompt


FORBIDDEN_FINAL_STDIN_LABELS = ("Lab 7.3L", "benchmark", "harness")


def final_codex_stdin(raw_task_prompt: str, *, packet: str | None = None, execution_rules: str | None = None) -> str:
    parts: list[str] = []
    if packet:
        parts.append(packet.strip())
    parts.extend([
        "## USER TASK",
        str(raw_task_prompt or "").strip(),
    ])
    rules = str(execution_rules or "").strip()
    if rules:
        parts.extend([
            "",
            "## EXECUTION RULES",
            rules,
        ])
    return "\n".join(parts).strip() + "\n"


def write_stdin_snapshot(
    out_dir: Path,
    *,
    raw_task_prompt: str,
    harness_constraints: str = "",
    final_stdin: str,
    packet_compile_input_task: str | None = None,
    packet_text: str | None = None,
    packet_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = str(raw_task_prompt or "")
    constraints = str(harness_constraints or "")
    packet_input = raw if packet_compile_input_task is None else str(packet_compile_input_task)
    final = str(final_stdin or "")

    (out_dir / "raw_task_prompt.txt").write_text(raw, encoding="utf-8")
    (out_dir / "harness_constraints.txt").write_text(constraints, encoding="utf-8")
    (out_dir / "final_codex_stdin.txt").write_text(final, encoding="utf-8")
    (out_dir / "final_codex_stdin.sha256").write_text(sha256_text(final) + "\n", encoding="utf-8")
    (out_dir / "packet_compile_input_task.txt").write_text(packet_input, encoding="utf-8")
    (out_dir / "packet_compile_input_task.sha256").write_text(sha256_text(packet_input) + "\n", encoding="utf-8")
    if packet_text is not None:
        (out_dir / "packet.md").write_text(packet_text, encoding="utf-8")
    if packet_json is not None:
        (out_dir / "packet.json").write_text(json.dumps(packet_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "raw_task_prompt_path": str(out_dir / "raw_task_prompt.txt"),
        "harness_constraints_path": str(out_dir / "harness_constraints.txt"),
        "final_codex_stdin_path": str(out_dir / "final_codex_stdin.txt"),
        "final_codex_stdin_sha256": sha256_text(final),
        "packet_compile_input_task_path": str(out_dir / "packet_compile_input_task.txt"),
        "packet_compile_input_task_sha256": sha256_text(packet_input),
        "packet_path": str(out_dir / "packet.md") if packet_text is not None else None,
        "packet_json_path": str(out_dir / "packet.json") if packet_json is not None else None,
    }


def compile_v3_scaffold_free(
    repo_root: Path,
    raw_task_prompt: str,
    out_dir: Path,
    *,
    harness_constraints: str = "",
    profile_name: str | None = "lite",
    packet_detail_mode: str = "auto",
    snippet_budget_tokens: int = 2000,
) -> dict[str, Any]:
    compiled = compile_prompt(
        repo_root,
        raw_task_prompt,
        profile_name,
        packet_version="v3",
        packet_detail_mode=packet_detail_mode,
        snippet_budget_tokens=snippet_budget_tokens,
        record_artifacts=False,
    )
    final = final_codex_stdin(raw_task_prompt, packet=compiled["packet"], execution_rules=harness_constraints)
    snapshot = write_stdin_snapshot(
        out_dir,
        raw_task_prompt=raw_task_prompt,
        harness_constraints=harness_constraints,
        final_stdin=final,
        packet_compile_input_task=raw_task_prompt,
        packet_text=compiled["packet"],
        packet_json={k: v for k, v in compiled.items() if k != "packet"},
    )
    return {**compiled, "stdin_snapshot": snapshot}
