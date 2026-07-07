from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .config import premode_dir
from .inventory import refresh_inventory_if_needed
from .locator import extract_prompt_evidence
from .paths import normalize_for_manifest
from .safe_reader import is_secret_name
from .timeutil import timestamp_iso
from .write_policy import WritePolicy, resolve_write_policy

TOPOLOGY_SCHEMA_VERSION = "repotopology.v1"
TOPOLOGY_REL_PATH = Path(".premode") / "topology" / "repo_topology.json"

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".kt",
    ".kts",
    ".cs",
}
DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".adoc", ".txt"}
CONFIG_EXTENSIONS = {".json", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".xml", ".gradle", ".kts"}
SOURCE_ROOT_NAMES = {"src", "source", "sources", "cmd", "pkg", "internal", "include", "lib"}
TEST_ROOT_NAMES = {"test", "tests", "__tests__", "spec", "specs"}
DOC_ROOT_NAMES = {"docs", "doc", "documentation", "website"}
GENERATED_ROOT_NAMES = {
    "generated",
    "gen",
    "dist",
    "build",
    "deriveddata",
    ".next",
    "target",
    "coverage",
}
VENDOR_ROOT_NAMES = {"vendor", "third_party", "node_modules", "pods"}
RUNTIME_ROOT_NAMES = {".git", ".premode", ".pcodex", ".codex", ".agents", ".venv", "__pycache__", ".pytest_cache"}

MARKER_ECOSYSTEMS: dict[str, str] = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "package.json": "node_ts",
    "pnpm-workspace.yaml": "node_ts",
    "yarn.lock": "node_ts",
    "package-lock.json": "node_ts",
    "tsconfig.json": "node_ts",
    "go.mod": "go",
    "go.work": "go",
    "Cargo.toml": "rust",
    "Package.swift": "swift_ios",
    "CMakeLists.txt": "cpp",
    "SConstruct": "cpp",
    "BUILD": "bazel_polyglot",
    "BUILD.bazel": "bazel_polyglot",
    "WORKSPACE": "bazel_polyglot",
    "MODULE.bazel": "bazel_polyglot",
    "pom.xml": "java_kotlin",
    "build.gradle": "java_kotlin",
    "settings.gradle": "java_kotlin",
    "mkdocs.yml": "docs",
}
BUILD_FILE_NAMES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "pnpm-workspace.yaml",
    "go.mod",
    "go.work",
    "Cargo.toml",
    "Package.swift",
    "CMakeLists.txt",
    "SConstruct",
    "BUILD",
    "BUILD.bazel",
    "WORKSPACE",
    "MODULE.bazel",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
}


@dataclass
class TopologyMetrics:
    topology_cache_hit: bool = False
    topology_cache_miss: bool = False
    topology_source: str | None = None
    topology_freshness: str | None = None
    topology_node_count: int = 0
    topology_build_ms: int = 0
    topology_files_listed: int = 0
    topology_bounded_reads: int = 0
    topology_full_walk_performed: bool = False
    topology_full_walk_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology_cache_hit": self.topology_cache_hit,
            "topology_cache_miss": self.topology_cache_miss,
            "topology_source": self.topology_source,
            "topology_freshness": self.topology_freshness,
            "topology_node_count": self.topology_node_count,
            "topology_build_ms": self.topology_build_ms,
            "topology_files_listed": self.topology_files_listed,
            "topology_bounded_reads": self.topology_bounded_reads,
            "topology_full_walk_performed": self.topology_full_walk_performed,
            "topology_full_walk_reason": self.topology_full_walk_reason,
        }


@dataclass
class TopologyBuildResult:
    topology: dict[str, Any] | None
    freshness: str
    metrics: TopologyMetrics = field(default_factory=TopologyMetrics)


def topology_cache_path(repo_root: Path | str) -> Path:
    return premode_dir(Path(repo_root)) / "topology" / "repo_topology.json"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(payload: Any) -> str:
    return _sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    tmp = Path(handle.name)
    try:
        with handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _git_text(repo_root: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired, TypeError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _inventory_signature(inventory: dict[str, Any] | None) -> str | None:
    if not isinstance(inventory, dict):
        return None
    return _sha256_json(
        {
            "schema_version": inventory.get("schema_version"),
            "lcc_version": inventory.get("lcc_version"),
            "git_index_signature": inventory.get("git_index_signature"),
            "ignore_signature": inventory.get("ignore_signature"),
            "file_count": inventory.get("file_count"),
            "marker_paths": inventory.get("marker_paths"),
            "skipped_generated_count": inventory.get("skipped_generated_count"),
            "skipped_runtime_count": inventory.get("skipped_runtime_count"),
        }
    )


def _marker_signature(paths: Iterable[str]) -> str:
    marker_paths = []
    for path in paths:
        name = Path(path).name
        lower = name.lower()
        if (
            name in MARKER_ECOSYSTEMS
            or name in BUILD_FILE_NAMES
            or lower.endswith((".xcodeproj", ".xcworkspace", ".sln", ".csproj"))
            or any(part in {"apps", "packages", "crates", "services"} for part in Path(path).parts)
        ):
            marker_paths.append(path)
    return _sha256_json(sorted(set(marker_paths)))


def _repo_root_hash(repo_root: Path) -> str:
    return _sha256_text(str(repo_root.resolve()))


def _norm_rel(repo_root: Path, path: str | Path) -> str | None:
    norm = normalize_for_manifest(path, repo_root)
    return norm.rel_path if norm.ok and norm.rel_path else None


def _parent_root(path: str) -> str:
    parent = Path(path).parent.as_posix()
    return "." if parent == "." else parent


def _root_child(path: str, root: str) -> str | None:
    if root == ".":
        parts = Path(path).parts
    elif path == root or path.startswith(root + "/"):
        parts = Path(path[len(root) :].strip("/")).parts
    else:
        return None
    return parts[0] if parts else None


def _inside(path: str, root: str) -> bool:
    return root == "." or path == root or path.startswith(root.rstrip("/") + "/")


def _node_id(root: str) -> str:
    return "root" if root == "." else root


def _tokens(value: str) -> set[str]:
    return {part for part in re.split(r"[^A-Za-z0-9]+", value.lower()) if part}


def _root_terms(root: str) -> set[str]:
    if root == ".":
        return {"root"}
    parts = [part for piece in root.split("/") for part in _tokens(piece)]
    return set(parts)


def _add_node(nodes: dict[str, dict[str, Any]], root: str, ecosystem: str, marker: str | None = None) -> dict[str, Any]:
    node = nodes.setdefault(
        root,
        {
            "id": _node_id(root),
            "root": root,
            "ecosystem": ecosystem,
            "confidence": 0.25,
            "markers": [],
            "source_roots": [],
            "test_roots": [],
            "docs_roots": [],
            "config_files": [],
            "build_files": [],
            "package_files": [],
            "local_dependencies": [],
            "generated_roots": [],
            "vendor_roots": [],
            "runtime_roots": [],
            "risk_roots": [],
            "file_count": 0,
            "source_count": 0,
            "test_count": 0,
            "docs_count": 0,
            "config_count": 0,
            "evidence": {
                "marker_paths": [],
                "file_extensions": {},
                "root_names": sorted(_root_terms(root)),
                "counts": {},
                "adapter_ids": [],
            },
        },
    )
    if ecosystem != "unknown" and node["ecosystem"] in {"unknown", "docs"}:
        node["ecosystem"] = ecosystem
    if marker:
        node["markers"].append(marker)
        node["evidence"]["marker_paths"].append(marker)
    return node


def _ecosystem_for_marker(path: str) -> str | None:
    name = Path(path).name
    lower = name.lower()
    if name in MARKER_ECOSYSTEMS:
        return MARKER_ECOSYSTEMS[name]
    if lower.endswith((".xcodeproj", ".xcworkspace")):
        return "swift_ios"
    if lower in {"docusaurus.config.js", "docusaurus.config.ts"}:
        return "docs"
    return None


def _candidate_roots(paths: list[str], marker_paths: list[str]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    all_paths = sorted(set([*paths, *marker_paths]))
    for path in all_paths:
        ecosystem = _ecosystem_for_marker(path)
        if ecosystem:
            _add_node(nodes, _parent_root(path), ecosystem, marker=path)
    for path in all_paths:
        parts = Path(path).parts
        if len(parts) >= 3 and parts[0] in {"apps", "packages", "crates", "services", "extensions"}:
            root = "/".join(parts[:2])
            ecosystem = _ecosystem_for_marker(path) or "unknown"
            if ecosystem != "unknown" or parts[0] in {"apps", "packages", "crates"}:
                _add_node(nodes, root, ecosystem, marker=path if ecosystem != "unknown" else None)
    if not nodes:
        root_exts = {Path(path).suffix.lower() for path in paths if "/" not in path or path.startswith(("src/", "tests/", "test/"))}
        if root_exts & {".py"} or any(path.startswith(("src/", "tests/")) for path in paths):
            _add_node(nodes, ".", "python", marker=None)
    if not nodes:
        _add_node(nodes, ".", "unknown", marker=None)
    return nodes


def _collect_roots(repo_root: Path, paths: list[str], root: str, names: set[str]) -> list[str]:
    roots: set[str] = set()
    for path in paths:
        if not _inside(path, root):
            continue
        child = _root_child(path, root)
        if child and child.lower() in names:
            roots.add(child if root == "." else f"{root}/{child}")
    # Finite top-level checks keep ignored generated/vendor dirs visible without walking.
    if root == ".":
        for name in names:
            candidate = repo_root / name
            if candidate.exists() and candidate.is_dir():
                roots.add(name)
    return sorted(roots)


def _classify_node_files(repo_root: Path, paths: list[str], node: dict[str, Any]) -> None:
    root = str(node["root"])
    ext_counts: dict[str, int] = {}
    config_files: set[str] = set()
    build_files: set[str] = set()
    package_files: set[str] = set()
    for path in paths:
        if not _inside(path, root):
            continue
        name = Path(path).name
        suffix = Path(path).suffix.lower()
        ext_counts[suffix] = ext_counts.get(suffix, 0) + 1
        node["file_count"] += 1
        parts_lower = {part.lower() for part in Path(path).parts}
        if suffix in SOURCE_EXTENSIONS:
            node["source_count"] += 1
        if suffix in DOC_EXTENSIONS or parts_lower & DOC_ROOT_NAMES:
            node["docs_count"] += 1
        if suffix in CONFIG_EXTENSIONS or name in MARKER_ECOSYSTEMS:
            node["config_count"] += 1
            config_files.add(path)
        if parts_lower & TEST_ROOT_NAMES or name.lower().startswith("test_") or name.lower().endswith(("_test.py", ".test.ts", ".spec.ts")):
            node["test_count"] += 1
        if name in BUILD_FILE_NAMES:
            build_files.add(path)
        if name in MARKER_ECOSYSTEMS or name in {"package.json", "Cargo.toml", "Package.swift"}:
            package_files.add(path)
    node["source_roots"] = _collect_roots(repo_root, paths, root, SOURCE_ROOT_NAMES)
    node["test_roots"] = _collect_roots(repo_root, paths, root, TEST_ROOT_NAMES)
    node["docs_roots"] = _collect_roots(repo_root, paths, root, DOC_ROOT_NAMES)
    node["generated_roots"] = _collect_roots(repo_root, paths, root, GENERATED_ROOT_NAMES)
    node["vendor_roots"] = _collect_roots(repo_root, paths, root, VENDOR_ROOT_NAMES)
    node["runtime_roots"] = _collect_roots(repo_root, paths, root, RUNTIME_ROOT_NAMES)
    node["risk_roots"] = sorted(set(node["generated_roots"] + node["vendor_roots"] + node["runtime_roots"]))
    node["config_files"] = sorted(config_files)[:40]
    node["build_files"] = sorted(build_files)[:40]
    node["package_files"] = sorted(package_files)[:40]
    node["markers"] = sorted(set(node["markers"]))[:40]
    node["evidence"]["marker_paths"] = sorted(set(node["evidence"]["marker_paths"]))[:40]
    node["evidence"]["file_extensions"] = {key: ext_counts[key] for key in sorted(ext_counts) if key}
    node["evidence"]["counts"] = {
        "files": node["file_count"],
        "source": node["source_count"],
        "tests": node["test_count"],
        "docs": node["docs_count"],
        "config": node["config_count"],
    }
    marker_bonus = min(0.35, 0.08 * len(node["markers"]))
    source_bonus = min(0.20, 0.03 * node["source_count"])
    test_bonus = 0.05 if node["test_count"] else 0
    node["confidence"] = round(min(0.95, 0.25 + marker_bonus + source_bonus + test_bonus), 2)


def _repo_shape(nodes: list[dict[str, Any]], inventory: dict[str, Any] | None) -> str:
    normal = [n for n in nodes if n.get("ecosystem") not in {"unknown", "docs"} or n.get("source_count")]
    ecosystems = {str(n.get("ecosystem")) for n in normal if n.get("ecosystem") not in {"unknown", "docs"}}
    total_source = sum(int(n.get("source_count") or 0) for n in nodes)
    total_docs = sum(int(n.get("docs_count") or 0) for n in nodes)
    skipped_generated = int((inventory or {}).get("skipped_generated_count") or 0)
    generated_roots = sum(len(n.get("generated_roots") or []) + len(n.get("vendor_roots") or []) for n in nodes)
    if skipped_generated + generated_roots >= max(3, total_source * 2):
        return "generated_heavy"
    if total_docs >= max(2, total_source * 2) and total_source <= 2:
        return "docs_heavy"
    if len(normal) <= 1 and ecosystems:
        return "single_package"
    if len(normal) > 1 and len(ecosystems) <= 1:
        return "multi_package"
    if len(normal) > 1 and len(ecosystems) > 1:
        return "polyglot_monorepo"
    if len(nodes) > 1:
        return "monorepo"
    return "unknown"


def _root_risk_zones(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zones: list[dict[str, Any]] = []
    for node in nodes:
        for key, category in (("generated_roots", "generated"), ("vendor_roots", "vendor"), ("runtime_roots", "runtime")):
            for root in node.get(key) or []:
                zones.append({"root": root, "category": category, "node": node.get("id")})
    return zones[:100]


def build_topology(
    repo_root: Path | str,
    inventory: dict[str, Any] | None = None,
    force: bool = False,
    *,
    write: bool = True,
    policy: WritePolicy | str | None = None,
) -> TopologyBuildResult:
    del force
    resolved_policy = resolve_write_policy(policy)
    write = write and resolved_policy.can_write_topology
    start = time.perf_counter()
    root = Path(repo_root)
    if inventory is None:
        inventory = refresh_inventory_if_needed(root, policy="write" if write else "read_only").inventory
    metrics = TopologyMetrics(topology_cache_miss=True, topology_source="inventory_paths")
    paths = [str(path) for path in (inventory or {}).get("paths") or [] if isinstance(path, str)]
    marker_paths = [str(path) for path in (inventory or {}).get("marker_paths") or [] if isinstance(path, str)]
    metrics.topology_files_listed = len(paths)
    safe_paths = [path for path in paths if not is_secret_name(path)]
    nodes_by_root = _candidate_roots(safe_paths, marker_paths)
    for node in nodes_by_root.values():
        _classify_node_files(root, safe_paths, node)
    nodes = sorted(nodes_by_root.values(), key=lambda item: (item["root"].count("/"), item["root"]))
    repo_shape = _repo_shape(nodes, inventory)
    default_node = sorted(nodes, key=lambda item: (float(item.get("confidence") or 0), int(item.get("source_count") or 0)), reverse=True)[0]
    payload = {
        "schema_version": TOPOLOGY_SCHEMA_VERSION,
        "lcc_version": __version__,
        "repo_root_hash": _repo_root_hash(root),
        "git_branch": _git_text(root, ["branch", "--show-current"]),
        "git_head": _git_text(root, ["rev-parse", "HEAD"]),
        "inventory_signature": _inventory_signature(inventory),
        "inventory_ignore_signature": (inventory or {}).get("ignore_signature"),
        "marker_signature": _marker_signature([*safe_paths, *marker_paths]),
        "topology_source": "inventory_paths",
        "freshness": "fresh",
        "created_at": timestamp_iso(),
        "repo_shape": repo_shape,
        "nodes": nodes,
        "root_risk_zones": _root_risk_zones(nodes),
        "default_node_policy": {
            "strategy": "highest_confidence_source_node",
            "primary_node": default_node.get("id"),
            "fallback_node": "root",
        },
        "warnings": [],
    }
    metrics.topology_node_count = len(nodes)
    metrics.topology_build_ms = int((time.perf_counter() - start) * 1000)
    metrics.topology_freshness = "fresh"
    if write:
        path = topology_cache_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, payload)
    return TopologyBuildResult(payload, "fresh", metrics)


def load_topology(repo_root: Path | str) -> dict[str, Any] | None:
    path = topology_cache_path(repo_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def topology_is_fresh(repo_root: Path | str, topology: dict[str, Any] | None, inventory: dict[str, Any] | None = None) -> str:
    root = Path(repo_root)
    if topology is None:
        return "missing"
    if not isinstance(topology, dict):
        return "invalid"
    if topology.get("schema_version") != TOPOLOGY_SCHEMA_VERSION or topology.get("lcc_version") != __version__:
        return "stale_schema_changed"
    if topology.get("repo_root_hash") != _repo_root_hash(root):
        return "invalid"
    if topology.get("git_branch") != _git_text(root, ["branch", "--show-current"]):
        return "stale_branch_changed"
    if topology.get("git_head") != _git_text(root, ["rev-parse", "HEAD"]):
        return "stale_head_changed"
    if inventory is None:
        inventory_result = refresh_inventory_if_needed(root, policy="read_only")
        if inventory_result.freshness == "stale_branch_changed":
            return "stale_branch_changed"
        if inventory_result.freshness == "stale_head_changed":
            return "stale_head_changed"
        if inventory_result.freshness == "stale_ignore_changed":
            return "stale_ignore_changed"
        if inventory_result.freshness in {"missing", "invalid", "stale_schema_changed"}:
            return "stale_inventory_changed" if inventory_result.freshness != "stale_schema_changed" else "stale_schema_changed"
        if inventory_result.freshness != "fresh":
            return "stale_inventory_changed"
        inventory = inventory_result.inventory
    inv_sig = _inventory_signature(inventory)
    if not inv_sig:
        return "unknown"
    paths = [str(path) for path in (inventory or {}).get("paths") or [] if isinstance(path, str)]
    marker_paths = [str(path) for path in (inventory or {}).get("marker_paths") or [] if isinstance(path, str)]
    if topology.get("marker_signature") != _marker_signature([*paths, *marker_paths]):
        return "stale_marker_changed"
    if topology.get("inventory_signature") != inv_sig:
        ignore_now = (inventory or {}).get("ignore_signature")
        ignore_then = topology.get("inventory_ignore_signature")
        return "stale_ignore_changed" if ignore_then is not None and ignore_now != ignore_then else "stale_inventory_changed"
    return "fresh"


def refresh_topology_if_needed(
    repo_root: Path | str,
    *,
    inventory: dict[str, Any] | None = None,
    policy: WritePolicy | str = "write",
) -> TopologyBuildResult:
    root = Path(repo_root)
    policy_name = str(policy).strip().lower().replace("-", "_")
    if policy_name not in {"write", "read_only", "no_write"}:
        resolved_policy = resolve_write_policy(policy)
        policy_name = "write" if resolved_policy.can_write_topology else "no_write"
    existing = load_topology(root)
    freshness = topology_is_fresh(root, existing, inventory)
    metrics = TopologyMetrics(topology_freshness=freshness)
    if freshness == "fresh" and existing is not None:
        metrics.topology_cache_hit = True
        metrics.topology_source = str(existing.get("topology_source") or "unknown")
        metrics.topology_node_count = len(existing.get("nodes") or [])
        return TopologyBuildResult(existing, freshness, metrics)
    if policy_name in {"read_only", "no_write"}:
        metrics.topology_cache_miss = True
        metrics.topology_source = str((existing or {}).get("topology_source") or "missing")
        metrics.topology_node_count = len((existing or {}).get("nodes") or [])
        return TopologyBuildResult(existing, freshness, metrics)
    return build_topology(root, inventory=inventory, write=policy_name != "no_write")


def summarize_topology(repo_root: Path | str, topology: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(repo_root)
    payload = load_topology(root) if topology is None else topology
    freshness = topology_is_fresh(root, payload)
    nodes = payload.get("nodes") if isinstance(payload, dict) else []
    default_policy = payload.get("default_node_policy") if isinstance(payload, dict) else {}
    return {
        "state": freshness,
        "repo_shape": payload.get("repo_shape") if isinstance(payload, dict) else None,
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "primary_node": default_policy.get("primary_node") if isinstance(default_policy, dict) else None,
        "freshness": freshness,
        "fallback_used": freshness != "fresh",
        "cache_path": str(TOPOLOGY_REL_PATH),
    }


def _path_node_matches(path: str, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = [node for node in nodes if _inside(path, str(node.get("root") or "."))]
    return sorted(matches, key=lambda item: str(item.get("root") or ".").count("/"), reverse=True)


def select_project_nodes(
    prompt: str,
    repo_root: Path | str,
    topology: dict[str, Any],
    *,
    cwd: Path | str | None = None,
    explicit_paths: list[str] | None = None,
    dirty_files: list[str] | None = None,
    max_nodes: int = 3,
) -> dict[str, Any]:
    root = Path(repo_root)
    nodes = [node for node in topology.get("nodes") or [] if isinstance(node, dict)]
    if not nodes:
        return {
            "selected_nodes": [],
            "primary_node": None,
            "selection_reason": "no_topology_nodes",
            "signal_scores": {},
            "ambiguous": False,
            "fallback_used": True,
            "confidence": 0.0,
        }
    evidence = extract_prompt_evidence(prompt)
    explicit = list(explicit_paths or [])
    explicit.extend(evidence.explicit_paths)
    signal_scores: dict[str, dict[str, int]] = {str(node.get("id")): {} for node in nodes}

    def add(node: dict[str, Any], signal: str, amount: int) -> None:
        node_id = str(node.get("id"))
        signal_scores.setdefault(node_id, {})
        signal_scores[node_id][signal] = signal_scores[node_id].get(signal, 0) + amount

    for raw in explicit:
        rel = _norm_rel(root, raw)
        if rel:
            for node in _path_node_matches(rel, nodes)[:1]:
                add(node, "explicit_path", 100)
    if not any("explicit_path" in scores for scores in signal_scores.values()):
        if cwd is not None:
            rel = _norm_rel(root, cwd)
            if rel:
                for node in _path_node_matches(rel, nodes)[:1]:
                    add(node, "cwd", 75)
        for raw in dirty_files or []:
            rel = _norm_rel(root, raw)
            if rel:
                for node in _path_node_matches(rel, nodes)[:1]:
                    add(node, "dirty_file", 60)
    prompt_terms = _tokens(prompt)
    test_hint = bool(prompt_terms & {"test", "tests", "failing", "spec"})
    source_hint = bool(prompt_terms & {"source", "src", "parser", "router", "client", "app"})
    ecosystem_terms = {
        "python": {"python", "pytest", "pyproject"},
        "node_ts": {"node", "typescript", "ts", "tsx", "npm", "package", "extension"},
        "go": {"go", "golang"},
        "rust": {"rust", "cargo", "crate"},
        "swift_ios": {"swift", "ios", "xcode", "launch"},
        "cpp": {"cmake", "cpp", "c++"},
        "java_kotlin": {"java", "kotlin", "gradle", "maven"},
        "bazel_polyglot": {"bazel", "workspace"},
        "docs": {"docs", "documentation", "install", "readme"},
    }
    for node in nodes:
        root_terms = _root_terms(str(node.get("root") or "."))
        if prompt_terms & root_terms:
            add(node, "prompt_root_term", 30)
        ecosystem = str(node.get("ecosystem") or "unknown")
        if prompt_terms & ecosystem_terms.get(ecosystem, set()):
            add(node, "prompt_ecosystem_term", 20)
        if test_hint and node.get("test_count"):
            add(node, "test_hint", 8)
        if source_hint and node.get("source_count"):
            add(node, "source_hint", 5)
    totals = {
        node_id: sum(scores.values())
        for node_id, scores in signal_scores.items()
    }
    sorted_nodes = sorted(nodes, key=lambda item: (totals.get(str(item.get("id")), 0), float(item.get("confidence") or 0)), reverse=True)
    top_score = totals.get(str(sorted_nodes[0].get("id")), 0)
    fallback_used = top_score == 0
    if fallback_used:
        fallback_id = (topology.get("default_node_policy") or {}).get("primary_node")
        sorted_nodes = sorted(nodes, key=lambda item: str(item.get("id")) != str(fallback_id))
        top_score = 1
        add(sorted_nodes[0], "root_fallback", 1)
    selected = [node for node in sorted_nodes if totals.get(str(node.get("id")), 0) >= max(1, top_score - 10)][:max_nodes]
    if fallback_used:
        selected = sorted_nodes[:1]
    primary = selected[0]
    close_count = sum(1 for node in nodes if totals.get(str(node.get("id")), 0) and totals.get(str(node.get("id")), 0) >= top_score - 5)
    ambiguous = close_count > 1 and not any("explicit_path" in scores for scores in signal_scores.values())
    return {
        "selected_nodes": [
            {
                "id": node.get("id"),
                "root": node.get("root"),
                "ecosystem": node.get("ecosystem"),
                "confidence": node.get("confidence"),
            }
            for node in selected
        ],
        "primary_node": primary.get("id"),
        "selection_reason": next(iter(sorted(signal_scores.get(str(primary.get("id")), {}).keys())), "root_fallback"),
        "signal_scores": signal_scores,
        "ambiguous": ambiguous,
        "fallback_used": fallback_used,
        "confidence": round(min(0.95, 0.35 + (top_score / 120)), 2) if not ambiguous else 0.45,
    }
