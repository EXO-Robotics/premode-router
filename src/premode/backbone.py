from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .locator import is_scaffold_meta_term
from .role_model import classify_path_role, infer_prompt_intent

MAX_DISCOVERY_BYTES_PER_FILE = 80_000
MAX_PRIMARY_FILES = 4
MAX_RELATED_TESTS = 3
MAX_SUPPORT_RELATIONS = 3
MAX_PRIMARY_ANCHORS = 3
MAX_RELATED_ANCHORS = 2
MAX_TOTAL_MODEL_ANCHORS = 12
MAX_INTERNAL_FILES_SCANNED = 8
MAX_INTERNAL_LINES_SCANNED = 12_000
MAX_INTERNAL_BYTES_SCANNED = 750_000

INTERNAL_ANCHOR_STRATEGIES = {
    "literal_symbol",
    "literal_symbol_test_names",
    "literal_symbol_config",
    "literal_symbol_config_gated",
    "literal_symbol_docs",
    "literal_symbol_docs_heading_gated",
    "literal_symbol_cli_route",
    "literal_symbol_import_boost",
    "literal_symbol_import_rank_json_only",
    "literal_symbol_collision_filter",
    "literal_symbol_policy_by_prompt_type",
    "tests_first_anchoring",
    "top1_primary",
    "policy_by_prompt_type",
}

ALLOWED_ANCHOR_TYPES = {
    "symbol",
    "literal",
    "heading",
    "config_section",
    "test_name",
    "cli_flag",
    "route",
    "package_name",
    "module_name",
    "import_name",
}

FORBIDDEN_ANCHOR_TERMS = {
    "acceptance",
    "benchmark",
    "because",
    "codex",
    "command",
    "confidence",
    "contract",
    "decision",
    "diagnostic",
    "do_not",
    "do-not-edit",
    "harness",
    "lab",
    "metadata",
    "must",
    "packet",
    "policy",
    "premode",
    "pre-mode",
    "review",
    "risk",
    "safety",
    "scope",
    "should",
    "validation",
    "verify",
    "warning",
    "why",
}

GENERIC_ANCHOR_TERMS = {
    "change",
    "command",
    "config",
    "file",
    "fix",
    "index",
    "main",
    "option",
    "path",
    "review",
    "run",
    "scope",
    "test",
    "update",
    "validation",
    "value",
    "warning",
}

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}|--?[A-Za-z][A-Za-z0-9_-]+")
QUOTED_RE = re.compile(r"['\"]([^'\"]{2,80})['\"]")
CLI_FLAG_RE = re.compile(r"(?<![A-Za-z0-9_-])--?[A-Za-z][A-Za-z0-9_-]+")
HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.{2,100})$")
CONFIG_SECTION_RE = re.compile(r"(?m)^\s*\[+([A-Za-z0-9_.-]{2,80})\]+\s*$")
CONFIG_KEY_RE = re.compile(r"(?m)^\s*[\"']?([A-Za-z_][A-Za-z0-9_.-]{2,80})[\"']?\s*[:=]")
PY_SYMBOL_RE = re.compile(r"(?m)^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
JS_SYMBOL_RE = re.compile(r"(?m)^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
JS_EXPORT_RE = re.compile(r"(?m)^\s*export\s+(?:const|let|var|type|interface)\s+([A-Za-z_][A-Za-z0-9_]*)")
GO_SYMBOL_RE = re.compile(r"(?m)^\s*(?:func|type)\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)")
RUST_SYMBOL_RE = re.compile(r"(?m)^\s*(?:pub\s+)?(?:async\s+)?(?:fn|struct|enum|mod)\s+([A-Za-z_][A-Za-z0-9_]*)")
SWIFT_SYMBOL_RE = re.compile(r"(?m)^\s*(?:public\s+|private\s+|internal\s+|fileprivate\s+)?(?:final\s+)?(?:func|class|struct|enum|protocol|actor)\s+([A-Za-z_][A-Za-z0-9_]*)")
TEST_NAME_RE = re.compile(r"\b(?:def\s+)?(test_[A-Za-z0-9_]+)\b|\b(?:it|test)\(['\"]([^'\"]{2,80})")
PY_IMPORT_RE = re.compile(r"(?m)^\s*(?:from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import|import\s+([A-Za-z_][A-Za-z0-9_.]*))")
JS_IMPORT_RE = re.compile(r"(?m)^\s*import\s+(?:.+?\s+from\s+)?['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\)")
GO_IMPORT_RE = re.compile(r"(?m)^\s*import\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?\"([^\"]+)\"")
ROUTE_RE = re.compile(r"['\"](/[A-Za-z0-9_./:<>{}-]{1,80})['\"]")
PACKAGE_NAME_RE = re.compile(r"(?m)^\s*(?:name|module)\s*[:=]\s*[\"']?([A-Za-z0-9_.@/-]{2,80})")


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        key = clean.lower()
        if clean and key not in seen:
            out.append(clean)
            seen.add(key)
    return out


def _path_values(items: Any, *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in list(items or []):
        value = item.get("path") if isinstance(item, dict) else item
        path = str(value or "").strip()
        key = path.lower()
        if path and key not in seen:
            out.append(path)
            seen.add(key)
        if len(out) >= limit:
            break
    return out


def _read_selected_file(repo_root: Path, rel_path: str) -> tuple[str, int]:
    path = repo_root / rel_path
    try:
        data = path.read_bytes()[: MAX_DISCOVERY_BYTES_PER_FILE + 1]
    except OSError:
        return "", 0
    if b"\x00" in data[:4096]:
        return "", len(data)
    clipped = data[:MAX_DISCOVERY_BYTES_PER_FILE]
    return clipped.decode("utf-8", errors="replace"), len(clipped)


def _prompt_terms(raw_prompt: str) -> list[str]:
    terms = [match.group(0) for match in WORD_RE.finditer(raw_prompt or "")]
    terms.extend(match.group(1) for match in QUOTED_RE.finditer(raw_prompt or ""))
    return [term for term in _dedupe(terms) if len(term) >= 3][:40]


def _tokenize(value: str) -> set[str]:
    return {part.lower() for part in re.findall(r"[A-Za-z0-9]+", value or "") if len(part) >= 3}


def _anchor_allowed(anchor_type: str, anchor_text: str) -> bool:
    if anchor_type not in ALLOWED_ANCHOR_TYPES:
        return False
    text = str(anchor_text or "").strip()
    if len(text) < 2 or len(text) > 80:
        return False
    if any(ch in text for ch in "\n\r\t<>"):
        return False
    lowered = text.lower()
    if is_scaffold_meta_term(lowered):
        return False
    lowered_parts = {part for part in re.split(r"[^a-z0-9]+|_", lowered) if part}
    for term in FORBIDDEN_ANCHOR_TERMS:
        if term in lowered_parts or re.search(rf"(?<![A-Za-z0-9_-]){re.escape(term)}(?![A-Za-z0-9_-])", lowered):
            return False
    return True


def _add_anchor(
    anchors: list[dict[str, Any]],
    rejected: list[str],
    seen: set[tuple[str, str]],
    *,
    path: str,
    anchor_type: str,
    anchor_text: str,
    source: str,
    line: int | None = None,
) -> None:
    text = str(anchor_text or "").strip().strip("\"'`")
    key = (anchor_type, text.lower())
    if key in seen:
        return
    if not _anchor_allowed(anchor_type, text):
        if text:
            rejected.append(text)
        return
    seen.add(key)
    anchors.append(
        {
            "anchor_text": text,
            "anchor_type": anchor_type,
            "source_file": path,
            "source_line_or_section": line,
            "source": source,
            "quality": 1.0,
            "collision_count": 0,
            "task_term_source": "locator_signal" if source == "locator_signal" else "content_scan",
            "scaffold_filtered": False,
            "model_facing_allowed": True,
            "reject_reason": None,
        }
    )


def _line_number(text: str, needle: str) -> int | None:
    if not needle:
        return None
    for idx, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return idx
    return None


def _signals_by_path(manifest: dict[str, Any]) -> dict[str, list[str]]:
    locator = manifest.get("locator_evidence") if isinstance(manifest.get("locator_evidence"), dict) else {}
    out: dict[str, list[str]] = {}
    for bucket in ("primary_files", "verification_files", "support_files"):
        for item in locator.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if path:
                out.setdefault(path, []).extend(str(signal) for signal in (item.get("matched_signals") or []))
    return {path: _dedupe(signals) for path, signals in out.items()}


def _anchor_from_signal(signal: str) -> tuple[str, str] | None:
    if ":" not in signal:
        return None
    prefix, value = signal.split(":", 1)
    prefix = prefix.strip().lower()
    value = value.strip().strip("\"'`")
    if not value:
        return None
    if prefix in {"symbol", "symbol_term"}:
        return "symbol", value
    if prefix in {"quoted_literal", "string", "content"}:
        return "literal", value
    if prefix in {"option_flag", "option_decl", "option_value_evidence", "option_default", "option_choices"}:
        return "cli_flag", value
    if prefix == "route":
        return "route", value
    if prefix in {"package_name", "package"}:
        return "package_name", value
    if prefix in {"module_name", "module"}:
        return "module_name", value
    return None


def _symbol_candidates(path: str, text: str) -> list[str]:
    suffix = Path(path).suffix.lower()
    patterns = [PY_SYMBOL_RE]
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        patterns = [JS_SYMBOL_RE, JS_EXPORT_RE]
    elif suffix == ".go":
        patterns = [GO_SYMBOL_RE]
    elif suffix == ".rs":
        patterns = [RUST_SYMBOL_RE]
    elif suffix == ".swift":
        patterns = [SWIFT_SYMBOL_RE]
    values: list[str] = []
    for pattern in patterns:
        values.extend(match.group(1) for match in pattern.finditer(text) if match.group(1))
    return _dedupe(values)


def _import_candidates(path: str, text: str) -> list[str]:
    suffix = Path(path).suffix.lower()
    values: list[str] = []
    if suffix == ".py":
        for left, right in PY_IMPORT_RE.findall(text):
            values.append(left or right)
    elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        for left, right in JS_IMPORT_RE.findall(text):
            values.append(left or right)
    elif suffix == ".go":
        values.extend(GO_IMPORT_RE.findall(text))
    elif suffix == ".rs":
        values.extend(re.findall(r"(?m)^\s*use\s+([A-Za-z0-9_:]+)", text))
    elif suffix == ".swift":
        values.extend(re.findall(r"(?m)^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)", text))
    return _dedupe([value.split(".")[0] if "." in value and not value.startswith(".") else value for value in values])


def _matched_symbol_priority(symbol: str, terms: list[str]) -> tuple[int, str]:
    symbol_tokens = _tokenize(symbol)
    term_tokens = set().union(*(_tokenize(term) for term in terms)) if terms else set()
    overlap = len(symbol_tokens & term_tokens)
    return (-overlap, symbol.lower())


def _anchors_for_file(path: str, text: str, terms: list[str], signals: list[str], *, role: str) -> tuple[list[dict[str, Any]], list[str]]:
    anchors: list[dict[str, Any]] = []
    rejected: list[str] = []
    seen: set[tuple[str, str]] = set()
    for signal in signals:
        parsed = _anchor_from_signal(signal)
        if parsed:
            _add_anchor(anchors, rejected, seen, path=path, anchor_type=parsed[0], anchor_text=parsed[1], source="locator_signal", line=_line_number(text, parsed[1]))

    lower_text = text.lower()
    for term in terms:
        if term.startswith("-") and term.lower() in lower_text:
            _add_anchor(anchors, rejected, seen, path=path, anchor_type="cli_flag", anchor_text=term, source="literal_match", line=_line_number(text, term))
        elif len(term) >= 4 and term.lower() in lower_text:
            _add_anchor(anchors, rejected, seen, path=path, anchor_type="literal", anchor_text=term, source="literal_match", line=_line_number(text, term))

    symbols = sorted(_symbol_candidates(path, text), key=lambda value: _matched_symbol_priority(value, terms))
    for symbol in symbols[:12]:
        _add_anchor(anchors, rejected, seen, path=path, anchor_type="symbol", anchor_text=symbol, source="symbol_scan", line=_line_number(text, symbol))

    if role == "related_test" or classify_path_role(path).is_test:
        for match in TEST_NAME_RE.finditer(text):
            value = match.group(1) or match.group(2)
            _add_anchor(anchors, rejected, seen, path=path, anchor_type="test_name", anchor_text=value, source="test_scan", line=_line_number(text, value))

    if Path(path).suffix.lower() in {".md", ".mdx", ".rst"}:
        for match in HEADING_RE.finditer(text):
            _add_anchor(anchors, rejected, seen, path=path, anchor_type="heading", anchor_text=match.group(1).strip(), source="heading_scan", line=text[: match.start()].count("\n") + 1)

    if Path(path).suffix.lower() in {".toml", ".json", ".yaml", ".yml"}:
        for match in CONFIG_SECTION_RE.finditer(text):
            _add_anchor(anchors, rejected, seen, path=path, anchor_type="config_section", anchor_text=match.group(1), source="config_scan", line=text[: match.start()].count("\n") + 1)
        for match in CONFIG_KEY_RE.finditer(text):
            _add_anchor(anchors, rejected, seen, path=path, anchor_type="config_section", anchor_text=match.group(1), source="config_scan", line=text[: match.start()].count("\n") + 1)
        for match in PACKAGE_NAME_RE.finditer(text):
            _add_anchor(anchors, rejected, seen, path=path, anchor_type="package_name", anchor_text=match.group(1), source="config_scan", line=text[: match.start()].count("\n") + 1)

    for match in CLI_FLAG_RE.finditer(text):
        _add_anchor(anchors, rejected, seen, path=path, anchor_type="cli_flag", anchor_text=match.group(0), source="literal_match", line=text[: match.start()].count("\n") + 1)
    for match in ROUTE_RE.finditer(text):
        _add_anchor(anchors, rejected, seen, path=path, anchor_type="route", anchor_text=match.group(1), source="literal_match", line=text[: match.start()].count("\n") + 1)
    for value in _import_candidates(path, text)[:12]:
        _add_anchor(anchors, rejected, seen, path=path, anchor_type="import_name", anchor_text=value, source="import_scan", line=_line_number(text, value))

    return anchors, rejected


def _anchor_source_probe(source: str) -> str:
    if source == "locator_signal":
        return "literal_probe"
    if source == "literal_match":
        return "literal_probe"
    if source == "symbol_scan":
        return "symbol_probe"
    if source == "test_scan":
        return "test_probe"
    if source == "heading_scan":
        return "docs_heading_probe"
    if source == "config_scan":
        return "config_probe"
    if source == "import_scan":
        return "import_adjacency_probe"
    return "literal_probe"


def _probes_for_strategy(strategy: str, task_class: str = "") -> set[str]:
    base = {"literal_probe", "symbol_probe", "test_probe"}
    return {
        "literal_symbol": base,
        "literal_symbol_test_names": base,
        "literal_symbol_config": base | {"config_probe"},
        "literal_symbol_config_gated": base | ({"config_probe"} if task_class == "config_package" else set()),
        "literal_symbol_docs": base | {"docs_heading_probe"},
        "literal_symbol_docs_heading_gated": base | ({"docs_heading_probe"} if task_class == "docs_only" else set()),
        "literal_symbol_cli_route": base,
        "literal_symbol_import_boost": base | {"import_adjacency_probe"},
        "literal_symbol_import_rank_json_only": base | {"import_adjacency_probe"},
        "literal_symbol_collision_filter": base,
        "tests_first_anchoring": base,
        "top1_primary": base,
        "policy_by_prompt_type": base,
    }.get(strategy, base)


def _internal_strategy_for_task_class(requested: str, task_class: str) -> str:
    normalized = str(requested or "policy_by_prompt_type").replace("-", "_").strip().lower()
    if normalized not in INTERNAL_ANCHOR_STRATEGIES:
        normalized = "policy_by_prompt_type"
    if normalized not in {"policy_by_prompt_type", "literal_symbol_policy_by_prompt_type"}:
        return normalized
    return {
        "runtime_source": "literal_symbol_cli_route",
        "test_only": "literal_symbol_test_names",
        "docs_only": "literal_symbol_docs_heading_gated",
        "config_package": "literal_symbol_config_gated",
        "multi_surface_runtime": "literal_symbol_cli_route",
        "ambiguous_low_confidence": "literal_symbol",
    }.get(str(task_class or ""), "literal_symbol")


def _anchor_priority(anchor: dict[str, Any], terms: list[str], strategy: str, role: str) -> tuple[int, str, str]:
    anchor_type = str(anchor.get("anchor_type") or "")
    source = str(anchor.get("source") or "")
    text = str(anchor.get("anchor_text") or "")
    term_tokens = set().union(*(_tokenize(term) for term in terms)) if terms else set()
    overlap = len(_tokenize(text) & term_tokens)
    priority = {
        "cli_flag": 0,
        "test_name": 1,
        "symbol": 2,
        "literal": 3,
        "config_section": 4,
        "package_name": 5,
        "heading": 6,
        "route": 7,
        "module_name": 8,
        "import_name": 9,
    }.get(anchor_type, 20)
    if strategy in {"tests_first_anchoring", "literal_symbol_test_names"} and (role == "related_test" or anchor_type == "test_name"):
        priority -= 5
    if strategy in {"literal_symbol_config", "literal_symbol_config_gated"} and anchor_type in {"config_section", "package_name"}:
        priority -= 4
    if strategy in {"literal_symbol_docs", "literal_symbol_docs_heading_gated"} and anchor_type == "heading":
        priority -= 4
    if strategy == "literal_symbol_cli_route" and anchor_type in {"cli_flag", "route"}:
        priority -= 4
    if strategy in {"literal_symbol_import_boost", "literal_symbol_import_rank_json_only"} and source == "import_scan":
        priority -= 3
    return (priority - min(overlap, 4), anchor_type, text.lower())


def _is_generic_anchor(anchor: dict[str, Any]) -> bool:
    text = str(anchor.get("anchor_text") or "").lower()
    parts = {part for part in re.split(r"[^a-z0-9]+|_", text) if part}
    return bool(parts & GENERIC_ANCHOR_TERMS)


def _with_anchor_collisions(generated: dict[str, list[dict[str, Any]]]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for anchors in generated.values():
        for anchor in anchors:
            key = (str(anchor.get("anchor_type") or ""), str(anchor.get("anchor_text") or "").lower())
            counts[key] = counts.get(key, 0) + 1
    for anchors in generated.values():
        for anchor in anchors:
            key = (str(anchor.get("anchor_type") or ""), str(anchor.get("anchor_text") or "").lower())
            anchor["collision_count"] = max(0, counts.get(key, 1) - 1)
            quality = 1.0
            if anchor["collision_count"]:
                quality -= min(0.5, anchor["collision_count"] * 0.1)
            if _is_generic_anchor(anchor):
                quality -= 0.4
            anchor["quality"] = round(max(0.0, quality), 3)


def _filter_anchors_for_strategy(
    anchors: list[dict[str, Any]],
    *,
    probes: set[str],
    terms: list[str],
    strategy: str,
    role: str,
) -> list[dict[str, Any]]:
    filtered = [
        anchor for anchor in anchors
        if _anchor_source_probe(str(anchor.get("source") or "")) in probes
    ]
    if strategy == "literal_symbol_import_rank_json_only":
        filtered = [
            anchor for anchor in filtered
            if str(anchor.get("source") or "") != "import_scan" and str(anchor.get("anchor_type") or "") != "import_name"
        ]
    if strategy == "literal_symbol_collision_filter":
        filtered = [
            anchor for anchor in filtered
            if not _is_generic_anchor(anchor) and int(anchor.get("collision_count") or 0) <= 1
        ]
    return sorted(filtered, key=lambda anchor: _anchor_priority(anchor, terms, strategy, role))


def _task_class(raw_prompt: str, primary: list[str], related: list[str], support: list[str], manifest: dict[str, Any]) -> str:
    intent = infer_prompt_intent(raw_prompt)
    prompt_lower = str(raw_prompt or "").lower()
    primary_roles = [classify_path_role(path) for path in primary]
    locator = manifest.get("locator_evidence") if isinstance(manifest.get("locator_evidence"), dict) else {}
    confidence = str(locator.get("confidence") or "").lower()
    ambiguity = locator.get("ambiguity_reasons") or []
    if any(term in prompt_lower for term in ("readme", ".md", "docs", "documentation", "heading")):
        return "docs_only"
    if any(term in prompt_lower for term in ("pyproject", "package.json", "cargo.toml", "manifest", "package metadata")):
        return "config_package"
    if confidence == "low" and len(ambiguity) >= 3:
        return "ambiguous_low_confidence"
    if primary and all(role.is_test for role in primary_roles):
        return "test_only"
    if getattr(intent, "intent", "") == "test_only":
        return "test_only"
    if primary and all(role.is_docs for role in primary_roles):
        return "docs_only"
    if primary and all(role.is_config for role in primary_roles):
        return "config_package"
    if len(primary) > 1 and any(role.role == "source" for role in primary_roles):
        return "multi_surface_runtime"
    if related and any(role.is_config for role in primary_roles):
        return "config_package"
    return "runtime_source"


def _relation_from_locator(raw: dict[str, Any]) -> dict[str, Any] | None:
    source = str(raw.get("source") or "")
    target = str(raw.get("target") or "")
    relation = str(raw.get("relation") or "")
    mapped = {
        "imports": "imports",
        "imported_by": "imported_by",
        "adjacent_test": "test_covers_source",
        "adjacent_source": "test_covers_source",
        "route_helper": "route_maps_to_handler",
        "same_stem": "test_covers_source",
    }.get(relation)
    if not source or not target or not mapped:
        return None
    return {
        "source": source,
        "target": target,
        "relation_type": mapped,
        "source_relation": relation,
        "strength": int(raw.get("strength") or 0),
        "source_kind": "locator_dependency_relation",
        "model_facing_allowed": True,
    }


def _infer_test_relation(primary: list[str], related: list[str]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for test in related:
        test_stem = re.sub(r"^(test_|spec_)", "", Path(test).stem.lower())
        for source in primary:
            source_stem = Path(source).stem.lower()
            if len(source_stem) >= 3 and (source_stem in test_stem or test_stem in source_stem):
                relations.append(
                    {
                        "source": test,
                        "target": source,
                        "relation_type": "test_covers_source",
                        "source_relation": "stem_match",
                        "strength": 64,
                        "source_kind": "bounded_test_source_inference",
                        "model_facing_allowed": True,
                    }
                )
    return relations


def _select_relations(manifest: dict[str, Any], primary: list[str], related: list[str], support: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_paths = set(primary + related + support)
    locator = manifest.get("locator_evidence") if isinstance(manifest.get("locator_evidence"), dict) else {}
    generated: list[dict[str, Any]] = []
    for raw in locator.get("dependency_relations") or []:
        if not isinstance(raw, dict):
            continue
        relation = _relation_from_locator(raw)
        if relation and relation["source"] in selected_paths and relation["target"] in selected_paths:
            generated.append(relation)
    generated.extend(_infer_test_relation(primary, related))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in sorted(generated, key=lambda item: (-int(item.get("strength") or 0), item["source"], item["target"], item["relation_type"])):
        key = (relation["source"], relation["target"], relation["relation_type"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(relation)
    return generated, deduped[:MAX_SUPPORT_RELATIONS]


def _anchor_quality(anchors_by_path: dict[str, list[dict[str, Any]]], rejected: list[str]) -> dict[str, Any]:
    type_mix: dict[str, int] = {}
    total = 0
    for anchors in anchors_by_path.values():
        for anchor in anchors:
            total += 1
            anchor_type = str(anchor.get("anchor_type") or "")
            type_mix[anchor_type] = type_mix.get(anchor_type, 0) + 1
    collisions = 0
    seen_global: set[tuple[str, str]] = set()
    for anchors in anchors_by_path.values():
        for anchor in anchors:
            key = (str(anchor.get("anchor_type") or ""), str(anchor.get("anchor_text") or "").lower())
            if key in seen_global:
                collisions += 1
            seen_global.add(key)
    return {
        "anchor_count": total,
        "anchor_type_mix": type_mix,
        "anchor_collision_count": collisions,
        "anchor_filter_reject_count": len(rejected),
        "filtered_anchor_terms": _dedupe(rejected)[:60],
        "anchors_per_file": {path: len(anchors) for path, anchors in anchors_by_path.items()},
    }


def build_tool_assisted_backbone(
    repo_root: Path,
    raw_prompt: str,
    manifest: dict[str, Any],
    *,
    primary_files: list[str],
    related_tests: list[str],
    support_files: list[str],
) -> dict[str, Any]:
    start = time.perf_counter()
    repo_root = Path(repo_root)
    primary = _path_values(primary_files, limit=MAX_PRIMARY_FILES)
    related = _path_values(related_tests, limit=MAX_RELATED_TESTS)
    support = _path_values(support_files, limit=2)
    paths = _dedupe(primary + related + support)
    terms = _prompt_terms(raw_prompt)
    signals = _signals_by_path(manifest)

    file_text: dict[str, str] = {}
    files_scanned = 0
    lines_scanned = 0
    bytes_scanned = 0
    discovery_notes: list[str] = []
    for path in paths:
        text, byte_count = _read_selected_file(repo_root, path)
        if text or byte_count:
            files_scanned += 1
            lines_scanned += len(text.splitlines())
            bytes_scanned += byte_count
            file_text[path] = text
        else:
            discovery_notes.append(f"unreadable:{path}")

    generated_anchors_by_path: dict[str, list[dict[str, Any]]] = {}
    selected_anchors_by_path: dict[str, list[dict[str, Any]]] = {}
    rejected_terms: list[str] = []
    total_selected = 0
    for path in paths:
        role = "primary" if path in primary else "related_test" if path in related else "support"
        anchors, rejected = _anchors_for_file(path, file_text.get(path, ""), terms, signals.get(path, []), role=role)
        generated_anchors_by_path[path] = anchors
        rejected_terms.extend(rejected)
        if role == "support":
            selected_anchors_by_path[path] = []
            continue
        limit = MAX_PRIMARY_ANCHORS if role == "primary" else MAX_RELATED_ANCHORS
        remaining = max(0, MAX_TOTAL_MODEL_ANCHORS - total_selected)
        selected = anchors[: min(limit, remaining)]
        selected_anchors_by_path[path] = selected
        total_selected += len(selected)

    generated_relations, selected_relations = _select_relations(manifest, primary, related, support)
    task_class = _task_class(raw_prompt, primary, related, support, manifest)
    anchor_quality = _anchor_quality(selected_anchors_by_path, rejected_terms)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    discovery_stats = {
        "discovery_wall_ms": elapsed_ms,
        "rg_call_count": 0,
        "files_scanned_count": files_scanned,
        "lines_scanned_count": lines_scanned,
        "bytes_scanned_count": bytes_scanned,
        "anchors_generated_count": sum(len(value) for value in generated_anchors_by_path.values()),
        "anchors_selected_count": sum(len(value) for value in selected_anchors_by_path.values()),
        "relations_generated_count": len(generated_relations),
        "relations_selected_count": len(selected_relations),
        "anchor_filter_reject_count": len(rejected_terms),
        "discovery_error_count": 0,
    }
    return {
        "task_class": task_class,
        "primary_files": primary,
        "related_tests": related,
        "support_files": support,
        "anchors_by_path": selected_anchors_by_path,
        "generated_anchors_by_path": generated_anchors_by_path,
        "support_relations": selected_relations,
        "generated_support_relations": generated_relations,
        "anchor_quality": anchor_quality,
        "discovery_notes": discovery_notes,
        "scaffold_filtered_terms": _dedupe(rejected_terms)[:60],
        "model_facing_allowed": {
            "task_class": True,
            "anchors": True,
            "support_relations": True,
        },
        "discovery_stats": discovery_stats,
    }


def build_tool_assisted_anchors_internal(
    repo_root: Path,
    raw_prompt: str,
    manifest: dict[str, Any],
    *,
    primary_files: list[str],
    related_tests: list[str],
    support_files: list[str],
    strategy: str = "policy_by_prompt_type",
) -> dict[str, Any]:
    start = time.perf_counter()
    repo_root = Path(repo_root)
    base_primary = _path_values(primary_files, limit=MAX_PRIMARY_FILES)
    base_related = _path_values(related_tests, limit=MAX_RELATED_TESTS)
    support = _path_values(support_files, limit=2)
    task_class = _task_class(raw_prompt, base_primary, base_related, support, manifest)
    selected_strategy = _internal_strategy_for_task_class(strategy, task_class)
    probes = _probes_for_strategy(selected_strategy, task_class)

    primary = base_primary[:1] if selected_strategy == "top1_primary" else list(base_primary)
    related = list(base_related)
    paths = _dedupe(primary + related + support)[:MAX_INTERNAL_FILES_SCANNED]
    terms = _prompt_terms(raw_prompt)
    signals = _signals_by_path(manifest)

    file_text: dict[str, str] = {}
    files_scanned = 0
    lines_scanned = 0
    bytes_scanned = 0
    discovery_notes: list[str] = []
    scan_limit_reached = False
    for path in paths:
        text, byte_count = _read_selected_file(repo_root, path)
        projected_lines = lines_scanned + len(text.splitlines())
        projected_bytes = bytes_scanned + byte_count
        if projected_lines > MAX_INTERNAL_LINES_SCANNED or projected_bytes > MAX_INTERNAL_BYTES_SCANNED:
            scan_limit_reached = True
            discovery_notes.append(f"scan_limit_skipped:{path}")
            continue
        if text or byte_count:
            files_scanned += 1
            lines_scanned = projected_lines
            bytes_scanned = projected_bytes
            file_text[path] = text
        else:
            discovery_notes.append(f"unreadable:{path}")

    generated_anchors_by_path: dict[str, list[dict[str, Any]]] = {}
    selected_anchors_by_path: dict[str, list[dict[str, Any]]] = {}
    rejected_terms: list[str] = []
    anchors_rejected: list[dict[str, Any]] = []
    for path in primary + related:
        role = "primary" if path in primary else "related_test"
        anchors, rejected = _anchors_for_file(path, file_text.get(path, ""), terms, signals.get(path, []), role=role)
        generated_anchors_by_path[path] = anchors
        rejected_terms.extend(rejected)

    for path in support:
        anchors, rejected = _anchors_for_file(path, file_text.get(path, ""), terms, signals.get(path, []), role="support")
        generated_anchors_by_path[path] = anchors
        rejected_terms.extend(rejected)

    _with_anchor_collisions(generated_anchors_by_path)

    total_selected = 0
    for path in primary + related:
        role = "primary" if path in primary else "related_test"
        anchors = generated_anchors_by_path.get(path, [])
        strategy_filtered = _filter_anchors_for_strategy(
            anchors,
            probes=probes,
            terms=terms,
            strategy=selected_strategy,
            role=role,
        )
        accepted_keys = {
            (str(anchor.get("anchor_type") or ""), str(anchor.get("anchor_text") or "").lower())
            for anchor in strategy_filtered
        }
        for anchor in anchors:
            key = (str(anchor.get("anchor_type") or ""), str(anchor.get("anchor_text") or "").lower())
            if key not in accepted_keys:
                anchors_rejected.append({**anchor, "reject_reason": "strategy_probe_filter"})
        limit = MAX_RELATED_ANCHORS if role == "related_test" else MAX_PRIMARY_ANCHORS
        remaining = max(0, MAX_TOTAL_MODEL_ANCHORS - total_selected)
        selected = strategy_filtered[: min(limit, remaining)]
        selected_anchors_by_path[path] = selected
        total_selected += len(selected)

    for path in support:
        anchors = generated_anchors_by_path.get(path, [])
        anchors_rejected.extend({**anchor, "reject_reason": "support_json_only"} for anchor in anchors)

    generated_relations, selected_relations = _select_relations(manifest, primary, related, support)
    ranking_adjustments: list[dict[str, Any]] = []
    if selected_strategy in {"literal_symbol_import_boost", "literal_symbol_import_rank_json_only"}:
        import_hits = {
            path: sum(1 for anchor in generated_anchors_by_path.get(path, []) if anchor.get("source") == "import_scan")
            for path in primary
        }
        if any(import_hits.values()):
            before = list(primary)
            primary = sorted(primary, key=lambda path: (-import_hits.get(path, 0), before.index(path)))
            if primary != before:
                ranking_adjustments.append({
                    "kind": "primary_import_boost",
                    "before": before,
                    "after": primary,
                    "model_facing_allowed": False,
                })

    anchor_quality = _anchor_quality(selected_anchors_by_path, rejected_terms)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    discovery_stats = {
        "discovery_wall_ms": elapsed_ms,
        "rg_call_count": 0,
        "files_scanned_count": files_scanned,
        "lines_scanned_count": lines_scanned,
        "bytes_scanned_count": bytes_scanned,
        "anchors_generated_count": sum(len(value) for value in generated_anchors_by_path.values()),
        "anchors_selected_count": sum(len(value) for value in selected_anchors_by_path.values()),
        "relations_generated_count": len(generated_relations),
        "relations_selected_count": len(selected_relations),
        "anchor_filter_reject_count": len(rejected_terms) + len(anchors_rejected),
        "discovery_error_count": 0,
        "max_files_scanned": MAX_INTERNAL_FILES_SCANNED,
        "max_lines_scanned": MAX_INTERNAL_LINES_SCANNED,
        "max_bytes_scanned": MAX_INTERNAL_BYTES_SCANNED,
        "scan_limit_reached": scan_limit_reached,
    }
    return {
        "packet_variant": "tool_assisted_anchors_internal",
        "base_variant": "ranked_paths_plus_anchors",
        "strategy_requested": strategy,
        "strategy_selected": selected_strategy,
        "probe_mix": sorted(probes),
        "task_class": task_class,
        "task_class_json_only": task_class,
        "primary_files_before": base_primary,
        "primary_files_after": primary,
        "related_tests_before": base_related,
        "related_tests_after": related,
        "primary_files": primary,
        "related_tests": related,
        "support_files": support,
        "support_files_json_only": support,
        "anchors_by_path": selected_anchors_by_path,
        "generated_anchors_by_path": generated_anchors_by_path,
        "anchors_generated": [
            anchor for anchors in generated_anchors_by_path.values() for anchor in anchors
        ],
        "anchors_selected": [
            anchor for anchors in selected_anchors_by_path.values() for anchor in anchors
        ],
        "anchors_rejected": anchors_rejected[:100],
        "internal_relations_json_only": selected_relations,
        "support_relations": selected_relations,
        "generated_support_relations": generated_relations,
        "ranking_adjustments": ranking_adjustments,
        "probe_stats": {
            "strategy": selected_strategy,
            "probe_mix": sorted(probes),
            "scan_limit_reached": scan_limit_reached,
        },
        "discovery_cost": discovery_stats,
        "discovery_stats": discovery_stats,
        "anchor_quality": anchor_quality,
        "discovery_notes": discovery_notes,
        "scaffold_filtered_terms": _dedupe(rejected_terms)[:60],
        "model_facing_allowed": {
            "task_class": False,
            "support_relations": False,
            "scores": False,
            "discovery_logs": False,
            "anchors": True,
        },
        "model_facing_sections": ["TASK", "PRIMARY_FILES", "RELATED_TESTS"],
        "model_facing_forbidden_sections_present": False,
    }
