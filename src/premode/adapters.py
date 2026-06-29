from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .intake import build_intake_report, intake_score_delta


PRIMARY_ROOT_MARKERS: tuple[str, ...] = (
    ".git",
    "pyproject.toml",
    "package.json",
    "mix.exs",
    "composer.json",
    "Gemfile",
    "Cargo.toml",
    "go.mod",
    "Package.swift",
    "SConstruct",
    "SCsub",
    "CMakeLists.txt",
    "meson.build",
    "BUILD.bazel",
    "WORKSPACE",
    "pom.xml",
    ".sln",
    ".csproj",
    "Directory.Build.props",
    "Directory.Build.targets",
    "build.zig",
    "build.zig.zon",
    "stack.yaml",
    ".cabal",
    "cabal.project",
    "build.gradle",
    "settings.gradle",
    "build.gradle.kts",
    "settings.gradle.kts",
    ".terraform.lock.hcl",
    "backend.tf",
    "providers.tf",
    ".xcodeproj",
    ".xcworkspace",
    "ProjectSettings",
    "Assets",
)

ROOT_MARKER_PRIORITY: dict[str, int] = {
    ".git": 130,
    "pyproject.toml": 100,
    "package.json": 100,
    "mix.exs": 105,
    "composer.json": 106,
    "gemfile": 106,
    "cargo.toml": 100,
    "go.mod": 100,
    "package.swift": 100,
    "sconstruct": 120,
    "scsub": 90,
    "cmakelists.txt": 105,
    "meson.build": 105,
    "build.bazel": 105,
    "workspace": 105,
    "pom.xml": 95,
    ".sln": 96,
    ".csproj": 94,
    "directory.build.props": 88,
    "directory.build.targets": 88,
    "build.zig": 98,
    "build.zig.zon": 92,
    "stack.yaml": 98,
    ".cabal": 96,
    "cabal.project": 96,
    "build.gradle": 95,
    "settings.gradle": 95,
    "build.gradle.kts": 95,
    "settings.gradle.kts": 95,
    ".terraform.lock.hcl": 88,
    "backend.tf": 96,
    "providers.tf": 96,
    ".xcodeproj": 95,
    ".xcworkspace": 95,
    "projectsettings": 85,
    "assets": 80,
}

PENALIZED_ROOT_SEGMENTS: tuple[str, ...] = (
    "_external_references",
    "node_modules",
    "vendor",
    "third_party",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "_claw_output",
    "generated",
    "artifacts",
    "proof",
    "proofs",
    "state",
    "saved",
    "intermediate",
    "binaries",
    "deriveddatacache",
)



OPENCLAW_AUTHORITY_MARKERS: tuple[str, ...] = (
    "AGENTS.md",
    "WORKFLOW.md",
    "PROJECT/tasks.json",
    "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    "PROJECT/state/worker_start/WORKER_STARTER_CONTEXT_V1.json",
    "PROJECT/state/task_queue_normalized_latest.json",
    "PROJECT/state/path_authority_latest.json",
    "PROJECT/state/artifact_authority_latest.json",
    "PROJECT/AI/OUTPUT_HYGIENE_GUARDRAILS.md",
    "ARTIFACT_STORAGE.md",
    "EXTERNAL_ARTIFACTS_INDEX.md",
)

OPENCLAW_EVIDENCE_ONLY_PATTERNS: tuple[str, ...] = (
    "_claw_output/",
    "PROJECT/state/history/",
    "PROJECT/state/archive/",
    "PROJECT/artifacts/generated/",
    "logs/",
    "proof/",
    "proofs/",
)

OPENCLAW_DANGEROUS_MUTATION_ZONES: tuple[str, ...] = (
    "PROJECT/tasks.json",
    "PROJECT/state/task_queue_normalized_latest.json",
    "PROJECT/state/path_authority_latest.json",
    "PROJECT/state/artifact_authority_latest.json",
    "_claw_output/",
    "Content/",
    "*.uasset",
    "*.umap",
    "*.blend",
)

OPENCLAW_PROOF_POLICY: dict[str, bool] = {
    "do_not_claim_runtime_from_static_or_browser_evidence": True,
    "do_not_claim_collision_or_input_proof_without_same_run_evidence": True,
    "do_not_mutate_bridge_unreal_or_blender_without_authorization": True,
    "do_not_mutate_project_task_queue_without_authorization": True,
    "do_not_treat_historical_proof_as_current_truth": True,
    "human_review_required_for_public_synthesis": True,
}

def _parent_root(rel_path: str) -> str:
    rel_path = rel_path.strip("/")
    if not rel_path or "/" not in rel_path:
        return "."
    return rel_path.rsplit("/", 1)[0] or "."


def _matched_primary_marker(rel_path: str) -> tuple[str, int] | None:
    p = rel_path.strip("/")
    name = Path(p).name
    lower_name = name.lower()
    lower_path = p.lower()
    if lower_name == ".git":
        return name, ROOT_MARKER_PRIORITY[".git"]
    if lower_name in {m.lower() for m in PRIMARY_ROOT_MARKERS if not m.startswith(".")}:
        if lower_name in {"assets", "projectsettings"} and name not in {"Assets", "ProjectSettings"}:
            return None
        return name, ROOT_MARKER_PRIORITY.get(lower_name, 70)
    if p in {"Assets", "ProjectSettings"}:
        return name, ROOT_MARKER_PRIORITY.get(lower_path, 70)
    if p.endswith("/Assets") or p.endswith("/ProjectSettings"):
        return name, ROOT_MARKER_PRIORITY.get(lower_name, 70)
    for suffix in (".xcodeproj", ".xcworkspace", ".sln", ".csproj", ".cabal"):
        if lower_name.endswith(suffix):
            return name, ROOT_MARKER_PRIORITY.get(suffix, 70)
    return None


def _root_depth(root: str) -> int:
    root = root.strip("/")
    if not root or root == ".":
        return 0
    return root.count("/") + 1


def _root_penalty(root: str) -> int:
    lower = root.lower().strip("/")
    if not lower or lower == ".":
        return 0
    parts = set(lower.split("/"))
    penalty = max(0, _root_depth(lower) - 1) * 12
    if parts & set(PENALIZED_ROOT_SEGMENTS):
        penalty += 180
    if lower.startswith("_external_references/") or "/_external_references/" in lower:
        penalty += 260
    return penalty


def _select_marker_root(marker_roots: dict[str, int]) -> str:
    return sorted(marker_roots.items(), key=lambda kv: (-(kv[1] - _root_penalty(kv[0])), _root_depth(kv[0]), kv[0]))[0][0]


def _root_has_penalized_segment(root: str) -> bool:
    parts = {p.lower() for p in root.strip("/").split("/") if p}
    return bool(parts & set(PENALIZED_ROOT_SEGMENTS))


def _root_marker_paths(repo_root: Path, root: str, rel_paths: list[str]) -> list[str]:
    prefix = "" if root == "." else root.strip("/") + "/"
    root_path = repo_root if root == "." else repo_root / root
    markers: set[str] = set()
    if (root_path / ".git").exists():
        markers.add(prefix + ".git")
    scoped = [p for p in rel_paths if not prefix or p == root.strip("/") or p.startswith(prefix)]
    for path in scoped:
        rel = path[len(prefix):] if prefix and path.startswith(prefix) else path
        rel_lower = rel.lower()
        name = Path(rel).name
        lower_name = name.lower()
        if lower_name == "package.json":
            markers.add(prefix + rel)
        elif lower_name == "package.swift" or rel_lower.endswith(".swift"):
            markers.add(prefix + rel)
        elif lower_name.endswith((".xcodeproj", ".xcworkspace")):
            markers.add(prefix + rel)
        elif rel_lower.endswith(".uproject"):
            markers.add(prefix + rel)
        elif rel_lower.startswith(("source/", "config/")):
            markers.add(prefix + rel.split("/", 1)[0] + "/")
        elif lower_name.endswith((".build.cs", ".target.cs")):
            markers.add(prefix + rel)
    return sorted(markers)[:20]


def _root_marker_bonus(markers: list[str]) -> tuple[int, list[str]]:
    lower = [m.lower() for m in markers]
    bonus = 0
    reasons: list[str] = []
    if any(m.endswith("/.git") or m == ".git" for m in lower):
        bonus += 80
        reasons.append(".git marker")
    if any(m.endswith(".uproject") or m.endswith(".build.cs") or m.endswith(".target.cs") or m.endswith("source/") or m.endswith("config/") for m in lower):
        bonus += 110
        reasons.append("unreal/native markers")
    if any(m.endswith(".xcodeproj") or m.endswith(".xcworkspace") or m.endswith("package.swift") or m.endswith(".swift") for m in lower):
        bonus += 100
        reasons.append("ios/swift markers")
    if any(m.endswith("package.json") for m in lower):
        bonus += 25
        reasons.append("package.json marker")
    return bonus, reasons


def _prompt_affinity_bonus(root: str, markers: list[str], prompt: str | None) -> tuple[int, list[str]]:
    prompt_l = (prompt or "").lower()
    root_l = root.lower()
    markers_l = " ".join(m.lower() for m in markers)
    bonus = 0
    reasons: list[str] = []
    has_unreal_marker = any(term in markers_l for term in [".uproject", ".build.cs", ".target.cs", "source/", "config/"])
    has_ios_marker = any(term in markers_l for term in [".xcodeproj", ".xcworkspace", "package.swift", ".swift"])
    has_node_marker = "package.json" in markers_l
    if "openclaw" in prompt_l and "openclaw" in root_l:
        bonus += 650
        reasons.append("prompt mentions OpenClaw and root name matches")
    if any(term in prompt_l for term in ["unreal", "gameplay", "game bug", "native"]):
        if has_unreal_marker or "openclaw" in root_l:
            bonus += 320
            reasons.append("prompt has Unreal/gameplay affinity")
    if any(term in prompt_l for term in ["ios", "swift", "xcode"]):
        if has_ios_marker or "ios" in root_l:
            bonus += 320
            reasons.append("prompt has iOS/Swift/Xcode affinity")
    if any(term in prompt_l for term in ["node", "web", "frontend", "react", "vite", "npm"]):
        if has_node_marker:
            bonus += 120
            reasons.append("prompt has Node/web affinity")
    return bonus, reasons


def _direct_child_git_roots(repo_root: Path) -> list[str]:
    roots: list[str] = []
    try:
        children = sorted(repo_root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return roots
    for child in children:
        if not child.is_dir():
            continue
        name = child.name
        lower = name.lower()
        if lower in set(PENALIZED_ROOT_SEGMENTS) or lower in {".git", ".premode", ".agents", ".codex"}:
            continue
        if (child / ".git").exists():
            roots.append(name)
    return roots


def _root_candidate(
    root: str,
    *,
    source: str,
    base_score: int,
    reasons: list[str],
    project_kind: str | None = None,
    repo_root: Path | None = None,
    rel_paths: list[str] | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    penalty = _root_penalty(root)
    markers = _root_marker_paths(repo_root, root, rel_paths or []) if repo_root is not None else []
    marker_bonus, marker_reasons = _root_marker_bonus(markers)
    prompt_bonus, prompt_reasons = _prompt_affinity_bonus(root, markers, prompt)
    return {
        "root": root,
        "source": source,
        "project_kind": project_kind,
        "score": base_score + marker_bonus + prompt_bonus - penalty,
        "base_score": base_score,
        "marker_bonus": marker_bonus,
        "prompt_affinity_bonus": prompt_bonus,
        "ignored_reference_penalty": penalty,
        "penalty": penalty,
        "depth": _root_depth(root),
        "ignored_or_reference_like": _root_has_penalized_segment(root),
        "markers": markers,
        "reasons": list(dict.fromkeys(reasons + marker_reasons + prompt_reasons)),
    }


def _synthetic_git_project(root: str) -> dict[str, Any]:
    return {
        "project_kind": "generic",
        "adapter": "generic",
        "display_name": ADAPTERS["generic"].display_name,
        "root": root,
        "confidence": 0.95,
        "markers": [f"{root}/.git"],
        "root_selection": {"strategy": "direct_child_git", "marker_roots": {root: ROOT_MARKER_PRIORITY[".git"]}, "source_roots": {}},
        "build_tools": list(ADAPTERS["generic"].build_tools),
        "rule_files": [],
        "important_dirs": [],
    }

SKIP_DIRS = {".git", ".premode", ".agents", "node_modules", "DerivedData", "build", "dist", ".next", ".venv", "venv", "__pycache__", ".build", "target", "vendor", "Pods"}

@dataclass(frozen=True)
class Adapter:
    id: str
    display_name: str
    markers: tuple[str, ...]
    extensions: tuple[str, ...]
    build_tools: tuple[str, ...]
    important_dirs: tuple[str, ...]
    important_files: tuple[str, ...]
    log_patterns: tuple[str, ...]


ADAPTERS: dict[str, Adapter] = {
    "generic": Adapter(
        "generic", "Generic repository", (".git", "README", "README.md"),
        (".py", ".js", ".ts", ".tsx", ".jsx", ".swift", ".rs", ".go", ".java", ".kt", ".ex", ".exs", ".php", ".rb", ".tf", ".c", ".cc", ".cpp", ".h", ".hpp", ".md"),
        ("build", "test"), ("src", "lib", "app", "tests", "test", "docs", "logs"),
        ("AGENTS.md", "README.md", "README", "CONTRIBUTING.md", "CHANGELOG.md"),
        ("error:", "failed", "traceback", "exception", "fatal"),
    ),

    "openclaw_control_plane": Adapter(
        "openclaw_control_plane", "OpenClaw / Proof-Governed Control Plane",
        (
            "AGENTS.md",
            "WORKFLOW.md",
            "PROJECT/tasks.json",
            "PROJECT/AI/worker_start/WORKER_START_HERE.md",
            "PROJECT/state/task_queue_normalized_latest.json",
            "PROJECT/state/path_authority_latest.json",
            "PROJECT/state/artifact_authority_latest.json",
            "_claw_output",
            "tools/gamebot",
            "tools/symphony",
        ),
        (".py", ".md", ".json", ".toml", ".yaml", ".yml"),
        ("pytest", "python"),
        ("PROJECT", "PROJECT/AI", "PROJECT/state", "tools/gamebot", "tools/symphony", "tests", "docs"),
        (
            "AGENTS.md",
            "WORKFLOW.md",
            "PROJECT/AI/worker_start/WORKER_START_HERE.md",
            "PROJECT/state/worker_start/WORKER_STARTER_CONTEXT_V1.json",
            "PROJECT/state/task_queue_normalized_latest.json",
            "PROJECT/state/path_authority_latest.json",
            "PROJECT/state/artifact_authority_latest.json",
            "PROJECT/AI/OUTPUT_HYGIENE_GUARDRAILS.md",
            "ARTIFACT_STORAGE.md",
            "EXTERNAL_ARTIFACTS_INDEX.md",
        ),
        ("FAILED", "Traceback", "AssertionError", "proof", "validator", "bridge", "runtime", "error"),
    ),
    "ios_swift": Adapter(
        "ios_swift", "iOS / Swift", ("Package.swift", ".xcodeproj", ".xcworkspace"),
        (".swift",), ("xcodebuild", "swift"), ("Sources", "Tests", "Docs"),
        ("Package.swift", "project.pbxproj", "AGENTS.md", "README.md"),
        ("SwiftCompile", "CompileSwift", "xcodebuild: error", "No such module", "Cannot find", "has no member", "error:"),
    ),
    "node": Adapter(
        "node", "Node / Web", ("package.json", "vite.config", "next.config", "webpack.config", "tsconfig.json"),
        (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"), ("npm", "pnpm", "yarn", "node", "tsc"),
        ("src", "app", "pages", "components", "tests", "test", "public"),
        ("package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "tsconfig.json", "vite.config.ts", "next.config.js"),
        ("Module not found", "TypeError", "ReferenceError", "npm ERR!", "vite", "webpack", "TS2307", "TS2322", "error"),
    ),
    "python": Adapter(
        "python", "Python", ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "pytest.ini"),
        (".py",), ("pytest", "python", "ruff", "mypy"), ("src", "tests", "test", "docs"),
        ("pyproject.toml", "requirements.txt", "setup.py", "pytest.ini", "tox.ini", "AGENTS.md", "README.md"),
        ("Traceback", "ModuleNotFoundError", "ImportError", "AssertionError", "FAILED", "E   ", "pytest"),
    ),
    "rust": Adapter(
        "rust", "Rust", ("Cargo.toml", "Cargo.lock"), (".rs",), ("cargo",), ("src", "tests", "benches"),
        ("Cargo.toml", "Cargo.lock"), ("error[E", "could not compile", "thread '", "panicked", "cargo check"),
    ),
    "go": Adapter(
        "go", "Go", ("go.mod", "go.sum"), (".go",), ("go",), ("cmd", "pkg", "internal", "test"),
        ("go.mod", "go.sum"), ("cannot find package", "undefined:", "go test", "panic:"),
    ),
    "elixir_phoenix": Adapter(
        "elixir_phoenix", "Elixir / Phoenix / Mix",
        ("mix.exs", "mix.lock", "config", "priv"),
        (".ex", ".exs"),
        ("mix",),
        ("lib", "test", "config", "priv", "assets"),
        ("mix.exs", "mix.lock", "config/config.exs", "config/runtime.exs"),
        ("** (", "mix test", "Compilation error", "UndefinedFunctionError", "Phoenix"),
    ),
    "php_composer": Adapter(
        "php_composer", "PHP / Composer",
        ("composer.json", "composer.lock", "phpunit.xml", "phpunit.xml.dist"),
        (".php",),
        ("composer", "phpunit", "php"),
        ("core", "plugins", "src", "app", "tests", "tests/PHPUnit"),
        ("composer.json", "composer.lock", "phpunit.xml", "phpunit.xml.dist"),
        ("PHP Fatal error", "PHPUnit", "Parse error", "composer"),
    ),
    "ruby_rails": Adapter(
        "ruby_rails", "Ruby / Rails",
        ("Gemfile", "Gemfile.lock", "Rakefile", "config/routes.rb"),
        (".rb",),
        ("bundle", "rails", "rake"),
        ("app", "lib", "spec", "test", "config"),
        ("Gemfile", "Gemfile.lock", "Rakefile", "config/routes.rb"),
        ("RSpec", "Failure/Error", "NameError", "bundle exec", "rails test"),
    ),
    "terraform": Adapter(
        "terraform", "Terraform / IaC",
        ("backend.tf", "providers.tf", ".terraform.lock.hcl"),
        (".tf", ".tfvars"),
        ("terraform",),
        ("modules", "environments", "envs"),
        ("backend.tf", "providers.tf", ".terraform.lock.hcl"),
        ("terraform", "Error:", "Invalid value", "Unsupported argument"),
    ),
    "dotnet_csharp": Adapter(
        "dotnet_csharp", ".NET / C#",
        (".sln", ".csproj", "Directory.Build.props", "Directory.Build.targets"),
        (".cs",),
        ("dotnet",),
        ("src", "app", "lib", "tests", "test"),
        ("*.sln", "*.csproj", "Directory.Build.props", "Directory.Build.targets", "packages.lock.json"),
        ("dotnet test", "dotnet build", "CS", "error"),
    ),
    "zig": Adapter(
        "zig", "Zig",
        ("build.zig", "build.zig.zon"),
        (".zig",),
        ("zig",),
        ("src", "test", "tests"),
        ("build.zig", "build.zig.zon"),
        ("zig build", "zig test", "error:"),
    ),
    "haskell_stack_cabal": Adapter(
        "haskell_stack_cabal", "Haskell / Stack / Cabal",
        ("stack.yaml", ".cabal", "cabal.project"),
        (".hs",),
        ("stack", "cabal"),
        ("src", "app", "test", "tests"),
        ("stack.yaml", "*.cabal", "cabal.project"),
        ("stack test", "cabal test", "error:"),
    ),

    "native_cpp": Adapter(
        "native_cpp", "Native C/C++ / SCons/CMake Engine",
        ("SConstruct", "SCsub", "CMakeLists.txt", "meson.build", "BUILD.bazel", "WORKSPACE"),
        (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"),
        ("scons", "cmake", "ninja", "make"),
        ("core", "scene", "modules", "platform", "servers", "drivers", "tests"),
        ("SConstruct", "SCsub", "CMakeLists.txt", "meson.build", "BUILD.bazel", "WORKSPACE"),
        ("error:", "undefined reference", "CXX", "scons", "ninja", "FAILED"),
    ),
    "java_kotlin": Adapter(
        "java_kotlin", "Java / Kotlin", ("pom.xml", "build.gradle", "settings.gradle", "build.gradle.kts", "settings.gradle.kts"),
        (".java", ".kt", ".kts"), ("gradle", "maven", "mvn"), ("src", "test", "main"),
        ("pom.xml", "build.gradle", "settings.gradle", "build.gradle.kts"), ("BUILD FAILED", "Compilation failed", "cannot find symbol", "Exception", "error:"),
    ),
    "unity": Adapter(
        "unity", "Unity", ("Assets", "ProjectSettings", "Packages/manifest.json"),
        (".cs", ".shader", ".asmdef"), ("Unity",), ("Assets", "ProjectSettings", "Packages"),
        ("ProjectSettings/ProjectVersion.txt", "Packages/manifest.json"), ("CS", "error", "UnityException", "NullReferenceException"),
    ),
}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_repo_paths(repo_root: Path, max_files: int = 30000) -> list[str]:
    paths: list[str] = []
    count = 0
    for current, dirs, files in os.walk(repo_root):
        cur = Path(current)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_cur = _rel(cur, repo_root) if cur != repo_root else ""
        for d in dirs:
            paths.append(f"{rel_cur}/{d}".strip("/"))
        for f in files:
            if count >= max_files:
                return paths
            count += 1
            paths.append(f"{rel_cur}/{f}".strip("/"))
    return paths


def _iter_filesystem_root_markers(repo_root: Path, max_dirs: int = 30000) -> list[str]:
    """Return project-marker paths that may be absent from the readable index.

    The index intentionally skips many directories and only stores readable
    files. Xcode/Unity markers such as `*.xcodeproj`, `*.xcworkspace`,
    `Assets/`, and `ProjectSettings/` are often directories, so compile-time
    detection must merge marker directories from the filesystem instead of
    relying only on indexed file entries.
    """
    markers: list[str] = []
    count = 0
    file_markers = {
        "pyproject.toml", "package.json", "mix.exs", "composer.json", "composer.lock", "gemfile", "gemfile.lock",
        "cargo.toml", "go.mod",
        "package.swift", "pom.xml", "build.gradle", "settings.gradle",
        "build.gradle.kts", "settings.gradle.kts", ".terraform.lock.hcl", "backend.tf", "providers.tf",
        "build.zig", "build.zig.zon", "stack.yaml", "cabal.project", "directory.build.props", "directory.build.targets",
    }
    for current, dirs, files in os.walk(repo_root):
        cur = Path(current)
        rel_cur = _rel(cur, repo_root) if cur != repo_root else ""
        kept_dirs: list[str] = []
        for d in dirs:
            count += 1
            rel = f"{rel_cur}/{d}".strip("/")
            lower = d.lower()
            if lower == ".git":
                markers.append(rel)
                continue
            if lower.endswith((".xcodeproj", ".xcworkspace")) or d in {"Assets", "ProjectSettings"}:
                markers.append(rel)
                # Do not descend into package/project marker directories.
                continue
            if d in SKIP_DIRS:
                continue
            kept_dirs.append(d)
            if count >= max_dirs:
                break
        dirs[:] = kept_dirs
        for f in files:
            if f.lower() in file_markers or f in {"SConstruct", "SCsub", "CMakeLists.txt", "BUILD.bazel", "WORKSPACE", "Gemfile", "Rakefile", "Directory.Build.props", "Directory.Build.targets"} or f.lower() == "meson.build" or f.endswith((".unity", ".asmdef", ".tf", ".sln", ".csproj", ".cabal")):
                markers.append(f"{rel_cur}/{f}".strip("/"))
        if count >= max_dirs:
            break
    return sorted(set(markers))


def _root_for_marker_suffix(marker_path: str, marker_suffix: str) -> str | None:
    marker = marker_path.strip("/")
    suffix = marker_suffix.strip("/")
    lower_marker = marker.lower()
    lower_suffix = suffix.lower()
    if lower_marker == lower_suffix:
        return "."
    if lower_marker.endswith("/" + lower_suffix):
        prefix = marker[:-(len(suffix) + 1)].strip("/")
        return prefix or "."
    return None




def _prompt_mentioned_paths(prompt: str | None, rel_paths: list[str]) -> list[str]:
    if not prompt:
        return []
    indexed = {p.lower(): p for p in rel_paths}
    mentioned: list[str] = []
    for raw in str(prompt).replace('\\', '/').split():
        token = raw.strip().strip('`\'"()[]{}<>.,;!')
        lower = token.lower().lstrip('/')
        if not lower:
            continue
        if lower in indexed:
            mentioned.append(indexed[lower])
            continue
        if '/' in lower:
            for path_lower, original in indexed.items():
                if path_lower.endswith('/' + lower):
                    mentioned.append(original)
    seen: set[str] = set()
    out: list[str] = []
    for item in mentioned:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _nearest_marker_root_for_path(path: str, rel_paths: list[str]) -> str | None:
    marker_paths = [p for p in rel_paths if _matched_primary_marker(p)]
    path_parts = path.strip('/').split('/')[:-1]
    best: tuple[int, str] | None = None
    for marker in marker_paths:
        root = _parent_root(marker)
        if root == '.':
            depth = 0
            prefix_match = True
        else:
            prefix_match = path == root or path.startswith(root.rstrip('/') + '/')
            depth = root.count('/') + 1
        if prefix_match and (best is None or depth > best[0]):
            best = (depth, root)
    return best[1] if best else None

def _is_openclaw_authority_path(path: str) -> bool:
    lower = path.strip("/").lower()
    return any(lower == marker.lower() for marker in OPENCLAW_AUTHORITY_MARKERS)


def _is_openclaw_evidence_only_path(path: str) -> bool:
    lower = path.strip("/").lower()
    return any(lower.startswith(pattern.lower()) or (pattern.startswith("*") and lower.endswith(pattern[1:].lower())) for pattern in OPENCLAW_EVIDENCE_ONLY_PATTERNS)


def openclaw_policy_from_detection(detection: dict[str, Any]) -> dict[str, Any] | None:
    active = detection.get("active_project", {}) if isinstance(detection, dict) else {}
    if active.get("adapter") != "openclaw_control_plane":
        return None
    return {
        "authority_model": "proof_governed_control_plane",
        "authority_surfaces": list(OPENCLAW_AUTHORITY_MARKERS),
        "evidence_only_patterns": list(OPENCLAW_EVIDENCE_ONLY_PATTERNS),
        "dangerous_mutation_zones": list(OPENCLAW_DANGEROUS_MUTATION_ZONES),
        "proof_policy": dict(OPENCLAW_PROOF_POLICY),
        "notes": [
            "Current authority surfaces outrank historical/generated proof artifacts.",
            "Generated proof/log folders are evidence-only unless explicitly task-named.",
            "Bridge, Unreal, Blender, and task-queue mutation require explicit authorization.",
        ],
    }

def detect_projects(repo_root: Path, entries: list[dict[str, Any]] | None = None, cwd: Path | None = None, prompt: str | None = None) -> dict[str, Any]:
    if entries is None:
        rel_paths = _iter_repo_paths(repo_root)
    else:
        # Indexed entries are readable files only. Merge filesystem-level root
        # markers so compile-time detection does not lose directory markers such
        # as `.xcodeproj` and then fall back to source frequency.
        rel_paths = [str(e.get("path", "")) for e in entries]
        rel_paths.extend(_iter_filesystem_root_markers(repo_root))
        rel_paths = sorted({p for p in rel_paths if p})
    rel_set = set(rel_paths)
    lower_paths = [p.lower() for p in rel_paths]
    intake_report = build_intake_report(repo_root, rel_paths)
    detected: list[dict[str, Any]] = []
    direct_child_git_roots = _direct_child_git_roots(repo_root)
    prompt_l = (prompt or "").lower()

    for kind, adapter in ADAPTERS.items():
        if kind == "generic":
            continue
        markers: list[str] = []
        marker_roots: dict[str, int] = {}
        source_roots: dict[str, int] = {}
        ext_hits = 0

        for p, pl in zip(rel_paths, lower_paths):
            path_obj = Path(p)
            name = path_obj.name
            suffix = path_obj.suffix.lower()
            if suffix in adapter.extensions:
                ext_hits += 1
                root = p.split("/", 1)[0] if "/" in p else "."
                source_roots[root] = source_roots.get(root, 0) + 1

            matched_adapter_marker = False
            for marker in adapter.markers:
                ml = marker.lower()
                if kind == "unity" and ml == "assets" and name != "Assets":
                    continue
                if ml.startswith(".") and pl.endswith(ml):
                    matched_adapter_marker = True
                elif "/" in ml and pl.endswith(ml):
                    matched_adapter_marker = True
                elif name.lower() == ml or pl.endswith("/" + ml):
                    matched_adapter_marker = True
                if matched_adapter_marker:
                    markers.append(p)
                    break

            primary = _matched_primary_marker(p)
            if primary and (matched_adapter_marker or kind == "unity"):
                _marker, priority = primary
                root = _parent_root(p)
                marker_roots[root] = max(marker_roots.get(root, 0), priority)

        if kind == "unity":
            strong_unity = any(
                p == "ProjectSettings/ProjectVersion.txt"
                or p == "Packages/manifest.json"
                or p.endswith(".unity")
                or p.endswith(".asmdef")
                or p == "ProjectSettings"
                or p.startswith("ProjectSettings/")
                for p in rel_paths
            )
            has_upper_assets = "Assets" in rel_set or any(p.startswith("Assets/") for p in rel_paths)
            has_project_settings = "ProjectSettings" in rel_set or any(p.startswith("ProjectSettings/") for p in rel_paths)
            if "Assets" in rel_set or any(p.startswith("Assets/") for p in rel_paths):
                markers.append("Assets/")
                marker_roots["."] = max(marker_roots.get(".", 0), ROOT_MARKER_PRIORITY["assets"])
            if "ProjectSettings" in rel_set or any(p.startswith("ProjectSettings/") for p in rel_paths):
                markers.append("ProjectSettings/")
                marker_roots["."] = max(marker_roots.get(".", 0), ROOT_MARKER_PRIORITY["projectsettings"])
            if not strong_unity and not (has_upper_assets and has_project_settings):
                continue

        if kind == "terraform" and ext_hits:
            marker_roots["."] = max(marker_roots.get(".", 0), 96)
            if not markers:
                markers.append("terraform_files")

        if kind == "native_cpp":
            native_markers = {m for m in markers if Path(m).name in {"SConstruct", "SCsub", "CMakeLists.txt", "meson.build", "BUILD.bazel", "WORKSPACE"}}
            engine_dirs = {"core", "scene", "modules", "platform", "servers", "drivers"}
            engine_hits = sum(1 for p in rel_paths if p.split("/", 1)[0].lower() in engine_dirs)
            if native_markers or engine_hits >= 4:
                marker_roots["."] = max(marker_roots.get(".", 0), 118 if "SConstruct" in {Path(m).name for m in native_markers} else 104)
                if not markers and engine_hits >= 4:
                    markers.append("native_engine_layout")
            elif ext_hits < 5:
                continue

        if kind == "openclaw_control_plane":
            # OpenClaw/control-plane detection must be marker-driven. Plain
            # Python/Markdown/JSON files are not enough, or generic repos with
            # AGENTS.md would be falsely promoted into the control-plane adapter.
            strong_markers = {m for m in markers if m.lower() not in {"agents.md", "readme.md", "readme"}}
            if len(strong_markers) < 3:
                continue
            # OpenClaw/control-plane authority markers define the repository root.
            # Do not let nested Node executor/package.json markers hijack the active project.
            authority_roots: dict[str, int] = {}
            for marker in strong_markers:
                for authority in (*OPENCLAW_AUTHORITY_MARKERS, "_claw_output", "tools/gamebot", "tools/symphony"):
                    root = _root_for_marker_suffix(marker, authority)
                    if root is not None:
                        authority_roots[root] = authority_roots.get(root, 0) + 1
                        break
            if authority_roots:
                root = sorted(authority_roots.items(), key=lambda kv: (-kv[1], _root_penalty(kv[0]), _root_depth(kv[0]), kv[0]))[0][0]
                marker_roots[root] = max(marker_roots.get(root, 0), 125)
            else:
                marker_roots["."] = max(marker_roots.get(".", 0), 120)

        if not markers and ext_hits == 0:
            continue

        if marker_roots:
            # Project markers are authoritative. Prefer strongest marker, then shortest path.
            root = _select_marker_root(marker_roots)
        elif source_roots:
            root = sorted(source_roots.items(), key=lambda x: (-(x[1] - _root_penalty(x[0])), _root_depth(x[0]), x[0]))[0][0]
        else:
            root = "."

        marker_score = min(0.55, 0.18 * len(set(markers)))
        ext_score = min(0.30, 0.02 * ext_hits)
        prompt_score = 0.10 if (kind.replace("_", " ") in prompt_l or kind.split("_")[0] in prompt_l) else 0
        confidence = round(min(0.99, 0.32 + marker_score + ext_score + prompt_score), 2)
        if kind in {"elixir_phoenix", "php_composer", "ruby_rails", "terraform"} and markers:
            confidence = round(min(0.99, confidence + 0.12), 2)
        if kind == "node" and any(Path(p).name in {"mix.exs", "composer.json", "Gemfile"} for p in rel_paths):
            confidence = round(max(0.10, confidence - 0.18), 2)
        confidence = round(max(0.10, confidence - min(0.35, _root_penalty(root) / 800)), 2)
        extra: dict[str, Any] = {}
        if kind == "openclaw_control_plane" and markers:
            authority_hits = [m for m in sorted(set(markers)) if _is_openclaw_authority_path(m) or m.lower() in {"_claw_output", "tools/gamebot", "tools/symphony"}]
            confidence = round(min(0.99, 0.72 + 0.04 * len(authority_hits) + prompt_score), 2)
            openclaw_traits = sorted(set(intake_report.get("traits", [])) | {
                "proof_governed_candidate",
                "control_plane_candidate",
                "authority_surface_driven",
                "generated_artifact_heavy",
                "nested_executor_present" if any("executor/" in p.lower() or "/executor/" in p.lower() for p in rel_paths) else "openclaw_profile",
            })
            extra = {
                "authority_model": "proof_governed_control_plane",
                "authority_surfaces": [m for m in OPENCLAW_AUTHORITY_MARKERS if Path(repo_root / m).exists()],
                "evidence_only_patterns": list(OPENCLAW_EVIDENCE_ONLY_PATTERNS),
                "dangerous_mutation_zones": list(OPENCLAW_DANGEROUS_MUTATION_ZONES),
                "proof_policy": dict(OPENCLAW_PROOF_POLICY),
                "profile": "openclaw",
                "traits": openclaw_traits,
            }
        detected.append({
            "project_kind": kind,
            "adapter": kind,
            "display_name": adapter.display_name,
            "root": root,
            "confidence": confidence,
            "markers": sorted(set(markers))[:20],
            "root_selection": {"strategy": "primary_marker" if marker_roots else "source_frequency", "marker_roots": marker_roots, "source_roots": source_roots},
            "build_tools": list(adapter.build_tools),
            "rule_files": [p for p in adapter.important_files if Path(repo_root / p).exists()],
            "important_dirs": [d for d in adapter.important_dirs if any(x == d or x.startswith(d.rstrip('/') + '/') for x in rel_paths)],
            **extra,
        })

    existing_roots = {str(d.get("root") or ".") for d in detected}
    for git_root in direct_child_git_roots:
        if git_root not in existing_roots:
            detected.append(_synthetic_git_project(git_root))

    if not detected:
        detected.append({
            "project_kind": "generic",
            "adapter": "generic",
            "display_name": ADAPTERS["generic"].display_name,
            "root": ".",
            "confidence": 1.0,
            "markers": [p for p in [".git", "README.md", "AGENTS.md"] if (repo_root / p).exists()],
            "root_selection": {"strategy": "generic_fallback"},
            "build_tools": list(ADAPTERS["generic"].build_tools),
            "rule_files": [p for p in ADAPTERS["generic"].important_files if (repo_root / p).exists()],
            "important_dirs": [d for d in ADAPTERS["generic"].important_dirs if (repo_root / d).exists()],
        })
    active_root_candidates: list[dict[str, Any]] = []
    for git_root in direct_child_git_roots:
        active_root_candidates.append(_root_candidate(
            git_root,
            source="direct_child_git",
            base_score=1000,
            reasons=["direct child .git marker"],
            project_kind=next((d.get("project_kind") for d in detected if d.get("root") == git_root), "generic"),
            repo_root=repo_root,
            rel_paths=rel_paths,
            prompt=prompt,
        ))
    for d in detected:
        root = str(d.get("root") or ".")
        marker_count = len(d.get("markers") or [])
        base = int(float(d.get("confidence") or 0) * 100) + marker_count * 5
        if root in direct_child_git_roots:
            base += 250
        active_root_candidates.append(_root_candidate(
            root,
            source=f"adapter:{d.get('adapter')}",
            base_score=base,
            reasons=[str((d.get("root_selection") or {}).get("strategy") or "adapter_detection")],
            project_kind=str(d.get("project_kind") or "generic"),
            repo_root=repo_root,
            rel_paths=rel_paths,
            prompt=prompt,
        ))
    deduped_candidates: dict[str, dict[str, Any]] = {}
    for candidate in active_root_candidates:
        root = str(candidate.get("root") or ".")
        previous = deduped_candidates.get(root)
        if previous is None or int(candidate["score"]) > int(previous["score"]):
            deduped_candidates[root] = candidate
    active_root_candidates = sorted(deduped_candidates.values(), key=lambda c: (-int(c["score"]), int(c["depth"]), str(c["root"])))
    direct_candidates = [c for c in active_root_candidates if c.get("root") in direct_child_git_roots]
    root_selection_ambiguity = None
    if len(direct_candidates) > 1:
        top = direct_candidates[0]
        close = [c for c in direct_candidates[1:] if int(top.get("score") or 0) - int(c.get("score") or 0) < 120]
        if close and not any(int(c.get("prompt_affinity_bonus") or 0) >= 250 for c in direct_candidates[: len(close) + 1]):
            root_selection_ambiguity = {
                "message": "Multiple direct child git roots are close-scoring and no prompt affinity clearly disambiguated them.",
                "candidate_count": len(close) + 1,
                "candidates": [
                    {
                        "root": c.get("root"),
                        "score": c.get("score"),
                        "prompt_affinity_bonus": c.get("prompt_affinity_bonus"),
                        "markers": c.get("markers"),
                        "reasons": c.get("reasons"),
                    }
                    for c in [top, *close]
                ],
            }
    prompt_paths = _prompt_mentioned_paths(prompt, rel_paths)
    task_root = None
    task_root_reason = None
    for mentioned in prompt_paths:
        candidate_root = _nearest_marker_root_for_path(mentioned, rel_paths)
        if candidate_root and candidate_root != '.':
            task_root = candidate_root
            task_root_reason = f'prompt-mentioned path {mentioned} is inside subproject root {candidate_root}'
            break

    detected.sort(key=lambda d: d["confidence"], reverse=True)
    openclaw = next((d for d in detected if d.get("adapter") == "openclaw_control_plane" and len(d.get("markers", [])) >= 3), None)
    active = openclaw or detected[0]
    best_root_candidate = active_root_candidates[0] if active_root_candidates else None
    if best_root_candidate and best_root_candidate.get("root") in direct_child_git_roots:
        active_root = str(active.get("root") or ".")
        active_is_weaker_nested = active_root == "." or _root_has_penalized_segment(active_root) or _root_depth(active_root) > 1
        active_candidate = next((c for c in active_root_candidates if c.get("root") == active_root), None)
        best_score = int(best_root_candidate.get("score") or 0)
        active_score = int((active_candidate or {}).get("score") or 0)
        prompt_clear = int(best_root_candidate.get("prompt_affinity_bonus") or 0) >= 250 and best_score > active_score
        if active_is_weaker_nested or prompt_clear:
            promoted = next((d for d in detected if d.get("root") == best_root_candidate["root"]), None)
            active = promoted or _synthetic_git_project(str(best_root_candidate["root"]))
            active = {
                **active,
                "task_root": best_root_candidate["root"],
                "task_root_reason": "prompt_affinity_direct_child_git" if prompt_clear and not active_is_weaker_nested else "direct_child_git outranks nested ignored/reference project markers",
                "root_selection": {
                    **(active.get("root_selection") or {}),
                    "strategy": "prompt_affinity_direct_child_git" if prompt_clear and not active_is_weaker_nested else "direct_child_git",
                    "promoted_over": active_root,
                    "candidate_score": best_score,
                    "prompt_affinity_bonus": best_root_candidate.get("prompt_affinity_bonus"),
                },
            }
    if task_root and not openclaw:
        for d in detected:
            if d.get('root') == task_root:
                active = {**d, 'task_root': task_root, 'task_root_reason': task_root_reason}
                break
    if cwd and not openclaw and not task_root:
        try:
            cwd_rel = cwd.resolve().relative_to(repo_root.resolve()).as_posix()
            for d in detected:
                if d["root"] != "." and (cwd_rel == d["root"] or cwd_rel.startswith(d["root"] + "/")):
                    active = d
                    break
        except Exception:
            pass
    repo_kind = "multi_project" if len([d for d in detected if d["project_kind"] != "generic"]) > 1 else active["project_kind"]
    intake_traits = list(intake_report.get("traits", []))
    active = {**active, "intake_traits": sorted(set(active.get("traits", []) + intake_traits))}
    return {
        "schema_version": 3,
        "repo_kind": repo_kind,
        "active_project_kind": active.get("profile") or ("proof_governed_control_plane" if "control_plane_candidate" in intake_traits else active["project_kind"]),
        "active_project": active,
        "task_root": task_root or active.get("root"),
        "task_root_reason": task_root_reason or active.get("root_selection", {}).get("strategy"),
        "active_root_candidates": active_root_candidates[:20],
        "root_selection_ambiguity": root_selection_ambiguity,
        "detected_projects": detected,
        "traits": intake_traits,
        "policy_packs": sorted((intake_report.get("policy_packs") or {}).keys()),
        "intake_warnings": intake_report.get("intake_warnings", []),
        "intake_report": intake_report,
    }


def adapter_for(kind: str | None) -> Adapter:
    return ADAPTERS.get(kind or "generic", ADAPTERS["generic"])


def adapter_score_bonus(entry: dict[str, Any], detection: dict[str, Any]) -> int:
    active = detection.get("active_project", {})
    adapter = adapter_for(active.get("adapter"))
    path = str(entry.get("path", ""))
    lower = path.lower()
    score = 0
    if Path(path).name in adapter.important_files or path in adapter.important_files:
        score += 250
    if any(lower == d.lower() or lower.startswith(d.lower().rstrip("/") + "/") for d in adapter.important_dirs):
        score += 60
    if Path(path).suffix.lower() in adapter.extensions:
        score += 60
    if path in active.get("markers", []):
        score += 300
    if active.get("adapter") == "openclaw_control_plane":
        if _is_openclaw_authority_path(path):
            score += 650
        if _is_openclaw_evidence_only_path(path):
            score -= 120
    intake_delta, _flags = intake_score_delta(path, detection.get("intake_report"))
    score += intake_delta
    if active.get("root") and active.get("root") != "." and (path == active["root"] or path.startswith(active["root"].rstrip("/") + "/")):
        score += 80
    return score


def adapter_acceptance_checks(classification: dict[str, Any], detection: dict[str, Any]) -> list[str]:
    active = detection.get("active_project", {})
    kind = active.get("project_kind", "generic")
    names = {i.get("name") for i in classification.get("intents", [])}
    checks: list[str] = []
    if "compile_repair" in names or "test_failure" in names:
        if kind == "ios_swift":
            checks.extend(["Run the configured xcodebuild or Swift build command if available.", "Resolve Swift compiler errors before warning cleanup."])
        elif kind == "node":
            checks.extend(["Run the configured npm/pnpm/yarn build command if available.", "Run tests/lint only if configured or clearly relevant."])
        elif kind == "openclaw_control_plane":
            checks.extend([
                "Use OpenClaw authority surfaces before historical/generated artifacts.",
                "Do not mutate bridge/Unreal/Blender/task-queue surfaces without explicit authorization.",
                "Do not claim runtime/collision/input proof from static, browser, editor, or historical evidence alone.",
                "Run only configured safe validators/tests when verifying.",
            ])
        elif kind == "python":
            checks.extend(["Run pytest if configured.", "Run ruff/mypy only if configured or already used by the repo."])
        elif kind == "rust":
            checks.extend(["Run cargo check or cargo test if configured."])
        elif kind == "go":
            checks.extend(["Run go test ./... if configured or clearly safe."])
        else:
            checks.extend(["Run the most relevant configured build/test command if available."])
    return checks


def adapter_log_patterns(detection: dict[str, Any]) -> list[str]:
    active = detection.get("active_project", {})
    return list(adapter_for(active.get("adapter")).log_patterns)


def default_commands_for_detection(detection: dict[str, Any]) -> dict[str, Any]:
    kind = detection.get("active_project", {}).get("project_kind", "generic")
    commands: dict[str, Any] = {}
    if kind == "openclaw_control_plane":
        commands["test_symphony"] = {"command": "pytest tests/symphony -q", "description": "OpenClaw Symphony validator tests if present.", "safe_to_suggest": True, "auto_run": False}
        commands["test_spatial"] = {"command": "pytest tests/spatial -q", "description": "OpenClaw spatial validator tests if present.", "safe_to_suggest": True, "auto_run": False}
        commands["task_queue_help"] = {"command": "python tools/gamebot/task_queue.py --help", "description": "Inspect task-queue CLI without mutating project state.", "safe_to_suggest": True, "auto_run": False}
        commands["bridge_write"] = {"command": "DO_NOT_RUN bridge-write / Unreal / Blender mutation commands unless explicitly authorized", "description": "Dangerous mutation class; included as a safety note, not a runnable command.", "safe_to_suggest": False, "auto_run": False}
    elif kind == "ios_swift":
        commands["build"] = {"command": "xcodebuild build", "description": "iOS/Swift build placeholder; customize scheme/destination.", "safe_to_suggest": True, "auto_run": False}
        commands["test"] = {"command": "xcodebuild test", "description": "iOS/Swift test placeholder; customize scheme/destination.", "safe_to_suggest": True, "auto_run": False}
    elif kind == "node":
        commands["build"] = {"command": "npm run build", "description": "Node/Web build command", "safe_to_suggest": True, "auto_run": False}
        commands["test"] = {"command": "npm test", "description": "Node/Web test command", "safe_to_suggest": True, "auto_run": False}
    elif kind == "python":
        commands["test"] = {"command": "pytest", "description": "Python test command", "safe_to_suggest": True, "auto_run": False}
        commands["lint"] = {"command": "ruff check .", "description": "Python lint command if ruff is used", "safe_to_suggest": True, "auto_run": False}
    elif kind == "rust":
        commands["build"] = {"command": "cargo check", "description": "Rust compile check", "safe_to_suggest": True, "auto_run": False}
        commands["test"] = {"command": "cargo test", "description": "Rust test command", "safe_to_suggest": True, "auto_run": False}
    elif kind == "go":
        commands["test"] = {"command": "go test ./...", "description": "Go test command", "safe_to_suggest": True, "auto_run": False}
    elif kind == "native_cpp":
        commands["build"] = {"command": "scons", "description": "Native/SCons build placeholder; customize if needed", "safe_to_suggest": True, "auto_run": False}
        commands["test"] = {"command": "scons tests", "description": "Native/SCons test placeholder if configured", "safe_to_suggest": True, "auto_run": False}
    else:
        commands["verify"] = {"command": "<configure build/test command>", "description": "Customize in .premode/commands.json", "safe_to_suggest": False, "auto_run": False}
    return {"schema_version": 1, "commands": commands}


def load_commands(repo_root: Path, detection: dict[str, Any] | None = None) -> dict[str, Any]:
    # Late import avoids an adapters/config command-discovery cycle during setup.
    from .command_discovery import discover_commands, load_user_commands, merge_user_commands, write_discovered_commands

    detection = detection or detect_projects(repo_root)
    discovered = discover_commands(repo_root, detection)
    try:
        write_discovered_commands(repo_root, discovered)
    except OSError:
        pass
    user = load_user_commands(repo_root)
    return merge_user_commands(discovered, user)


def read_rules_and_memory(repo_root: Path, max_chars: int = 6000) -> dict[str, Any]:
    out: dict[str, Any] = {"rules": "", "memory": "", "paths": []}
    for key, rel in [("rules", ".premode/rules.md"), ("memory", ".premode/memory/project_memory.md")]:
        path = repo_root / rel
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
            out[key] = text
            out["paths"].append(rel)
    return out
