from __future__ import annotations

"""Context selection constraints for transport and routing.

These helpers classify paths for retrieval/context transport. They preserve
legacy category names used by saved manifests and review contracts.
"""

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

SOURCE_CODE_SECRET_FALSE_POSITIVE_SUFFIXES = {
    ".c",
    ".cpp",
    ".cs",
    ".dart",
    ".ex",
    ".exs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
    ".zig",
}
SENSITIVE_STATE_PATH_SEGMENTS = {
    ".agents",
    ".codex",
    ".git",
    ".premode",
    "._backup_codex",
}
SOURCE_LIKE_ROOT_SEGMENTS = {"app", "apps", "lib", "packages", "services", "src"}
SENSITIVE_EXACT_FILENAMES = {
    ".npmrc",
    ".pypirc",
    "aws_credentials",
    "id_ed25519",
    "id_rsa",
}
SENSITIVE_SUFFIXES = (
    ".cer",
    ".crt",
    ".jks",
    ".key",
    ".keystore",
    ".mobileprovision",
    ".p12",
    ".pem",
    ".pfx",
    ".ppk",
)
SECRET_CONFIG_SUFFIXES = {
    "",
    ".bak",
    ".cfg",
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".local",
    ".secret",
    ".secrets",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_CONFIG_TERMS = {"auth", "credential", "credentials", "secret", "secrets", "token", "tokens"}

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
    ".cache",
    ".next",
    "coverage",
    "deriveddata",
    "deriveddatacache",
    "node_modules",
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
    if parts and parts[0] == "cache":
        return True
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


def _split_name_terms(name: str) -> set[str]:
    return {term for term in re.split(r"[^a-z0-9]+", name.lower()) if term}


def _is_env_like_name(name: str) -> bool:
    if name == ".env" or name.startswith(".env."):
        return True
    if name == "env.local" or name.endswith(".env"):
        return True
    if name.startswith("env.") and name.endswith(".bak"):
        return True
    if name.startswith("env.local.") and name.endswith(".bak"):
        return True
    return name.endswith(".env.bak")


def _is_secret_config_like_name(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    stem = Path(name).stem.lower()
    terms = _split_name_terms(stem)
    if name.startswith(("secrets.", "secret.", "credentials.", "credential.")):
        return True
    if name.endswith((".secret", ".secrets", ".credentials")):
        return True
    if suffix in SOURCE_CODE_SECRET_FALSE_POSITIVE_SUFFIXES:
        return False
    return bool(terms & SECRET_CONFIG_TERMS and suffix in SECRET_CONFIG_SUFFIXES)


def is_sensitive_or_secret_path(path: str) -> bool:
    """Return True for path/name-only secret or local-state candidates."""
    lower = normalize_path(path).lower()
    if not lower:
        return False
    parts = [part for part in lower.split("/") if part]
    name = Path(lower).name
    if any(part in SENSITIVE_STATE_PATH_SEGMENTS for part in parts):
        return True
    if name in SENSITIVE_EXACT_FILENAMES:
        return True
    if _is_env_like_name(name):
        return True
    if name.endswith(SENSITIVE_SUFFIXES):
        return True
    if _is_secret_config_like_name(name):
        return True
    if any("backup" in part for part in parts[:-1]) and (_is_env_like_name(name) or _is_secret_config_like_name(name)):
        return True
    return False


def is_secret_state_proof_runtime_path(path: str) -> bool:
    lower = normalize_path(path).lower()
    parts = [part for part in lower.split("/") if part]
    if is_sensitive_or_secret_path(lower):
        return True
    if any(part in RUNTIME_STATE_SEGMENTS for part in parts):
        return True
    return False


def is_source_like_path(path: str) -> bool:
    lower = normalize_path(path).lower()
    parts = [part for part in lower.split("/") if part]
    suffix = Path(lower).suffix.lower()
    if suffix not in SOURCE_CODE_SECRET_FALSE_POSITIVE_SUFFIXES:
        return False
    return bool(parts and (parts[0] in SOURCE_LIKE_ROOT_SEGMENTS or "src" in parts or "sources" in parts))


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
    if is_secret_state_proof_runtime_path(normalized) and not is_source_like_path(normalized):
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
