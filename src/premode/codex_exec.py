from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

from .compiler import compile_prompt
from .config import premode_dir
from .audit import sha256_text, write_audit
from .metrics import append_metric


@dataclass
class CodexOptions:
    sandbox: str = "workspace-write"
    approval: str = "on-request"
    ephemeral: bool = True
    json: bool = False
    output_last_message: str | None = None
    output_schema: str | None = None
    structured_final_report: bool = False
    codex_profile: str | None = None
    add_dir: list[str] = field(default_factory=list)
    skip_git_repo_check: bool = False
    model: str | None = None
    oss: bool = False
    dry_run: bool = False
    execute: bool = False
    watch: bool = False
    show_raw: bool = False
    use_repo_map: bool = True
    cache_optimized: bool = True
    packet_version: str | None = None
    save: bool = True


def default_schema_path(repo_root: Path) -> str:
    return str(premode_dir(repo_root) / "schemas" / "codex_final_report.schema.json")


def build_codex_args(repo_root: Path, options: CodexOptions) -> list[str]:
    args = [
        "codex",
        "exec",
        "-C",
        str(repo_root.resolve()),
        "--sandbox",
        options.sandbox,
        "--ask-for-approval",
        options.approval,
    ]
    if options.ephemeral:
        args.append("--ephemeral")
    if options.json:
        args.append("--json")
    if options.output_last_message:
        args.extend(["--output-last-message", options.output_last_message])
    schema = options.output_schema
    if options.structured_final_report and not schema:
        schema = default_schema_path(repo_root)
    if schema:
        args.extend(["--output-schema", schema])
    if options.codex_profile:
        args.extend(["--profile", options.codex_profile])
    for p in options.add_dir:
        args.extend(["--add-dir", p])
    if options.skip_git_repo_check:
        args.append("--skip-git-repo-check")
    if options.model:
        args.extend(["--model", options.model])
    if options.oss:
        args.append("--oss")
    args.append("-")
    return args


def validate_codex_args(args: list[str], raw_prompt: str) -> None:
    if not args or args[-1] != "-":
        raise AssertionError("Codex args must end with stdin prompt sentinel '-'.")
    if raw_prompt and any(raw_prompt == arg or raw_prompt in arg for arg in args):
        raise AssertionError("Raw prompt leaked into subprocess args.")
    # For codex exec, the only non-flag positional after the subcommand must be '-'.
    # Values for known flags are skipped.
    value_flags = {
        "-C", "--cd", "--sandbox", "-s", "--ask-for-approval", "-a", "--output-last-message", "-o",
        "--output-schema", "--profile", "-p", "--add-dir", "--model", "-m", "--color", "-c", "--config",
    }
    positionals: list[str] = []
    i = 2  # skip codex exec
    while i < len(args):
        a = args[i]
        if a in value_flags:
            i += 2
            continue
        if a.startswith("-") and a != "-":
            i += 1
            continue
        positionals.append(a)
        i += 1
    if positionals != ["-"]:
        raise AssertionError(f"Unexpected Codex positional prompt args: {positionals!r}")


def run_codex(
    repo_root: Path,
    raw_prompt: str,
    resource_profile: str | None = None,
    options: CodexOptions | None = None,
) -> dict[str, Any]:
    options = options or CodexOptions()
    effective_profile = resource_profile or "lite"
    compiled = compile_prompt(
        repo_root,
        raw_prompt,
        effective_profile,
        use_repo_map=options.use_repo_map,
        cache_optimized=options.cache_optimized,
        packet_version=options.packet_version,
        save=options.save,
    )
    packet = compiled["packet"]
    if packet == raw_prompt:
        raise AssertionError("Compiled packet must not equal raw prompt.")
    args = build_codex_args(repo_root, options)
    validate_codex_args(args, raw_prompt)
    command_record = {"args": args, "stdin_sha256": sha256_text(packet), "dry_run": options.dry_run}
    if options.dry_run:
        output = {
            "command": args,
            "stdin": "<compiled-packet-on-stdin>",
            "compiled_packet_sha256": sha256_text(packet),
            "raw_prompt_sha256": sha256_text(raw_prompt),
            "compile_settings": {
                "profile": effective_profile,
                "use_repo_map": options.use_repo_map,
                "cache_optimized": options.cache_optimized,
                "packet_version": compiled.get("packet_version"),
                "save": options.save,
            },
            "saved_artifacts": compiled.get("saved_artifacts"),
        }
        if options.show_raw:
            output["raw_prompt"] = raw_prompt
        write_audit(repo_root, "codex_dry_run", sha256_text(raw_prompt), command_record)
        append_metric(repo_root, {"event": "codex_dry_run", "raw_prompt_sha256": sha256_text(raw_prompt), "estimated_input_bytes": len(packet.encode()), "actual_usage": None})
        return output

    if options.watch:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        assert proc.stdin is not None
        proc.stdin.write(packet)
        proc.stdin.close()
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        def pump(stream, sink: list[str], target):
            if stream is None:
                return
            for line in stream:
                sink.append(line)
                target.write(line)
                target.flush()

        threads = [
            threading.Thread(target=pump, args=(proc.stdout, stdout_parts, sys.stdout), daemon=True),
            threading.Thread(target=pump, args=(proc.stderr, stderr_parts, sys.stderr), daemon=True),
        ]
        for t in threads:
            t.start()
        returncode = proc.wait()
        for t in threads:
            t.join(timeout=1)
        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
    else:
        completed = subprocess.run(args, input=packet, text=True, capture_output=True, check=False)
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr

    actual_usage = _extract_usage_from_jsonl(stdout)
    write_audit(repo_root, "codex_execute", sha256_text(raw_prompt), {
        **command_record,
        "watch": options.watch,
        "returncode": returncode,
        "stdout_sha256": sha256_text(stdout or ""),
        "stderr_sha256": sha256_text(stderr or ""),
    })
    append_metric(repo_root, {
        "event": "codex_execute",
        "raw_prompt_sha256": sha256_text(raw_prompt),
        "estimated_input_bytes": len(packet.encode()),
        "actual_usage": actual_usage,
        "returncode": returncode,
    })
    return {"args": args, "returncode": returncode, "stdout": stdout, "stderr": stderr, "actual_usage": actual_usage}


def _extract_usage_from_jsonl(text: str) -> dict[str, Any] | None:
    usage: dict[str, Any] = {}
    for line in (text or "").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidate = obj.get("usage") if isinstance(obj, dict) else None
        if isinstance(candidate, dict):
            usage.update(candidate)
    return usage or None
