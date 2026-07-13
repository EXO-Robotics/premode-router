#!/usr/bin/env python3
"""Private, reproducible corpus profiling and regression-fixture preparation.

The durable corpus and all task answers stay outside the product repository.
Only this content-free framework and sanitized summaries are intended for Git.
"""

from __future__ import annotations

import argparse
from collections import Counter
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
from typing import Any, Iterable


SCHEMA_VERSION = "pcodex-scouting-corpus/1.0.0"
EXCLUDED_DIRECTORY_NAMES = {
    ".Trash", ".cache", ".gradle", ".m2", ".npm", ".pnpm-store", ".venv",
    "DerivedData", "Library", "Pods", "__pycache__", "build", "dist",
    "node_modules", "target", "venv",
}
SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".java", ".js",
    ".jsx", ".kt", ".m", ".mm", ".php", ".py", ".rb", ".rs", ".sh",
    ".swift", ".ts", ".tsx", ".vue", ".zig",
}
TEST_PARTS = {"test", "tests", "testing", "spec", "specs", "__tests__"}
DOC_PARTS = {"doc", "docs", "documentation", "guide", "guides"}
GENERATED_PARTS = {"generated", "gen", "autogen", "codegen", "dist", "build"}
VENDOR_PARTS = {"vendor", "vendors", "third_party", "third-party", "node_modules", "Pods"}
HISTORY_PARTS = {"archive", "archives", "deprecated", "history", "legacy", "old"}
CONFIG_NAMES = {
    ".editorconfig", ".pre-commit-config.yaml", "Cargo.toml", "CMakeLists.txt",
    "Gemfile", "Makefile", "Package.swift", "go.mod", "package.json",
    "pyproject.toml", "setup.cfg", "tsconfig.json",
}
LANGUAGE_BY_SUFFIX = {
    ".c": "C", ".cc": "C++", ".cpp": "C++", ".cs": "C#", ".go": "Go",
    ".h": "C/C++", ".hpp": "C++", ".java": "Java", ".js": "JavaScript",
    ".jsx": "JavaScript", ".kt": "Kotlin", ".m": "Objective-C",
    ".mm": "Objective-C++", ".php": "PHP", ".py": "Python", ".rb": "Ruby",
    ".rs": "Rust", ".sh": "Shell", ".swift": "Swift", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".vue": "Vue", ".zig": "Zig",
}
TASK_CLASSES = (
    "localized_source_repair",
    "test_only_repair",
    "configuration_tooling_repair",
    "documentation_tied_to_implementation",
    "cross_module_change",
)
TASK_GENERATION = "g2"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def run_git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if check and completed.returncode:
        raise RuntimeError(f"git {' '.join(arguments)} failed in {repo}: {completed.stderr.strip()}")
    return completed


def directory_size(root: Path) -> int:
    total = 0
    for current, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name not in EXCLUDED_DIRECTORY_NAMES]
        for name in files:
            try:
                total += (Path(current) / name).lstat().st_size
            except OSError:
                pass
    return total


def discover_repositories(roots: Iterable[Path], max_depth: int = 5) -> list[Path]:
    found: set[Path] = set()
    for supplied_root in roots:
        root = supplied_root.expanduser()
        if not root.exists():
            continue
        root_depth = len(root.parts)
        for current, directories, _files in os.walk(root, followlinks=False):
            current_path = Path(current)
            depth = len(current_path.parts) - root_depth
            directories[:] = [
                name for name in directories
                if name not in EXCLUDED_DIRECTORY_NAMES and not name.startswith(".")
            ]
            if (current_path / ".git").exists():
                found.add(current_path.resolve())
                directories[:] = []
                continue
            if depth >= max_depth:
                directories[:] = []
    return sorted(found)


def tracked_paths(repo: Path) -> list[str]:
    raw = run_git(repo, "ls-files", "-z").stdout
    return sorted(path for path in raw.split("\0") if path)


def primary_languages(paths: Iterable[str]) -> list[dict[str, Any]]:
    counts = Counter(LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower()) for path in paths)
    counts.pop(None, None)
    return [{"language": language, "files": count} for language, count in counts.most_common()]


def repository_inventory_record(repo: Path, opaque_id: str) -> dict[str, Any]:
    paths = tracked_paths(repo)
    status = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all", check=False)
    branch = run_git(repo, "branch", "--show-current", check=False).stdout.strip() or None
    commit = run_git(repo, "rev-parse", "HEAD", check=False).stdout.strip() or None
    remote = run_git(repo, "remote", "get-url", "origin", check=False).stdout.strip() or None
    depths = [len(Path(path).parts) for path in paths]
    basename_counts = Counter(Path(path).name for path in paths)
    package_count = sum(Path(path).name in CONFIG_NAMES for path in paths)
    test_directories = {part for path in paths for part in Path(path).parts if part.casefold() in TEST_PARTS}
    public_private = "unknown"
    if remote and re.match(r"^(https://|git" + r"@)github\.com[:/]", remote):
        public_private = "unverified_remote"
    safe = bool(remote and commit and not status.stdout)
    return {
        "schema_version": SCHEMA_VERSION,
        "opaque_repository_id": opaque_id,
        "local_path": str(repo),
        "remote_url": remote,
        "current_branch": branch,
        "current_commit": commit,
        "clean_or_dirty": "clean" if not status.stdout else "dirty",
        "tracked_file_count": len(paths),
        "working_tree_size": directory_size(repo),
        "git_directory_size": directory_size(repo / ".git") if (repo / ".git").is_dir() else 0,
        "primary_languages": primary_languages(paths)[:6],
        "package_count": package_count,
        "maximum_directory_depth": max(depths, default=0),
        "test_directory_count": len(test_directories),
        "duplicate_basename_count": sum(1 for count in basename_counts.values() if count > 1),
        "generated_directory_count": len({part for path in paths for part in Path(path).parts if part in GENERATED_PARTS}),
        "vendor_directory_count": len({part for path in paths for part in Path(path).parts if part in VENDOR_PARTS}),
        "archive_or_history_directory_count": len({part for path in paths for part in Path(path).parts if part in HISTORY_PARTS}),
        "repository_layout_class": classify_layout(paths),
        "public_or_private": public_private,
        "safe_for_corpus": safe,
        "reason": "reclone from verified remote" if safe else "exclude until clean identity and public or ownership status are verified",
    }


def classify_layout(paths: list[str]) -> str:
    packages = sum(Path(path).name in {"package.json", "pyproject.toml", "Cargo.toml", "Package.swift", "go.mod"} for path in paths)
    roots = {Path(path).parts[0] for path in paths if Path(path).parts}
    if packages >= 8 or {"packages", "apps"}.issubset(roots):
        return "monorepo"
    if any(part in HISTORY_PARTS for path in paths for part in Path(path).parts) or len(roots) > 20:
        return "irregular_or_legacy"
    if sum(Path(path).suffix.lower() in {".md", ".rst", ".adoc"} for path in paths) > max(20, len(paths) // 3):
        return "documentation_or_config_heavy"
    return "conventional"


def profile_repository(repo: Path, repository_id: str, source_type: str, license_name: str) -> dict[str, Any]:
    paths = tracked_paths(repo)
    source = [path for path in paths if Path(path).suffix.lower() in SOURCE_SUFFIXES and not is_test_path(path)]
    tests = [path for path in paths if is_test_path(path)]
    docs = [path for path in paths if is_doc_path(path)]
    configs = [path for path in paths if Path(path).name in CONFIG_NAMES or Path(path).suffix.lower() in {".toml", ".yaml", ".yml"}]
    depths = [len(Path(path).parts) for path in paths]
    basenames = Counter(Path(path).name for path in paths)
    commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    remote = run_git(repo, "remote", "get-url", "origin", check=False).stdout.strip() or None
    git_config = run_git(repo, "config", "--get", "remote.origin.promisor", check=False).stdout.strip()
    sparse = run_git(repo, "config", "--bool", "core.sparseCheckout", check=False).stdout.strip() == "true"
    profile = {
        "schema_version": SCHEMA_VERSION,
        "repository_id": repository_id,
        "source_type": source_type,
        "remote_url": remote,
        "pinned_commit": commit,
        "license": license_name,
        "shallow_clone": (repo / ".git" / "shallow").exists(),
        "partial_clone": git_config == "true",
        "sparse_checkout": sparse,
        "tracked_files": len(paths),
        "source_files": len(source),
        "test_files": len(tests),
        "documentation_files": len(docs),
        "configuration_files": len(configs),
        "package_count": sum(Path(path).name in CONFIG_NAMES for path in paths),
        "language_mix": primary_languages(paths),
        "maximum_directory_depth": max(depths, default=0),
        "median_directory_depth": statistics.median(depths) if depths else 0,
        "duplicate_basename_count": sum(1 for count in basenames.values() if count > 1),
        "generated_path_count": sum(any(part in GENERATED_PARTS for part in Path(path).parts) for path in paths),
        "vendor_path_count": sum(any(part in VENDOR_PARTS for part in Path(path).parts) for path in paths),
        "history_or_archive_path_count": sum(any(part in HISTORY_PARTS for part in Path(path).parts) for path in paths),
        "binary_or_asset_count": sum(Path(path).suffix.lower() in {".gif", ".ico", ".jpg", ".jpeg", ".pdf", ".png", ".svg", ".zip"} for path in paths),
        "repository_size_bytes": directory_size(repo),
        "git_size_bytes": directory_size(repo / ".git"),
        "size_class": size_class(len(paths)),
        "layout_class": classify_layout(paths),
        "test_to_source_distance": test_to_source_distance(source, tests),
    }
    return profile


def is_test_path(path: str) -> bool:
    lowered_parts = {part.casefold() for part in Path(path).parts}
    name = Path(path).name.casefold()
    return bool(lowered_parts & TEST_PARTS) or name.startswith("test_") or name.endswith((".test.ts", ".test.tsx", ".spec.js", ".spec.ts"))


def is_doc_path(path: str) -> bool:
    parts = {part.casefold() for part in Path(path).parts}
    return bool(parts & DOC_PARTS) or Path(path).suffix.lower() in {".md", ".rst", ".adoc"}


def size_class(count: int) -> str:
    if count < 300:
        return "small"
    if count <= 2_000:
        return "medium"
    if count <= 10_000:
        return "large"
    return "very_large"


def test_to_source_distance(source: list[str], tests: list[str]) -> float | None:
    if not source or not tests:
        return None
    source_directories = [Path(path).parent.parts for path in source[:500]]
    distances: list[int] = []
    for test in tests[:500]:
        test_parts = Path(test).parent.parts
        best = None
        for source_parts in source_directories:
            common = 0
            for left, right in zip(test_parts, source_parts):
                if left != right:
                    break
                common += 1
            distance = len(test_parts) + len(source_parts) - 2 * common
            best = distance if best is None else min(best, distance)
        if best is not None:
            distances.append(best)
    return round(statistics.median(distances), 2) if distances else None


def usable_text(repo: Path, path: str) -> bool:
    target = repo / path
    try:
        data = target.read_bytes()
    except OSError:
        return False
    return 32 <= len(data) <= 100_000 and b"\0" not in data


def choose_candidates(repo: Path, paths: list[str], task_class: str, count: int) -> list[str]:
    candidates = [path for path in paths if usable_text(repo, path) and not any(part in VENDOR_PARTS | GENERATED_PARTS for part in Path(path).parts)]
    if task_class == "localized_source_repair":
        preferred = [path for path in candidates if Path(path).suffix.lower() in SOURCE_SUFFIXES and not is_test_path(path)]
    elif task_class == "test_only_repair":
        preferred = [path for path in candidates if is_test_path(path)]
    elif task_class == "configuration_tooling_repair":
        preferred = [path for path in candidates if Path(path).name in CONFIG_NAMES or Path(path).suffix.lower() in {".toml", ".yaml", ".yml"}]
    elif task_class == "documentation_tied_to_implementation":
        preferred = [path for path in candidates if is_doc_path(path)]
    else:
        preferred = [path for path in candidates if Path(path).suffix.lower() in SOURCE_SUFFIXES and not is_test_path(path)]
    ordered = sorted(preferred, key=lambda value: (len(Path(value).parts), len(value), value))
    if len(ordered) < count:
        ordered.extend(path for path in sorted(candidates) if path not in ordered)
    return ordered[:count]


QUOTED_VALUE = re.compile(r"(?P<quote>['\"])(?P<value>[A-Za-z][A-Za-z0-9_ ./:-]{3,50})(?P=quote)")


def mutate_file(path: Path, task_id: str) -> tuple[bytes, bytes]:
    original = path.read_bytes()
    text = original.decode("utf-8")
    lines = text.splitlines(keepends=True)
    marker = f"-broken-{task_id[-6:]}"
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("#", "//", "/*", "*")):
            continue
        match = QUOTED_VALUE.search(line)
        if match and "http" not in match.group("value").casefold():
            start, end = match.span("value")
            lines[index] = line[:start] + match.group("value") + marker + line[end:]
            return original, "".join(lines).encode("utf-8")
    for index, line in enumerate(lines):
        replacement = re.sub(r"\b(True|False|true|false)\b", lambda match: {"True": "False", "False": "True", "true": "false", "false": "true"}[match.group(0)], line, count=1)
        if replacement != line:
            lines[index] = replacement
            return original, "".join(lines).encode("utf-8")
    for index, line in enumerate(lines):
        if line.strip() and not line.lstrip().startswith(("#", "//", "/*", "*")):
            newline = "\n" if line.endswith("\n") else ""
            body = line[:-1] if newline else line
            comment = " #" if path.suffix.lower() in {".py", ".rb", ".sh", ".toml", ".yaml", ".yml"} else " //"
            lines[index] = f"{body}{comment}-broken-{task_id[-6:]}{newline}"
            return original, "".join(lines).encode("utf-8")
    raise ValueError(f"no mutable line in {path}")


def patch_for_files(repo: Path, mutations: list[tuple[str, bytes, bytes]]) -> bytes:
    output: list[str] = []
    for relative, original, mutated in mutations:
        output.extend(difflib.unified_diff(
            original.decode("utf-8").splitlines(keepends=True),
            mutated.decode("utf-8").splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        ))
    return "".join(output).encode("utf-8")


def task_prompt(task_class: str, marker: str) -> str:
    descriptions = {
        "localized_source_repair": "A localized source regression corrupted one canonical value",
        "test_only_repair": "A focused test contract was accidentally corrupted",
        "configuration_tooling_repair": "A repository configuration or tooling contract contains a corrupted value",
        "documentation_tied_to_implementation": "Developer documentation no longer matches the repository's canonical contract",
        "cross_module_change": "The same regression was introduced in more than one source module",
    }
    return (
        f"{descriptions[task_class]}; the bad value carries the suffix `{marker}`. "
        "Locate the affected ordinary repository file or files and restore the intended value. "
        "Keep the patch minimal. Do not edit generated, vendored, archived, or repository-control files."
    )


def generate_tasks(repo: Path, repository_id: str, output_root: Path, tasks_per_repo: int = 5) -> list[dict[str, Any]]:
    paths = tracked_paths(repo)
    commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    generated: list[dict[str, Any]] = []
    validator_source_hash = sha256_bytes(Path(__file__).read_bytes())
    for index, task_class in enumerate(TASK_CLASSES[:tasks_per_repo], 1):
        task_id = f"{repository_id}-{TASK_GENERATION}-t{index:02d}"
        requested_count = 2 if task_class == "cross_module_change" else 1
        selected = choose_candidates(repo, paths, task_class, requested_count)
        if len(selected) < requested_count:
            raise RuntimeError(f"{repository_id} lacks candidates for {task_class}")
        mutations: list[tuple[str, bytes, bytes]] = []
        expected_hashes: dict[str, str] = {}
        mutated_hashes: dict[str, str] = {}
        marker = f"-broken-{task_id[-6:]}"
        for relative in selected:
            original, mutated = mutate_file(repo / relative, task_id)
            mutations.append((relative, original, mutated))
            expected_hashes[relative] = sha256_bytes(original)
            mutated_hashes[relative] = sha256_bytes(mutated)
        patch = patch_for_files(repo, mutations)
        patch_path = output_root / "mutations" / f"{task_id}.patch"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_bytes(patch)
        prompt = task_prompt(task_class, marker)
        private_validator_spec = {
            "task_id": task_id,
            "base_commit": commit,
            "expected_hashes": expected_hashes,
            "mutated_hashes": mutated_hashes,
            "allowed_mutation_paths": selected,
            "forbidden_mutation_path_classes": ["generated", "vendor", "history", "repository_control"],
        }
        validator_hash = sha256_bytes(canonical_bytes(private_validator_spec) + validator_source_hash.encode())
        generated.append({
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "repository_id": repository_id,
            "task_class": task_class,
            "prompt": prompt,
            "prompt_hash": sha256_bytes(prompt.encode()),
            "mutation_patch_hash": sha256_bytes(patch),
            "validator_hash": validator_hash,
            "base_commit": commit,
            "allowed_mutation_paths": selected,
            "forbidden_mutation_paths": [".git/**", ".premode/**", ".pcodex/**", "**/generated/**", "**/vendor/**", "**/history/**"],
            "expected_success": True,
            "expected_abstention_behavior": "abstain only if the corrupted marker cannot be found in ordinary tracked text",
            "_private_validator_spec": private_validator_spec,
            "_mutation_path": str(patch_path),
        })
    return generated


def validate_task(task: dict[str, Any], root: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    spec = task["_private_validator_spec"]
    for relative, expected in spec["expected_hashes"].items():
        target = root / relative
        actual = sha256_bytes(target.read_bytes()) if target.is_file() else None
        if actual != expected:
            errors.append(f"hash_mismatch:{relative}")
    status = run_git(root, "status", "--porcelain=v1", "--untracked-files=all", check=False)
    if status.returncode:
        errors.append("git_status_failed")
    else:
        changed = {line[3:] for line in status.stdout.splitlines() if len(line) >= 4}
        allowed = set(spec["allowed_mutation_paths"])
        for path in changed - allowed:
            errors.append(f"forbidden_change:{path}")
    return not errors, errors


def self_test_task(task: dict[str, Any], repo: Path) -> dict[str, Any]:
    spec = task["_private_validator_spec"]
    selected = list(spec["allowed_mutation_paths"])
    patch_path = Path(task["_mutation_path"])
    apply_check = run_git(repo, "apply", "--check", str(patch_path), check=False).returncode == 0
    with tempfile.TemporaryDirectory(prefix="pcodex-task-selftest-") as temporary:
        root = Path(temporary)
        for relative in selected:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((repo / relative).read_bytes())
        clean = all(sha256_bytes((root / relative).read_bytes()) == expected for relative, expected in spec["expected_hashes"].items())
        for relative in selected:
            original = (root / relative).read_bytes()
            expected = spec["expected_hashes"][relative]
            if sha256_bytes(original) != expected:
                raise AssertionError("clean fixture hash drift")
            source_text = (repo / relative).read_text(encoding="utf-8")
            marker = f"-broken-{task['task_id'][-6:]}"
            mutated_text = source_text.replace(marker, marker + "-incomplete") if marker in source_text else source_text
            if mutated_text == source_text:
                _original, mutated = mutate_file(repo / relative, task["task_id"])
                (root / relative).write_bytes(mutated)
            else:
                (root / relative).write_text(mutated_text, encoding="utf-8")
        mutated_fails = any(sha256_bytes((root / relative).read_bytes()) != expected for relative, expected in spec["expected_hashes"].items())
        first = selected[0]
        (root / first).write_bytes((repo / first).read_bytes())
        if len(selected) == 1:
            data = (root / first).read_bytes()
            (root / first).write_bytes(data + b"\n")
        incomplete_fails = any(sha256_bytes((root / relative).read_bytes()) != expected for relative, expected in spec["expected_hashes"].items())
    return {
        "task_id": task["task_id"],
        "clean_correct_state_passed": clean,
        "mutated_state_failed": mutated_fails,
        "incomplete_repair_failed": incomplete_fails,
        "git_apply_check_passed": apply_check,
        "passed": clean and mutated_fails and incomplete_fails and apply_check,
    }


def command_inventory(arguments: argparse.Namespace) -> int:
    roots = [Path(value) for value in arguments.roots]
    repositories = discover_repositories(roots, arguments.max_depth)
    records = [repository_inventory_record(repo, f"local-{index:03d}") for index, repo in enumerate(repositories, 1)]
    write_json(Path(arguments.output), records)
    print(json.dumps({"repositories": len(records), "output": arguments.output}, sort_keys=True))
    return 0


def load_selection(path: Path) -> list[dict[str, str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("selection must be an array")
    return value


def command_build(arguments: argparse.Namespace) -> int:
    corpus_root = Path(arguments.corpus_root).resolve()
    selection = load_selection(Path(arguments.selection))
    profiles: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    manifest_repositories: list[dict[str, Any]] = []
    self_tests: list[dict[str, Any]] = []
    for item in selection:
        repo = corpus_root / "repos" / "immutable" / item["directory"]
        profile = profile_repository(repo, item["repository_id"], item.get("source_type", "public_shallow_clone"), item["license"])
        profiles.append(profile)
        generated = generate_tasks(repo, item["repository_id"], corpus_root, int(item.get("tasks", 5)))
        tasks.extend(generated)
        self_tests.extend(self_test_task(task, repo) for task in generated)
        manifest_repositories.append({
            "repository_id": item["repository_id"],
            "directory": item["directory"],
            "pinned_commit": profile["pinned_commit"],
            "remote_url": profile["remote_url"],
            "license": profile["license"],
            "sparse_spec": item.get("sparse_spec", []),
            "sparse_justification": item.get("sparse_justification"),
        })
    public_tasks = [{key: value for key, value in task.items() if not key.startswith("_")} for task in tasks]
    validator_index = [{
        "task_id": task["task_id"],
        "validator_hash": task["validator_hash"],
        "validator_type": "exact_known-good_blob_hash_plus_forbidden-change_check",
        "self_test": next(result for result in self_tests if result["task_id"] == task["task_id"]),
    } for task in tasks]
    mutation_index = [{
        "task_id": task["task_id"],
        "mutation_patch_hash": task["mutation_patch_hash"],
        "mutation_patch_path": task["_mutation_path"],
    } for task in tasks]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repositories": manifest_repositories,
        "task_count": len(tasks),
        "repository_count": len(profiles),
        "sealed_corpus_used": False,
        "model_visible_boundary": {
            "allowed": ["exact task prompt", "disposable mutated repository", "fixed repository-only tools"],
            "forbidden": ["validator internals", "expected paths", "mutation patch", "private manifests", "prior arm results"],
        },
    }
    write_json(corpus_root / "manifests" / "PRIVATE_REPOSITORY_PROFILES.json", profiles)
    write_json(corpus_root / "manifests" / "PRIVATE_CORPUS_MANIFEST.json", manifest)
    write_json(corpus_root / "tasks" / "PRIVATE_TASK_DEFINITIONS.json", public_tasks)
    write_json(corpus_root / "validators" / "PRIVATE_VALIDATOR_INDEX.json", validator_index)
    write_json(corpus_root / "validators" / "PRIVATE_VALIDATOR_SPECS.json", {task["task_id"]: task["_private_validator_spec"] for task in tasks})
    write_json(corpus_root / "mutations" / "PRIVATE_MUTATION_INDEX.json", mutation_index)
    write_json(corpus_root / "private-results" / "PRIVATE_VALIDATOR_SELF_TEST_RESULTS.json", self_tests)
    write_json(corpus_root / "manifests" / "PRIVATE_BUILD_RECEIPT.json", {
        "schema_version": SCHEMA_VERSION,
        "manifest_hash": sha256_bytes(canonical_bytes(manifest)),
        "all_validator_self_tests_passed": all(result["passed"] for result in self_tests),
        "task_count": len(tasks),
        "repository_count": len(profiles),
    })
    print(json.dumps({"repositories": len(profiles), "tasks": len(tasks), "self_tests_passed": all(result["passed"] for result in self_tests)}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--roots", nargs="+", required=True)
    inventory.add_argument("--max-depth", type=int, default=5)
    inventory.add_argument("--output", required=True)
    inventory.set_defaults(function=command_inventory)
    build = subparsers.add_parser("build")
    build.add_argument("--corpus-root", required=True)
    build.add_argument("--selection", required=True)
    build.set_defaults(function=command_build)
    return result


def main() -> int:
    arguments = parser().parse_args()
    return int(arguments.function(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
