#!/usr/bin/env python3
"""Statically validate canonical product documentation without executing examples."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import shlex
import sys
from typing import Any


SHELL_FENCES = {"bash", "console", "sh", "shell", "zsh"}
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
FENCE = re.compile(r"^```([^\s`]*)\s*$")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
BACKTICK_FILE = re.compile(
    r"`((?:README\.md|premode\.(?:product|ai)\.json|(?:docs|schemas|scripts|plugins)/[^`\s]+))`"
)
BACKTICK_STATE = re.compile(
    r"`((?:\$HOME/)?\.(?:premode|pcodex(?:-alpha|-beta)?)(?:/[^`\s]*)?)`"
)
CANONICAL_DOCS = [
    "README.md",
    "docs/GETTING_STARTED.md",
    "docs/CODEX_INTEGRATION.md",
    "docs/OPENCLAW_INTEGRATION.md",
    "docs/TROUBLESHOOTING.md",
    "docs/PRIVACY_AND_SAFETY.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/MIGRATION.md",
    "docs/ROLLBACK.md",
    "docs/UNINSTALL.md",
]
EXTERNAL_COMMANDS = {"codex", "openclaw", "pipx", "export", "python", "python3"}
CHECKSUM_CODE = "import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); print(hashlib.sha256(p.read_bytes()).hexdigest())"

# Make the advertised source-checkout invocation independent of an editable install.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
source_package = str(SOURCE_ROOT / "src")
if source_package not in sys.path:
    sys.path.insert(0, source_package)


def _parser_options(parser: argparse.ArgumentParser) -> set[str]:
    options: set[str] = set()
    for action in parser._actions:
        options.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                options.update(_parser_options(child))
    return options


def _parse_without_output(
    parser: argparse.ArgumentParser, argv: list[str]
) -> tuple[Any | None, str | None]:
    sink = io.StringIO()
    try:
        with redirect_stdout(sink), redirect_stderr(sink):
            return parser.parse_args(argv), None
    except SystemExit as exc:
        if int(exc.code or 0) == 0:
            return None, None
        detail = sink.getvalue().strip().splitlines()
        return None, detail[-1] if detail else "argument parsing failed"


def _validate_cli_command(tokens: list[str]) -> list[str]:
    if not tokens or tokens[0] not in {"pcodex", "premode"}:
        return []

    from premode.cli import build_parser as build_premode_parser
    from premode.pcodex_bootstrap import (
        _parser as build_pcodex_parser,
        validate_pcodex_namespace,
    )

    parser = build_pcodex_parser() if tokens[0] == "pcodex" else build_premode_parser()
    failures: list[str] = []
    allowed_options = _parser_options(parser)
    for token in tokens[1:]:
        if token.startswith("--"):
            option = token.split("=", 1)[0]
            if option not in allowed_options:
                failures.append(f"unknown or abbreviated option {option}")
    namespace, parse_error = _parse_without_output(parser, tokens[1:])
    if parse_error:
        failures.append(parse_error)
    elif namespace is not None and tokens[0] == "pcodex":
        failures.extend(validate_pcodex_namespace(namespace))
    return failures


def _fenced_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    language: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        match = FENCE.match(line)
        if match:
            if language is None:
                language = match.group(1).lower()
                body = []
            else:
                blocks.append((language, "\n".join(body)))
                language = None
                body = []
            continue
        if language is not None:
            body.append(line)
    if language is not None:
        raise ValueError(f"unclosed {language or 'plain'} fenced block")
    return blocks


def _shell_commands(body: str) -> list[list[str]]:
    commands: list[list[str]] = []
    logical_lines: list[str] = []
    pending = ""
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append(pending)
        pending = ""
    if pending:
        logical_lines.append(pending)

    for line in logical_lines:
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            lexer.commenters = "#"
            tokens = list(lexer)
        except ValueError:
            commands.append(["<invalid-shell>", line])
            continue
        while tokens and ASSIGNMENT.match(tokens[0]):
            tokens.pop(0)
        if tokens:
            commands.append(tokens)
    return commands


def _contained_regular_file(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path is absolute or contains traversal")
    path = root / candidate
    if path.is_symlink():
        raise ValueError("symbolic links are not accepted")
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("resolved path escapes repository")
    if not resolved.is_file():
        raise ValueError("file is missing or is not regular")
    return resolved


def _validate_shell_command(tokens: list[str], root: Path) -> list[str]:
    failures: list[str] = []
    operators = {";", "&&", "&", "||", "|", "<", ">", "<<", ">>"}
    if any(token in operators for token in tokens):
        return ["compound commands and shell redirections are not canonical"]
    command = tokens[0]
    if command in {"pcodex", "premode"}:
        return _validate_cli_command(tokens)
    if command.startswith("scripts/"):
        try:
            _contained_regular_file(root, command)
        except ValueError as exc:
            failures.append(f"invalid script command {command}: {exc}")
        if command == "scripts/install_pcodex_from_source.sh":
            unsupported = [
                value for value in tokens[1:] if value not in {"--uninstall"}
            ]
            if unsupported:
                failures.append(
                    f"unsupported source-installer arguments: {' '.join(unsupported)}"
                )
        return failures
    installed_python = command == "$HOME/.pcodex-beta/bin/python"
    if command not in EXTERNAL_COMMANDS and not installed_python:
        return [f"unknown documented executable: {command}"]
    if command == "codex" and tokens[1:] != ["--version"]:
        failures.append(
            "only the declared codex --version documentation probe is accepted"
        )
    if command == "openclaw" and tokens[1:] not in (
        ["--version"],
        ["config", "validate", "--json"],
        ["mcp", "show", "pcodex", "--json"],
    ):
        failures.append("unsupported canonical OpenClaw command shape")
    if command == "pipx":
        supported = (
            len(tokens) == 4
            and tokens[1] == "install"
            and tokens[2].endswith("premode_router-0.3.0b1-py3-none-any.whl")
            and tokens[3] == "--pip-args=--no-index --no-deps"
        )
        if not supported:
            failures.append(
                "only the exact offline local-wheel pipx install is accepted"
            )
    if command == "export" and tokens[1:] not in (
        ["PATH=$HOME/.pcodex-beta/bin:$PATH"],
        ["PATH=$HOME/.pcodex-alpha/bin:$PATH"],
    ):
        failures.append(
            "only an exact declared pCodex install-root PATH export is accepted"
        )
    if command == "python":
        supported = {
            ("-m", "pytest", "-q"),
            ("scripts/check_public_hygiene.py", "--json"),
            ("scripts/validate_documentation.py", "--root", ".", "--json"),
        }
        if tuple(tokens[1:]) not in supported:
            failures.append("unsupported canonical python command shape")
    elif command == "python3":
        supported = (
            tokens[1:] == ["--version"]
            or tokens[1:] == ["-m", "venv", "$HOME/.pcodex-beta"]
            or (
                len(tokens) == 4
                and tokens[1] == "-c"
                and tokens[2] == CHECKSUM_CODE
                and tokens[3].endswith("premode_router-0.3.0b1-py3-none-any.whl")
            )
        )
        if not supported:
            failures.append("unsupported canonical python3 command shape")
    elif installed_python:
        supported = (
            len(tokens) == 7
            and tokens[1:6] == ["-m", "pip", "install", "--no-index", "--no-deps"]
            and tokens[6].endswith((".whl", "authorized-replacement.whl"))
        ) or tokens[1:] == ["-m", "pip", "uninstall", "premode-router"]
        if not supported:
            failures.append("unsupported invited-beta Python command shape")
    for token in tokens[1:]:
        if token.startswith("scripts/"):
            try:
                _contained_regular_file(root, token)
            except ValueError as exc:
                failures.append(f"invalid Python script {token}: {exc}")
    return failures


def _validate_json_example(root: Path, payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["JSON example must be an object"]
    schema_ref = payload.get("$schema")
    if not isinstance(schema_ref, str):
        return ["JSON example has no local $schema"]
    schema_path = (root / schema_ref.removeprefix("./")).resolve()
    if root.resolve() not in schema_path.parents or not schema_path.is_file():
        return [
            f"JSON example schema does not exist inside the repository: {schema_ref}"
        ]
    try:
        from jsonschema import Draft202012Validator

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema).iter_errors(payload),
            key=lambda item: list(item.path),
        )
    except (ImportError, json.JSONDecodeError, OSError) as exc:
        return [f"could not validate JSON example: {exc}"]
    return [error.message for error in errors]


def validate_documentation(root: Path) -> dict[str, Any]:
    root = root.resolve()
    failures: list[dict[str, str]] = []
    manifest_path = root / "premode.product.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        contract = manifest["documentation_contract"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return {
            "schema_version": "pcodex.documentation-validation.v1",
            "status": "failed",
            "failures": [{"path": "premode.product.json", "message": str(exc)}],
        }

    if contract.get("canonical_docs") != CANONICAL_DOCS:
        failures.append(
            {
                "path": "premode.product.json",
                "message": "canonical_docs must equal the authoritative ordered set",
            }
        )
    canonical_paths: list[tuple[str, Path]] = []
    for relative in contract.get("canonical_docs", []):
        try:
            canonical_paths.append((relative, _contained_regular_file(root, relative)))
        except ValueError as exc:
            failures.append(
                {"path": relative, "message": f"unsafe canonical document: {exc}"}
            )
    extracted: set[tuple[str, ...]] = set()
    checked_commands = 0
    checked_json = 0

    declared_state = [
        part.strip()
        for entry in manifest.get("stateful_surface_inventory", [])
        for part in str(entry.get("location", "")).split(" and ")
        if part.strip()
    ]
    for relative, path in canonical_paths:
        text = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            target = target.strip("<>").split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            try:
                link_relative = (path.parent / target).relative_to(root)
                _contained_regular_file(root, link_relative.as_posix())
            except (ValueError, OSError) as exc:
                failures.append(
                    {
                        "path": relative,
                        "message": f"invalid linked file {target}: {exc}",
                    }
                )

        for target in BACKTICK_FILE.findall(text):
            try:
                _contained_regular_file(root, target.rstrip(".,;:"))
            except ValueError as exc:
                directory = root / target.rstrip(".,;:")
                resolved = directory.resolve()
                if (
                    directory.is_symlink()
                    or not directory.is_dir()
                    or (resolved != root and root not in resolved.parents)
                ):
                    failures.append(
                        {
                            "path": relative,
                            "message": f"invalid referenced file {target}: {exc}",
                        }
                    )
        for target in BACKTICK_STATE.findall(text):
            normalized = target.rstrip("/")
            if not any(
                normalized == item.rstrip("/")
                or normalized.startswith(item.rstrip("/") + "/")
                or item.rstrip("/").startswith(normalized + "/")
                for item in declared_state
            ):
                failures.append(
                    {
                        "path": relative,
                        "message": f"undeclared generated/state path: {target}",
                    }
                )

        try:
            blocks = _fenced_blocks(text)
        except ValueError as exc:
            failures.append({"path": relative, "message": str(exc)})
            blocks = []
        for language, body in blocks:
            if language in SHELL_FENCES:
                for tokens in _shell_commands(body):
                    checked_commands += 1
                    if tokens[0] == "<invalid-shell>":
                        failures.append(
                            {
                                "path": relative,
                                "message": f"invalid shell example: {tokens[1]}",
                            }
                        )
                        continue
                    extracted.add(tuple(tokens))
                    for error in _validate_shell_command(tokens, root):
                        failures.append(
                            {
                                "path": relative,
                                "message": f"{' '.join(tokens)}: {error}",
                            }
                        )
            elif language == "json":
                checked_json += 1
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError as exc:
                    failures.append(
                        {"path": relative, "message": f"invalid JSON example: {exc}"}
                    )
                    continue
                for error in _validate_json_example(root, payload):
                    failures.append({"path": relative, "message": error})

    for journey, commands in contract["required_journeys"].items():
        for command in commands:
            try:
                tokens = tuple(shlex.split(command))
            except ValueError as exc:
                failures.append(
                    {"path": "premode.product.json", "message": f"{journey}: {exc}"}
                )
                continue
            if tokens not in extracted:
                failures.append(
                    {
                        "path": "premode.product.json",
                        "message": f"required {journey} command is not canonical: {command}",
                    }
                )

    version_checks = {
        "docs/GETTING_STARTED.md": [
            contract["current_product_version"],
            *contract["supported_codex_versions"],
        ],
        "docs/CODEX_INTEGRATION.md": contract["supported_codex_versions"],
        "docs/KNOWN_LIMITATIONS.md": [
            *contract["supported_codex_versions"],
            *contract["supported_openclaw_versions"],
        ],
        "docs/OPENCLAW_INTEGRATION.md": contract["supported_openclaw_versions"],
        "docs/MIGRATION.md": contract["declared_legacy_product_versions"],
    }
    for relative, versions in version_checks.items():
        text = (
            (root / relative).read_text(encoding="utf-8")
            if (root / relative).is_file()
            else ""
        )
        for version in versions:
            if version not in text:
                failures.append(
                    {
                        "path": relative,
                        "message": f"required version reference is missing: {version}",
                    }
                )

    failures.sort(key=lambda item: (item["path"], item["message"]))
    return {
        "schema_version": "pcodex.documentation-validation.v1",
        "status": "passed" if not failures else "failed",
        "canonical_documents": len(canonical_paths),
        "shell_commands_checked": checked_commands,
        "json_examples_checked": checked_json,
        "failures": failures,
        "execution_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = validate_documentation(args.root)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["status"] == "passed":
        print(
            f"documentation validation passed ({result['canonical_documents']} documents)"
        )
    else:
        for failure in result["failures"]:
            print(f"{failure['path']}: {failure['message']}", file=sys.stderr)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
