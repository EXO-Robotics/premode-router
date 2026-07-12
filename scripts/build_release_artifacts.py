#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import gzip
from fnmatch import fnmatch
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


def run(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(args)}\n{completed.stderr.strip()}")
    return completed.stdout.strip()


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


def validate_archive_content(path: Path, policy: dict[str, object]) -> list[str]:
    patterns = tuple(str(item).encode("utf-8") for item in policy.get("content_prohibited_patterns", []))
    allowed_signatures = {
        str(name): tuple(str(value).encode("utf-8") for value in values)
        for name, values in dict(policy.get("content_allowed_signatures_by_member", {})).items()
    }
    failures: list[str] = []
    payloads: list[tuple[str, bytes]] = []
    if path.suffix in {".whl", ".zip"}:
        with zipfile.ZipFile(path) as archive:
            payloads = [(item.filename, archive.read(item)) for item in archive.infolist() if not item.is_dir()]
    elif path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            payloads = [(item.name, archive.extractfile(item).read()) for item in archive.getmembers() if item.isfile() and archive.extractfile(item) is not None]
    for name, data in payloads:
        for signature in allowed_signatures.get(name, ()):
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
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return bundle


def normalize_gzip(path: Path) -> None:
    raw = gzip.decompress(path.read_bytes())
    with path.open("wb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as archive:
            archive.write(raw)


def build(commit: str, output: Path, *, python: str, with_sdist: bool = False) -> None:
    commit_sha = run("git", "rev-parse", f"{commit}^{{commit}}")
    epoch = run("git", "show", "-s", "--format=%ct", commit_sha)
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
        env = {**os.environ, "SOURCE_DATE_EPOCH": epoch, "PYTHONHASHSEED": "0"}
        run(
            python, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation",
            "--wheel-dir", str(dist), cwd=source, env=env,
        )
        if with_sdist:
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
        (fixture / "src").mkdir(parents=True)
        (fixture / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0"\n', encoding="utf-8")
        (fixture / "src" / "app.py").write_text("def calculate_total(values):\n    return sum(values)\n", encoding="utf-8")
        (fixture / "tests").mkdir()
        (fixture / "tests" / "test_app.py").write_text("from src.app import calculate_total\n\ndef test_total():\n    assert calculate_total([1, 2]) == 3\n", encoding="utf-8")
        smoke_home = temp / "home"
        smoke_home.mkdir()
        smoke_env = {**env, "HOME": str(smoke_home), "PATH": str(smoke_bin) + os.pathsep + env.get("PATH", "")}
        run(str(smoke_bin / "pcodex"), "--help", cwd=temp, env=smoke_env)
        setup_payload = json.loads(run(str(smoke_bin / "pcodex"), "setup", "--skip-tune", "--no-mcp", "--json", "--repo-root", str(fixture), cwd=temp, env=smoke_env))
        status_payload = json.loads(run(str(smoke_bin / "pcodex"), "status", "--json", "--repo-root", str(fixture), cwd=temp, env=smoke_env))
        before_user_files = {path.relative_to(fixture).as_posix(): sha256(path) for path in fixture.rglob("*") if path.is_file() and ".premode" not in path.parts}
        dry_payload = json.loads(run(str(smoke_bin / "pcodex"), "run", "--dry-run", "--json", "Change calculate_total in src/app.py and update tests/test_app.py", cwd=fixture, env=smoke_env))
        after_user_files = {path.relative_to(fixture).as_posix(): sha256(path) for path in fixture.rglob("*") if path.is_file() and ".premode" not in path.parts}
        if before_user_files != after_user_files:
            raise RuntimeError("installed dry-run mutated non-owned fixture files")
        selected = dry_payload.get("selected_paths") or []
        if any(part in str(path).split("/") for path in selected for part in {".git", ".pcodex", ".premode"}):
            raise RuntimeError(f"installed smoke selected runtime state: {selected}")
        decision = dry_payload.get("routing_decision") if isinstance(dry_payload.get("routing_decision"), dict) else {}
        if decision.get("mode") == "abstain" or "src/app.py" not in selected:
            raise RuntimeError(f"installed smoke did not exercise routed default strategy: {decision} {selected}")
        write_json(output / "receipts" / "install-smoke.json", {
            "status": "passed", "offline": True, "source_checkout_absent": True,
            "default_strategy": probe, "commit": commit_sha,
            "setup_status": setup_payload.get("setup_status"), "pcodex_status": status_payload.get("status"),
            "dry_run_codex_launch": dry_payload.get("codex_launch"), "selected_paths": selected,
            "external_strategy_distribution_present": False,
        })
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
    parser.add_argument("--with-sdist", action="store_true", help="Also build the optional source distribution.")
    args = parser.parse_args()
    build(args.commit, args.output.resolve(), python=args.python, with_sdist=args.with_sdist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
