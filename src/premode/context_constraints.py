from __future__ import annotations

"""Context selection constraints for transport and routing.

These helpers classify paths for retrieval/context transport. They preserve
legacy category names used by saved manifests and review contracts.
"""

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

GENERATED_BUILD_SEGMENTS = {
    "_output",
    "_claw_output",
    "generated",
    "gen",
    "build",
    "dist",
    "target",
    "out",
    ".dart_tool",
    ".terraform",
    "tmp",
    "cache",
    ".cache",
    "coverage",
    "deriveddata",
    "deriveddatacache",
    "saved",
    "intermediate",
    "binaries",
}

RUNTIME_STATE_SEGMENTS = {
    ".premode",
    ".agents",
    ".codex",
    "state",
    "proof",
    "proofs",
    "artifacts",
}

READ_ONLY_MANIFEST_NAMES = {
    "package.json",
    "composer.json",
    "composer.lock",
    "gemfile",
    "gemfile.lock",
    "rakefile",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
    "package.swift",
    "pom.xml",
    "directory.build.props",
    "directory.build.targets",
    "packages.lock.json",
    "build.zig",
    "build.zig.zon",
    "stack.yaml",
    "cabal.project",
    "mvnw",
    "gradlew",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    ".terraform.lock.hcl",
    "makefile",
    "sconstruct",
    "cmakelists.txt",
    "justfile",
}

MANIFEST_EDIT_RE = re.compile(
    r"(?i)\b("
    r"dependenc(?:y|ies)|package(?:\.json)?|package metadata|project files?|project metadata|manifest|lockfile|lock file|script|scripts|"
    r"maven|gradle|pom\.xml|mvnw|gradlew|go\.mod|go\.sum|cargo\.toml|pyproject\.toml|"
    r"requirements(?:[-.]txt)?|\.csproj|\.sln|cabal|stack\.yaml|build\.zig(?:\.zon)?|"
    r"build config|build script|config file|configuration file"
    r")\b"
)

NEGATIVE_MANIFEST_RE = re.compile(
    r"(?i)\b(?:do not|don't|dont|must not|never|avoid|without|leave)\b[^\n;]*"
    r"(?:package(?:\.json)?|package metadata|project files?|project metadata|manifest|dependenc(?:y|ies)|scripts?|lockfile|lock file|"
    r"pom\.xml|mvnw|gradlew|go\.mod|go\.sum|cargo\.toml|pyproject\.toml|requirements)"
)


def normalize_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/")


def path_matches_any(path: str, patterns: list[str] | tuple[str, ...] | set[str]) -> bool:
    lower = normalize_path(path).lower()
    for pattern in patterns:
        p = normalize_path(str(pattern)).lower()
        if not p:
            continue
        if fnmatch(lower, p):
            return True
        if p.startswith("*") and lower.endswith(p[1:]):
            return True
        if p.endswith("/*"):
            base = p[:-2].strip("/")
            if lower == base or lower.startswith(base + "/"):
                return True
        if lower == p or lower.startswith(p.rstrip("/") + "/") or lower.endswith("/" + p):
            return True
    return False


def path_is_same_or_suffix(path: str, candidates: set[str] | list[str] | tuple[str, ...]) -> bool:
    lower = normalize_path(path).lower()
    return any(
        lower == normalize_path(str(candidate)).lower()
        or lower.endswith("/" + normalize_path(str(candidate)).lower())
        or lower.endswith(normalize_path(str(candidate)).lower())
        for candidate in candidates
        if str(candidate).strip()
    )


def prompt_allows_manifest_edits(raw_prompt: str) -> bool:
    prompt = raw_prompt or ""
    if NEGATIVE_MANIFEST_RE.search(prompt):
        return False
    return bool(MANIFEST_EDIT_RE.search(prompt))


def is_read_only_manifest_path(path: str) -> bool:
    lower = normalize_path(path).lower()
    name = Path(lower).name
    return (
        name in READ_ONLY_MANIFEST_NAMES
        or lower == ".premode/commands.json"
        or name.endswith((".sln", ".csproj", ".cabal"))
    )


def is_generated_or_build_output_path(path: str) -> bool:
    lower = normalize_path(path).lower()
    if not lower:
        return False
    parts = [part for part in lower.split("/") if part]
    name = Path(lower).name
    if any(part in GENERATED_BUILD_SEGMENTS for part in parts):
        return True
    if any(part.startswith("bazel-") for part in parts):
        return True
    return (
        name.endswith(".pb.go")
        or name.endswith(".g.dart")
        or ".generated." in lower
        or ".gen." in lower
        or "_generated." in lower
        or name.endswith(".tfstate")
        or name.endswith(".tfstate.backup")
        or name.endswith(".ckpt")
        or name.endswith(".pt")
        or name.endswith(".pth")
        or name.endswith(".onnx")
    )


def is_secret_state_proof_runtime_path(path: str) -> bool:
    lower = normalize_path(path).lower()
    parts = [part for part in lower.split("/") if part]
    name = Path(lower).name
    if any(part in RUNTIME_STATE_SEGMENTS for part in parts):
        return True
    return (
        name.startswith(".env")
        or name.endswith(".pem")
        or name.endswith(".key")
        or name.endswith(".p12")
        or name.endswith(".pfx")
        or name in {"id_rsa", "id_ed25519"}
        or "secret" in name
        or "credential" in name
        or "token" in name
    )


def classify_path_for_routing(
    path: str,
    raw_prompt: str = "",
    *,
    explicit_paths: set[str] | None = None,
    prompt_forbidden_paths: set[str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_path(path)
    explicit_paths = explicit_paths or set()
    prompt_forbidden_paths = prompt_forbidden_paths or set()
    explicit = path_is_same_or_suffix(normalized, explicit_paths)
    prompt_forbidden = path_is_same_or_suffix(normalized, prompt_forbidden_paths)
    manifest_authorized = (explicit or prompt_allows_manifest_edits(raw_prompt)) and not prompt_forbidden

    if prompt_forbidden:
        return {
            "category": "forbidden_or_prompt_blocked",
            "reason": "prompt_forbidden_boundary",
            "editable": False,
            "explicitly_authorized": False,
        }
    if is_secret_state_proof_runtime_path(normalized):
        return {
            "category": "secret_state_proof_runtime",
            "reason": "secret_state_proof_runtime_boundary",
            "editable": False,
            "explicitly_authorized": explicit,
        }
    if is_generated_or_build_output_path(normalized):
        return {
            "category": "generated_or_build_output",
            "reason": "generated_build_output_boundary",
            "editable": bool(explicit and not prompt_forbidden),
            "explicitly_authorized": explicit and not prompt_forbidden,
        }
    if is_read_only_manifest_path(normalized) and not manifest_authorized:
        return {
            "category": "read_only_manifest",
            "reason": "read_only_manifest_boundary",
            "editable": False,
            "explicitly_authorized": False,
        }
    return {
        "category": "editable_source_or_support",
        "reason": "editable_candidate",
        "editable": True,
        "explicitly_authorized": explicit,
    }


def is_restricted_edit_bucket_path(
    path: str,
    raw_prompt: str = "",
    *,
    explicit_paths: set[str] | None = None,
    prompt_forbidden_paths: set[str] | None = None,
    include_read_only_manifests: bool = True,
) -> bool:
    safety = classify_path_for_routing(
        path,
        raw_prompt,
        explicit_paths=explicit_paths,
        prompt_forbidden_paths=prompt_forbidden_paths,
    )
    if safety["category"] == "read_only_manifest" and not include_read_only_manifests:
        return False
    return safety["category"] != "editable_source_or_support" and not safety.get("editable")
