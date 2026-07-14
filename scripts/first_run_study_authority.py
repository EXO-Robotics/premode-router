#!/usr/bin/env python3
"""Trusted, source-bound authorities for the private first-run study kit."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LEGACY_COMMIT = "99ebc95c9db7f40333c661743920485e0d45c134"  # pragma: allowlist secret
LEGACY_PATHS = (
    ".agents/plugins/plugins/premode-router",
    ".agents/skills/pcodex",
    ".agents/skills/pcodex-dry-run",
    ".agents/skills/pcodex-status",
    ".agents/skills/pcodex-tune",
)
ARTIFACT_HASH_CODE = (
    "import hashlib,pathlib,sys; "
    "print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())"
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_digest(value: object) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _digest(data)


def validated_executable(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise RuntimeError(f"--{label} must not be a symlink")
    executable = path.resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"--{label} must be an absolute executable file")
    if not path.is_absolute():
        raise RuntimeError(f"--{label} must be absolute")
    return executable


def executable_authority(path: Path, label: str) -> dict[str, str]:
    executable = validated_executable(path, label)
    return {"path": str(executable), "sha256": _digest(executable.read_bytes())}


def _git(executable: Path, *args: str) -> bytes:
    executable = validated_executable(executable, "git")
    completed = subprocess.run(
        (str(executable), *args),
        cwd=ROOT,
        env={
            "HOME": "/dev/null",
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        },
        capture_output=True,
        check=True,
        timeout=30,
    )
    return completed.stdout


def expected_fixture_members(fixture_id: str, git_executable: Path) -> dict[str, str]:
    members: dict[str, bytes] = {"README.md": f"# {fixture_id}\n".encode()}
    if fixture_id == "fixture-02":
        members[".agents/unrelated/README.md"] = b"unrelated user state\n"
    elif fixture_id == "fixture-03":
        members["fixture-codex-home/config.toml"] = (
            b'model = "preserve-me"\n[unknown]\nvalue = true\n'
        )
    elif fixture_id == "fixture-04":
        names = (
            _git(
                git_executable,
                "ls-tree",
                "-r",
                "--name-only",
                LEGACY_COMMIT,
                "--",
                *LEGACY_PATHS,
            )
            .decode("utf-8")
            .splitlines()
        )
        for name in names:
            members[name] = _git(git_executable, "show", f"{LEGACY_COMMIT}:{name}")
    elif fixture_id == "fixture-05":
        members["fixture-codex-home/config.toml"] = (
            b'# preserve formatting and unrelated MCP\n[mcp_servers.unrelated]\ncommand = "/usr/bin/true"\n'
        )
    elif fixture_id != "fixture-01":
        raise ValueError(f"unknown first-run fixture: {fixture_id}")
    return {name: _digest(data) for name, data in sorted(members.items())}


def expected_fixture_surfaces(
    fixture_id: str, git_executable: Path
) -> list[dict[str, str]]:
    members = expected_fixture_members(fixture_id, git_executable)
    if fixture_id == "fixture-01":
        definitions = [("repository_readme", "README.md", "file_bytes")]
    elif fixture_id == "fixture-02":
        definitions = [
            ("unrelated_agents", ".agents/unrelated", "directory_manifest"),
            ("dirty_untracked", "dirty-untracked.txt", "post_restore_file_bytes"),
        ]
    elif fixture_id == "fixture-03":
        definitions = [
            (
                "unrelated_codex_config",
                "fixture-codex-home/config.toml",
                "file_bytes",
            )
        ]
    elif fixture_id == "fixture-04":
        definitions = [("repository_readme", "README.md", "file_bytes")]
    elif fixture_id == "fixture-05":
        definitions = [
            (
                "unrelated_mcp_config",
                "fixture-codex-home/config.toml",
                "file_bytes",
            )
        ]
    else:
        raise ValueError(f"unknown first-run fixture: {fixture_id}")
    result: list[dict[str, str]] = []
    for name, relative, kind in definitions:
        if kind == "file_bytes":
            initial = members[relative]
        elif kind == "post_restore_file_bytes":
            initial = _digest(b"must remain unrelated\n")
        else:
            prefix = relative.rstrip("/") + "/"
            entries = [
                {"path": path[len(prefix) :], "sha256": digest}
                for path, digest in sorted(members.items())
                if path.startswith(prefix)
            ]
            initial = _canonical_digest(entries)
        result.append(
            {
                "name": name,
                "relative_path": relative,
                "measurement_kind": kind,
                "initial_sha256": initial,
            }
        )
    return result


def operation_command(operation: str) -> str:
    fixed = {
        "artifact_verify": f"<ABSOLUTE_PYTHON> -c '{ARTIFACT_HASH_CODE}' <PAYLOAD_WHEEL>",
        "venv_create": "<ABSOLUTE_PYTHON> -m venv <VENV>",
        "package_install": "<VENV>/bin/python -m pip install --no-index --no-deps <PAYLOAD_WHEEL>",
        "help": "pcodex --help",
        "doctor_advisory": "pcodex doctor --advisory --json",
        "status_advisory": "pcodex status --advisory --json",
        "run_dry_run": 'pcodex run --dry-run "Fix the failing test" --json',
        "managed_install_preview": "pcodex install --json",
        "managed_install_apply": "pcodex install --apply --json",
        "managed_uninstall_preview": "pcodex uninstall --dry-run --json",
        "managed_uninstall_apply": "pcodex uninstall --yes --json",
    }
    if operation in fixed:
        return fixed[operation]
    flags = {
        "codex_preview": "--dry-run",
        "codex_install": "--write",
        "codex_status": "--status",
        "codex_install_idempotent": "--write",
        "codex_repair_preview": "--repair --dry-run",
        "codex_disable": "--disable",
        "codex_reenable": "--repair",
        "codex_uninstall_preview": "--uninstall --dry-run",
        "codex_uninstall_apply": "--uninstall",
        "codex_reinstall": "--write",
        "codex_status_final": "--status",
        "codex_final_uninstall": "--uninstall",
        "missing_codex_status": "--status",
        "migration_preview": "--dry-run --migrate",
        "migration_apply": "--write --migrate",
        "mcp_preview": "--dry-run --with-mcp",
        "mcp_apply": "--write --with-mcp",
        "mcp_status": "--status",
        "mcp_install_idempotent": "--write --with-mcp",
        "mcp_disable": "--disable",
        "mcp_repair_preview": "--repair --dry-run",
        "mcp_repair": "--repair",
        "mcp_uninstall_preview": "--uninstall --dry-run",
        "mcp_uninstall_apply": "--uninstall",
        "mcp_reinstall": "--write --with-mcp",
        "mcp_final_uninstall": "--uninstall",
    }
    return f"pcodex integrate codex {flags[operation]} --json"


def task_card_text(fixture_id: str, operations: list[str]) -> str:
    commands = "\n".join(
        f"{index}. `{operation_command(operation)}`"
        for index, operation in enumerate(operations, start=1)
    )
    controlled_path = (
        "<VENV>/bin:/usr/bin:/bin"
        if fixture_id == "fixture-01"
        else "<VENV>/bin:<SANDBOX>/bin:/usr/bin:/bin"
    )
    return (
        f"# Blind first-run journey: {fixture_id}\n\n"
        "This frozen task card is part of the study payload, not undocumented coaching.\n"
        "Replace only the angle-bracket paths supplied by the coordinator.\n\n"
        "Before every command, the coordinator must create one private sandbox and export:\n\n"
        "```console\n"
        "HOME=<SANDBOX>/home\nXDG_CONFIG_HOME=<SANDBOX>/xdg-config\n"
        "XDG_CACHE_HOME=<SANDBOX>/xdg-cache\nXDG_DATA_HOME=<SANDBOX>/xdg-data\n"
        "TMPDIR=<SANDBOX>/tmp\nCODEX_HOME=<SANDBOX>/codex-home\n"
        f"PATH={controlled_path}\nexport HOME XDG_CONFIG_HOME XDG_CACHE_HOME XDG_DATA_HOME TMPDIR CODEX_HOME PATH\n"
        "```\n\n"
        "Run these commands in order and do not substitute another pCodex executable:\n\n"
        f"{commands}\n"
    )


def runbook_text() -> str:
    return """# First-Run Coordinator Runbook

Give each tester the blind payload, exactly one frozen task card, and the restored repository. This assignment is protocol material, not coaching.

Create a fresh private sandbox for every tester and restore the repository beneath it. Create its HOME, XDG_CONFIG_HOME, XDG_CACHE_HOME, XDG_DATA_HOME, TMPDIR, and CODEX_HOME directories. For supported-Codex fixtures, create only the recorder-managed sandboxed Codex wrapper and insert its directory between the installed study venv and `/usr/bin:/bin` in PATH. Refuse to continue if a controlled path escapes the sandbox or if `pcodex` does not resolve to `<VENV>/bin/pcodex`.

Use the copied `record_first_run_study.py` only. Preassign the five session files as `<fixture-id>.session.json` in one empty private 0700 session directory. Keep the HMAC-chained `attempt-ledger.jsonl` in a different coordinator-owned 0700 directory and run tester journeys sequentially. A failed or interrupted session and its ledger history are retained under that authority; do not delete or replace either. The coordinator and HMAC-key holder are the study trust anchor, so archive the completed ledger with private evidence and obtain an external digest witness before using the study for a release claim.

Use these exact controller commands, replacing only angle-bracket values. Omit `--codex` for fixture-01; supply the absolute Codex 0.143.x path for fixtures 02 through 05.

```console
<PYTHON> -B <COORDINATOR>/record_first_run_study.py init --session <SESSION_DIR>/<FIXTURE_ID>.session.json --study-kit <COORDINATOR>/study-kit.json --study-kit-sha256 <STUDY_KIT_SHA256> --fixture <FIXTURE_ID> --tester-id <TESTER_ID> --repository <RESTORED_REPOSITORY> --venv <SANDBOX>/venv --sandbox <SANDBOX> --codex <CODEX_0_143_PATH> --attestation-key <HMAC_KEY> --attempt-ledger <PRIVATE_AUTHORITY>/attempt-ledger.jsonl
<PYTHON> -B <COORDINATOR>/record_first_run_study.py run-next --session <SESSION_DIR>/<FIXTURE_ID>.session.json --operation <NEXT_OPERATION> --attestation-key <HMAC_KEY>
<PYTHON> -B <COORDINATOR>/record_first_run_study.py build-review-manifest --session <SESSION_DIR>/<FIXTURE_ID>.session.json --output <PRIVATE_REVIEW_DIR>/<FIXTURE_ID>.review.json --signer-id <COORDINATOR_SIGNER_ID> --attestation-key <HMAC_KEY>
<PYTHON> -B <COORDINATOR>/record_first_run_study.py review --session <SESSION_DIR>/<FIXTURE_ID>.session.json --review-manifest <PRIVATE_REVIEW_DIR>/<FIXTURE_ID>.review.json --attestation-key <HMAC_KEY>
<PYTHON> -B <COORDINATOR>/record_first_run_study.py finalize --session <SESSION_DIR>/<FIXTURE_ID>.session.json --output <ABSENT_PRIVATE_OUTPUT_DIR> --attestation-key <HMAC_KEY>
```

Repeat `run-next` only with the exact next operation printed by the recorder until it reports the journey complete. The generated review manifest deliberately contains `false` approvals and an incomplete documentation finding. After inspecting every bound stream, condition, and preservation measurement, the coordinator records the tester's actual help, failure, and documentation outcomes, changes only genuinely approved entries, and then submits it to `review`.

If a session becomes `failed_closed`, retain it and the ledger and count that assigned activation as failed; do not retry. If finalization is interrupted after the state becomes `finalizing`, rerun `finalize` with the identical absolute output path. Any other authority mismatch fails closed and requires preservation for manual audit, not deletion.

Initialize one HMAC-protected private session, require the tester to confirm each task-card operation with `run-next`, complete exact per-stream sensitivity review, and finalize the receipt last. Never hand-edit session state, evidence, attestations, receipts, or the attempt ledger.

The recorder's before/after filesystem digest is supplemental first-run drift evidence. It does not replace the release qualification's literal no-write monitor, transient-write detection, or forbidden-process-launch checks, and must not be cited as G2/G5 no-write proof.

Restore the assigned fixture with the exact restore_argv in study-kit.json. Keep evidence, receipts, the witness HMAC key, and coordinator files outside the study-kit root. Hash every preservation surface at every required checkpoint. Never use the tester's real HOME, XDG, Codex, MCP, or package state.

Fixture notes:
- fixture-01: Codex must be unavailable inside the controlled PATH.
- fixture-02: `git status --porcelain` must show only the frozen unrelated dirty file.
- fixture-03: the sandboxed CODEX_HOME must preserve the fixture's unrelated config bytes.
- fixture-04: restore to a repository path containing spaces and Unicode.
- fixture-05: use only the task card's explicit optional-MCP commands.
"""
