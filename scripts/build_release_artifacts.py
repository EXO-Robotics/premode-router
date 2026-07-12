#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
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


def validate_names(names: list[str], *, allowed_prefixes: list[str], policy: dict[str, object]) -> list[str]:
    failures: list[str] = []
    prohibited_parts = {str(item).lower() for item in policy["prohibited_parts"]}
    prohibited_suffixes = tuple(str(item).lower() for item in policy["prohibited_suffixes"])
    for name in names:
        normalized = PurePosixPath(name).as_posix().lstrip("./")
        lowered_parts = {part.lower() for part in PurePosixPath(normalized).parts}
        if lowered_parts & prohibited_parts or normalized.lower().endswith(prohibited_suffixes):
            failures.append(f"prohibited:{normalized}")
        if allowed_prefixes and not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
            failures.append(f"not_allowed:{normalized}")
        if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
            failures.append(f"unsafe_path:{normalized}")
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


def build(commit: str, output: Path, *, python: str) -> None:
    commit_sha = run("git", "rev-parse", f"{commit}^{{commit}}")
    epoch = run("git", "show", "-s", "--format=%ct", commit_sha)
    policy = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
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
        dist = temp / "dist"
        env = {**os.environ, "SOURCE_DATE_EPOCH": epoch, "PYTHONHASHSEED": "0"}
        run(python, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(dist), cwd=source, env=env)
        artifacts = output / "artifacts"
        shutil.copytree(dist, artifacts, dirs_exist_ok=True)

        inventory: list[dict[str, object]] = []
        allowlist_failures: list[str] = []
        for artifact in sorted(artifacts.iterdir()):
            item_members = members(artifact)
            prefixes = policy["wheel_allowed_prefixes"] if artifact.suffix == ".whl" else []
            allowlist_failures.extend(validate_names(item_members, allowed_prefixes=list(prefixes), policy=policy))
            inventory.append({"file": f"artifacts/{artifact.name}", "sha256": sha256(artifact), "size": artifact.stat().st_size, "members": item_members})
        report = {"schema_version": "pcodex.allowlist_report.v1", "commit": commit_sha, "passed": not allowlist_failures, "failures": allowlist_failures}
        write_json(output / "receipts" / "artifact-inventory.json", inventory)
        write_json(output / "receipts" / "package-content-allowlist.json", report)
        write_json(output / "receipts" / "known-limitations.json", {"final_holdout_executed": False, "public_registry_published": False, "live_codex_discovery_tested": False})
        if allowlist_failures:
            raise RuntimeError("artifact allowlist failed: " + ", ".join(allowlist_failures[:10]))

        wheel = next(artifacts.glob("*.whl"))
        smoke_root = temp / "smoke"
        run(python, "-m", "venv", str(smoke_root))
        smoke_python = smoke_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(str(smoke_python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel), cwd=temp)
        probe = run(str(smoke_python), "-c", "from premode.plugins import resolve_packet_plugin as r; print(r('literal_symbol').packet_strategy)", cwd=temp)
        write_json(output / "receipts" / "install-smoke.json", {"status": "passed", "offline": True, "source_checkout_absent": True, "default_strategy": probe, "commit": commit_sha})
        bundle = write_tester_bundle(source, output, artifacts)
        bundle_failures = validate_names(members(bundle), allowed_prefixes=list(policy["bundle_allowed_prefixes"]), policy=policy)
        if bundle_failures:
            raise RuntimeError("tester bundle allowlist failed: " + ", ".join(bundle_failures[:10]))

    manifest = [{"file": path.relative_to(output).as_posix(), "sha256": sha256(path), "size": path.stat().st_size} for path in sorted(output.rglob("*")) if path.is_file()]
    write_json(output / "SHA256-MANIFEST.json", manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and smoke-test pCodex release artifacts from a committed tree.")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    build(args.commit, args.output.resolve(), python=args.python)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
