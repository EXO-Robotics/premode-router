from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

CommandMap = dict[str, Any]


def _cmd(command: str, *, source: str, description: str, confidence: float = 0.8, note: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "command": command,
        "description": description,
        "source": source,
        "confidence": round(confidence, 2),
        "safe_to_suggest": True,
        "auto_run": False,
    }
    if note:
        out["note"] = note
    return out


def _read(path: Path, max_chars: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(_read(path))
    except Exception:
        return {}


def _contains_tool(repo_root: Path, tool: str) -> tuple[bool, str | None]:
    needles = [tool.lower()]
    candidates = [
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "setup.cfg",
        "tox.ini",
        "pytest.ini",
    ]
    for rel in candidates:
        path = repo_root / rel
        if path.exists() and any(n in _read(path).lower() for n in needles):
            return True, rel
    return False, None



def _discover_openclaw(repo_root: Path) -> dict[str, Any]:
    commands: dict[str, Any] = {}
    sources: list[str] = []
    if (repo_root / "tests" / "symphony").exists():
        commands["test_symphony"] = _cmd("pytest tests/symphony -q", source="tests/symphony", description="OpenClaw Symphony validator tests", confidence=0.85)
        sources.append("tests/symphony")
    else:
        commands["test_symphony"] = _cmd("pytest tests/symphony -q", source="openclaw profile", description="OpenClaw Symphony validator tests if present", confidence=0.45, note="Verify tests/symphony exists before running.")
    if (repo_root / "tests" / "spatial").exists():
        commands["test_spatial"] = _cmd("pytest tests/spatial -q", source="tests/spatial", description="OpenClaw spatial validator tests", confidence=0.85)
        sources.append("tests/spatial")
    else:
        commands["test_spatial"] = _cmd("pytest tests/spatial -q", source="openclaw profile", description="OpenClaw spatial validator tests if present", confidence=0.45, note="Verify tests/spatial exists before running.")
    if (repo_root / "tools" / "gamebot" / "task_queue.py").exists():
        commands["task_queue_help"] = _cmd("python tools/gamebot/task_queue.py --help", source="tools/gamebot/task_queue.py", description="Inspect task-queue CLI without mutating state", confidence=0.85)
        sources.append("tools/gamebot/task_queue.py")
    commands["bridge_write"] = {
        "command": "DO_NOT_RUN bridge-write / Unreal / Blender mutation commands unless explicitly authorized",
        "description": "Dangerous mutation class; included as a safety note, not a runnable command.",
        "source": "openclaw profile",
        "confidence": 0.95,
        "safe_to_suggest": False,
        "auto_run": False,
    }
    return {"commands": commands, "sources": sources or ["openclaw profile"]}

def _discover_python(repo_root: Path) -> dict[str, Any]:
    commands: dict[str, Any] = {}
    sources: list[str] = []
    if (repo_root / "pytest.ini").exists():
        commands["test"] = _cmd("pytest", source="pytest.ini", description="Python test command", confidence=0.9)
        sources.append("pytest.ini")
    pyproject = repo_root / "pyproject.toml"
    data = _load_toml(pyproject) if pyproject.exists() else {}
    if data:
        sources.append("pyproject.toml")
        if "pytest" in data.get("tool", {}) or any("pytest" in str(v).lower() for v in data.values()):
            commands.setdefault("test", _cmd("pytest", source="pyproject.toml", description="Python test command", confidence=0.85))
        if "ruff" in data.get("tool", {}) or "ruff" in _read(pyproject).lower():
            commands["lint"] = _cmd("ruff check .", source="pyproject.toml", description="Python lint command", confidence=0.9)
        if "mypy" in data.get("tool", {}) or "mypy" in _read(pyproject).lower():
            commands["typecheck"] = _cmd("mypy .", source="pyproject.toml", description="Python typecheck command", confidence=0.85)
    if (repo_root / "tox.ini").exists():
        commands.setdefault("test", _cmd("tox", source="tox.ini", description="Python tox test matrix", confidence=0.85))
        sources.append("tox.ini")
    if (repo_root / "noxfile.py").exists():
        commands.setdefault("test", _cmd("nox", source="noxfile.py", description="Python nox sessions", confidence=0.8))
        sources.append("noxfile.py")
    makefile = repo_root / "Makefile"
    if makefile.exists():
        text = _read(makefile)
        sources.append("Makefile")
        for name in ("test", "lint", "typecheck", "build"):
            if re.search(rf"(?m)^{re.escape(name)}\s*:", text):
                commands.setdefault(name, _cmd(f"make {name}", source="Makefile", description=f"Makefile {name} target", confidence=0.75))
    justfile = repo_root / "justfile"
    if justfile.exists():
        text = _read(justfile)
        sources.append("justfile")
        for name in ("test", "lint", "typecheck", "build"):
            if re.search(rf"(?m)^{re.escape(name)}\s*(?:$|:|\s)", text):
                commands.setdefault(name, _cmd(f"just {name}", source="justfile", description=f"just {name} recipe", confidence=0.75))
    has_ruff, ruff_source = _contains_tool(repo_root, "ruff")
    if has_ruff:
        commands.setdefault("lint", _cmd("ruff check .", source=ruff_source or "project files", description="Python lint command", confidence=0.7))
    has_mypy, mypy_source = _contains_tool(repo_root, "mypy")
    if has_mypy:
        commands.setdefault("typecheck", _cmd("mypy .", source=mypy_source or "project files", description="Python typecheck command", confidence=0.7))
    if pyproject.exists() and "test" not in commands:
        commands["test"] = _cmd("pytest", source="pyproject.toml", description="Python test command placeholder; pytest is common but not proven configured", confidence=0.45, note="Verify pytest is installed/configured before running.")
    return {"commands": commands, "sources": sources}


def _detect_package_manager(repo_root: Path) -> str:
    if (repo_root / "pnpm-lock.yaml").exists() or (repo_root / "pnpm-workspace.yaml").exists():
        return "pnpm"
    if (repo_root / "yarn.lock").exists():
        return "yarn"
    if (repo_root / "bun.lockb").exists() or (repo_root / "bun.lock").exists():
        return "bun"
    if (repo_root / "package-lock.json").exists() or (repo_root / "package.json").exists():
        return "npm"
    return "none"


def _discover_node(repo_root: Path) -> dict[str, Any]:
    commands: dict[str, Any] = {}
    sources: list[str] = []
    pm = _detect_package_manager(repo_root)
    package = repo_root / "package.json"
    if not package.exists():
        return {"package_manager": pm, "commands": commands, "sources": sources}
    sources.append("package.json")
    try:
        data = json.loads(_read(package))
    except Exception:
        data = {}
    scripts = data.get("scripts") if isinstance(data, dict) else {}
    if isinstance(scripts, dict):
        for key in ("build", "test", "lint", "typecheck"):
            if key in scripts:
                if key == "test" and pm in {"npm", "pnpm", "yarn", "bun"}:
                    command = f"{pm} test"
                else:
                    command = f"{pm} run {key}"
                commands[key] = _cmd(command, source="package.json", description=f"Node/Web {key} script", confidence=0.9)
    return {"package_manager": pm, "commands": commands, "sources": sources}


def _discover_swift(repo_root: Path) -> dict[str, Any]:
    commands: dict[str, Any] = {}
    sources: list[str] = []
    if (repo_root / "Package.swift").exists():
        sources.append("Package.swift")
        commands["build"] = _cmd("swift build", source="Package.swift", description="Swift Package build", confidence=0.9)
        commands["test"] = _cmd("swift test", source="Package.swift", description="Swift Package tests", confidence=0.85)
    has_xcode = any(repo_root.glob("*.xcodeproj")) or any(repo_root.glob("*.xcworkspace"))
    if has_xcode:
        sources.extend([p.name for p in repo_root.glob("*.xcodeproj")])
        sources.extend([p.name for p in repo_root.glob("*.xcworkspace")])
        commands.setdefault("build", _cmd("xcodebuild build", source="xcode project/workspace", description="Conservative Xcode build placeholder", confidence=0.55, note="Customize scheme/destination in .premode/commands.json unless safely detected."))
        commands.setdefault("test", _cmd("xcodebuild test", source="xcode project/workspace", description="Conservative Xcode test placeholder", confidence=0.45, note="Customize scheme/destination in .premode/commands.json unless safely detected."))
    return {"commands": commands, "sources": sources}


def _discover_jvm(repo_root: Path) -> dict[str, Any]:
    commands: dict[str, Any] = {}
    sources: list[str] = []
    if (repo_root / "mvnw").exists():
        commands["test"] = _cmd("./mvnw test", source="mvnw", description="Maven wrapper test command", confidence=0.9)
        sources.append("mvnw")
    elif (repo_root / "pom.xml").exists():
        commands["test"] = _cmd("mvn test", source="pom.xml", description="Maven test command", confidence=0.82)
        sources.append("pom.xml")

    gradle_markers = ["build.gradle", "settings.gradle", "build.gradle.kts", "settings.gradle.kts"]
    if (repo_root / "gradlew").exists():
        if (repo_root / "app" / "build.gradle").exists() or (repo_root / "app" / "build.gradle.kts").exists():
            commands["test"] = _cmd("./gradlew :app:testDebugUnitTest", source="gradlew + app module", description="Android app module unit tests", confidence=0.9)
            commands["build"] = _cmd("./gradlew :app:assembleDebug", source="gradlew + app module", description="Android app module debug build", confidence=0.85)
        else:
            commands.setdefault("test", _cmd("./gradlew test", source="gradlew", description="Gradle wrapper test command", confidence=0.9))
        commands["gradle_test"] = _cmd("./gradlew test", source="gradlew", description="Gradle wrapper test command", confidence=0.9)
        sources.append("gradlew")
    elif any((repo_root / marker).exists() for marker in gradle_markers):
        commands.setdefault("test", _cmd("gradle test", source="Gradle build files", description="Gradle test command", confidence=0.78))
        commands["gradle_test"] = _cmd("gradle test", source="Gradle build files", description="Gradle test command", confidence=0.78)
        sources.extend(marker for marker in gradle_markers if (repo_root / marker).exists())
    return {"commands": commands, "sources": sorted(set(sources))}


def _discover_elixir(repo_root: Path) -> dict[str, Any]:
    if not (repo_root / "mix.exs").exists():
        return {"commands": {}, "sources": []}
    return {
        "commands": {
            "test": _cmd("mix test", source="mix.exs", description="Elixir/Mix test command", confidence=0.9),
            "build": _cmd("mix compile", source="mix.exs", description="Elixir/Mix compile command", confidence=0.85),
        },
        "sources": ["mix.exs"],
    }


def _discover_php(repo_root: Path) -> dict[str, Any]:
    commands: dict[str, Any] = {}
    sources: list[str] = []
    if (repo_root / "vendor" / "bin" / "phpunit").exists():
        commands["test"] = _cmd("vendor/bin/phpunit", source="vendor/bin/phpunit", description="Composer-installed PHPUnit", confidence=0.9)
        sources.append("vendor/bin/phpunit")
    composer = repo_root / "composer.json"
    if composer.exists():
        sources.append("composer.json")
        try:
            data = json.loads(_read(composer))
        except Exception:
            data = {}
        scripts = data.get("scripts") if isinstance(data, dict) else {}
        if isinstance(scripts, dict) and "test" in scripts and "test" not in commands:
            commands["test"] = _cmd("composer test", source="composer.json scripts.test", description="Composer test script", confidence=0.82)
    if (repo_root / "phpunit.xml").exists() or (repo_root / "phpunit.xml.dist").exists():
        commands.setdefault("test", _cmd("phpunit", source="phpunit.xml", description="PHPUnit fallback", confidence=0.65))
        sources.extend([p.name for p in (repo_root / "phpunit.xml", repo_root / "phpunit.xml.dist") if p.exists()])
    return {"commands": commands, "sources": sorted(set(sources))}


def _discover_ruby(repo_root: Path) -> dict[str, Any]:
    commands: dict[str, Any] = {}
    sources: list[str] = []
    if (repo_root / "Gemfile").exists():
        commands["test"] = _cmd("bundle exec rspec", source="Gemfile", description="RSpec test command", confidence=0.82)
        sources.append("Gemfile")
    if (repo_root / "bin" / "rails").exists():
        commands["rails_test"] = _cmd("bin/rails test", source="bin/rails", description="Rails/Minitest command", confidence=0.8)
        commands.setdefault("test", commands["rails_test"])
        sources.append("bin/rails")
    elif (repo_root / "config" / "routes.rb").exists():
        commands.setdefault("rails_test", _cmd("bundle exec rails test", source="config/routes.rb", description="Rails/Minitest command", confidence=0.68))
    return {"commands": commands, "sources": sorted(set(sources))}


def _discover_terraform(repo_root: Path) -> dict[str, Any]:
    has_tf = any(repo_root.glob("*.tf")) or (repo_root / "modules").exists()
    if not has_tf:
        return {"commands": {}, "sources": []}
    return {
        "commands": {
            "fmt": _cmd("terraform fmt -check", source="Terraform files", description="Terraform formatting check", confidence=0.85),
            "validate": _cmd("terraform validate", source="Terraform files", description="Terraform validation", confidence=0.8),
        },
        "sources": ["Terraform files"],
    }


def _discover_dotnet(repo_root: Path) -> dict[str, Any]:
    commands: dict[str, Any] = {
        "test": _cmd("dotnet test", source=".NET project files", description=".NET test command", confidence=0.85),
        "build": _cmd("dotnet build", source=".NET project files", description=".NET build command", confidence=0.82),
    }
    sources: list[str] = []
    for path in sorted(repo_root.glob("*.sln")):
        sources.append(path.name)
        break
    csproj_paths = sorted(repo_root.glob("**/*.csproj"))
    sources.extend(path.relative_to(repo_root).as_posix() for path in csproj_paths[:6])
    test_projects = [
        path
        for path in csproj_paths
        if any(part.lower() in {"test", "tests"} or part.lower().endswith(".tests") for part in path.relative_to(repo_root).parts)
    ]
    if test_projects:
        rel = test_projects[0].relative_to(repo_root).as_posix()
        commands["test_project"] = _cmd(f"dotnet test {rel}", source=rel, description="Targeted .NET test project", confidence=0.9)
    return {"commands": commands, "sources": sorted(set(sources)) or [".NET project files"]}


def _discover_zig(repo_root: Path) -> dict[str, Any]:
    if not (repo_root / "build.zig").exists() and not any(repo_root.glob("src/*.zig")):
        return {"commands": {}, "sources": []}
    commands: dict[str, Any] = {
        "test": _cmd("zig build test", source="build.zig", description="Zig build test command", confidence=0.88),
    }
    for path in sorted(list((repo_root / "test").glob("*.zig")) + list((repo_root / "tests").glob("*.zig"))):
        rel = path.relative_to(repo_root).as_posix()
        commands["test_file"] = _cmd(f"zig test {rel}", source=rel, description="Targeted Zig test file", confidence=0.78)
        break
    sources = [name for name in ("build.zig", "build.zig.zon") if (repo_root / name).exists()]
    return {"commands": commands, "sources": sources or ["Zig files"]}


def _discover_haskell(repo_root: Path) -> dict[str, Any]:
    has_stack = (repo_root / "stack.yaml").exists()
    has_cabal = (repo_root / "cabal.project").exists() or any(repo_root.glob("*.cabal"))
    if not has_stack and not has_cabal:
        return {"commands": {}, "sources": []}
    if has_stack:
        commands = {
            "test": _cmd("stack test", source="stack.yaml", description="Stack test command", confidence=0.9),
            "build": _cmd("stack build", source="stack.yaml", description="Stack build command", confidence=0.84),
        }
    else:
        commands = {
            "test": _cmd("cabal test", source="cabal project files", description="Cabal test command", confidence=0.84),
            "build": _cmd("cabal build", source="cabal project files", description="Cabal build command", confidence=0.8),
        }
    sources = []
    if has_stack:
        sources.append("stack.yaml")
    if (repo_root / "cabal.project").exists():
        sources.append("cabal.project")
    sources.extend(path.name for path in sorted(repo_root.glob("*.cabal"))[:3])
    return {"commands": commands, "sources": sorted(set(sources))}


def _root_path(repo_root: Path, detection: dict[str, Any]) -> Path:
    root = str((detection.get("active_project") or {}).get("root") or ".")
    return repo_root if root == "." else repo_root / root


def discover_commands(repo_root: Path, detection: dict[str, Any] | None = None) -> dict[str, Any]:
    detection = detection or {"active_project": {"project_kind": "generic", "root": "."}}
    kind = str((detection.get("active_project") or {}).get("project_kind") or "generic")
    project_root = _root_path(repo_root, detection)
    if kind == "openclaw_control_plane":
        found = _discover_openclaw(project_root)
    elif kind == "python":
        found = _discover_python(project_root)
    elif kind == "node":
        found = _discover_node(project_root)
    elif kind == "ios_swift":
        found = _discover_swift(project_root)
    elif kind == "java_kotlin":
        found = _discover_jvm(project_root)
    elif kind == "elixir_phoenix":
        found = _discover_elixir(project_root)
    elif kind == "php_composer":
        found = _discover_php(project_root)
    elif kind == "ruby_rails":
        found = _discover_ruby(project_root)
    elif kind == "terraform":
        found = _discover_terraform(project_root)
    elif kind == "dotnet_csharp":
        found = _discover_dotnet(project_root)
    elif kind == "zig":
        found = _discover_zig(project_root)
    elif kind == "haskell_stack_cabal":
        found = _discover_haskell(project_root)
    elif kind == "rust" and (project_root / "Cargo.toml").exists():
        found = {"commands": {"build": _cmd("cargo check", source="Cargo.toml", description="Rust compile check", confidence=0.85), "test": _cmd("cargo test", source="Cargo.toml", description="Rust tests", confidence=0.85)}, "sources": ["Cargo.toml"]}
    elif kind == "go" and (project_root / "go.mod").exists():
        found = {"commands": {"test": _cmd("go test ./...", source="go.mod", description="Go tests", confidence=0.85)}, "sources": ["go.mod"]}
    elif kind == "native_cpp":
        if (project_root / "SConstruct").exists():
            found = {"commands": {"build": _cmd("scons", source="SConstruct", description="SCons native build", confidence=0.75), "test": _cmd("scons tests", source="SConstruct", description="SCons tests if configured", confidence=0.45)}, "sources": ["SConstruct"]}
        elif (project_root / "CMakeLists.txt").exists():
            found = {"commands": {"build": _cmd("cmake --build build", source="CMakeLists.txt", description="CMake build placeholder", confidence=0.55), "configure": _cmd("cmake -S . -B build", source="CMakeLists.txt", description="CMake configure placeholder", confidence=0.55)}, "sources": ["CMakeLists.txt"]}
        else:
            found = {"commands": {"build": _cmd("make", source="native_cpp fallback", description="Native build placeholder", confidence=0.30)}, "sources": []}
    else:
        found = {"commands": {"verify": {"command": "<configure build/test command>", "description": "Customize in .premode/commands.json", "source": "fallback", "confidence": 0.2, "safe_to_suggest": False, "auto_run": False}}, "sources": []}
    return {
        "schema_version": 2,
        "project_root": str((detection.get("active_project") or {}).get("root") or "."),
        "discovery": "deterministic",
        **found,
    }


def discovered_commands_path(repo_root: Path) -> Path:
    return repo_root / ".premode" / "out" / "discovered_commands.json"


def write_discovered_commands(repo_root: Path, discovered: dict[str, Any]) -> Path:
    path = discovered_commands_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_by": "premode", **discovered}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def default_user_commands() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "commands": {},
        "note": "User overrides only. Discovered commands are written to .premode/out/discovered_commands.json.",
    }


def _looks_generated_commands(data: dict[str, Any]) -> bool:
    return data.get("generated_by") == "premode" or data.get("discovery") == "deterministic" or bool(data.get("sources")) or bool(data.get("project_root"))


def load_user_commands(repo_root: Path) -> dict[str, Any]:
    path = repo_root / ".premode" / "commands.json"
    if not path.exists():
        return default_user_commands()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schema_version": 2, "commands": {}, "error": str(exc)}
    if not isinstance(data, dict):
        return {"schema_version": 2, "commands": {}, "error": "commands.json must contain an object"}
    # v2.4 wrote generated discovery into commands.json. Preserve compatibility,
    # but do not report those generated entries as user overrides.
    if _looks_generated_commands(data):
        return {
            "schema_version": 2,
            "commands": {},
            "legacy_generated_commands_ignored": True,
            "legacy_generated_command_count": len(data.get("commands") or {}),
            "note": "Generated v2.4 commands.json detected; use .premode/commands.json for user overrides only.",
        }
    data.setdefault("schema_version", 2)
    data.setdefault("commands", {})
    return data


def merge_user_commands(discovered: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(discovered))
    merged.setdefault("commands", {})
    user_commands = user.get("commands") or {}
    for name, value in user_commands.items():
        merged["commands"][name] = value
    if user.get("error"):
        merged["user_commands_error"] = user["error"]
    if user.get("legacy_generated_commands_ignored"):
        merged["legacy_generated_commands_ignored"] = True
        merged["legacy_generated_command_count"] = user.get("legacy_generated_command_count", 0)
    if user_commands:
        merged["user_overrides_applied"] = sorted(user_commands.keys())
    else:
        merged["user_overrides_applied"] = []
    return merged
