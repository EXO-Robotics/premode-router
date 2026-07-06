from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


MODEL_FACING_PACKET_BOUNDARY = [
    "TASK",
    "PRIMARY_FILES",
    "RELATED_TESTS",
    "END_PREMODE_CONTEXT_PACKET_V5",
]

TUNING_DIR = PurePosixPath(".premode/tuning")
PROFILE_SCHEMA_VERSION = "pcodex.repo_profile.v1"
ARTIFACT_SCHEMAS = {
    "path_taxonomy": "pcodex.path_taxonomy.v1",
    "repo_vocabulary": "pcodex.repo_vocabulary.v1",
    "source_test_map": "pcodex.source_test_map.v1",
    "prompt_phrase_routes": "pcodex.prompt_phrase_routes.v1",
    "hotspots_and_suppressions": "pcodex.hotspots_and_suppressions.v1",
    "literal_symbol_weights": "pcodex.literal_symbol_weights.v1",
}
ARTIFACT_FILES = {
    "path_taxonomy": TUNING_DIR / "path_taxonomy.json",
    "repo_vocabulary": TUNING_DIR / "repo_vocabulary.json",
    "source_test_map": TUNING_DIR / "source_test_map.json",
    "prompt_phrase_routes": TUNING_DIR / "prompt_phrase_routes.json",
    "hotspots_and_suppressions": TUNING_DIR / "hotspots_and_suppressions.json",
    "literal_symbol_weights": TUNING_DIR / "literal_symbol_weights.json",
}

MAX_FILES_INDEXED = 10_000
MAX_FILE_BYTES_READ = 64_000
MAX_SYMBOLS_PER_FILE = 40
MAX_TERMS = 2_000
MAX_PATHS_PER_TERM = 8
MAX_PROMPT_ROUTES = 500
MAX_GIT_HISTORY_ENTRIES = 500
MAX_REPORT_LINE_LENGTH = 160
MAX_EVALUATION_PROMPTS = 200

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
}
DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt"}
CONFIG_NAMES = {
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "cargo.toml",
    "go.mod",
    "go.sum",
    "package.swift",
    "makefile",
    "dockerfile",
    "tsconfig.json",
    "vite.config.ts",
    "webpack.config.js",
}
CONFIG_EXTENSIONS = {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".plist"}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    ".cache",
    ".dart_tool",
    ".terraform",
}
NOISE_DIRS = {"build", "dist", "out", "target", "tmp", "temp", "coverage", ".next"}
GENERATED_SEGMENTS = {"generated", "gen", "autogen", "codegen"}
VENDOR_SEGMENTS = {"vendor", "third_party", "external", "externals"}
SECRET_NAME_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|credential|passwd|password|private[_-]?key|secret|token|cookie)"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"AKIA[0-9A-Z]{12,}|"
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|"
    r"(?:secret|token|password|api[_-]?key)[\"'\s:=]{1,8}[A-Za-z0-9_./+=-]{8,}|"
    r"bearer\s+[A-Za-z0-9_./+=-]{12,}"
    r")"
)
HIGH_ENTROPY_RE = re.compile(r"\b[A-Za-z0-9_+/=-]{32,}\b")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{1,79}")
PY_SYMBOL_RE = re.compile(r"(?m)^\s*(?:class|def|async\s+def)\s+([A-Za-z_][A-Za-z0-9_]*)")
JS_SYMBOL_RE = re.compile(r"(?m)^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|const|let)\s+([A-Za-z_$][A-Za-z0-9_$]*)")
SWIFT_SYMBOL_RE = re.compile(r"(?m)^\s*(?:public\s+|private\s+|internal\s+)?(?:struct|class|enum|protocol|func)\s+([A-Za-z_][A-Za-z0-9_]*)")
C_SYMBOL_RE = re.compile(r"(?m)^\s*(?:class|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)")
IMPORT_RE = re.compile(
    r"""(?m)^\s*(?:from\s+([.A-Za-z0-9_]+)\s+import|import\s+([A-Za-z0-9_.,\s]+)|import\s+[^"'\n]+?\s+from\s+["']([^"']+)["']|#include\s+[<"]([^>"]+)[>"])"""
)
HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.{1,80})$")


@dataclass
class StaticInventory:
    repo_root: Path
    files: list[str]
    caps_hit: list[str] = field(default_factory=list)


def find_repo_root(start: Path | str | None = None) -> Path:
    current = Path.cwd() if start is None else Path(start)
    current = current.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def _posix_rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _is_under_tuning(path: str) -> bool:
    return path == ".premode/tuning" or path.startswith(".premode/tuning/")


def _safe_out_dir(repo_root: Path, out_dir: Path | str | None = None) -> Path:
    candidate = repo_root / ".premode" / "tuning" if out_dir is None else Path(out_dir)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        rel = _posix_rel(candidate.resolve(), repo_root.resolve())
    except ValueError as exc:
        raise ValueError("pcodex tuning artifacts must be written under .premode/tuning/") from exc
    if not _is_under_tuning(rel):
        raise ValueError("pcodex tuning artifacts must be written under .premode/tuning/")
    return candidate


def _iter_files(repo_root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(repo_root):
        rel_dir = Path(dirpath).relative_to(repo_root).as_posix() if Path(dirpath) != repo_root else ""
        parts = set(rel_dir.split("/")) if rel_dir else set()
        dirnames[:] = [
            name
            for name in sorted(dirnames)
            if name not in SKIP_DIRS and not _is_under_tuning(f"{rel_dir}/{name}".strip("/"))
        ]
        if parts & NOISE_DIRS:
            dirnames[:] = []
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = _posix_rel(path, repo_root)
            if _is_under_tuning(rel):
                continue
            yield path


def collect_static_repo_inventory(repo_root: Path | str, *, max_files: int = MAX_FILES_INDEXED) -> StaticInventory:
    root = find_repo_root(repo_root)
    files: list[str] = []
    caps_hit: list[str] = []
    for path in _iter_files(root):
        if len(files) >= max_files:
            caps_hit.append("max_files_indexed")
            break
        if path.is_file():
            files.append(_posix_rel(path, root))
    return StaticInventory(repo_root=root, files=files, caps_hit=caps_hit)


def _path_parts(path: str) -> list[str]:
    return [part.lower() for part in path.split("/") if part]


def _is_generated(path: str) -> bool:
    lower = path.lower()
    parts = set(_path_parts(path))
    return bool(parts & GENERATED_SEGMENTS) or any(marker in lower for marker in (".generated.", "_generated.", ".gen."))


def _is_vendor(path: str) -> bool:
    return bool(set(_path_parts(path)) & VENDOR_SEGMENTS)


def _classify_path(path: str) -> tuple[str, str, str]:
    lower = path.lower()
    name = PurePosixPath(lower).name
    ext = PurePosixPath(lower).suffix
    parts = set(_path_parts(path))
    if _is_vendor(path):
        return "vendor", "high", "vendor_directory"
    if _is_generated(path):
        return "generated", "high", "generated_directory_or_suffix"
    if parts & NOISE_DIRS:
        return "noise", "high", "noise_directory"
    if "fixture" in lower or "fixtures" in parts:
        return "fixture", "medium", "fixture_name"
    if "snapshot" in lower or "snapshots" in parts or "__snapshots__" in parts:
        return "snapshot", "medium", "snapshot_name"
    if "test" in parts or "tests" in parts or name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.ts") or name.endswith(".spec.ts"):
        return "test", "high", "test_path_or_filename"
    if ext in DOC_EXTENSIONS or "docs" in parts or name in {"readme", "readme.md"}:
        return "docs", "high", "docs_extension_or_directory"
    if name in CONFIG_NAMES or ext in CONFIG_EXTENSIONS or "config" in name:
        return "config", "medium", "config_name_or_extension"
    if ext in SOURCE_EXTENSIONS:
        return "source", "medium", "source_extension"
    return "unknown", "low", "no_rule_match"


def classify_paths(inventory: StaticInventory) -> dict[str, Any]:
    paths = []
    role_counts: dict[str, int] = {}
    for rel in inventory.files:
        role, confidence, reason = _classify_path(rel)
        role_counts[role] = role_counts.get(role, 0) + 1
        paths.append({"path": rel, "role": role, "confidence": confidence, "reason": reason})
    return {
        "schema_version": ARTIFACT_SCHEMAS["path_taxonomy"],
        "paths": paths,
        "role_counts": role_counts,
        "ignored_globs": sorted(SKIP_DIRS),
        "generated_globs": ["generated/**", "gen/**", "*.generated.*", "*_generated.*"],
        "caps": {"max_files_indexed": MAX_FILES_INDEXED},
        "caps_hit": list(inventory.caps_hit),
    }


def _safe_read_text(path: Path) -> str:
    try:
        data = path.read_bytes()[:MAX_FILE_BYTES_READ]
    except OSError:
        return ""
    if b"\x00" in data:
        return ""
    return data.decode("utf-8", errors="replace")


def _safe_term(term: str) -> str | None:
    normalized = term.strip().strip("#`'\"").replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not (2 <= len(normalized) <= 80):
        return None
    if SECRET_NAME_RE.search(normalized) or SECRET_VALUE_RE.search(normalized) or HIGH_ENTROPY_RE.fullmatch(normalized):
        return None
    return normalized.lower()


def _tokenize_path(path: str) -> list[str]:
    pieces = re.split(r"[/_.\-\s]+", path)
    terms = []
    for piece in pieces:
        term = _safe_term(piece)
        if term and term not in {"src", "lib", "test", "tests", "docs", "file"}:
            terms.append(term)
    return terms[:12]


def _symbol_patterns(path: str) -> list[re.Pattern[str]]:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".py":
        return [PY_SYMBOL_RE]
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return [JS_SYMBOL_RE]
    if suffix == ".swift":
        return [SWIFT_SYMBOL_RE]
    if suffix in {".c", ".cc", ".cpp", ".h", ".hpp"}:
        return [C_SYMBOL_RE]
    return [PY_SYMBOL_RE, JS_SYMBOL_RE, SWIFT_SYMBOL_RE, C_SYMBOL_RE]


def _add_term(store: dict[str, dict[str, Any]], term: str, path: str, source: str) -> None:
    safe = _safe_term(term)
    if safe is None:
        return
    item = store.setdefault(safe, {"term": safe, "paths": [], "count": 0, "sources": []})
    item["count"] += 1
    if path not in item["paths"] and len(item["paths"]) < MAX_PATHS_PER_TERM:
        item["paths"].append(path)
    if source not in item["sources"]:
        item["sources"].append(source)


def extract_repo_vocabulary(inventory: StaticInventory, taxonomy: dict[str, Any]) -> dict[str, Any]:
    by_path = {entry["path"]: entry for entry in taxonomy.get("paths", [])}
    terms: dict[str, dict[str, Any]] = {}
    symbols: dict[str, dict[str, Any]] = {}
    imports: dict[str, dict[str, Any]] = {}
    headings: dict[str, dict[str, Any]] = {}
    for rel in inventory.files:
        role = by_path.get(rel, {}).get("role")
        for token in _tokenize_path(rel):
            _add_term(terms, token, rel, "path")
        if role in {"generated", "vendor", "noise"}:
            continue
        text = _safe_read_text(inventory.repo_root / rel)
        if not text:
            continue
        for pattern in _symbol_patterns(rel):
            for match in pattern.findall(text)[:MAX_SYMBOLS_PER_FILE]:
                symbol = match[0] if isinstance(match, tuple) else match
                _add_term(symbols, symbol, rel, "symbol")
                _add_term(terms, symbol, rel, "symbol")
        for groups in IMPORT_RE.findall(text)[:MAX_SYMBOLS_PER_FILE]:
            module = next((group.strip() for group in groups if group and group.strip()), "")
            for chunk in re.split(r"[,\s]+", module):
                _add_term(imports, chunk, rel, "import")
                _add_term(terms, chunk, rel, "import")
        if PurePosixPath(rel).suffix.lower() in DOC_EXTENSIONS:
            for heading in HEADING_RE.findall(text)[:MAX_SYMBOLS_PER_FILE]:
                _add_term(headings, heading, rel, "heading")
                _add_term(terms, heading, rel, "heading")
    term_items = sorted(terms.values(), key=lambda item: (-int(item["count"]), item["term"]))[:MAX_TERMS]
    return {
        "schema_version": ARTIFACT_SCHEMAS["repo_vocabulary"],
        "terms": term_items,
        "symbols": sorted(symbols.values(), key=lambda item: (-int(item["count"]), item["term"]))[:MAX_TERMS],
        "imports": sorted(imports.values(), key=lambda item: (-int(item["count"]), item["term"]))[:MAX_TERMS],
        "headings": sorted(headings.values(), key=lambda item: (-int(item["count"]), item["term"]))[:MAX_TERMS],
        "caps": {
            "max_terms": MAX_TERMS,
            "max_paths_per_term": MAX_PATHS_PER_TERM,
            "max_symbols_per_file": MAX_SYMBOLS_PER_FILE,
            "max_file_bytes_read": MAX_FILE_BYTES_READ,
        },
    }


def _stem_key(path: str) -> str:
    stem = PurePosixPath(path).stem.lower()
    stem = re.sub(r"^(test_|test-)", "", stem)
    stem = re.sub(r"(_test|-test|\.test|\.spec)$", "", stem)
    return re.sub(r"[^a-z0-9]+", "", stem)


def _dir_terms(path: str) -> set[str]:
    return {term for part in PurePosixPath(path).parts[:-1] for term in _tokenize_path(part)}


def infer_source_test_map(inventory: StaticInventory, taxonomy: dict[str, Any]) -> dict[str, Any]:
    entries = taxonomy.get("paths", [])
    sources = [entry["path"] for entry in entries if entry.get("role") == "source"]
    tests = [entry["path"] for entry in entries if entry.get("role") == "test"]
    mappings = []
    for source in sources:
        matches = []
        source_key = _stem_key(source)
        source_dirs = _dir_terms(source)
        for test in tests:
            test_key = _stem_key(test)
            confidence = 0.0
            relation_type = "weak_name_overlap"
            evidence = []
            if source_key and source_key == test_key:
                confidence = 0.92
                relation_type = "basename_exact"
                evidence.append(source_key)
            else:
                shared = sorted((source_dirs & _dir_terms(test)) - {"src", "source", "tests", "test"})
                if shared:
                    confidence = 0.62
                    relation_type = "directory_term_overlap"
                    evidence.extend(shared[:3])
                elif source_key and source_key in test_key:
                    confidence = 0.55
                    relation_type = "basename_partial"
                    evidence.append(source_key)
            if confidence:
                matches.append({"test_path": test, "confidence": confidence, "relation_type": relation_type, "evidence": evidence[:3]})
        matches.sort(key=lambda item: (-float(item["confidence"]), item["test_path"]))
        if matches:
            mappings.append({"source_path": source, "tests": matches[:8]})
    mapped_sources = {item["source_path"] for item in mappings}
    mapped_tests = {test["test_path"] for item in mappings for test in item["tests"]}
    return {
        "schema_version": ARTIFACT_SCHEMAS["source_test_map"],
        "mappings": mappings,
        "unmapped_sources": [path for path in sources if path not in mapped_sources],
        "unmapped_tests": [path for path in tests if path not in mapped_tests],
        "caps": {"max_tests_per_source": 8},
    }


def infer_prompt_phrase_routes(taxonomy: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    role_terms: dict[str, set[str]] = {}
    for entry in taxonomy.get("paths", []):
        role = entry.get("role")
        if not isinstance(role, str) or role in {"generated", "vendor", "noise", "unknown"}:
            continue
        for term in _tokenize_path(entry["path"]):
            role_terms.setdefault(term, set()).add(role)
    routes = []
    ambiguous = []
    for item in vocabulary.get("terms", [])[:MAX_TERMS]:
        term = item.get("term")
        if not isinstance(term, str) or len(term) > 80:
            continue
        roles = sorted(role_terms.get(term, []))
        if not roles:
            continue
        route = {
            "phrase": term,
            "targets": [{"role": role} for role in roles[:3]],
            "confidence": 0.45 if len(roles) > 1 else 0.7,
            "ambiguity": "ambiguous" if len(roles) > 1 else "none",
            "evidence": {"source": "static_vocabulary", "term_count": item.get("count", 0)},
        }
        if len(roles) > 1:
            ambiguous.append({"phrase": term, "candidate_roles": roles[:5], "tie_break_policy": "prefer explicit prompt paths and exact symbols"})
        routes.append(route)
        if len(routes) >= MAX_PROMPT_ROUTES:
            break
    return {
        "schema_version": ARTIFACT_SCHEMAS["prompt_phrase_routes"],
        "routes": routes,
        "ambiguous_phrases": ambiguous,
        "caps": {"max_prompt_routes": MAX_PROMPT_ROUTES},
    }


def _git_recent_counts(repo_root: Path) -> tuple[dict[str, int], bool]:
    try:
        completed = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", f"-n{MAX_GIT_HISTORY_ENTRIES}"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return {}, False
    if completed.returncode != 0:
        return {}, False
    counts: dict[str, int] = {}
    for line in completed.stdout.splitlines():
        path = line.strip()
        if path and not path.startswith("/") and not _is_under_tuning(path):
            counts[path] = counts.get(path, 0) + 1
    return counts, True


def infer_hotspots_and_suppressions(inventory: StaticInventory, taxonomy: dict[str, Any]) -> dict[str, Any]:
    git_counts, git_available = _git_recent_counts(inventory.repo_root)
    current = set(inventory.files)
    boosts = [
        {"path": path, "weight": min(1.0, 0.2 + count / 10), "confidence": 0.5, "source": "local_git_history", "count": count}
        for path, count in sorted(git_counts.items(), key=lambda item: (-item[1], item[0]))
        if path in current
    ][:200]
    suppressions = []
    for entry in taxonomy.get("paths", []):
        role = entry.get("role")
        if role in {"generated", "vendor", "noise"}:
            suppressions.append({"path": entry["path"], "reason": f"{role}_path", "weight": -2.5, "confidence": 0.95})
    return {
        "schema_version": ARTIFACT_SCHEMAS["hotspots_and_suppressions"],
        "boosts": boosts,
        "suppressions": suppressions,
        "git_history_window": {"max_entries": MAX_GIT_HISTORY_ENTRIES, "available": git_available},
        "decay_policy": "bounded_static_counts_only",
    }


def build_literal_symbol_weights() -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMAS["literal_symbol_weights"],
        "weights": {
            "exact_symbol_match": 2.0,
            "filename_term_match": 1.4,
            "directory_term_match": 0.8,
            "source_test_relation": 1.1,
            "docs_intent_match": 0.6,
            "config_intent_match": 0.7,
            "generated_suppression": -2.5,
            "vendor_suppression": -2.5,
            "noise_suppression": -2.0,
            "ambiguous_phrase_penalty": -0.4,
        },
        "caps": {"per_path_total_boost": 5.0, "per_path_total_penalty": -5.0},
        "tie_breakers": ["explicit_prompt_path", "exact_symbol", "source_test_map", "path_taxonomy_role"],
        "safety_caps": {"cannot_disable_suppressions": True, "max_weight_abs": 5.0},
    }


def _artifact_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _repo_head(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, capture_output=True, check=False, timeout=5)
    except Exception:
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _relative_artifact(path: PurePosixPath) -> str:
    return path.as_posix()


def _evaluation_prompts(inventory: StaticInventory, source_map: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, mapping in enumerate(source_map.get("mappings", [])[:MAX_EVALUATION_PROMPTS], start=1):
        source = mapping["source_path"]
        tests = [item["test_path"] for item in mapping.get("tests", [])[:3]]
        stem = PurePosixPath(source).stem.replace("_", " ").replace("-", " ")
        rows.append(
            {
                "id": f"static-{index:03d}",
                "prompt": f"Update {stem} behavior and related tests.",
                "expected_primary_files": [source],
                "expected_related_tests": tests,
                "tags": ["static", "generated-by-pcodex-tune"],
            }
        )
    if not rows and inventory.files:
        first_source = next((path for path in inventory.files if _classify_path(path)[0] == "source"), inventory.files[0])
        rows.append(
            {
                "id": "static-001",
                "prompt": f"Inspect {PurePosixPath(first_source).name} and report the relevant path.",
                "expected_primary_files": [first_source],
                "expected_related_tests": [],
                "tags": ["static", "fallback"],
            }
        )
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _report_lines(repo_root: Path, artifacts: dict[str, str], validation: dict[str, Any], inventory: StaticInventory) -> list[str]:
    lines = [
        "# pCodex Static Tuning Report",
        "",
        "## Summary",
        f"- repo: {repo_root.name}",
        f"- files indexed: {len(inventory.files)}",
        "- mode: static-only local metadata",
        "- source edits: none",
        "- model-facing packet expansion: none",
        "- secret values stored: none",
        "- diagnostics: out-of-band",
        "",
        "## Artifacts",
    ]
    lines.extend(f"- {name}: {path}" for name, path in artifacts.items())
    lines.extend(["", "## Safety", "- local-only scan", "- generated/vendor/noise paths suppressed", "- no large source snippets stored", "", "## Validation", f"- status: {validation.get('status', 'not_run')}"])
    return [line[:MAX_REPORT_LINE_LENGTH] for line in lines]


def write_tuning_artifacts(repo_root: Path | str, *, out_dir: Path | str | None = None) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    output_dir = _safe_out_dir(root, out_dir)
    inventory = collect_static_repo_inventory(root)
    taxonomy = classify_paths(inventory)
    vocabulary = extract_repo_vocabulary(inventory, taxonomy)
    source_map = infer_source_test_map(inventory, taxonomy)
    routes = infer_prompt_phrase_routes(taxonomy, vocabulary)
    hotspots = infer_hotspots_and_suppressions(inventory, taxonomy)
    weights = build_literal_symbol_weights()
    artifacts = {name: _relative_artifact(path) for name, path in ARTIFACT_FILES.items()}
    profile = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "base_algorithm": "literal_symbol",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repo_fingerprint": {"root_name": root.name, "git_head": _repo_head(root), "file_count": len(inventory.files)},
        "artifacts": artifacts,
        "model_facing_packet_boundary": MODEL_FACING_PACKET_BOUNDARY,
        "diagnostics_out_of_band": True,
        "generated_by": "pcodex tune --static-only",
        "caps": {
            "max_files_indexed": MAX_FILES_INDEXED,
            "max_symbols_per_file": MAX_SYMBOLS_PER_FILE,
            "max_vocabulary_terms": MAX_TERMS,
            "max_prompt_routes": MAX_PROMPT_ROUTES,
            "max_git_history_entries": MAX_GIT_HISTORY_ENTRIES,
            "max_report_line_length": MAX_REPORT_LINE_LENGTH,
        },
        "caps_hit": inventory.caps_hit,
    }
    payloads = {
        "repo_profile": profile,
        "path_taxonomy": taxonomy,
        "repo_vocabulary": vocabulary,
        "source_test_map": source_map,
        "prompt_phrase_routes": routes,
        "hotspots_and_suppressions": hotspots,
        "literal_symbol_weights": weights,
    }
    for name, payload in payloads.items():
        filename = "repo_profile.json" if name == "repo_profile" else f"{name}.json"
        _write_json(output_dir / filename, payload)
    _write_jsonl(output_dir / "evaluation_prompts.jsonl", _evaluation_prompts(inventory, source_map))
    validation = validate_tuning_artifacts(root, out_dir=output_dir, write_report=False)
    (output_dir / "TUNING_REPORT.md").write_text("\n".join(_report_lines(root, {"repo_profile": ".premode/tuning/repo_profile.json", **artifacts, "evaluation_prompts": ".premode/tuning/evaluation_prompts.jsonl", "TUNING_REPORT": ".premode/tuning/TUNING_REPORT.md"}, validation, inventory)) + "\n", encoding="utf-8")
    validation = validate_tuning_artifacts(root, out_dir=output_dir, write_report=True)
    return {
        "status": "generated" if validation["status"] == "pass" else "generated_with_validation_failures",
        "repo_root": str(root),
        "out_dir": str(output_dir),
        "artifacts": {"repo_profile": str(output_dir / "repo_profile.json"), **{name: str(output_dir / f"{name}.json") for name in ARTIFACT_FILES}, "evaluation_prompts": str(output_dir / "evaluation_prompts.jsonl"), "TUNING_REPORT": str(output_dir / "TUNING_REPORT.md")},
        "safety_summary": {
            "static_only": True,
            "local_only": True,
            "source_edits": False,
            "model_facing_packet_expansion": False,
            "diagnostics_out_of_band": True,
            "secrets_stored": False,
        },
        "validation_status": validation["status"],
        "validation_failures": validation.get("failures", []),
        "next": "pcodex tune --validate",
    }


def _walk_values(obj: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _walk_values(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _walk_values(value, f"{path}[{index}]")
    elif isinstance(obj, str):
        yield path, obj


def _is_snippet_like(value: str) -> bool:
    if "\n" in value:
        return True
    if len(value) > 240:
        return True
    code_markers = ("def ", "class ", "function ", "=>", "return ", "import ", "#include", "public struct ")
    return len(value) > 120 and any(marker in value for marker in code_markers)


def _load_json(path: Path, failures: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"invalid_json:{path.name}:{exc.__class__.__name__}")
        return None


def _validate_no_absolute_or_external_paths(obj: Any, failures: list[str], *, artifact: str) -> None:
    for value_path, value in _walk_values(obj):
        if value.startswith("/"):
            failures.append(f"absolute_path:{artifact}:{value_path}")
        if ".premode/tuning" in value and not value.startswith(".premode/tuning"):
            failures.append(f"unsafe_tuning_path:{artifact}:{value_path}")


def _validate_safe_strings(obj: Any, failures: list[str], *, artifact: str) -> None:
    for value_path, value in _walk_values(obj):
        if SECRET_VALUE_RE.search(value):
            failures.append(f"secret_like_value:{artifact}:{value_path}")
        if _is_snippet_like(value):
            failures.append(f"large_or_snippet_like_string:{artifact}:{value_path}")


def _validate_artifact_paths(profile: dict[str, Any], out_dir: Path, failures: list[str]) -> None:
    artifacts = profile.get("artifacts")
    if not isinstance(artifacts, dict):
        failures.append("profile_artifacts_missing")
        return
    for key, rel in ARTIFACT_FILES.items():
        actual = artifacts.get(key)
        expected = rel.as_posix()
        if actual != expected:
            failures.append(f"profile_artifact_path_mismatch:{key}")
        if not (out_dir / f"{key}.json").exists():
            failures.append(f"missing_artifact:{key}")


def validate_tuning_artifacts(repo_root: Path | str, *, out_dir: Path | str | None = None, write_report: bool = True) -> dict[str, Any]:
    root = find_repo_root(repo_root)
    output_dir = _safe_out_dir(root, out_dir)
    failures: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, str]] = []
    profile_path = output_dir / "repo_profile.json"
    if not profile_path.exists():
        failures.append("missing_artifact:repo_profile")
        profile = None
    else:
        profile = _load_json(profile_path, failures)
    if isinstance(profile, dict):
        expected = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "base_algorithm": "literal_symbol",
            "diagnostics_out_of_band": True,
        }
        for key, value in expected.items():
            if profile.get(key) != value:
                failures.append(f"profile_{key}_invalid")
        if profile.get("model_facing_packet_boundary") != MODEL_FACING_PACKET_BOUNDARY:
            failures.append("profile_model_facing_packet_boundary_invalid")
        _validate_artifact_paths(profile, output_dir, failures)
        _validate_no_absolute_or_external_paths(profile, failures, artifact="repo_profile")
        _validate_safe_strings(profile, failures, artifact="repo_profile")
    loaded: dict[str, Any] = {}
    for key, schema in ARTIFACT_SCHEMAS.items():
        path = output_dir / f"{key}.json"
        if not path.exists():
            failures.append(f"missing_artifact:{key}")
            continue
        payload = _load_json(path, failures)
        loaded[key] = payload
        if isinstance(payload, dict):
            if payload.get("schema_version") != schema:
                failures.append(f"{key}_schema_version_invalid")
            _validate_no_absolute_or_external_paths(payload, failures, artifact=key)
            _validate_safe_strings(payload, failures, artifact=key)
    eval_path = output_dir / "evaluation_prompts.jsonl"
    if not eval_path.exists():
        failures.append("missing_artifact:evaluation_prompts")
    else:
        seen_ids = set()
        for index, line in enumerate(eval_path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                failures.append(f"evaluation_prompts_invalid_json:{index}")
                continue
            prompt = row.get("prompt")
            row_id = row.get("id")
            if not isinstance(row_id, str) or not row_id:
                failures.append(f"evaluation_prompts_missing_id:{index}")
            elif row_id in seen_ids:
                failures.append(f"evaluation_prompts_duplicate_id:{row_id}")
            seen_ids.add(row_id)
            if not isinstance(prompt, str) or len(prompt) > 500:
                failures.append(f"evaluation_prompts_invalid_prompt:{index}")
            _validate_safe_strings(row, failures, artifact="evaluation_prompts")
            _validate_no_absolute_or_external_paths(row, failures, artifact="evaluation_prompts")
    if not (output_dir / "TUNING_REPORT.md").exists():
        failures.append("missing_artifact:TUNING_REPORT")
    else:
        report = (output_dir / "TUNING_REPORT.md").read_text(encoding="utf-8")
        if SECRET_VALUE_RE.search(report):
            failures.append("secret_like_value:TUNING_REPORT")
        for line_no, line in enumerate(report.splitlines(), start=1):
            if len(line) > MAX_REPORT_LINE_LENGTH:
                warnings.append(f"long_report_line:{line_no}")
    if "path_taxonomy" in loaded and isinstance(loaded["path_taxonomy"], dict):
        suppress_roles = {entry.get("role") for entry in loaded["path_taxonomy"].get("paths", []) if isinstance(entry, dict)}
        if not ({"generated", "vendor"} & suppress_roles):
            warnings.append("no_generated_or_vendor_paths_observed")
    status = "fail" if failures else "pass"
    checks.append({"name": "schema_and_safety", "status": status})
    artifact_hashes = {}
    for path in sorted(output_dir.glob("*")):
        if path.is_file() and path.name not in {"VALIDATION.json", "VALIDATION.md"}:
            artifact_hashes[path.name] = _artifact_hash(path)
    result = {"status": status, "checks": checks, "artifact_hashes": artifact_hashes, "warnings": warnings, "failures": failures}
    if write_report:
        _write_json(output_dir / "VALIDATION.json", result)
        lines = ["# pCodex Tuning Validation", "", f"status: {status}", "", "## Checks"]
        lines.extend(f"- {check['name']}: {check['status']}" for check in checks)
        if failures:
            lines.extend(["", "## Blocking failures", *[f"- {failure}" for failure in failures]])
        if warnings:
            lines.extend(["", "## Warnings", *[f"- {warning}" for warning in warnings]])
        (output_dir / "VALIDATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
