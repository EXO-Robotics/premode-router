from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Any

from .compiler import compile_prompt
from .config import premode_dir
from .audit import sha256_text, write_audit
from .launch_safety import write_external_payload_manifest
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
    context_only: bool = False
    record: bool = True
    lane: str = "codex"
    repo_is_private: bool = False
    private_paths_forbidden: bool = False


@dataclass(frozen=True)
class CodexInvocation:
    args: list[str]
    cwd: Path | None
    capabilities: dict[str, Any]
    warnings: list[str]


def default_schema_path(repo_root: Path) -> str:
    return str(premode_dir(repo_root) / "schemas" / "codex_final_report.schema.json")


def _has_short_flag(help_text: str, flag: str) -> bool:
    escaped = re.escape(flag)
    return bool(re.search(rf"(^|[\s,\[]){escaped}($|[\s,=<\]])", help_text))


def codex_capabilities_from_help(help_text: str, help_available: bool = True, help_error: str | None = None) -> dict[str, Any]:
    supports = {
        "approval_mode": "--approval-mode" in help_text,
        "ask_for_approval": "--ask-for-approval" in help_text,
        "cd_short": _has_short_flag(help_text, "-C"),
        "cd_long": "--cd" in help_text,
        "sandbox": "--sandbox" in help_text,
        "ephemeral": "--ephemeral" in help_text,
        "json": "--json" in help_text,
        "output_last_message": "--output-last-message" in help_text,
        "output_schema": "--output-schema" in help_text,
        "profile": "--profile" in help_text,
        "add_dir": "--add-dir" in help_text,
        "skip_git_repo_check": "--skip-git-repo-check" in help_text,
        "model": "--model" in help_text or _has_short_flag(help_text, "-m"),
        "oss": "--oss" in help_text,
    }
    return {"help_available": help_available, "supports": supports, "help_error": help_error}


def detect_codex_capabilities() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["codex", "exec", "--help"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return codex_capabilities_from_help("", help_available=False, help_error=str(exc))
    help_text = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    if completed.returncode != 0 and not help_text:
        return codex_capabilities_from_help("", help_available=False, help_error=f"codex exec --help exited {completed.returncode}")
    return codex_capabilities_from_help(help_text, help_available=True)


def _warn_unsupported(warnings: list[str], flag: str) -> None:
    warnings.append(f"Codex CLI help does not advertise {flag}; omitting that option.")


def build_codex_invocation(
    repo_root: Path,
    options: CodexOptions,
    capabilities: dict[str, Any] | None = None,
) -> CodexInvocation:
    detected = capabilities if capabilities is not None else detect_codex_capabilities()
    supports = detected.get("supports", {})
    warnings: list[str] = []
    if not detected.get("help_available", False):
        detail = detected.get("help_error") or "unknown error"
        warnings.append(f"Could not inspect `codex exec --help` ({detail}); only stdin sentinel and subprocess cwd are assumed.")

    args = ["codex", "exec"]
    cwd: Path | None = None
    resolved_root = repo_root.resolve()
    cd_strategy = "subprocess_cwd"
    if supports.get("cd_short"):
        args.extend(["-C", str(resolved_root)])
        cd_strategy = "-C"
    elif supports.get("cd_long"):
        args.extend(["--cd", str(resolved_root)])
        cd_strategy = "--cd"
    else:
        cwd = resolved_root
        warnings.append("Codex CLI help does not advertise -C or --cd; running subprocess with cwd=repo_root.")

    approval_strategy = "omitted"
    if options.sandbox:
        if supports.get("sandbox"):
            args.extend(["--sandbox", options.sandbox])
        else:
            _warn_unsupported(warnings, "--sandbox")
    if options.approval:
        if supports.get("approval_mode"):
            args.extend(["--approval-mode", options.approval])
            approval_strategy = "--approval-mode"
        elif supports.get("ask_for_approval"):
            args.extend(["--ask-for-approval", options.approval])
            approval_strategy = "--ask-for-approval"
        else:
            warnings.append("Codex CLI help does not advertise --approval-mode or --ask-for-approval; approval mode omitted.")
    if options.ephemeral:
        if supports.get("ephemeral"):
            args.append("--ephemeral")
        else:
            _warn_unsupported(warnings, "--ephemeral")
    if options.json:
        if supports.get("json"):
            args.append("--json")
        else:
            _warn_unsupported(warnings, "--json")
    if options.output_last_message:
        if supports.get("output_last_message"):
            args.extend(["--output-last-message", options.output_last_message])
        else:
            _warn_unsupported(warnings, "--output-last-message")
    schema = options.output_schema
    if options.structured_final_report and not schema:
        schema = default_schema_path(repo_root)
    if schema:
        if supports.get("output_schema"):
            args.extend(["--output-schema", schema])
        else:
            _warn_unsupported(warnings, "--output-schema")
    if options.codex_profile:
        if supports.get("profile"):
            args.extend(["--profile", options.codex_profile])
        else:
            _warn_unsupported(warnings, "--profile")
    for p in options.add_dir:
        if supports.get("add_dir"):
            args.extend(["--add-dir", p])
        else:
            _warn_unsupported(warnings, "--add-dir")
    if options.skip_git_repo_check:
        if supports.get("skip_git_repo_check"):
            args.append("--skip-git-repo-check")
        else:
            _warn_unsupported(warnings, "--skip-git-repo-check")
    if options.model:
        if supports.get("model"):
            args.extend(["--model", options.model])
        else:
            _warn_unsupported(warnings, "--model")
    if options.oss:
        if supports.get("oss"):
            args.append("--oss")
        else:
            _warn_unsupported(warnings, "--oss")
    args.append("-")
    capability_record = {**detected, "cd_strategy": cd_strategy, "approval_strategy": approval_strategy}
    return CodexInvocation(args=args, cwd=cwd, capabilities=capability_record, warnings=warnings)


def build_codex_args(repo_root: Path, options: CodexOptions, capabilities: dict[str, Any] | None = None) -> list[str]:
    args = build_codex_invocation(repo_root, options, capabilities).args
    return args


def validate_codex_args(args: list[str], raw_prompt: str) -> None:
    if not args or args[-1] != "-":
        raise AssertionError("Codex args must end with stdin prompt sentinel '-'.")
    if raw_prompt and any(raw_prompt == arg or raw_prompt in arg for arg in args):
        raise AssertionError("Raw prompt leaked into subprocess args.")
    # For codex exec, the only non-flag positional after the subcommand must be '-'.
    # Values for known flags are skipped.
    value_flags = {
        "-C", "--cd", "--sandbox", "-s", "--approval-mode", "--ask-for-approval", "-a", "--output-last-message", "-o",
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
        context_only=options.context_only,
        record_artifacts=options.record,
    )
    packet = compiled["packet"]
    if packet == raw_prompt:
        raise AssertionError("Compiled packet must not equal raw prompt.")
    external_payload = None
    if options.record:
        external_payload = write_external_payload_manifest(
            repo=repo_root,
            packet=packet,
            compiled=compiled,
            lane=options.lane,
            repo_is_private=options.repo_is_private,
            private_paths_forbidden=options.private_paths_forbidden,
        )
    invocation = build_codex_invocation(repo_root, options)
    args = invocation.args
    validate_codex_args(args, raw_prompt)
    command_record = {
        "args": args,
        "cwd": str(invocation.cwd) if invocation.cwd else None,
        "stdin_sha256": sha256_text(packet),
        "dry_run": options.dry_run,
        "codex_capabilities": invocation.capabilities,
        "codex_warnings": invocation.warnings,
        "external_payload_manifest": external_payload["manifest_path"] if external_payload else None,
        "external_launch_allowed": (external_payload["manifest"]["launch_allowed"] if external_payload else None),
    }
    if options.dry_run:
        output = {
            "command": args,
            "command_cwd": str(invocation.cwd) if invocation.cwd else None,
            "stdin": "<compiled-packet-on-stdin>",
            "compiled_packet_sha256": sha256_text(packet),
            "raw_prompt_sha256": sha256_text(raw_prompt),
            "codex_capabilities": invocation.capabilities,
            "codex_warnings": invocation.warnings,
            "compile_settings": {
                "profile": effective_profile,
                "use_repo_map": options.use_repo_map,
                "cache_optimized": options.cache_optimized,
                "packet_version": compiled.get("packet_version"),
                "save": options.save,
                "context_only": options.context_only,
                "record": options.record,
            },
            "saved_artifacts": compiled.get("saved_artifacts"),
            "external_payload_manifest": external_payload["manifest_path"] if external_payload else None,
            "external_launch_allowed": (external_payload["manifest"]["launch_allowed"] if external_payload else None),
        }
        if options.show_raw:
            output["raw_prompt"] = raw_prompt
        if options.record:
            write_audit(repo_root, "codex_dry_run", sha256_text(raw_prompt), command_record)
            append_metric(repo_root, {"event": "codex_dry_run", "raw_prompt_sha256": sha256_text(raw_prompt), "estimated_input_bytes": len(packet.encode()), "actual_usage": None})
        return output

    if external_payload and not external_payload["manifest"]["launch_allowed"]:
        blocked = {
            "args": args,
            "cwd": str(invocation.cwd) if invocation.cwd else None,
            "returncode": 2,
            "stdout": "",
            "stderr": "External Codex launch blocked by external_payload_manifest policy.",
            "actual_usage": None,
            "codex_capabilities": invocation.capabilities,
            "codex_warnings": invocation.warnings,
            "external_payload_manifest": external_payload["manifest_path"],
            "external_launch_allowed": False,
            "external_launch_block_reasons": external_payload["manifest"].get("block_reasons") or [],
        }
        if options.record:
            write_audit(repo_root, "codex_execute_blocked", sha256_text(raw_prompt), {**command_record, **blocked})
            append_metric(repo_root, {
                "event": "codex_execute_blocked",
                "raw_prompt_sha256": sha256_text(raw_prompt),
                "estimated_input_bytes": len(packet.encode()),
                "actual_usage": None,
                "returncode": 2,
                "external_launch_block_reasons": blocked["external_launch_block_reasons"],
            })
        return blocked

    if options.watch:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, cwd=invocation.cwd)
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
        completed = subprocess.run(args, input=packet, text=True, capture_output=True, check=False, cwd=invocation.cwd)
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr

    actual_usage = _extract_usage_from_jsonl(stdout)
    if options.record:
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
    return {
        "args": args,
        "cwd": str(invocation.cwd) if invocation.cwd else None,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "actual_usage": actual_usage,
        "codex_capabilities": invocation.capabilities,
        "codex_warnings": invocation.warnings,
        "external_payload_manifest": external_payload["manifest_path"] if external_payload else None,
        "external_launch_allowed": (external_payload["manifest"]["launch_allowed"] if external_payload else None),
    }


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
