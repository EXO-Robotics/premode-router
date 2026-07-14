#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import gzip
from fnmatch import fnmatch
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "release" / "artifact-allowlist.json"
LEGACY_FIXTURE_COMMIT = "99ebc95c9db7f40333c661743920485e0d45c134"
LEGACY_FIXTURE_PATHS = (
    ".agents/plugins/plugins/premode-router",
    ".agents/skills/pcodex",
    ".agents/skills/pcodex-dry-run",
    ".agents/skills/pcodex-status",
    ".agents/skills/pcodex-tune",
)


def run(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(args)}\n{completed.stderr.strip()}")
    return completed.stdout.strip()


def validated_python_interpreter(value: str) -> str:
    """Return one absolute, executable Python >=3.11 path.

    The release build changes working directories repeatedly.  Accepting a
    relative interpreter therefore makes an otherwise valid build depend on
    the current phase of the builder.
    """
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise RuntimeError("--python must be an absolute interpreter path")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeError(f"Python interpreter is missing or not executable: {candidate}")
    completed = subprocess.run(
        [str(candidate), "-c", "import json,sys; print(json.dumps(list(sys.version_info[:2])))"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    try:
        version = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Python interpreter validation returned malformed output") from exc
    if completed.returncode or not isinstance(version, list) or tuple(version) < (3, 11):
        raise RuntimeError("release builds require a working Python 3.11 or newer interpreter")
    return str(candidate)


def run_json_probe(
    *args: str,
    output: Path,
    label: str,
    cwd: Path,
    env: dict[str, str],
) -> tuple[dict[str, object], int]:
    """Run one installed-artifact probe and preserve evidence before failure."""
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        write_json(output / "private-receipts" / "probe-execution" / f"{label}.json", {
            "schema_version": "pcodex.probe-execution.private.v1",
            "label": label,
            "result": "execution_error",
            "error_type": type(exc).__name__,
        })
        write_json(output / "receipts" / "probe-execution" / f"{label}.json", {
            "schema_version": "pcodex.probe-execution.v1",
            "label": label,
            "result": "execution_error",
            "error_type": type(exc).__name__,
        })
        raise RuntimeError(f"{label} probe could not execute: {type(exc).__name__}") from exc
    stdout_hash = hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest()
    stderr_hash = hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest()
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        payload = None
    parsed = isinstance(payload, dict)
    private_receipt = {
        "schema_version": "pcodex.probe-execution.private.v1",
        "label": label,
        "returncode": completed.returncode,
        "stdout_sha256": stdout_hash,
        "stderr_sha256": stderr_hash,
        "payload_parsed": parsed,
        "payload": payload if parsed else None,
        "stderr": completed.stderr,
        "result": "passed" if completed.returncode == 0 and parsed and payload.get("passed") is True else "failed",
    }
    public_receipt = {
        "schema_version": "pcodex.probe-execution.v1",
        "label": label,
        "returncode": completed.returncode,
        "stdout_sha256": stdout_hash,
        "stderr_sha256": stderr_hash,
        "payload_parsed": parsed,
        "payload_schema_version": payload.get("schema_version") if parsed else None,
        "payload_passed": payload.get("passed") if parsed else None,
        "result": private_receipt["result"],
    }
    write_json(output / "private-receipts" / "probe-execution" / f"{label}.json", private_receipt)
    write_json(output / "receipts" / "probe-execution" / f"{label}.json", public_receipt)
    if not parsed:
        raise RuntimeError(
            f"{label} probe returned non-JSON output ({completed.returncode}); "
            f"failure evidence was preserved"
        )
    return payload, completed.returncode


def require_probe_passed(label: str, payload: dict[str, object], returncode: int) -> None:
    if returncode or payload.get("passed") is not True:
        raise RuntimeError(f"{label} probe failed; structured evidence was preserved")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def members(path: Path) -> list[str]:
    if path.suffix == ".whl" or path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            return sorted(item.filename for item in archive.infolist() if not item.is_dir())
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            return sorted(item.name for item in archive.getmembers() if item.isfile())
    return [path.name]


def validate_names(names: list[str], *, allowed_prefixes: list[str], policy: dict[str, object], exact_wheel: bool = False) -> list[str]:
    failures: list[str] = []
    prohibited_parts = {str(item).lower() for item in policy["prohibited_parts"]}
    prohibited_suffixes = tuple(str(item).lower() for item in policy["prohibited_suffixes"])
    prohibited_globs = tuple(str(item) for item in policy.get("wheel_prohibited_globs", []))
    exact_members = {str(item) for item in policy.get("wheel_allowed_members", [])}
    exact_globs = tuple(str(item) for item in policy.get("wheel_allowed_globs", []))
    for name in names:
        normalized = PurePosixPath(name).as_posix().lstrip("./")
        lowered_parts = {part.lower() for part in PurePosixPath(normalized).parts}
        if lowered_parts & prohibited_parts or normalized.lower().endswith(prohibited_suffixes):
            failures.append(f"prohibited:{normalized}")
        if any(fnmatch(normalized, pattern) for pattern in prohibited_globs):
            failures.append(f"prohibited_glob:{normalized}")
        if allowed_prefixes and not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
            failures.append(f"not_allowed:{normalized}")
        if exact_wheel and normalized not in exact_members and not any(fnmatch(normalized, pattern) for pattern in exact_globs):
            failures.append(f"unexpected_wheel_member:{normalized}")
        if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
            failures.append(f"unsafe_path:{normalized}")
    return failures


def validate_sdist_names(names: list[str], policy: dict[str, object]) -> list[str]:
    """Default-deny sdist members after stripping the generated archive root."""
    relative_names = []
    for name in names:
        parts = PurePosixPath(name).parts
        relative_names.append(PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else "")
    allowed_members = {
        "CHANGELOG.md", "LICENSE", "MANIFEST.in", "PKG-INFO", "README.md",
        "premode.product.json", "pyproject.toml", "setup.cfg", "setup.py",
        *(
            "src/" + str(member)
            for member in policy.get("wheel_allowed_members", [])
            if str(member).startswith("premode/")
        ),
        *("plugins/pcodex/" + str(member) for member in policy.get("plugin_allowed_members", [])),
    }
    allowed_globs = (
        "docs/*.md", "docs/*.json", "docs/**/*.md", "docs/**/*.json",
        "examples/*",
        "schemas/*.json", "src/premode_router.egg-info/*",
    )
    failures = validate_names(relative_names, allowed_prefixes=[], policy=policy)
    for name in relative_names:
        if not name or (name not in allowed_members and not any(fnmatch(name, pattern) for pattern in allowed_globs)):
            failures.append(f"unexpected_sdist_member:{name or '<empty>'}")
    return failures


def validate_required_plugin_resources(
    names: list[str], policy: dict[str, object], *, archive_kind: str,
) -> list[str]:
    """Require every canonical plugin resource in both distributable forms."""
    required = [str(item) for item in policy.get("plugin_allowed_members", [])]
    normalized = [PurePosixPath(name).as_posix().lstrip("./") for name in names]
    if archive_kind == "wheel":
        present = {
            relative for relative in required
            if any(name.endswith("/share/premode-router/plugins/pcodex/" + relative) for name in normalized)
        }
    elif archive_kind == "sdist":
        stripped = {
            PurePosixPath(*PurePosixPath(name).parts[1:]).as_posix()
            for name in normalized if len(PurePosixPath(name).parts) > 1
        }
        present = {relative for relative in required if "plugins/pcodex/" + relative in stripped}
    else:
        raise ValueError(f"unsupported archive kind: {archive_kind}")
    return [f"missing_plugin_resource:{relative}" for relative in required if relative not in present]


def validate_archive_content(path: Path, policy: dict[str, object]) -> list[str]:
    patterns = tuple(str(item).encode("utf-8") for item in policy.get("content_prohibited_patterns", []))
    allowed_signatures = {
        str(name): tuple(str(value).encode("utf-8") for value in values)
        for name, values in dict(policy.get("content_allowed_signatures_by_member", {})).items()
    }
    failures: list[str] = []

    def archive_members(name: str, data: bytes) -> list[tuple[str, bytes]] | None:
        if name.endswith((".whl", ".zip")):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                return [(item.filename, archive.read(item)) for item in archive.infolist() if not item.is_dir()]
        if name.endswith((".tar.gz", ".tgz")):
            result: list[tuple[str, bytes]] = []
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                for item in archive.getmembers():
                    if not item.isfile():
                        continue
                    extracted = archive.extractfile(item)
                    if extracted is not None:
                        result.append((item.name, extracted.read()))
            return result
        return None

    root_members = archive_members(path.name, path.read_bytes())
    if root_members is None:
        return [f"unsupported_archive:{path.name}"]
    payloads: list[tuple[str, bytes]] = []
    pending = [(name, data, 1) for name, data in root_members]
    while pending:
        name, data, depth = pending.pop()
        nested = archive_members(name, data)
        if nested is None:
            payloads.append((name, data))
            continue
        if depth >= 4:
            failures.append(f"archive_nesting_exceeded:{name}")
            continue
        pending.extend((f"{name}!{member}", payload, depth + 1) for member, payload in nested)
    for name, data in payloads:
        logical_name = name.rsplit("!", 1)[-1]
        member_signatures = tuple(
            signature
            for member, signatures in allowed_signatures.items()
            if logical_name == member
            or logical_name.endswith("/" + member)
            or (member.startswith("premode/") and logical_name.endswith("/src/" + member))
            for signature in signatures
        )
        for signature in member_signatures:
            data = data.replace(signature, b"")
        for pattern in patterns:
            lowered = data.lower()
            marker = pattern.lower()
            if marker == b"sk-":
                matched = re.search(rb"(?<![a-z])sk-[a-z0-9_-]{12,}", lowered) is not None
            elif marker in {b"akia", b"asia"}:
                matched = re.search(rb"\b(?:akia|asia)[a-z0-9]{16}\b", lowered) is not None
            elif marker in {b"password=", b"token=", b"secret=", b"api_key"}:
                matched = re.search(rb"\b(?:PASSWORD|TOKEN|SECRET|API_KEY)\s*=\s*[A-Za-z0-9_./+-]{8,}", data) is not None
            else:
                matched = marker in lowered
            if matched:
                failures.append(f"prohibited_content:{name}:{pattern.decode('utf-8')}")
        regex_checks = (
            ("secret", rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{12,}|github_pat_[A-Za-z0-9_]{12,}|ghp_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|(?:AKIA|ASIA)[A-Z0-9]{16}|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|(?i:\bBearer\s+[A-Za-z0-9._~+/-]{12,})"),
            ("email", rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
            ("private_network", rb"(?i)(?:https?://(?:localhost|127\.0\.0\.1|\[?::1\]?|[^/\s]+\.(?:internal|local|lan|corp))\b|git@github\.com:|ssh://git@github\.com/|\b10(?:\.\d{1,3}){3}\b|\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b|\b192\.168(?:\.\d{1,3}){2}\b)"),
            ("system_id", rb"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"),
        )
        for label, pattern in regex_checks:
            for match in re.finditer(pattern, data):
                value = match.group(0)
                if label == "email" and value.lower().endswith((b"@example.com", b"@example.invalid", b"@example.test", b"@users.noreply.github.com")):
                    continue
                failures.append(f"prohibited_{label}:{name}:{value[:60].decode('utf-8', 'replace')}")
    return failures


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def persist_no_write_probe(output: Path, label: str, payload: dict[str, object]) -> dict[str, object]:
    if payload.get("receipts_validated") is not True:
        raise RuntimeError(f"{label} installed no-write receipts were not schema-validated")
    for name, receipt in dict(payload.get("public_receipts") or {}).items():
        write_json(output / "receipts" / "no-write" / label / f"{name}.json", receipt)
    for name, receipt in dict(payload.get("private_receipts") or {}).items():
        write_json(output / "private-receipts" / "no-write" / label / f"{name}.json", receipt)
    summary = {
        "schema_version": payload.get("schema_version"),
        "commands": payload.get("commands"),
        "forbidden_agent_marker_created": payload.get("forbidden_agent_marker_created"),
        "installed_import_isolated": True,
        "receipts_validated": True,
        "passed": payload.get("passed"),
    }
    write_json(output / "receipts" / f"installed-no-write-{label}.json", summary)
    return summary


def persist_lifecycle_probe(output: Path, label: str, payload: dict[str, object]) -> dict[str, object]:
    write_json(output / "private-receipts" / "lifecycle" / f"{label}.json", payload)
    summary = {
        "schema_version": payload.get("schema_version"),
        "passed": payload.get("passed"),
        "full_cycle": payload.get("full_cycle"),
        "modified_cycle": payload.get("modified_cycle"),
        "receipts": payload.get("receipts"),
        "performance": payload.get("performance"),
        "installed_import_isolated": True,
    }
    write_json(output / "receipts" / f"installed-lifecycle-{label}.json", summary)
    return summary


def persist_codex_plugin_probe(output: Path, label: str, payload: dict[str, object]) -> dict[str, object]:
    write_json(output / "private-receipts" / "codex-plugin" / f"{label}.json", payload)
    summary = {
        "schema_version": payload.get("schema_version"),
        "passed": payload.get("passed"),
        "live_codex_available": payload.get("live_codex_available"),
        "installed_import_isolated": payload.get("installed_import_isolated"),
        "supported_codex_versions": payload.get("supported_codex_versions"),
        "codex_version": payload.get("codex_version"),
        "static_contract": payload.get("static_contract"),
        "schemas_validated": payload.get("schemas_validated"),
        "lifecycle": payload.get("lifecycle"),
        "discovery": payload.get("discovery"),
        "mcp": payload.get("mcp"),
        "migration": payload.get("migration"),
        "preservation": payload.get("preservation"),
        "performance": payload.get("performance"),
        "deferred_reason": payload.get("deferred_reason"),
    }
    write_json(output / "receipts" / f"installed-codex-plugin-{label}.json", summary)
    return summary


def write_tester_bundle(source: Path, output: Path, artifacts: Path) -> Path:
    bundle = output / "pcodex-private-tester-bundle.zip"
    entries: list[tuple[Path, str]] = []
    for artifact in sorted(artifacts.iterdir()):
        entries.append((artifact, f"artifacts/{artifact.name}"))
    plugin_root = source / "plugins" / "pcodex"
    for path in sorted(plugin_root.rglob("*")):
        if path.is_file():
            entries.append((path, f"plugins/pcodex/{path.relative_to(plugin_root).as_posix()}"))
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if name == "plugins/pcodex/skills/pcodex/bin/resolve-pcodex.sh" else 0o644
            info.external_attr = mode << 16
            archive.writestr(info, path.read_bytes())
    return bundle


def normalize_gzip(path: Path) -> None:
    raw = gzip.decompress(path.read_bytes())
    with path.open("wb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as archive:
            archive.write(raw)


def materialize_legacy_fixture(destination: Path) -> None:
    """Extract the accepted historical plugin bytes used by migration authority."""
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination.parent / "legacy-fixture.tar"
    with archive_path.open("wb") as handle:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", LEGACY_FIXTURE_COMMIT, "--", *LEGACY_FIXTURE_PATHS],
            cwd=ROOT, stdout=handle, stderr=subprocess.PIPE, check=False,
        )
    if completed.returncode:
        raise RuntimeError("could not materialize the accepted legacy migration fixture")
    with tarfile.open(archive_path) as archive:
        archive.extractall(destination, filter="data")
    archive_path.unlink()


def write_smoke_fixture(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0"\n', encoding="utf-8")
    (root / "src/app.py").write_text("def calculate_total(values):\n    return sum(values)\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests/test_app.py").write_text(
        "from src.app import calculate_total\n\ndef test_total():\n    assert calculate_total([1, 2]) == 3\n",
        encoding="utf-8",
    )


def build(commit: str, output: Path, *, python: str, with_sdist: bool = True) -> None:
    if not with_sdist:
        raise RuntimeError("wheel and sdist qualification are both mandatory")
    python = validated_python_interpreter(python)
    commit_sha = run("git", "rev-parse", f"{commit}^{{commit}}")
    if Path(run("git", "rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise RuntimeError("release builder is not executing from its authoritative repository")
    dirty = run("git", "status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        raise RuntimeError("release builder requires a clean worktree and index")
    committed_builder = subprocess.check_output(
        ["git", "show", f"{commit_sha}:scripts/build_release_artifacts.py"], cwd=ROOT,
    )
    if committed_builder != Path(__file__).read_bytes():
        raise RuntimeError("executing release builder does not match the requested committed source")
    epoch = run("git", "show", "-s", "--format=%ct", commit_sha)
    evidence_timestamp = datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    policy = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"output directory must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pcodex-release-") as raw_temp:
        temp = Path(raw_temp)
        archive = temp / "source.tar"
        with archive.open("wb") as handle:
            subprocess.run(["git", "archive", "--format=tar", commit_sha], cwd=ROOT, stdout=handle, check=True)
        source = temp / "source"
        source.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(source, filter="data")
        for pattern in policy.get("release_source_excluded_globs", []):
            for path in source.glob(str(pattern)):
                if path.is_file():
                    path.unlink()
        dist = temp / "dist"
        env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
        env.update({"SOURCE_DATE_EPOCH": epoch, "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1"})
        run(
            python, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation",
            "--wheel-dir", str(dist), cwd=source, env=env,
        )
        run(python, "setup.py", "sdist", "--dist-dir", str(dist), cwd=source, env=env)
        for sdist in dist.glob("*.tar.gz"):
            normalize_gzip(sdist)
        artifacts = output / "artifacts"
        shutil.copytree(dist, artifacts, dirs_exist_ok=True)

        inventory: list[dict[str, object]] = []
        allowlist_failures: list[str] = []
        for artifact in sorted(artifacts.iterdir()):
            item_members = members(artifact)
            prefixes = policy["wheel_allowed_prefixes"] if artifact.suffix == ".whl" else []
            allowlist_failures.extend(validate_names(item_members, allowed_prefixes=list(prefixes), policy=policy, exact_wheel=artifact.suffix == ".whl"))
            if artifact.suffix == ".whl":
                allowlist_failures.extend(validate_required_plugin_resources(item_members, policy, archive_kind="wheel"))
            if artifact.name.endswith((".tar.gz", ".tgz")):
                allowlist_failures.extend(validate_sdist_names(item_members, policy))
                allowlist_failures.extend(validate_required_plugin_resources(item_members, policy, archive_kind="sdist"))
            allowlist_failures.extend(validate_archive_content(artifact, policy))
            inventory.append({"file": f"artifacts/{artifact.name}", "sha256": sha256(artifact), "size": artifact.stat().st_size, "members": item_members})
        report = {"schema_version": "pcodex.allowlist_report.v1", "commit": commit_sha, "passed": not allowlist_failures, "failures": allowlist_failures}
        write_json(output / "receipts" / "artifact-inventory.json", inventory)
        write_json(output / "receipts" / "package-content-allowlist.json", report)
        write_json(output / "receipts" / "known-limitations.json", {"final_holdout_executed": False, "public_registry_published": False, "live_codex_discovery_tested": False})
        if allowlist_failures:
            raise RuntimeError("artifact allowlist failed: " + ", ".join(allowlist_failures[:10]))

        wheels = list(artifacts.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected exactly one wheel, found {len(wheels)}")
        wheel = wheels[0]
        smoke_root = temp / "smoke"
        run(python, "-m", "venv", str(smoke_root))
        smoke_python = smoke_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        smoke_bin = smoke_root / ("Scripts" if os.name == "nt" else "bin")
        run(str(smoke_python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel), cwd=temp)
        probe = run(
            str(smoke_python), "-c",
            "from importlib.metadata import packages_distributions; from premode.plugins import resolve_packet_plugin as r; "
            "assert 'premode_plugin_literal_symbol' not in packages_distributions(); print(r('literal_symbol').packet_strategy)",
            cwd=temp,
        )
        fixture = temp / "repository with spaces"
        write_smoke_fixture(fixture)
        smoke_home = temp / "home"
        smoke_home.mkdir()
        smoke_env = {
            **env,
            "HOME": str(smoke_home),
            "XDG_CONFIG_HOME": str(smoke_home / "xdg-config"),
            "XDG_CACHE_HOME": str(smoke_home / "xdg-cache"),
            "XDG_DATA_HOME": str(smoke_home / "xdg-data"),
            "TMPDIR": str(temp / "smoke-tmp"),
            "PATH": str(smoke_bin) + os.pathsep + env.get("PATH", ""),
        }
        Path(smoke_env["TMPDIR"]).mkdir()
        legacy_fixture = temp / "accepted-legacy-fixture"
        materialize_legacy_fixture(legacy_fixture)
        legacy_inventory = {
            path.relative_to(legacy_fixture).as_posix(): sha256(path)
            for path in sorted(legacy_fixture.rglob("*")) if path.is_file()
        }
        write_json(output / "receipts/accepted-legacy-fixture.json", {
            "schema_version": "pcodex.accepted-legacy-fixture.v1",
            "source_commit": LEGACY_FIXTURE_COMMIT,
            "file_count": len(legacy_inventory),
            "files": legacy_inventory,
            "inventory_sha256": hashlib.sha256(
                json.dumps(legacy_inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        })
        run(str(smoke_bin / "pcodex"), "--help", cwd=temp, env=smoke_env)
        wheel_no_write, wheel_no_write_rc = run_json_probe(
            str(smoke_python), str(source / "scripts" / "installed_no_write_probe.py"),
            "--pcodex", str(smoke_bin / "pcodex"),
            "--repository", str(fixture),
            "--control-root", str(temp / "wheel-no-write-control"),
            "--commit-sha", commit_sha,
            "--timestamp", evidence_timestamp,
            output=output, label="wheel-no-write", cwd=temp,
            env={**smoke_env, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        wheel_no_write_summary = persist_no_write_probe(output, "wheel", wheel_no_write)
        require_probe_passed("wheel no-write", wheel_no_write, wheel_no_write_rc)
        wheel_lifecycle, wheel_lifecycle_rc = run_json_probe(
            str(smoke_python), str(source / "scripts" / "installed_lifecycle_probe.py"),
            "--pcodex", str(smoke_bin / "pcodex"),
            "--control-root", str(temp / "wheel-lifecycle-control"),
            output=output, label="wheel-lifecycle", cwd=temp,
            env={**smoke_env, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        wheel_lifecycle_summary = persist_lifecycle_probe(output, "wheel", wheel_lifecycle)
        require_probe_passed("wheel lifecycle", wheel_lifecycle, wheel_lifecycle_rc)
        wheel_codex_plugin, wheel_codex_plugin_rc = run_json_probe(
            str(smoke_python), str(source / "scripts" / "installed_codex_plugin_probe.py"),
            "--pcodex", str(smoke_bin / "pcodex"),
            "--control-root", str(temp / "wheel-codex-plugin-control"),
            "--legacy-fixture", str(legacy_fixture),
            output=output, label="wheel-codex-plugin", cwd=temp,
            env={**smoke_env, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        wheel_codex_plugin_summary = persist_codex_plugin_probe(output, "wheel", wheel_codex_plugin)
        require_probe_passed("wheel Codex plugin", wheel_codex_plugin, wheel_codex_plugin_rc)
        wheel_missing_codex, wheel_missing_codex_rc = run_json_probe(
            str(smoke_python), str(source / "scripts/installed_codex_plugin_probe.py"),
            "--pcodex", str(smoke_bin / "pcodex"),
            "--control-root", str(temp / "wheel-missing-codex-control"),
            "--legacy-fixture", str(legacy_fixture),
            "--force-codex-unavailable",
            output=output, label="wheel-codex-plugin-missing-codex", cwd=temp,
            env={**smoke_env, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        wheel_missing_codex_summary = persist_codex_plugin_probe(output, "wheel-missing-codex", wheel_missing_codex)
        require_probe_passed("wheel missing-Codex plugin", wheel_missing_codex, wheel_missing_codex_rc)
        installed_contract = json.loads(run(
            str(smoke_python), "-c",
            "import json; from premode.product_contract import validate_installed_product_contract as v; print(json.dumps(v(),sort_keys=True))",
            cwd=temp, env=smoke_env,
        ))
        setup_payload = json.loads(run(str(smoke_bin / "pcodex"), "setup", "--skip-tune", "--no-mcp", "--json", "--repo-root", str(fixture), cwd=temp, env=smoke_env))
        status_payload = json.loads(run(str(smoke_bin / "pcodex"), "status", "--json", "--repo-root", str(fixture), cwd=temp, env=smoke_env))
        before_user_files = {path.relative_to(fixture).as_posix(): sha256(path) for path in fixture.rglob("*") if path.is_file() and ".premode" not in path.parts}
        smoke_task = "Change calculate_total in src/app.py and update tests/test_app.py"
        dry_payload = json.loads(run(str(smoke_bin / "pcodex"), "run", "--dry-run", "--json", smoke_task, cwd=fixture, env=smoke_env))
        compile_payload = json.loads(run(
            str(smoke_python), "-c",
            "import json,sys; from pathlib import Path; from premode.compiler import compile_prompt; "
            "r=compile_prompt(Path(sys.argv[1]),sys.argv[2],'lite',packet_version='v5',"
            "packet_variant='tool_assisted_anchors_internal',packet_strategy='literal_symbol',"
            "canonical_core_packet=True,record_artifacts=False); "
            "d=r.get('production_ranking') or {}; "
            "print(json.dumps({'production_ranking':d,'selected_paths':[*(d.get('primary_paths') or []),*(d.get('verify_paths') or []),*(d.get('support_paths') or [])]}))",
            str(fixture), smoke_task, cwd=temp, env=smoke_env,
        ))
        after_user_files = {path.relative_to(fixture).as_posix(): sha256(path) for path in fixture.rglob("*") if path.is_file() and ".premode" not in path.parts}
        if before_user_files != after_user_files:
            raise RuntimeError("installed dry-run mutated non-owned fixture files")
        selected = compile_payload.get("selected_paths") or []
        if any(part in str(path).split("/") for path in selected for part in {".git", ".pcodex", ".premode"}):
            raise RuntimeError(f"installed smoke selected runtime state: {selected}")
        decision = compile_payload.get("production_ranking") if isinstance(compile_payload.get("production_ranking"), dict) else {}
        if decision.get("routing_mode") == "abstain" or "src/app.py" not in selected:
            raise RuntimeError(f"installed smoke did not exercise routed default strategy: {decision} {selected}")
        before_uninstall_preview = {path.relative_to(fixture).as_posix(): sha256(path) for path in fixture.rglob("*") if path.is_file()}
        uninstall_preview = json.loads(run(
            str(smoke_bin / "pcodex"), "uninstall", "--dry-run", "--json", "--repo-root", str(fixture),
            cwd=temp, env=smoke_env,
        ))
        after_uninstall_preview = {path.relative_to(fixture).as_posix(): sha256(path) for path in fixture.rglob("*") if path.is_file()}
        if before_uninstall_preview != after_uninstall_preview or uninstall_preview.get("writes_performed") is not False:
            raise RuntimeError("installed uninstall preview mutated fixture state")

        sdist_smoke = "not_requested"
        sdist_no_write: dict[str, object] | str = "not_requested"
        sdist_lifecycle: dict[str, object] | str = "not_requested"
        sdist_codex_plugin: dict[str, object] | str = "not_requested"
        if with_sdist:
            sdists = list(artifacts.glob("*.tar.gz"))
            if len(sdists) != 1:
                raise RuntimeError(f"expected exactly one sdist, found {len(sdists)}")
            sdist_wheel_dir = temp / "sdist-wheel"
            sdist_wheel_dir.mkdir()
            run(python, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(sdist_wheel_dir), str(sdists[0]), cwd=temp, env=env)
            sdist_wheels = list(sdist_wheel_dir.glob("*.whl"))
            if len(sdist_wheels) != 1:
                raise RuntimeError("sdist did not produce exactly one wheel")
            sdist_root = temp / "smoke-sdist"
            run(python, "-m", "venv", str(sdist_root))
            sdist_python = sdist_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            sdist_bin = sdist_root / ("Scripts" if os.name == "nt" else "bin")
            run(str(sdist_python), "-m", "pip", "install", "--no-index", "--no-deps", str(sdist_wheels[0]), cwd=temp)
            rebuilt_members = members(sdist_wheels[0])
            rebuilt_failures = validate_names(
                rebuilt_members, allowed_prefixes=list(policy["wheel_allowed_prefixes"]),
                policy=policy, exact_wheel=True,
            )
            rebuilt_failures.extend(validate_required_plugin_resources(rebuilt_members, policy, archive_kind="wheel"))
            rebuilt_failures.extend(validate_archive_content(sdist_wheels[0], policy))
            if rebuilt_failures:
                raise RuntimeError("sdist-rebuilt wheel allowlist failed: " + ", ".join(rebuilt_failures[:10]))
            run(str(sdist_python), "-c", "from premode.product_contract import validate_installed_product_contract as v; assert v()['status']=='valid'", cwd=temp)
            run(str(sdist_python), "-c", "from premode.production_ranking import PRODUCTION_RANKING_PROVIDER_VERSION as v; assert v=='production-ranking-provider.v1'", cwd=temp)
            run(str(sdist_bin / "pcodex"), "--help", cwd=temp)
            sdist_fixture = temp / "sdist repository with spaces"
            write_smoke_fixture(sdist_fixture)
            sdist_home = temp / "sdist-home"
            sdist_home.mkdir()
            sdist_env = {
                **env,
                "HOME": str(sdist_home),
                "XDG_CONFIG_HOME": str(sdist_home / "xdg-config"),
                "XDG_CACHE_HOME": str(sdist_home / "xdg-cache"),
                "XDG_DATA_HOME": str(sdist_home / "xdg-data"),
                "TMPDIR": str(temp / "sdist-tmp"),
                "PATH": str(sdist_bin) + os.pathsep + env.get("PATH", ""),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            Path(sdist_env["TMPDIR"]).mkdir()
            sdist_no_write, sdist_no_write_rc = run_json_probe(
                str(sdist_python), str(source / "scripts" / "installed_no_write_probe.py"),
                "--pcodex", str(sdist_bin / "pcodex"),
                "--repository", str(sdist_fixture),
                "--control-root", str(temp / "sdist-no-write-control"),
                "--commit-sha", commit_sha,
                "--timestamp", evidence_timestamp,
                output=output, label="sdist-no-write", cwd=temp,
                env=sdist_env,
            )
            sdist_no_write_summary = persist_no_write_probe(output, "sdist", sdist_no_write)
            require_probe_passed("sdist no-write", sdist_no_write, sdist_no_write_rc)
            sdist_lifecycle, sdist_lifecycle_rc = run_json_probe(
                str(sdist_python), str(source / "scripts" / "installed_lifecycle_probe.py"),
                "--pcodex", str(sdist_bin / "pcodex"),
                "--control-root", str(temp / "sdist-lifecycle-control"),
                output=output, label="sdist-lifecycle", cwd=temp,
                env=sdist_env,
            )
            sdist_lifecycle_summary = persist_lifecycle_probe(output, "sdist", sdist_lifecycle)
            require_probe_passed("sdist lifecycle", sdist_lifecycle, sdist_lifecycle_rc)
            sdist_codex_plugin, sdist_codex_plugin_rc = run_json_probe(
                str(sdist_python), str(source / "scripts" / "installed_codex_plugin_probe.py"),
                "--pcodex", str(sdist_bin / "pcodex"),
                "--control-root", str(temp / "sdist-codex-plugin-control"),
                "--legacy-fixture", str(legacy_fixture),
                output=output, label="sdist-codex-plugin", cwd=temp,
                env=sdist_env,
            )
            sdist_codex_plugin_summary = persist_codex_plugin_probe(output, "sdist", sdist_codex_plugin)
            require_probe_passed("sdist Codex plugin", sdist_codex_plugin, sdist_codex_plugin_rc)
            sdist_missing_codex, sdist_missing_codex_rc = run_json_probe(
                str(sdist_python), str(source / "scripts/installed_codex_plugin_probe.py"),
                "--pcodex", str(sdist_bin / "pcodex"),
                "--control-root", str(temp / "sdist-missing-codex-control"),
                "--legacy-fixture", str(legacy_fixture),
                "--force-codex-unavailable",
                output=output, label="sdist-codex-plugin-missing-codex", cwd=temp,
                env=sdist_env,
            )
            sdist_missing_codex_summary = persist_codex_plugin_probe(output, "sdist-missing-codex", sdist_missing_codex)
            require_probe_passed("sdist missing-Codex plugin", sdist_missing_codex, sdist_missing_codex_rc)
            run(str(sdist_python), "-m", "pip", "uninstall", "-y", "premode-router", cwd=temp)
            run(
                str(sdist_python), "-c",
                "import importlib.metadata as m,importlib.util; assert importlib.util.find_spec('premode') is None; "
                "\ntry: m.distribution('premode-router'); raise AssertionError('metadata remained')\nexcept m.PackageNotFoundError: pass",
                cwd=temp,
            )
            if any((sdist_bin / name).exists() for name in ("pcodex", "premode")):
                raise RuntimeError("sdist package uninstall left console scripts")
            sdist_smoke = "passed"
        write_json(output / "receipts" / "known-limitations.json", {
            "final_holdout_executed": False,
            "public_registry_published": False,
            "live_codex_discovery_tested": bool(wheel_codex_plugin.get("live_codex_available")) and (
                not with_sdist or bool(isinstance(sdist_codex_plugin, dict) and sdist_codex_plugin.get("live_codex_available"))
            ),
            "model_visible_skill_trigger_executed": False,
        })
        write_json(output / "receipts" / "install-smoke.json", {
            "status": "passed", "offline": True, "source_import_absent": True,
            "default_strategy": probe, "commit": commit_sha,
            "setup_status": setup_payload.get("setup_status"), "pcodex_status": status_payload.get("status"),
            "dry_run_codex_launch": dry_payload.get("codex_launch"), "selected_paths": selected,
            "installed_contract": installed_contract,
            "provider_version": decision.get("provider_version"),
            "uninstall_preview_status": uninstall_preview.get("status"),
            "uninstall_preview_writes": uninstall_preview.get("writes_performed"),
            "sdist_smoke": sdist_smoke,
            "wheel_no_write": wheel_no_write_summary,
            "sdist_no_write": sdist_no_write_summary if isinstance(sdist_no_write, dict) else sdist_no_write,
            "wheel_lifecycle": wheel_lifecycle_summary,
            "sdist_lifecycle": sdist_lifecycle_summary if isinstance(sdist_lifecycle, dict) else sdist_lifecycle,
            "wheel_codex_plugin": wheel_codex_plugin_summary,
            "sdist_codex_plugin": sdist_codex_plugin_summary if isinstance(sdist_codex_plugin, dict) else sdist_codex_plugin,
            "wheel_missing_codex_plugin": wheel_missing_codex_summary,
            "sdist_missing_codex_plugin": sdist_missing_codex_summary,
            "external_strategy_distribution_present": False,
        })
        run(str(smoke_python), "-m", "pip", "uninstall", "-y", "premode-router", cwd=temp)
        run(
            str(smoke_python), "-c",
            "import importlib.metadata as m,importlib.util; assert importlib.util.find_spec('premode') is None; "
            "\ntry: m.distribution('premode-router'); raise AssertionError('metadata remained')\nexcept m.PackageNotFoundError: pass",
            cwd=temp,
        )
        if any((smoke_bin / name).exists() for name in ("pcodex", "premode")):
            raise RuntimeError("wheel package uninstall left console scripts")
        bundle = write_tester_bundle(source, output, artifacts)
        bundle_failures = validate_names(members(bundle), allowed_prefixes=list(policy["bundle_allowed_prefixes"]), policy=policy)
        bundle_failures.extend(validate_archive_content(bundle, policy))
        if bundle_failures:
            raise RuntimeError("tester bundle allowlist failed: " + ", ".join(bundle_failures[:10]))

    manifest = [{"file": path.relative_to(output).as_posix(), "sha256": sha256(path), "size": path.stat().st_size} for path in sorted(output.rglob("*")) if path.is_file()]
    write_json(output / "SHA256-MANIFEST.json", manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and smoke-test pCodex release artifacts from a committed tree.")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--with-sdist", action="store_true", help="Compatibility flag; wheel and sdist are always required.")
    args = parser.parse_args()
    build(args.commit, args.output.resolve(), python=args.python, with_sdist=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
