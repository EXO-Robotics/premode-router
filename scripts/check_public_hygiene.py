#!/usr/bin/env python3
from __future__ import annotations

"""Deterministic public-repository release guard, not a secret-detection guarantee."""

import argparse
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKED_BYTES = 5_000_000
FORBIDDEN_TRACKED_PARTS = {
    ".DS_Store", ".env", ".git", ".pcodex", ".premode", ".venv", "venv", "__MACOSX", "__pycache__",
    "observer/evidence", "observer/runs", "artifacts", "dist", "build",
}
FORBIDDEN_SUFFIXES = {".db", ".jsonl", ".key", ".log", ".p12", ".pem", ".sqlite", ".sqlite3"}
ABSOLUTE_PATHS = re.compile(r"/(?:Users|home)/[^\s'\"`]+|/private/tmp/[^\s'\"`]+", re.IGNORECASE)
SECRET_PREFIXES = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{12,}|github_pat_[A-Za-z0-9_]{12,}|ghp_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|(?:AKIA|ASIA)[A-Z0-9]{16}|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|(?i:\bBearer\s+[A-Za-z0-9._~+/-]{12,})")
SECRET_ASSIGNMENTS = re.compile(r"\b(?:(?:PASSWORD|TOKEN|SECRET|API_KEY)|(?i:password|authorization|x_api_key))\s*[:=]\s*['\"]?(?!SECRET_SENTINEL|EXAMPLE_|FAKE_|REDACTED)[A-Za-z0-9_./+:-]{8,}")
PRIVATE_IDENTITIES = re.compile(r"(?i)\b(?:Goldpine(?:Valley)?|RoboTriage|Rich[-_]CLI)\b")
INTERNAL_NETWORK = re.compile(r"(?i)(?:https?://(?:localhost|127\.0\.0\.1|\[?::1\]?|[^/\s]+\.(?:internal|local|lan|corp))\b|(?:git@github\.com:|ssh://git@github\.com/|git@|ssh://git@)(?:localhost|[^/\s:]+\.(?:internal|local|lan|corp))?|\b10(?:\.\d{1,3}){3}\b|\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b|\b192\.168(?:\.\d{1,3}){2}\b)")
PRIVATE_SYSTEM_ID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PUBLIC_EMAIL_SUFFIXES = ("@example.com", "@example.invalid", "@example.test", "@users.noreply.github.com")
SYNTHETIC_MATCHES = {
    "AKIAABCDEFGHIJKLMNOP", "ghp_abcdefghijklmnopqrstuvwxyz", "-----BEGIN PRIVATE KEY-----",
    "token=plainsecret", "TOKEN=baseline", "TOKEN=do-not-route", "SECRET=baseline",
    "SECRET=do-not-leak", "api_key = sk_test_1234567890",
}


def _allowed_match(rel: str, line: str, value: str) -> bool:
    stripped = line.strip()
    detector_values = {
        "scripts/check_public_hygiene.py": {
            "Goldpine", "RoboTriage", "Rich-CLI", "Rich_CLI", "n@click.option",
            "/private/" + "tmp/[^\\s", "git" + "@", "ssh://git" + "@",
        },
        "src/premode/redaction.py": {
            "github_" + "pat_", "sk-" + "[A-Za-z0-9_-]{12,}",
        },
        "src/premode/launch_safety.py": set(),
        "scripts/build_release_artifacts.py": {"git" + "@", "ssh://git" + "@"},
    }
    if value in detector_values.get(rel, set()):
        return True
    if rel in {"release/artifact-allowlist.json", "scripts/check_public_hygiene.py"} and value in {"Goldpine", "RoboTriage", "Rich-CLI", "Rich_CLI"}:
        return True
    if rel == "release/artifact-allowlist.json" and value == "n@click.option":
        return True
    if value in SYNTHETIC_MATCHES:
        return True
    if value == "n@click.option" and rel in {"src/premode/locator.py", "scripts/check_public_hygiene.py"}:
        return True
    return False


def tracked_files(root: Path) -> list[str]:
    completed = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root, check=True, capture_output=True)
    return sorted(item.decode("utf-8") for item in completed.stdout.split(b"\0") if item)


def scan(root: Path) -> dict[str, object]:
    failures: list[str] = []
    files = tracked_files(root)
    reviewed = 0
    for rel in files:
        path = root / rel
        if not path.exists():
            continue
        normalized = rel.replace("\\", "/")
        if PRIVATE_IDENTITIES.search(normalized):
            failures.append(f"private_identity_path:{normalized}")
        parts = set(Path(normalized).parts)
        if parts & FORBIDDEN_TRACKED_PARTS or any(normalized.startswith(item + "/") for item in FORBIDDEN_TRACKED_PARTS):
            failures.append(f"forbidden_tracked_path:{normalized}")
        if any(part.startswith(".env.") for part in parts):
            failures.append(f"forbidden_env_variant:{normalized}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden_suffix:{normalized}")
        size = path.stat().st_size
        if size > MAX_TRACKED_BYTES:
            failures.append(f"unexpected_large_file:{normalized}:{size}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"unexpected_binary:{normalized}")
            continue
        except OSError:
            failures.append(f"unreadable_tracked_file:{normalized}")
            continue
        reviewed += 1
        checks = (
            ("absolute_local_path", ABSOLUTE_PATHS),
            ("private_identity_content", PRIVATE_IDENTITIES),
            ("internal_network_content", INTERNAL_NETWORK),
            ("private_system_id", PRIVATE_SYSTEM_ID),
            ("secret_like_content", SECRET_PREFIXES),
            ("secret_assignment", SECRET_ASSIGNMENTS),
            ("email_content", EMAIL),
        )
        for line_number, line in enumerate(text.splitlines(), 1):
            for label, pattern in checks:
                for match in pattern.finditer(line):
                    value = match.group(0)
                    if _allowed_match(normalized, line, value):
                        continue
                    if label == "email_content" and value.casefold().endswith(PUBLIC_EMAIL_SUFFIXES):
                        continue
                    failures.append(f"{label}:{normalized}:{line_number}:{value[:100]}")
    return {
        "schema_version": "pcodex.public_hygiene.v1",
        "passed": not failures,
        "tracked_files": len(files),
        "text_files_reviewed": reviewed,
        "failures": sorted(set(failures)),
        "limitations": "Deterministic release guard only; manual semantic review remains required.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = scan(args.root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else "\n".join(result["failures"]))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
