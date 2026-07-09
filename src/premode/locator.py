from __future__ import annotations

from dataclasses import dataclass, field
import posixpath
import re
import time
from pathlib import Path

from .context_constraints import is_sensitive_or_secret_path
from .ignore import IgnoreMatcher
from .role_model import classify_path_role
from .safe_reader import is_probably_binary_path, is_secret_name


MAX_LOCATOR_BYTES = 64_000
MAX_IMPORT_SUFFIX_SCAN_PATHS = 1_200
MAX_IMPORT_SUFFIX_INDEX_PATHS = 5_000
MAX_RELATION_FILES = 1_200
MAX_SAME_DIRECTORY_GROUP = 48
MAX_SOURCE_TEST_PAIR_SCAN = 8_000
MAX_ASSET_STAT_CANDIDATES = 256

MEDIA_ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".blend",
    ".mp4", ".mov", ".wav", ".mp3", ".aiff", ".ttf", ".otf", ".woff", ".woff2",
}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".xz", ".7z", ".rar", ".dmg", ".xcarchive"}
MEDIA_LOOKUP_TERMS = {"find", "locate", "show", "list", "identify", "where"}
MEDIA_QUERY_TERMS = {
    "png", "jpg", "jpeg", "webp", "gif", "svg", "image", "images", "sprite",
    "sprites", "icon", "icons", "texture", "textures", "asset", "assets",
    "blender", "blend", "media", "render", "renders",
}
MEDIA_RECENCY_TERMS = {"latest", "newest", "recent", "most", "current"}
MEDIA_READ_ONLY_TERMS = {"readonly", "read", "only", "modify", "edit", "changes", "change", "files", "file"}
MEDIA_CODE_EDIT_TERMS = {
    "fix", "change", "update", "patch", "implement", "refactor", "debug",
    "test", "tests", "failing", "error", "traceback", "function", "class",
    "method", "symbol",
}
MEDIA_GENERIC_TERMS = (
    MEDIA_LOOKUP_TERMS
    | MEDIA_QUERY_TERMS
    | MEDIA_RECENCY_TERMS
    | MEDIA_READ_ONLY_TERMS
    | {"do", "not", "no", "is", "the", "a", "an", "for", "to", "in", "of", "and"}
)
MEDIA_DIRECTORY_HINTS = {
    "asset", "assets", "image", "images", "media", "texture", "textures",
    "render", "renders", "sprite", "sprites", "icon", "icons", "art", "blender",
}
MEDIA_PRUNE_SEGMENTS = {
    ".git", ".premode", ".agents", ".codex", ".venv", "node_modules",
    "__pycache__", "archive", "archives", "snapshot", "snapshots", "backup",
    "backups", "generated", "gen", "build", "dist", "target", "tmp", "cache",
    ".cache", "_claw_output",
}
SIMPLE_TERM_RE = re.compile(r"[a-z0-9]+")

ACTION_PHRASES = {
    "speed up",
}
ACTION_WORDS = {
    "add", "clarify", "fix", "improve", "move", "remove", "rename",
    "update", "validate",
}
SURFACE_HINTS = {
    "api", "build", "button", "cli", "command", "config", "database", "docs",
    "dashboard", "documentation", "endpoint", "guide", "html", "readme",
    "route", "screen", "test", "view",
}
BOUNDED_SYNONYM_GROUPS = {
    "auth": frozenset({"auth", "authentication", "authorization", "login", "credential", "token"}),
    "docs": frozenset({"docs", "documentation", "guide", "quickstart", "usage", "tutorial"}),
    "config": frozenset({"config", "configuration", "settings", "options", "metadata"}),
}
DOMAIN_TERMS = {
    "actuator", "button", "checkout", "config", "csv", "database", "endpoint",
    "behavior", "calculation", "classification", "classify", "compute",
    "console", "coverage", "diagnostic", "entry", "error", "execute",
    "export", "failed", "failure", "failing", "flow", "folder", "handler",
    "generated", "guide", "handling", "helper", "html", "install",
    "instructions", "inventory", "login", "missing",
    "output", "payload", "point", "pricing", "process", "regression",
    "replay", "report", "reporting", "result", "route", "rounding",
    "runtime", "screen", "script", "service", "settings", "setup", "start",
    "state", "status", "success", "telemetry", "timeout", "token", "total",
    "troubleshooting", "update", "user",
    "allowed", "argument", "choice", "choices", "default", "fallback",
    "format", "happens", "invalid", "mode", "option", "options", "pass",
    "profile", "style", "theme", "unsupported", "valid", "value", "values",
}
SCAFFOLD_META_TERMS = {
    "benchmark", "cache", "codex", "commit", "constraint", "constraints",
    "controlled", "download", "harness", "lab", "lane", "packet", "premode",
    "prompt", "repo", "repository", "repeat", "review", "review-patch",
    "scoped", "stage", "staging", "token", "validate", "validation",
    "worktree", "xcode", "xcodebuild",
}
OPTION_VALUE_TERMS = {
    "option", "options", "argument", "value", "values", "theme", "style",
    "profile", "mode", "format", "choice", "choices", "pass", "happens",
}
INVALID_VALUE_TERMS = {
    "invalid", "unsupported", "error", "fail", "fails", "failed",
    "exception",
}
ALLOWED_VALUE_TERMS = {"allowed", "valid", "value", "values", "choice", "choices"}
DEFAULT_FALLBACK_TERMS = {
    "default", "defaults", "fallback", "fallbacks", "fall back", "falls back",
}
OPTION_ENTITY_TERMS = {
    "box", "format", "lexer", "mode", "option", "output", "panel", "profile",
    "rule", "style", "theme",
}
BEHAVIOR_PHRASES = {
    "diagnostic result",
    "error handling",
    "output generation",
}
BEHAVIOR_TERMS = {
    "behavior", "calculation", "classification", "classify", "compute",
    "diagnostic result", "error handling", "execute", "failed", "failure",
    "handling", "output generation", "process", "report", "reporting",
    "result", "runtime", "status", "timeout",
}
BEHAVIOR_DOMAIN_TERMS = {
    "actuator", "checkout", "csv", "diagnostic", "discount", "error",
    "export", "failure", "folder", "missing", "output", "payload",
    "pricing", "replay", "settings", "status", "timeout", "total", "user",
}
STOP_TERMS = {
    "and", "for", "from", "into", "that", "the", "this", "when", "with",
    "without", "clarify", "fix", "improve", "move", "remove", "rename",
    "update", "validate", "make", "not", "one", "small", "three",
    "change", "changes", "improvement", "improvements", "are", "is", "was", "were",
    # Generic comprehension / quality / meta words that appear in human
    # improvement prompts but are not locatable domain concepts. Keeping them out
    # of "core terms" prevents false `uncovered_core_terms` ambiguity inflation.
    "clear", "clearer", "clearest", "unclear", "clarity",
    "easy", "easier", "easiest", "simple", "simpler", "simplest",
    "better", "best", "nicer", "useful", "helpful", "good", "great",
    "understand", "understands", "understandable", "understanding",
    "know", "knows", "knowing", "tell", "tells", "feel", "feels", "feeling",
    "next", "important", "everything", "anything", "something", "nothing",
    "read", "reading", "longer", "shorter", "short", "long",
    "new", "newer", "old", "finish", "finishes", "finished", "done",
    "want", "wants", "should", "able", "still", "more", "less",
    "really", "little", "bit", "look", "looks", "seem", "seems",
    "able", "easily", "quickly", "properly", "correctly", "clearly",
    "choose", "chooses", "choosing", "user", "users", "they", "them",
    "their", "what", "who", "why",
    "there", "issue", "problem", "broken", "bug", "wrong", "working",
}
NON_LOCATING_FILLER_TERMS = {"there", "issue", "problem", "broken", "bug", "fix", "wrong", "working", "not", "not working"}


def is_scaffold_meta_term(term: str) -> bool:
    normalized = _normalize_term(str(term or "").replace("_", "-"))
    if not normalized:
        return False
    return normalized in SCAFFOLD_META_TERMS or normalized.replace("-", "") in {
        item.replace("-", "") for item in SCAFFOLD_META_TERMS
    }
NEGATIVE_RE = re.compile(
    r"(?i)\b(?:do\s+not|don't|dont|avoid|without)\s+"
    r"(?:edit(?:ing)?|change|changing|touch(?:ing)?|modify(?:ing)?)?\s*"
    r"(?P<terms>[a-z0-9_./*\-\s]+?)(?:[.;,\n]|$)"
)
TEST_EDIT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bfix\s+(?:the\s+)?failing\s+.+\btest\b",
        r"\bfix\s+(?:the\s+)?(?:test|tests?|regression)\b",
        r"\b(?:update|change|repair|adjust)\s+(?:the\s+)?(?:test|tests?|regression\s+test|test\s+expectation|expectation|assertion|expected\s+output)\b",
        r"\b(?:add|write)\s+(?:a\s+)?(?:test|tests?|coverage)\b",
        r"\badd\s+coverage\b",
        r"\bthe\s+test\s+itself\s+is\s+wrong\b",
        r"\bfix\s+(?:the\s+)?test\s+assertion\b",
        r"\brepair\s+(?:the\s+)?regression\s+runner\b",
        r"\bfix\s+(?:the\s+)?regression\s+runner\b",
    )
]
TEST_VERIFICATION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\brun\s+(?:the\s+)?(?:tests?|regression|regression\s+command|diagnostic\s+regression\s+command)\b",
        r"\bverify\s+(?:with|using)\s+(?:the\s+)?(?:tests?|regression)\b",
        r"\bmake\s+sure\s+(?:the\s+)?(?:tests?|regression)\s+pass(?:es)?\b",
        r"\bensure\s+(?:the\s+)?(?:tests?|regression)\s+pass(?:es)?\b",
        r"\b(?:the\s+)?regression\s+(?:should\s+)?still\s+pass(?:es)?\b",
        r"\bkeep\s+(?:the\s+)?(?:tests?|test|regression)\s+pass(?:ing|es)?\b",
        r"\bafter\s+(?:the\s+)?patch[^\n.;]*\brun\s+(?:the\s+)?(?:tests?|regression)\b",
        r"\bdo\s+not\s+(?:edit|change|modify|touch)\s+tests?\b",
        r"\bdon't\s+(?:edit|change|modify|touch)\s+tests?\b",
        r"\bwithout\s+(?:editing|changing|modifying|touching)\s+tests?\b",
    )
]
VERIFICATION_TERM_RE = re.compile(r"\b(?:run|verify|ensure|pass|passes|passing|regression|tests?|coverage)\b", re.IGNORECASE)
PATH_RE = re.compile(
    r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+(?![\w.-])"
)
OPTION_FLAG_RE = re.compile(r"(?<![\w-])--[A-Za-z0-9][A-Za-z0-9_-]*")
QUOTED_RE = re.compile(r'"([^"\n]{1,120})"|\'([^\'\n]{1,120})\'')
CAMEL_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*)+\b")
SNAKE_OR_ENTITY_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9]+(?:[_-][a-zA-Z0-9]+)+\b")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")

SYMBOL_PATTERNS = [
    re.compile(r"(?m)^\s*(?:class|def)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"(?m)^\s*([A-Z][A-Z0-9_]{2,})\s*="),
    re.compile(r"(?m)^\s*(?:export\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
    re.compile(r"(?m)^\s*(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
    re.compile(r"(?m)^\s*(?:struct|class|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"(?m)^\s*func\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"(?m)^\s*func\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"(?m)^\s*(?:func|type)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"(?m)^\s*(?:fn|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
]
STRING_RE = re.compile(r'"([^"\n]{2,160})"|\'([^\'\n]{2,160})\'')
ROUTE_RE = re.compile(r'["\'](/[A-Za-z0-9_./{}:-]{1,120})["\']')
COMMENT_LINE_RE = re.compile(r"(?m)^\s*(?:#|//|/\*+|\*|\"\"\"|''')\s?(.*)$")
PY_IMPORT_RE = re.compile(r"(?m)^\s*import\s+([A-Za-z0-9_., \t]+)")
PY_FROM_IMPORT_RE = re.compile(r"(?m)^\s*from\s+([.A-Za-z0-9_]+)\s+import\s+([A-Za-z0-9_*, \t]+)")
JS_IMPORT_RE = re.compile(r"""(?m)\b(?:import|export)\b[\s\S]{0,160}?\bfrom\s*["']([^"']+)["']""")
JS_REQUIRE_RE = re.compile(r"""(?m)\brequire\s*\(\s*["']([^"']+)["']\s*\)""")
LOCAL_IMPORT_EXTENSIONS = ("", ".py", ".ts", ".tsx", ".js", ".jsx", ".swift", ".go", ".rs", ".cs", ".kt")


@dataclass
class PromptEvidence:
    explicit_paths: list[str]
    option_flags: list[str]
    quoted_literals: list[str]
    symbols_or_entities: list[str]
    domain_terms: list[str]
    behavior_terms: list[str]
    option_value_terms: list[str]
    invalid_value_terms: list[str]
    allowed_value_terms: list[str]
    default_fallback_terms: list[str]
    action_verbs: list[str]
    surface_hints: list[str]
    negative_terms: list[str]
    test_edit_intent: bool
    test_verification_intent: bool
    verification_terms: list[str]
    raw_prompt: str
    typo_normalizations: dict[str, str] = field(default_factory=dict)


@dataclass
class LocatedFile:
    path: str
    score: int
    role: str
    confidence: str
    matched_signals: list[str]


@dataclass
class FileRelation:
    source: str
    target: str
    relation: str
    strength: int


@dataclass
class LocateResult:
    primary_files: list[LocatedFile]
    support_files: list[LocatedFile]
    verification_files: list[LocatedFile]
    confidence: str
    covered_prompt_terms: list[str]
    uncovered_prompt_terms: list[str]
    ambiguity_reasons: list[str]
    dependency_relations: list[FileRelation] = field(default_factory=list)
    typo_normalizations: dict[str, str] = field(default_factory=dict)
    relation_degraded_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class _FileEvidence:
    path: str
    role: str
    text: str
    path_terms: set[str]
    content_terms: set[str]
    symbols: set[str]
    symbol_terms: set[str]
    strings: list[str]
    comments: list[str]
    routes: list[str]
    config_keys: set[str]
    import_refs: set[str]
    option_flags: set[str]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip()
        if not clean:
            continue
        key = clean.lower()
        if key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _split_identifier(value: str) -> list[str]:
    value = value.replace("\\", "/")
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"[^A-Za-z0-9]+", " ", value)
    return [part.lower() for part in value.split() if part]


def _normalize_term(value: str) -> str:
    return " ".join(_split_identifier(value))


def _base_term_variants(value: str) -> set[str]:
    parts = _split_identifier(value)
    if not parts:
        return set()
    variants = set(parts)
    variants.add(" ".join(parts))
    variants.add("_".join(parts))
    variants.add("-".join(parts))
    variants.add("".join(parts))
    return {variant for variant in variants if variant}


def _term_variants(value: str) -> set[str]:
    parts = _split_identifier(value)
    variants = _base_term_variants(value)
    if not parts:
        return set()
    if "calculation" in parts:
        variants.update({"calculate", "calculated", "calculating"})
    if "handling" in parts:
        variants.update({"handle", "handled"})
    if "report" in parts or "reporting" in parts or "reported" in parts:
        variants.update({"report", "reports", "reported", "reporting"})
    if "failure" in parts or "failures" in parts or "failed" in parts:
        variants.update({"failure", "failures", "fail", "fails", "failed"})
    if "settings" in parts:
        variants.add("setting")
    if "script" in parts:
        variants.add("scripts")
    if "scripts" in parts:
        variants.add("script")
    if "instruction" in parts:
        variants.add("instructions")
    if "instructions" in parts:
        variants.add("instruction")
    if "option" in parts:
        variants.add("options")
    if "options" in parts:
        variants.add("option")
    if "value" in parts:
        variants.add("values")
    if "values" in parts:
        variants.add("value")
    if "choice" in parts:
        variants.add("choices")
    if "choices" in parts:
        variants.add("choice")
    if "theme" in parts:
        variants.add("themes")
    if "themes" in parts:
        variants.add("theme")
    if "style" in parts:
        variants.add("styles")
    if "styles" in parts:
        variants.add("style")
    if "default" in parts:
        variants.add("defaults")
    if "defaults" in parts:
        variants.add("default")
    if "fallback" in parts:
        variants.update({"fallbacks", "fall back", "falls back"})
    if "unsupported" in parts:
        variants.add("invalid")
    if "invalid" in parts:
        variants.add("unsupported")
    if "valid" in parts:
        variants.add("allowed")
    if "allowed" in parts:
        variants.add("valid")
    return {variant for variant in variants if variant}


def _tokens_from_text(text: str) -> set[str]:
    tokens: set[str] = set()
    for word in WORD_RE.findall(text):
        tokens.update(_base_term_variants(word))
    for entity in CAMEL_RE.findall(text):
        tokens.update(_base_term_variants(entity))
    for entity in SNAKE_OR_ENTITY_RE.findall(text):
        tokens.update(_base_term_variants(entity))
    return tokens


def _important_terms(evidence: PromptEvidence) -> list[str]:
    terms: list[str] = []
    terms.extend(evidence.symbols_or_entities)
    terms.extend(evidence.domain_terms)
    terms.extend(evidence.option_value_terms)
    terms.extend(evidence.invalid_value_terms)
    terms.extend(evidence.allowed_value_terms)
    terms.extend(evidence.default_fallback_terms)
    terms.extend(evidence.surface_hints)
    for flag in evidence.option_flags:
        terms.extend(_split_identifier(flag))
    for literal in evidence.quoted_literals:
        terms.extend(_split_identifier(literal))
    negative = {_normalize_term(term) for term in evidence.negative_terms if _normalize_term(term)}
    return _dedupe([
        _normalize_term(term)
        for term in terms
        if _normalize_term(term)
        and _normalize_term(term) not in negative
        and _normalize_term(term) not in NON_LOCATING_FILLER_TERMS
        and not is_scaffold_meta_term(term)
    ])


def _prompt_synonym_terms(prompt: PromptEvidence) -> set[str]:
    terms: set[str] = set()
    terms.update(_normalize_term(term) for term in prompt.domain_terms)
    terms.update(_normalize_term(term) for term in prompt.surface_hints)
    terms.update(_normalize_term(term) for term in prompt.option_value_terms)
    terms.update(_normalize_term(term) for term in prompt.symbols_or_entities)
    for flag in prompt.option_flags:
        terms.update(_split_identifier(flag))
    for literal in prompt.quoted_literals:
        terms.update(_split_identifier(literal))
    return {term for term in terms if term}


def _active_synonym_groups(prompt: PromptEvidence) -> dict[str, set[str]]:
    prompt_terms = _prompt_synonym_terms(prompt)
    return {
        group: prompt_terms & set(group_terms)
        for group, group_terms in BOUNDED_SYNONYM_GROUPS.items()
        if prompt_terms & set(group_terms)
    }


def _edit_distance_limited(a: str, b: str, limit: int = 2) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _repo_vocabulary(files: list["_FileEvidence"]) -> set[str]:
    vocab: set[str] = set()
    for file in files:
        for term in set(file.path_terms) | set(file.content_terms) | set(file.symbol_terms):
            normalized = _normalize_term(term)
            if len(normalized) >= 4 and normalized not in STOP_TERMS and not is_scaffold_meta_term(normalized):
                vocab.add(normalized)
    return vocab


def _code_like_term(term: str, evidence: PromptEvidence) -> bool:
    if term in {flag.lstrip("-").lower() for flag in evidence.option_flags}:
        return True
    if any(term == _normalize_term(symbol) for symbol in evidence.symbols_or_entities):
        return True
    return bool(re.search(r"[_./:-]", term)) or any(ch.isupper() for ch in term)


def _safe_typo_correction(term: str, vocabulary: set[str], evidence: PromptEvidence) -> str | None:
    normalized = _normalize_term(term)
    if (
        len(normalized) < 5
        or normalized in vocabulary
        or normalized in DOMAIN_TERMS
        or normalized in OPTION_VALUE_TERMS
        or normalized in INVALID_VALUE_TERMS
        or normalized in ALLOWED_VALUE_TERMS
        or normalized in DEFAULT_FALLBACK_TERMS
        or normalized in SURFACE_HINTS
        or normalized in BEHAVIOR_TERMS
        or normalized in STOP_TERMS
        or normalized in NON_LOCATING_FILLER_TERMS
        or is_scaffold_meta_term(normalized)
        or _code_like_term(str(term), evidence)
    ):
        return None
    scored: list[tuple[int, str]] = []
    for candidate in vocabulary:
        if candidate[0:1] != normalized[0:1] or abs(len(candidate) - len(normalized)) > 2:
            continue
        distance = _edit_distance_limited(normalized, candidate, 2)
        if distance <= 1 or (distance == 2 and len(normalized) >= 6 and len(candidate) >= 6):
            scored.append((distance, candidate))
    scored.sort()
    if not scored:
        return None
    best_distance, best = scored[0]
    ties = [candidate for distance, candidate in scored if distance == best_distance]
    if len(ties) == 1:
        return best
    return None


def _replace_terms(values: list[str], typo_map: dict[str, str]) -> list[str]:
    out: list[str] = []
    for value in values:
        normalized = _normalize_term(value)
        out.append(typo_map.get(normalized, value))
    return _dedupe(out)


def _apply_typo_normalization(evidence: PromptEvidence, files: list["_FileEvidence"]) -> PromptEvidence:
    vocab = _repo_vocabulary(files)
    source_terms = (
        list(evidence.domain_terms)
        + list(evidence.behavior_terms)
        + list(evidence.surface_hints)
        + list(evidence.option_value_terms)
        + list(evidence.invalid_value_terms)
        + list(evidence.allowed_value_terms)
        + list(evidence.default_fallback_terms)
    )
    typo_map: dict[str, str] = {}
    for term in source_terms:
        normalized = _normalize_term(term)
        correction = _safe_typo_correction(normalized, vocab, evidence)
        if correction and correction != normalized:
            typo_map[normalized] = correction
    if not typo_map:
        return evidence
    return PromptEvidence(
        explicit_paths=evidence.explicit_paths,
        option_flags=evidence.option_flags,
        quoted_literals=evidence.quoted_literals,
        symbols_or_entities=evidence.symbols_or_entities,
        domain_terms=_replace_terms(evidence.domain_terms, typo_map),
        behavior_terms=_replace_terms(evidence.behavior_terms, typo_map),
        option_value_terms=_replace_terms(evidence.option_value_terms, typo_map),
        invalid_value_terms=_replace_terms(evidence.invalid_value_terms, typo_map),
        allowed_value_terms=_replace_terms(evidence.allowed_value_terms, typo_map),
        default_fallback_terms=_replace_terms(evidence.default_fallback_terms, typo_map),
        action_verbs=evidence.action_verbs,
        surface_hints=_replace_terms(evidence.surface_hints, typo_map),
        negative_terms=evidence.negative_terms,
        test_edit_intent=evidence.test_edit_intent,
        test_verification_intent=evidence.test_verification_intent,
        verification_terms=evidence.verification_terms,
        raw_prompt=evidence.raw_prompt,
        typo_normalizations=typo_map,
    )


def extract_prompt_evidence(prompt: str) -> PromptEvidence:
    explicit_paths = _dedupe(PATH_RE.findall(prompt))
    option_flags = _dedupe(OPTION_FLAG_RE.findall(prompt))
    quoted_literals = _dedupe([a or b for a, b in QUOTED_RE.findall(prompt)])

    symbols: list[str] = []
    for match in CAMEL_RE.findall(prompt):
        if match not in {"README", "API", "CSV"} and not is_scaffold_meta_term(match):
            symbols.append(match)
    for match in SNAKE_OR_ENTITY_RE.findall(prompt):
        if "/" not in match and not is_scaffold_meta_term(match):
            symbols.append(match)

    prompt_terms = _tokens_from_text(prompt)
    domain_terms: list[str] = []
    for term in sorted(DOMAIN_TERMS):
        if is_scaffold_meta_term(term):
            continue
        variants = _term_variants(term)
        if prompt_terms & variants:
            domain_terms.append(term)
    for token in sorted(prompt_terms):
        if len(token) >= 3 and token not in STOP_TERMS and token not in NON_LOCATING_FILLER_TERMS and not is_scaffold_meta_term(token) and "/" not in token:
            domain_terms.append(token)

    prompt_lower = prompt.lower()
    behavior_terms = [phrase for phrase in sorted(BEHAVIOR_PHRASES) if phrase in prompt_lower]
    for term in sorted(BEHAVIOR_TERMS - BEHAVIOR_PHRASES):
        variants = _term_variants(term)
        if prompt_terms & variants:
            behavior_terms.append(term)
    option_value_terms: list[str] = []
    for term in sorted(OPTION_VALUE_TERMS):
        if term in {"fall back", "falls back"}:
            continue
        if prompt_terms & _term_variants(term):
            option_value_terms.append(term)
    option_value_terms.extend(_split_identifier(" ".join(option_flags)))
    invalid_value_terms = [
        term for term in sorted(INVALID_VALUE_TERMS)
        if prompt_terms & _base_term_variants(term)
    ]
    allowed_value_terms = [
        term for term in sorted(ALLOWED_VALUE_TERMS)
        if prompt_terms & _term_variants(term)
    ]
    default_fallback_terms = [
        term for term in sorted(DEFAULT_FALLBACK_TERMS)
        if (term in {"fall back", "falls back"} and term in prompt_lower)
        or (term not in {"fall back", "falls back"} and prompt_terms & _term_variants(term))
    ]
    action_verbs = [phrase for phrase in sorted(ACTION_PHRASES) if phrase in prompt_lower and not is_scaffold_meta_term(phrase)]
    action_verbs.extend(word for word in sorted(ACTION_WORDS) if not is_scaffold_meta_term(word) and re.search(rf"\b{re.escape(word)}\b", prompt_lower))

    surface_hints = [hint for hint in sorted(SURFACE_HINTS) if not is_scaffold_meta_term(hint) and prompt_terms & _term_variants(hint)]
    if {"console", "script"} <= prompt_terms:
        surface_hints.extend(["cli", "command"])

    negative_terms: list[str] = []
    for match in NEGATIVE_RE.finditer(prompt):
        raw_terms = match.group("terms")
        for token in _split_identifier(raw_terms):
            if token in {"or", "and", "the", "a", "an", "to"}:
                continue
            negative_terms.append(token)

    test_edit_text = NEGATIVE_RE.sub(" ", prompt)
    test_edit_intent = any(pattern.search(test_edit_text) for pattern in TEST_EDIT_PATTERNS)
    test_verification_intent = any(pattern.search(prompt) for pattern in TEST_VERIFICATION_PATTERNS)
    verification_terms = _dedupe([match.group(0).lower() for match in VERIFICATION_TERM_RE.finditer(prompt)])

    return PromptEvidence(
        explicit_paths=explicit_paths,
        option_flags=option_flags,
        quoted_literals=quoted_literals,
        symbols_or_entities=_dedupe(symbols),
        domain_terms=_dedupe(domain_terms),
        behavior_terms=_dedupe(behavior_terms),
        option_value_terms=_dedupe(option_value_terms),
        invalid_value_terms=_dedupe(invalid_value_terms),
        allowed_value_terms=_dedupe(allowed_value_terms),
        default_fallback_terms=_dedupe(default_fallback_terms),
        action_verbs=_dedupe(action_verbs),
        surface_hints=_dedupe(surface_hints),
        negative_terms=_dedupe(negative_terms),
        test_edit_intent=test_edit_intent,
        test_verification_intent=test_verification_intent,
        verification_terms=verification_terms,
        raw_prompt=prompt,
    )


def _role_for_path(rel_path: str) -> str:
    rel = rel_path.replace("\\", "/")
    role = classify_path_role(rel)
    lower = rel.lower()
    parts = lower.split("/")
    name = parts[-1]
    suffix = Path(name).suffix.lower()
    if is_secret_name(rel) or is_sensitive_or_secret_path(rel) or name in {".npmrc", ".pypirc"} or "private_key" in lower:
        return "secret"
    if role.generated_or_vendor_status == "generated_or_vendor" and any(part in {"node_modules", "vendor", "vendors", "third_party"} for part in parts):
        return "vendor"
    if role.generated_or_vendor_status == "generated_or_vendor":
        return "build"
    if "generated" in parts or "__generated__" in parts or ".generated." in lower or ".gen." in lower:
        return "generated"
    if suffix in MEDIA_ASSET_EXTENSIONS | ARCHIVE_EXTENSIONS | {".pdf"}:
        return "asset"
    if role.is_test:
        return "test"
    if role.is_docs:
        return "docs"
    if role.is_config:
        return "config"
    return "source"


def _iter_repo_files(repo_root: Path, inventory_paths: list[str] | None = None) -> list[Path]:
    if inventory_paths is not None:
        return [repo_root / rel for rel in inventory_paths]
    ignore = IgnoreMatcher.from_repo(repo_root)
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        parts = rel.split("/")
        if any(part in {".git", ".premode", ".venv", "node_modules", "__pycache__"} for part in parts):
            continue
        if ignore.is_ignored(rel):
            continue
        files.append(path)
    return files


def _read_bounded(path: Path) -> str:
    if is_probably_binary_path(path):
        return ""
    try:
        data = path.read_bytes()[: MAX_LOCATOR_BYTES + 1]
    except OSError:
        return ""
    if b"\x00" in data[:4096]:
        return ""
    return data[:MAX_LOCATOR_BYTES].decode("utf-8", errors="replace")


def _simple_path_terms(value: str) -> set[str]:
    return {term for term in SIMPLE_TERM_RE.findall(value.lower()) if len(term) >= 2}


def is_media_lookup_prompt(prompt: str) -> bool:
    text = (prompt or "").lower()
    terms = _simple_path_terms(text)
    if terms & MEDIA_CODE_EDIT_TERMS:
        return False
    has_lookup = bool(terms & MEDIA_LOOKUP_TERMS) or "where is" in text or "where's" in text
    has_media = bool(terms & MEDIA_QUERY_TERMS)
    return has_lookup and has_media


def _media_prompt_wants_recency(prompt: str) -> bool:
    text = (prompt or "").lower()
    terms = _simple_path_terms(text)
    return bool(terms & MEDIA_RECENCY_TERMS) or "most recent" in text


def _media_prompt_extensions(prompt_terms: set[str]) -> set[str]:
    out = {f".{term}" for term in prompt_terms if f".{term}" in MEDIA_ASSET_EXTENSIONS}
    if "blender" in prompt_terms:
        out.add(".blend")
    return out


def _media_domain_terms(prompt: str) -> set[str]:
    terms = _simple_path_terms(prompt)
    return {term for term in terms if len(term) >= 3 and term not in MEDIA_GENERIC_TERMS}


def _media_path_is_pruned(rel_path: str) -> bool:
    lower = rel_path.lower().replace("\\", "/").strip("/")
    parts = [part for part in lower.split("/") if part]
    name = parts[-1] if parts else lower
    if is_secret_name(lower) or is_sensitive_or_secret_path(lower):
        return True
    return any(part in MEDIA_PRUNE_SEGMENTS for part in parts)


def _media_directory_hint_score(rel_path: str) -> int:
    parts = [part for part in _simple_path_terms(posixpath.dirname(rel_path)) if part]
    return 70 if any(part in MEDIA_DIRECTORY_HINTS for part in parts) else 0


def _media_explicit_match(prompt_lower: str, rel_path: str) -> bool:
    lower = rel_path.lower()
    name = posixpath.basename(lower)
    return lower in prompt_lower or name in prompt_lower


def _media_confidence(selected: list[LocatedFile], uncovered_terms: list[str]) -> str:
    if not selected:
        return "low"
    if uncovered_terms:
        return "medium"
    return "high"


def locate_media_files(
    repo_root: Path,
    prompt: str,
    *,
    max_files: int = 8,
    inventory_paths: list[str] | None = None,
) -> LocateResult:
    started = time.perf_counter()
    repo_root = Path(repo_root)
    prompt_lower = (prompt or "").lower()
    prompt_terms = _simple_path_terms(prompt_lower)
    wanted_extensions = _media_prompt_extensions(prompt_terms)
    domain_terms = _media_domain_terms(prompt)
    wants_recency = _media_prompt_wants_recency(prompt)
    raw_paths = [
        str(path).replace("\\", "/").strip("/")
        for path in (inventory_paths if inventory_paths is not None else [path.relative_to(repo_root).as_posix() for path in _iter_repo_files(repo_root)])
        if str(path).strip()
    ]

    candidate_count = 0
    pruned_count = 0
    stat_calls = 0
    scored: list[dict[str, object]] = []
    for rel in raw_paths:
        suffix = Path(rel).suffix.lower()
        if suffix not in MEDIA_ASSET_EXTENSIONS:
            continue
        candidate_count += 1
        explicit = _media_explicit_match(prompt_lower, rel)
        if _media_path_is_pruned(rel) and not explicit:
            pruned_count += 1
            continue
        path_terms = _simple_path_terms(rel)
        overlap = sorted(domain_terms & path_terms)
        if domain_terms and not overlap and not explicit:
            pruned_count += 1
            continue
        score = 100
        signals = ["asset_media_fast_path", f"extension:{suffix.lstrip('.')}"]
        if wanted_extensions:
            if suffix in wanted_extensions:
                score += 260
                signals.append(f"extension_match:{suffix.lstrip('.')}")
            else:
                score -= 90
        if explicit:
            score += 600
            signals.append("explicit_media_path_or_basename")
        if overlap:
            score += 135 * len(overlap)
            signals.extend(f"filename_term:{term}" for term in overlap[:8])
        dir_score = _media_directory_hint_score(rel)
        if dir_score:
            score += dir_score
            signals.append("asset_directory_hint")
        scored.append({
            "path": rel,
            "score": score,
            "signals": signals,
            "overlap_count": len(overlap),
            "explicit": explicit,
            "mtime_ns": None,
        })

    recency_pool = [
        item for item in scored
        if bool(item.get("explicit")) or int(item.get("overlap_count") or 0) > 0 or not domain_terms
    ]
    if not recency_pool:
        recency_pool = scored
    if wants_recency:
        recency_candidates = sorted(recency_pool, key=lambda item: (-int(item.get("score") or 0), str(item.get("path") or "")))[:MAX_ASSET_STAT_CANDIDATES]
        for item in recency_candidates:
            try:
                item["mtime_ns"] = int((repo_root / str(item["path"])).stat().st_mtime_ns)
                stat_calls += 1
            except OSError:
                item["mtime_ns"] = 0
            signals = list(item.get("signals") or [])
            signals.append("mtime_recency_requested")
            item["signals"] = signals
    sortable = recency_pool
    sortable.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            -(int(item.get("mtime_ns") or 0) if wants_recency else 0),
            str(item.get("path") or ""),
        )
    )
    selected_items = sortable[:max(1, int(max_files or 8))]
    selected = [
        LocatedFile(
            path=str(item["path"]),
            score=int(item.get("score") or 0),
            role="asset",
            confidence="high" if int(item.get("score") or 0) >= 450 else "medium",
            matched_signals=[str(signal) for signal in item.get("signals") or []],
        )
        for item in selected_items
    ]
    covered = sorted(
        term
        for term in domain_terms
        if any(term in _simple_path_terms(file.path) for file in selected)
    )
    uncovered = sorted(domain_terms - set(covered))
    ambiguity: list[str] = []
    if pruned_count:
        ambiguity.append("asset_candidates_pruned")
    if len(selected) >= max_files and len(sortable) > len(selected):
        ambiguity.append("result hit max_files cap")
    metadata = {
        "schema_version": "asset_media_fast_path.v1",
        "context_selection_mode": "asset_media_fast_path",
        "asset_fast_path_triggered": True,
        "asset_fast_path_reason": "media_lookup_prompt",
        "asset_candidate_count": candidate_count,
        "asset_candidate_pruned_count": pruned_count,
        "asset_selected_count": len(selected),
        "asset_search_elapsed_ms": int((time.perf_counter() - started) * 1000),
        "asset_stat_calls": stat_calls,
        "content_reads": 0,
    }
    return LocateResult(
        primary_files=selected,
        support_files=[],
        verification_files=[],
        confidence=_media_confidence(selected, uncovered),
        covered_prompt_terms=covered,
        uncovered_prompt_terms=uncovered,
        ambiguity_reasons=ambiguity,
        dependency_relations=[],
        metadata=metadata,
    )


def _extract_symbols(text: str) -> set[str]:
    symbols: set[str] = set()
    for pattern in SYMBOL_PATTERNS:
        for match in pattern.findall(text):
            if isinstance(match, tuple):
                match = next((part for part in match if part), "")
            if match:
                symbols.add(match)
    return symbols


def _relative_python_base(source_path: str, module: str) -> str:
    parent_parts = source_path.split("/")[:-1]
    dots = len(module) - len(module.lstrip("."))
    remainder = module.lstrip(".")
    if dots:
        keep = max(0, len(parent_parts) - (dots - 1))
        parent_parts = parent_parts[:keep]
    if remainder:
        parent_parts.extend(remainder.split("."))
    return "/".join(part for part in parent_parts if part)


def _extract_import_refs(text: str, rel_path: str) -> set[str]:
    refs: set[str] = set()
    suffix = Path(rel_path).suffix.lower()

    if suffix == ".py":
        for raw in PY_IMPORT_RE.findall(text):
            for name in raw.split(","):
                module = name.strip().split(" as ", 1)[0].strip()
                if module:
                    refs.add(module.replace(".", "/"))
        for module, imported in PY_FROM_IMPORT_RE.findall(text):
            base = _relative_python_base(rel_path, module) if module.startswith(".") else module.replace(".", "/")
            if base:
                refs.add(base)
            if imported:
                for name in imported.split(","):
                    clean = name.strip().split(" as ", 1)[0].strip()
                    if clean and clean != "*" and base:
                        refs.add(f"{base}/{clean}")

    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for raw in [*JS_IMPORT_RE.findall(text), *JS_REQUIRE_RE.findall(text)]:
            if raw.startswith("."):
                refs.add(str(Path(rel_path).parent.joinpath(raw)).replace("\\", "/"))

    return refs


def _extract_option_flags(text: str) -> set[str]:
    return set(OPTION_FLAG_RE.findall(text))


def _file_evidence(repo_root: Path, path: Path) -> _FileEvidence | None:
    rel = path.relative_to(repo_root).as_posix()
    role = _role_for_path(rel)
    if role == "secret":
        return None
    if role in {"vendor", "build", "asset"}:
        return None
    text = _read_bounded(path)
    if not text and path.stat().st_size > 0:
        return None
    symbols = _extract_symbols(text)
    strings = _dedupe([a or b for a, b in STRING_RE.findall(text)])[:80]
    comments = _dedupe(COMMENT_LINE_RE.findall(text))[:80]
    routes = _dedupe(ROUTE_RE.findall(text))
    config_keys = set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*[:=]", text))
    config_keys.update(re.findall(r"(?m)^\s*\[+([A-Za-z0-9_.-]+)\]+", text))
    content_blob = "\n".join([text, "\n".join(strings), "\n".join(comments), "\n".join(routes), " ".join(config_keys)])
    return _FileEvidence(
        path=rel,
        role=role,
        text=text,
        path_terms=_tokens_from_text(rel),
        content_terms=_tokens_from_text(content_blob),
        symbols=symbols,
        symbol_terms=_tokens_from_text(" ".join(symbols)),
        strings=strings,
        comments=comments,
        routes=routes,
        config_keys=config_keys,
        import_refs=_extract_import_refs(text, rel),
        option_flags=_extract_option_flags(text),
    )


def _norm_rel_path(value: str) -> str:
    normalized = posixpath.normpath(value.replace("\\", "/")).lstrip("./")
    return "" if normalized == "." else normalized


def _candidate_import_paths(source_path: str, ref: str) -> list[str]:
    source_dir = posixpath.dirname(source_path)
    raw = _norm_rel_path(ref)
    candidates: list[str] = []
    if raw:
        candidates.append(raw)
        if source_dir and not raw.startswith(source_dir + "/") and not raw.startswith(("src/", "tests/", "tools/", "docs/")):
            candidates.append(_norm_rel_path(posixpath.join(source_dir, raw)))

    expanded: list[str] = []
    for candidate in candidates:
        expanded.append(candidate)
        if Path(candidate).suffix:
            continue
        for extension in LOCAL_IMPORT_EXTENSIONS:
            if extension:
                expanded.append(candidate + extension)
        for extension in LOCAL_IMPORT_EXTENSIONS:
            if extension:
                expanded.append(posixpath.join(candidate, "index" + extension))
                expanded.append(posixpath.join(candidate, "__init__" + extension))
    return _dedupe([path for path in expanded if path])


def _suffix_candidates_for_ref(source_path: str, ref: str) -> list[str]:
    suffix_candidates = []
    for candidate in _candidate_import_paths(source_path, ref):
        if Path(candidate).suffix:
            suffix_candidates.append(candidate)
        else:
            suffix_candidates.extend(candidate + ext for ext in LOCAL_IMPORT_EXTENSIONS if ext)
    return _dedupe(suffix_candidates)


def _build_import_suffix_lookup(path_index: set[str]) -> dict[str, list[str]] | None:
    if len(path_index) > MAX_IMPORT_SUFFIX_INDEX_PATHS:
        return None
    suffix_lookup: dict[str, list[str]] = {}
    for path in sorted(path_index):
        parts = [part for part in path.split("/") if part]
        for start in range(max(0, len(parts) - 6), len(parts)):
            suffix = "/".join(parts[start:])
            if not suffix or suffix == path:
                continue
            bucket = suffix_lookup.setdefault(suffix, [])
            if len(bucket) < 3:
                bucket.append(path)
    return suffix_lookup


def _resolve_import_ref(
    source_path: str,
    ref: str,
    path_index: set[str],
    *,
    suffix_lookup: dict[str, list[str]] | None = None,
) -> str | None:
    for candidate in _candidate_import_paths(source_path, ref):
        if candidate in path_index:
            return candidate

    # Python absolute imports may omit the repository package prefix in small repos.
    suffix_candidates = _suffix_candidates_for_ref(source_path, ref)
    if suffix_lookup is not None:
        for candidate in suffix_candidates:
            matches = suffix_lookup.get(candidate) or []
            if len(matches) == 1:
                return matches[0]
        return None
    if len(path_index) > MAX_IMPORT_SUFFIX_SCAN_PATHS:
        return None
    for candidate in suffix_candidates:
        matches = sorted(path for path in path_index if path.endswith("/" + candidate))
        if len(matches) == 1:
            return matches[0]
    return None


def _stem_key(path: str) -> str:
    name = Path(path).name
    for suffix in [".test.tsx", ".test.ts", ".spec.tsx", ".spec.ts"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    else:
        name = Path(name).stem
    name = re.sub(r"^(test_|spec_)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(_test|_spec)$", "", name, flags=re.IGNORECASE)
    return "".join(_split_identifier(name))


def _is_test_path(path: str) -> bool:
    return _role_for_path(path) == "test"


def _add_relation(relations: list[FileRelation], seen: set[tuple[str, str, str]], source: str, target: str, relation: str, strength: int) -> None:
    if not source or not target or source == target:
        return
    key = (source, target, relation)
    if key in seen:
        return
    seen.add(key)
    relations.append(FileRelation(source=source, target=target, relation=relation, strength=strength))


def _shared_prompt_terms(a: _FileEvidence, b: _FileEvidence, prompt_terms: list[str]) -> set[str]:
    shared: set[str] = set()
    combined_a = a.path_terms | a.content_terms | a.symbol_terms
    combined_b = b.path_terms | b.content_terms | b.symbol_terms
    for term in prompt_terms:
        if _has_term(term, combined_a) and _has_term(term, combined_b):
            shared.add(_normalize_term(term))
    return shared


def _build_file_relations(
    files: list[_FileEvidence],
    prompt_terms: list[str],
    *,
    degraded_reasons: list[str] | None = None,
) -> list[FileRelation]:
    relation_files = files
    if len(files) > MAX_RELATION_FILES:
        relation_files = files[:MAX_RELATION_FILES]
        if degraded_reasons is not None:
            degraded_reasons.append("relation_file_count_cap")
    path_index = {file.path for file in relation_files}
    relations: list[FileRelation] = []
    seen: set[tuple[str, str, str]] = set()
    suffix_lookup = _build_import_suffix_lookup(path_index)
    if suffix_lookup is None and degraded_reasons is not None:
        degraded_reasons.append("import_suffix_lookup_path_cap")

    for file in relation_files:
        for ref in file.import_refs:
            target = _resolve_import_ref(file.path, ref, path_index, suffix_lookup=suffix_lookup)
            if target is not None:
                _add_relation(relations, seen, file.path, target, "imports", 86)
                _add_relation(relations, seen, target, file.path, "imported_by", 78)

    by_stem: dict[str, list[_FileEvidence]] = {}
    stem_by_path: dict[str, str] = {}
    name_terms_by_path: dict[str, set[str]] = {}
    for file in relation_files:
        stem = _stem_key(file.path)
        stem_by_path[file.path] = stem
        name_terms_by_path[file.path] = _tokens_from_text(Path(file.path).stem)
        if len(stem) >= 4:
            by_stem.setdefault(stem, []).append(file)
    for stem, grouped in by_stem.items():
        if len(grouped) < 2 or len(grouped) > 8:
            continue
        for source in grouped:
            for target in grouped:
                if source.path == target.path:
                    continue
                relation = "adjacent_test" if source.role != "test" and target.role == "test" else "same_stem"
                strength = 76 if relation == "adjacent_test" else 70
                _add_relation(relations, seen, source.path, target.path, relation, strength)

    by_dir: dict[str, list[_FileEvidence]] = {}
    for file in relation_files:
        source_dir = posixpath.dirname(file.path)
        if source_dir:
            by_dir.setdefault(source_dir, []).append(file)
    for source_dir, grouped in by_dir.items():
        if len(grouped) > MAX_SAME_DIRECTORY_GROUP:
            if degraded_reasons is not None:
                degraded_reasons.append("same_directory_relation_group_cap")
            grouped = grouped[:MAX_SAME_DIRECTORY_GROUP]
        for source in grouped:
            source_name_terms = name_terms_by_path.get(source.path, set())
            for target in grouped:
                if source.path == target.path:
                    continue
                target_name_terms = name_terms_by_path.get(target.path, set())
                shared_prompt = _shared_prompt_terms(source, target, prompt_terms)
                if shared_prompt:
                    _add_relation(relations, seen, source.path, target.path, "same_directory", 46)

                route_terms = {"route", "handler", "service", "settings", "user", "payload"}
                if source_name_terms & {"handler", "route"} and target_name_terms & {"service", "helper"} and (source_name_terms | target_name_terms) & route_terms:
                    _add_relation(relations, seen, source.path, target.path, "route_helper", 66)
                if source_name_terms & {"page", "screen", "view"} and target_name_terms & {"helper", "state", "actions", "action", "hook", "use"}:
                    _add_relation(relations, seen, source.path, target.path, "component_state_helper", 64)
                if target_name_terms & {"page", "screen", "view"} and source_name_terms & {"helper", "state", "actions", "action", "hook", "use"}:
                    _add_relation(relations, seen, source.path, target.path, "component_state_helper", 58)

    # Nearby tests that mention source stems are verification candidates even when
    # language-specific imports are too loose to resolve.
    tests = [file for file in relation_files if file.role == "test"]
    sources = [file for file in relation_files if file.role != "test"]
    pair_count = len(sources) * len(tests)
    if pair_count > MAX_SOURCE_TEST_PAIR_SCAN:
        if degraded_reasons is not None:
            degraded_reasons.append("source_test_relation_pair_cap")
        for source in sources:
            source_stem = stem_by_path.get(source.path) or _stem_key(source.path)
            if len(source_stem) < 4:
                continue
            for test in by_stem.get(source_stem, []):
                if test.role == "test":
                    _add_relation(relations, seen, source.path, test.path, "adjacent_test", 68)
                    _add_relation(relations, seen, test.path, source.path, "adjacent_source", 62)
    else:
        test_blob_by_path = {
            test.path: " ".join(sorted(test.path_terms | test.content_terms | test.symbol_terms)).replace(" ", "")
            for test in tests
        }
        for source in sources:
            source_stem = stem_by_path.get(source.path) or _stem_key(source.path)
            if len(source_stem) < 4:
                continue
            for test in tests:
                if source_stem in (stem_by_path.get(test.path) or _stem_key(test.path)) or source_stem in test_blob_by_path.get(test.path, ""):
                    _add_relation(relations, seen, source.path, test.path, "adjacent_test", 68)
                    _add_relation(relations, seen, test.path, source.path, "adjacent_source", 62)

    return relations


def _literal_in_file(literal: str, file: _FileEvidence) -> bool:
    lower = literal.lower()
    if not lower:
        return False
    haystacks = [file.text, *file.strings, *file.comments, *file.routes]
    if re.fullmatch(r"[A-Za-z0-9_ -]+", literal):
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(literal)}(?![A-Za-z0-9_])", re.IGNORECASE)
        return any(pattern.search(value) for value in haystacks)
    return any(lower in value.lower() for value in haystacks)


def _has_term(term: str, terms: set[str]) -> bool:
    return bool(_term_variants(term) & terms)


def _signal_terms(signal: str) -> set[str]:
    if ":" not in signal:
        return set()
    value = signal.split(":", 1)[1].strip('"')
    return set(_split_identifier(value))


def _signal_covers_term(signal: str, term: str) -> bool:
    return bool(_term_variants(term) & _signal_terms(signal))


def _terms_covered_by_file(file: LocatedFile, important: list[str]) -> set[str]:
    covered: set[str] = set()
    for term in important:
        normalized = _normalize_term(term)
        if any(_signal_covers_term(signal, normalized) for signal in file.matched_signals):
            covered.add(normalized)
    return covered


def _has_high_value_signal(file: LocatedFile) -> bool:
    return any(
        signal.startswith((
            "explicit_path:",
            "symbol:",
            "quoted_literal:",
            "content_cluster:",
            "artifact_surface:",
            "option_decl:",
            "option_use:",
            "option_choices:",
        ))
        for signal in file.matched_signals
    )


def _has_bounded_synonym_identity_evidence(file: LocatedFile) -> bool:
    return any(
        signal.startswith(("bounded_synonym_path:", "bounded_synonym_symbol:"))
        for signal in file.matched_signals
    )


def _content_signal_count(file: LocatedFile) -> int:
    return sum(
        1
        for signal in file.matched_signals
        if signal.startswith((
            "content:",
            "string:",
            "route:",
            "symbol_term:",
            "message_surface:",
            "behavior_source:",
            "option_flag:",
            "option_decl:",
            "option_use:",
            "option_choices:",
            "option_default:",
            "option_value_evidence:",
            "option_error_handler:",
            "option_exception:",
        ))
    )


def _is_proximity_signal(signal: str) -> bool:
    return signal.startswith((
        "imports:",
        "imported_by:",
        "adjacent_test:",
        "adjacent_source:",
        "same_stem:",
        "same_directory_with:",
        "route_helper:",
        "component_state_helper:",
        "proximity_to_primary:",
    ))


def _has_proximity_signal(file: LocatedFile) -> bool:
    return any(_is_proximity_signal(signal) for signal in file.matched_signals)


def _has_direct_prompt_evidence(file: LocatedFile) -> bool:
    return any(
        not signal.startswith(("negative_constraint:", "role:")) and not _is_proximity_signal(signal)
        for signal in file.matched_signals
    )


def _has_transportable_content_evidence(file: LocatedFile) -> bool:
    return _has_high_value_signal(file) or _content_signal_count(file) >= 2


def _has_any_non_role_evidence(file: LocatedFile) -> bool:
    return any(
        not signal.startswith(("negative_constraint:", "role:"))
        for signal in file.matched_signals
    )


def _is_surface_only(file: LocatedFile) -> bool:
    evidence_signals = [
        signal
        for signal in file.matched_signals
        if not signal.startswith(("negative_constraint:", "role:")) and not _is_proximity_signal(signal)
    ]
    return not evidence_signals


def _is_generic_path(path: str) -> bool:
    name = Path(path).name.lower()
    return name in {
        "button.ts",
        "button.tsx",
        "handler.py",
        "index.py",
        "index.ts",
        "index.tsx",
        "main.py",
        "utils.py",
    }


def _is_helperish_path(path: str) -> bool:
    terms = _tokens_from_text(path)
    return bool(terms & {"helper", "helpers", "util", "utils"})


def _docs_synonym_requested(prompt: PromptEvidence) -> bool:
    active = _active_synonym_groups(prompt).get("docs", set())
    return bool(active & {"docs", "documentation", "guide", "quickstart", "tutorial"})


def _docs_requested(prompt: PromptEvidence) -> bool:
    terms = (set(prompt.surface_hints) | set(prompt.domain_terms)) - set(prompt.negative_terms)
    raw = prompt.raw_prompt.lower()
    return bool(
        {"docs", "documentation", "readme", "troubleshooting", "instructions", "guide", "setup", "install"} & terms
        or _docs_synonym_requested(prompt)
        or re.search(r"\b(?:getting started|new user|how to run|setup instructions|install instructions|clarify setup)\b", raw)
    )


def _docs_artifact_requested(prompt: PromptEvidence) -> bool:
    if not _docs_requested(prompt):
        return False
    terms = (set(prompt.surface_hints) | set(prompt.domain_terms)) - set(prompt.negative_terms)
    raw = prompt.raw_prompt.lower()
    return bool(
        {"docs", "documentation", "readme", "troubleshooting", "instructions", "guide", "setup", "install"} & terms
        or _docs_synonym_requested(prompt)
        or re.search(r"\b(?:getting started|new user|how to run|setup instructions|install instructions|clarify setup)\b", raw)
    )


def _is_docs_artifact_path(file: _FileEvidence) -> bool:
    lower = file.path.lower()
    name = Path(lower).name
    return file.role == "docs" or lower.startswith("docs/") or "/docs/" in lower or name.startswith("readme")


def _tests_requested(prompt: PromptEvidence) -> bool:
    return prompt.test_edit_intent and not _tests_forbidden_by_prompt(prompt)


def _tests_requested_for_verification(prompt: PromptEvidence) -> bool:
    return prompt.test_verification_intent or bool(set(prompt.verification_terms) & {"run", "verify", "ensure", "pass", "passes", "passing", "regression"})


def _tests_forbidden_by_prompt(prompt: PromptEvidence) -> bool:
    negative = {term.lower() for term in prompt.negative_terms}
    return bool({"test", "tests"} & negative)


def _config_requested(prompt: PromptEvidence) -> bool:
    terms = (set(prompt.surface_hints) | set(prompt.domain_terms) | {_normalize_term(symbol) for symbol in prompt.symbols_or_entities}) - set(prompt.negative_terms)
    config_synonyms = _active_synonym_groups(prompt).get("config", set()) - {"options"}
    return bool({"build", "ci", "config", "console", "entry", "package", "packaging", "point", "script", "workflow"} & terms or config_synonyms)


def _cli_prompt_requested(prompt: PromptEvidence) -> bool:
    terms = set(prompt.surface_hints) | set(prompt.domain_terms) | {_normalize_term(symbol) for symbol in prompt.symbols_or_entities}
    return bool({"cli", "command", "help", "usage"} & terms)


def _message_prompt_requested(prompt: PromptEvidence) -> bool:
    terms = set(prompt.domain_terms) | {_normalize_term(symbol) for symbol in prompt.symbols_or_entities}
    return bool({"message", "user message", "user-message", "error", "status", "success", "help", "text"} & terms)


def _behavior_prompt_requested(prompt: PromptEvidence) -> bool:
    terms = set(prompt.domain_terms) | set(prompt.behavior_terms) | {_normalize_term(symbol) for symbol in prompt.symbols_or_entities}
    concrete_terms = terms & BEHAVIOR_DOMAIN_TERMS
    action_terms = set(prompt.action_verbs) & {"fix", "improve", "update", "validate"}
    return bool(concrete_terms and (set(prompt.behavior_terms) or action_terms))


def _swift_screen_action_prompt(prompt: PromptEvidence) -> bool:
    terms = set(prompt.domain_terms) | set(prompt.surface_hints) | {_normalize_term(symbol) for symbol in prompt.symbols_or_entities}
    has_surface = bool(terms & {"screen", "screens", "surface", "ui", "view", "views"})
    has_action_goal = bool(terms & {"next", "today", "action", "plan", "priority", "important", "obvious"})
    return has_surface and has_action_goal


def _score_swift_screen_action_source(file: _FileEvidence, prompt: PromptEvidence) -> tuple[int, list[str], set[str], set[str]]:
    if not _swift_screen_action_prompt(prompt):
        return 0, [], set(), set()
    lower_path = file.path.lower().replace("\\", "/")
    if not lower_path.endswith(".swift"):
        return 0, [], set(), set()
    if any(term in lower_path for term in (".xcodeproj/", ".xcworkspace/", ".xcassets/", "/tests/", "devtools/", "frontierrisk/", "riskresolver", "minigame", "engine")):
        return -180, ["swift_screen_action:non_primary_surface_downranked"], set(), set()

    prompt_terms = {
        _normalize_term(term)
        for term in (
            list(prompt.domain_terms)
            + list(prompt.surface_hints)
            + list(prompt.symbols_or_entities)
        )
        if _normalize_term(term)
    }
    path_blob = " ".join(_split_identifier(file.path))
    content_terms = file.content_terms | file.symbol_terms | file.path_terms
    matched_terms = {
        term for term in prompt_terms
        if term not in {"screen", "screens", "surface", "view", "views", "make", "want"}
        and (_has_term(term, content_terms) or term in path_blob)
    }
    surface_source = (
        "/views/" in lower_path
        or "/viewmodels/" in lower_path
        or lower_path.endswith(("view.swift", "viewmodel.swift"))
        or "viewmodel" in lower_path
    )
    if not surface_source or not matched_terms:
        return 0, [], set(), set()

    score = 260 + min(360, 90 * len(matched_terms))
    signals = ["swift_screen_action_source"]
    if "/views/" in lower_path or lower_path.endswith("view.swift"):
        score += 160
        signals.append("swift_surface:view")
    if "/viewmodels/" in lower_path or "viewmodel" in lower_path:
        score += 150
        signals.append("swift_surface:viewmodel")
    if matched_terms & {"today", "plan", "action", "next"}:
        score += 180
        signals.append("swift_next_today_signal:" + ",".join(sorted(matched_terms & {"today", "plan", "action", "next"})))
    if matched_terms & {"homestead"}:
        score += 160
        signals.append("swift_domain_signal:homestead")
    signals.append("swift_prompt_terms:" + ",".join(sorted(matched_terms)[:6]))
    covered = matched_terms | ({"screen"} if "screen" in prompt_terms else set())
    return score, signals, covered, matched_terms


def _option_prompt_requested(prompt: PromptEvidence) -> bool:
    if prompt.option_flags or prompt.allowed_value_terms or prompt.default_fallback_terms:
        return True
    option_subject_terms = {
        "option", "options", "argument", "value", "values", "theme", "style",
        "profile", "mode", "format", "choice", "choices",
    }
    prompt_subjects = set(prompt.option_value_terms) | set(prompt.domain_terms)
    return bool(prompt_subjects & option_subject_terms)


def _concrete_option_terms(prompt: PromptEvidence) -> set[str]:
    terms: set[str] = set()
    for flag in prompt.option_flags:
        terms.update(_split_identifier(flag))
    prompt_terms = (
        set(prompt.domain_terms)
        | set(prompt.option_value_terms)
        | {_normalize_term(symbol) for symbol in prompt.symbols_or_entities}
    )
    for term in prompt_terms:
        normalized = _normalize_term(term)
        if normalized in OPTION_ENTITY_TERMS:
            terms.add(normalized)
    return {term for term in terms if term and term not in {"option", "options", "value", "values"}}


def _flag_declared_in_text(text: str, flag: str) -> bool:
    marker_re = re.compile(r"\b(?:click\.option|typer\.Option|add_argument|parser\.add_argument|click\.Choice)\b")
    for match in re.finditer(re.escape(flag), text):
        window = text[max(0, match.start() - 120): match.end() + 520]
        if marker_re.search(window):
            return True
    return False


def _extract_choices_values(text: str) -> list[str]:
    values: list[str] = []
    for body in re.findall(r"choices\s*=\s*\[([^\]]{1,240})\]", text, flags=re.IGNORECASE):
        values.extend(a or b for a, b in QUOTED_RE.findall(body))
    for body in re.findall(r"click\.Choice\s*\(\s*\[([^\]]{1,240})\]", text, flags=re.IGNORECASE):
        values.extend(a or b for a, b in QUOTED_RE.findall(body))
    return _dedupe(values)[:8]


def _extract_default_values(text: str) -> list[str]:
    values: list[str] = []
    for match in re.findall(r"default\s*=\s*(?:[\"']([^\"'\n]{1,80})[\"']|([A-Za-z0-9_.-]{1,80}))", text):
        values.append(match[0] or match[1])
    return _dedupe(values)[:8]


def _extract_relevant_default_values(text: str, concrete_terms: set[str], prompt_flags: list[str]) -> list[str]:
    values: list[str] = []
    anchors = set(concrete_terms) | set(prompt_flags)
    for match in re.finditer(r"default\s*=\s*(?:[\"']([^\"'\n]{1,80})[\"']|([A-Za-z0-9_.-]{1,80}))", text):
        window = text[max(0, match.start() - 420): match.end() + 220].lower()
        if not anchors or any(anchor.lower() in window for anchor in anchors):
            values.append(match.group(1) or match.group(2) or "")
    return _dedupe(values)[:8]


def _extract_option_block_default_values(text: str, flags: set[str]) -> list[str]:
    values: list[str] = []
    for flag in sorted(flags):
        for match in re.finditer(re.escape(flag), text):
            start = max(0, match.start() - 140)
            next_option = text.find("\n@click.option", match.end())
            next_def = text.find("\ndef ", match.end())
            end_candidates = [value for value in (next_option, next_def) if value != -1]
            end = min(end_candidates) if end_candidates else min(len(text), match.end() + 520)
            block = text[start:end]
            values.extend(_extract_default_values(block))
    return _dedupe(values)[:8]


def _has_option_use_site(text: str, term: str) -> bool:
    if not term:
        return False
    escaped = re.escape(term)
    patterns = (
        rf"\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*{escaped}\b",
        rf"\b{escaped}\s*=\s*[A-Za-z_][A-Za-z0-9_]*\b",
        rf"\b(?:Syntax|Console|Markdown|Theme)\s*\([\s\S]{{0,220}}\b{escaped}\b",
        rf"\b(?:code_theme|theme|style|format|mode|profile)\s*=\s*{escaped}\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _score_option_value_evidence(file: _FileEvidence, prompt: PromptEvidence) -> tuple[int, list[str], set[str], set[str]]:
    if not _option_prompt_requested(prompt):
        return 0, [], set(), set()

    score = 0
    signals: list[str] = []
    covered: set[str] = set()
    content_hits: set[str] = set()
    text = file.text
    lower = text.lower()
    concrete_terms = _concrete_option_terms(prompt)

    for flag in prompt.option_flags:
        if flag in file.option_flags or flag in text:
            if _flag_declared_in_text(text, flag):
                score += 340
                signals.append(f"option_decl:{flag}")
            else:
                score += 150
                signals.append(f"option_flag:{flag}")
            flag_terms = set(_split_identifier(flag))
            covered.update(flag_terms)
            content_hits.update(flag_terms)

    for flag in sorted(file.option_flags):
        flag_terms = set(_split_identifier(flag))
        if concrete_terms & flag_terms:
            if _flag_declared_in_text(text, flag):
                score += 280
                signals.append(f"option_decl:{flag}")
            else:
                score += 110
                signals.append(f"option_flag:{flag}")
            covered.update(concrete_terms & flag_terms)
            content_hits.update(concrete_terms & flag_terms)

    for term in sorted(concrete_terms):
        if _has_option_use_site(text, term):
            score += 180
            signals.append(f"option_use:{term}")
            covered.add(term)
            content_hits.add(term)

    choices_values = _extract_choices_values(text)
    choices_requested = bool(prompt.allowed_value_terms or {"choice", "choices", "values", "value"} & set(prompt.option_value_terms))
    if choices_requested and (
        choices_values
        or "choices=" in lower
        or "allowed values" in lower
        or "valid values" in lower
        or "must be one of" in lower
    ):
        score += 210
        signals.append("option_choices:" + (",".join(choices_values) if choices_values else "declared"))
        value_terms = {"allowed", "valid", "value", "values", "choice", "choices"}
        covered.update(value_terms & (set(prompt.allowed_value_terms) | set(prompt.option_value_terms) | set(prompt.domain_terms)))
        content_hits.update(value_terms)

    relevant_flags = {
        flag
        for flag in file.option_flags | set(prompt.option_flags)
        if concrete_terms & set(_split_identifier(flag)) or flag in prompt.option_flags
    }
    default_values = _extract_option_block_default_values(text, relevant_flags)
    if not default_values:
        default_values = _extract_relevant_default_values(text, concrete_terms, prompt.option_flags)
    default_requested = bool(prompt.default_fallback_terms or {"default"} & set(prompt.domain_terms))
    if default_values and (default_requested or _option_prompt_requested(prompt)):
        score += 130 if default_requested else 45
        signals.append("option_default:" + ",".join(default_values))
        if default_requested:
            covered.add("default")
            content_hits.add("default")

    if prompt.invalid_value_terms:
        marker_checks = (
            ("invalid", "invalid" in lower),
            ("unsupported", "unsupported" in lower),
            ("parser.error", "parser.error" in lower),
            ("on_error", "on_error" in lower),
            ("ClassNotFound", "ClassNotFound" in text),
            ("except", bool(re.search(r"\bexcept\b", text))),
            ("raise", bool(re.search(r"\braise\b", text))),
            ("ValueError", "ValueError" in text),
            ("BadParameter", "BadParameter" in text),
        )
        invalid_markers = [name for name, matched in marker_checks if matched]
        if invalid_markers:
            score += 165
            signals.append("option_value_evidence:" + ",".join(invalid_markers[:5]))
            covered.update(set(prompt.invalid_value_terms) & {"invalid", "unsupported", "error", "fail", "fails", "failed", "exception"})
            content_hits.update({"invalid", "unsupported", "error", "exception"} & (set(prompt.invalid_value_terms) | set(prompt.domain_terms)))
            if "ClassNotFound" in invalid_markers:
                signals.append("option_exception:ClassNotFound")
            error_handlers = [marker for marker in invalid_markers if marker in {"parser.error", "on_error"}]
            if error_handlers:
                signals.append("option_error_handler:" + ",".join(error_handlers))

    if prompt.default_fallback_terms:
        fallback_markers: list[str] = []
        if "fallback" in lower or "fall back" in lower or "falls back" in lower:
            fallback_markers.append("fallback")
        if re.search(r"\bexcept\b[\s\S]{0,220}\bdefault\b", text, flags=re.IGNORECASE):
            fallback_markers.append("except_default")
        if default_values:
            fallback_markers.append("default")
        if fallback_markers:
            score += 170
            signals.append("option_value_evidence:" + ",".join(_dedupe(fallback_markers)[:4]))
            covered.update(set(prompt.default_fallback_terms) & {"default", "fallback", "fall back", "falls back"})
            content_hits.update({"default", "fallback"})

    if "metavar=" in lower and concrete_terms:
        score += 50
        signals.append("option_metavar")

    return score, _dedupe(signals), covered, content_hits


def _score_bounded_synonym_evidence(file: _FileEvidence, prompt: PromptEvidence) -> tuple[int, list[str], set[str]]:
    active_groups = _active_synonym_groups(prompt)
    if not active_groups:
        return 0, [], set()

    score = 0
    signals: list[str] = []
    covered: set[str] = set()

    for group, prompt_terms in sorted(active_groups.items()):
        if group == "docs":
            if not _docs_synonym_requested(prompt) or not _is_docs_artifact_path(file):
                continue
        elif group == "config":
            if not _config_requested(prompt) or file.role != "config":
                continue
        elif group == "auth":
            if file.role in {"docs", "test"} or _is_helperish_path(file.path):
                continue

        group_terms = set(BOUNDED_SYNONYM_GROUPS[group])
        path_hits = sorted(term for term in group_terms if _has_term(term, file.path_terms))
        symbol_hits = sorted(term for term in group_terms if _has_term(term, file.symbol_terms))
        content_hits = sorted(term for term in group_terms if _has_term(term, file.content_terms))
        if group == "auth" and not (path_hits or symbol_hits):
            continue
        if not (path_hits or symbol_hits or content_hits):
            continue

        if path_hits:
            score += 70
            signals.append(f"bounded_synonym_path:{group}:{','.join(path_hits[:4])}")
        if symbol_hits:
            score += 64
            signals.append(f"bounded_synonym_symbol:{group}:{','.join(symbol_hits[:4])}")
        if content_hits and group in {"docs", "config"}:
            score += min(54, 22 + (len(content_hits) * 12))
            signals.append(f"bounded_synonym_content:{group}:{','.join(content_hits[:4])}")
        elif content_hits and (path_hits or symbol_hits):
            score += 12

        covered.update(prompt_terms)

    return score, _dedupe(signals), covered


def _is_cli_entrypoint(file: _FileEvidence) -> bool:
    text = file.text
    lower_path = file.path.lower()
    return (
        "argparse.ArgumentParser" in text
        or "click.command" in text
        or "typer.Typer" in text
        or "if __name__" in text and "__main__" in text and lower_path.startswith(("tools/", "scripts/", "bin/"))
        or "int main(" in text and ("Usage:" in text or "std::cout" in text or "std::cerr" in text)
        or lower_path.startswith(("tools/", "scripts/", "bin/")) and Path(lower_path).suffix in {".py", ".js", ".ts", ".sh"}
    )


def _is_runtime_node_without_cli_entrypoint(file: _FileEvidence) -> bool:
    lower_path = file.path.lower()
    text = file.text
    return (
        not _is_cli_entrypoint(file)
        and (
            lower_path.endswith("_node.py")
            or "rclpy" in text
            or "get_logger()" in text
            or "create_subscription(" in text
            or "create_publisher(" in text
        )
    )


def _message_surface_terms(file: _FileEvidence) -> set[str]:
    text = file.text.lower()
    terms: set[str] = set()
    if "usage:" in text or "argumentparser" in text or "parser.add_argument" in text or " help=" in text:
        terms.add("help")
    if "error" in text or "failed" in text or "missing" in text or "unsupported" in text or "raise " in text or "runtime_error" in text:
        terms.add("error")
    if (
        "success" in text
        or "status" in text
        or "created" in text
        or "written" in text
        or "wrote" in text
        or "summary written" in text
        or "std::cout" in text
        or "print(" in text
    ):
        terms.add("status")
    return terms


def _report_surface_without_prompt(file: _FileEvidence, prompt: PromptEvidence) -> bool:
    prompt_terms = set(prompt.domain_terms) | set(prompt.surface_hints)
    if prompt_terms & {"docs", "readme"}:
        return False
    # Distinguish genuine report/dashboard ARTIFACT-editing intent ("improve the
    # generated report output", "the html dashboard") from "report" used as a
    # runtime behavior verb ("failures are reported clearly"). Only real artifact
    # intent should protect report/dashboard/html files from demotion; for a
    # behavior/runtime prompt a bare "reported" must NOT keep report artifacts high.
    report_mention = bool(prompt_terms & {"report", "reports"})
    artifact_words = bool(prompt_terms & {
        "html", "dashboard", "output", "generate", "generated",
        "render", "rendered", "page", "visualization", "chart",
    })
    report_artifact_intent = (
        bool(prompt_terms & {"html", "dashboard"})
        or (report_mention and artifact_words)
        or (report_mention and not _behavior_prompt_requested(prompt))
    )
    if report_artifact_intent:
        return False
    lower_path = file.path.lower()
    return (
        "report" in lower_path
        or "dashboard" in lower_path
        or lower_path.endswith(".html")
        or "streamlit" in lower_path
    )


def _output_artifact_requested(prompt: PromptEvidence) -> bool:
    """True when the prompt genuinely asks to work on report/dashboard/output/data
    artifacts (so those surfaces should NOT be demoted for a behavior prompt).
    A bare 'reported'/'report' behavior verb does not count."""
    terms = set(prompt.domain_terms) | set(prompt.surface_hints)
    raw = prompt.raw_prompt.lower()
    if terms & {"html", "dashboard"}:
        return True
    if re.search(r"\b(?:generated|diagnostic|html|evidence|visual)?\s*report\s+(?:output|template|page|view|presentation)\b", raw):
        return True
    if re.search(r"\b(?:generated|rendered|report|dashboard)\s+output\b", raw):
        return True
    if re.search(r"\b(?:users?|operators?)\s+can\s+understand\b", raw) and terms & {"report", "output", "dashboard"}:
        return True
    if terms & {"output", "generate", "generated", "render", "rendered", "page",
                "visualization", "chart", "png", "evidence", "demo", "data", "sample", "samples"}:
        return True
    if (terms & {"report", "reports"}) and not _behavior_prompt_requested(prompt):
        return True
    return False


def _report_artifact_requested(prompt: PromptEvidence) -> bool:
    if _docs_artifact_requested(prompt):
        return False
    if _cli_prompt_requested(prompt) and _message_prompt_requested(prompt):
        return False
    terms = set(prompt.domain_terms) | set(prompt.surface_hints)
    raw = prompt.raw_prompt.lower()
    return bool(
        _output_artifact_requested(prompt)
        and (
            terms & {"report", "reports", "dashboard", "html", "output", "generated", "render", "rendered", "evidence"}
            or re.search(r"\b(?:diagnostic report|report output|html report|generated report|dashboard|report template|render output)\b", raw)
        )
    )


def _is_output_or_evidence_generator_path(file: _FileEvidence) -> bool:
    """Path/name-based detection of report/dashboard/evidence/demo output generators
    (independent of incidental 'result' text they may read)."""
    lower = file.path.lower()
    name = Path(lower).name
    return (
        "report" in lower
        or "dashboard" in lower
        or "streamlit" in lower
        or "evidence" in lower
        or "render" in name
        or "png" in name
        or lower.endswith(".html")
        or name.startswith(("build_html", "create_demo", "generate_", "render_"))
    )


def _data_generation_surface_without_prompt(file: _FileEvidence, prompt: PromptEvidence) -> bool:
    prompt_terms = set(prompt.domain_terms) | set(prompt.surface_hints)
    if prompt_terms & {"data", "generate", "generated", "sample", "samples", "telemetry"}:
        return False
    lower_path = file.path.lower()
    return (
        "generate_sample_data" in lower_path
        or "/sample_data/" in lower_path
        or lower_path.startswith("sample_data/")
        or (lower_path.startswith("results/") and lower_path.endswith(".json"))
    )


def _verification_script_without_prompt(file: _FileEvidence, prompt: PromptEvidence) -> bool:
    prompt_terms = set(prompt.domain_terms) | set(prompt.surface_hints) | {_normalize_term(symbol) for symbol in prompt.symbols_or_entities}
    if prompt_terms & {"build", "ci", "config", "script", "docker"}:
        return False
    lower_path = file.path.lower()
    if not lower_path.startswith(("scripts/", ".github/workflows/")):
        return False
    terms = file.path_terms | file.content_terms
    return bool({"regression", "test", "tests", "docker", "check"} & terms)


def _file_prompt_domain_overlap(file: _FileEvidence, prompt: PromptEvidence) -> set[str]:
    combined_terms = file.path_terms | file.content_terms | file.symbol_terms
    return {
        term
        for term in prompt.domain_terms
        if term in BEHAVIOR_DOMAIN_TERMS and _has_term(term, combined_terms)
    }


def _file_behavior_terms(file: _FileEvidence) -> set[str]:
    text = file.text.lower()
    path_terms = file.path_terms | file.symbol_terms
    content_terms = file.content_terms | file.symbol_terms
    terms: set[str] = set()
    has_error_word = bool({"error", "failure", "failed", "missing"} & content_terms)
    if re.search(r"\b(?:raise|except|catch|throw)\b", text) or has_error_word:
        terms.add("error_handling")
    if _has_term("timeout", content_terms) and (
        re.search(r"\b(?:if|raise|except|catch|throw|status|result|return)\b", text)
        or {"failure", "failed", "error"} & content_terms
    ):
        terms.add("timeout_handling")
    if {"status", "result", "diagnostic", "failure", "message"} & content_terms:
        terms.add("result_construction")
    if {"classify", "classification", "classified"} & content_terms:
        terms.add("classification")
    if {"calculate", "calculation", "compute", "computed", "total", "discount", "tax", "pricing"} & content_terms:
        terms.add("calculation")
    if {"run", "execute", "executed", "process", "processed", "replay"} & content_terms or {"runner"} & path_terms:
        terms.add("execution")
    if {"write", "written", "generate", "generated", "output", "csv", "folder"} & content_terms:
        terms.add("output_generation")
    if {"emit", "publish", "publisher", "subscription"} & content_terms:
        terms.add("runtime_event")
    return terms


def _scenario_data_surface_for_behavior_prompt(file: _FileEvidence, prompt: PromptEvidence) -> bool:
    if not _behavior_prompt_requested(prompt):
        return False
    if _cli_prompt_requested(prompt) or _message_prompt_requested(prompt):
        return False
    prompt_terms = set(prompt.domain_terms) | set(prompt.surface_hints)
    if prompt_terms & {"scenario", "data", "load", "loading", "fixture", "fixtures"}:
        return False
    lower_path = file.path.lower()
    terms = file.path_terms | file.content_terms | file.symbol_terms
    data_surface = (
        "scenario_loader" in lower_path
        or "fixtures/" in lower_path
        or bool({"loader", "loading", "parse", "parser", "yaml", "fixture", "fixtures", "definition", "definitions"} & terms)
    )
    behavior_surface = bool({"runner", "handler", "service", "writer", "result", "diagnostic", "pricing"} & file.path_terms)
    return data_surface and not behavior_surface


def _runtime_node_support_for_behavior_prompt(file: _FileEvidence, prompt: PromptEvidence) -> bool:
    if not _behavior_prompt_requested(prompt) or not _is_runtime_node_without_cli_entrypoint(file):
        return False
    # A runtime node that actually implements the result/timeout/runtime behavior
    # under fix is an edit target, not mere support context.
    if _file_behavior_terms(file) & {"timeout_handling", "result_construction", "runtime_event"} and _file_prompt_domain_overlap(file, prompt):
        return False
    prompt_terms = set(prompt.domain_terms) | set(prompt.surface_hints) | {_normalize_term(symbol) for symbol in prompt.symbols_or_entities}
    return not bool(prompt_terms & {"bridge", "node", "ros", "publish", "publisher", "subscription"})


def _score_file(file: _FileEvidence, prompt: PromptEvidence) -> tuple[int, list[str], set[str]]:
    score = 0
    signals: list[str] = []
    covered: set[str] = set()
    content_hit_terms: set[str] = set()

    for explicit in prompt.explicit_paths:
        if file.path == explicit or file.path.endswith("/" + explicit) or explicit.endswith("/" + file.path):
            score += 1000
            signals.append(f"explicit_path:{explicit}")
            covered.update(_split_identifier(explicit))

    for symbol in prompt.symbols_or_entities:
        symbol_norm = _normalize_term(symbol)
        exact_symbol = any(_normalize_term(item) == symbol_norm for item in file.symbols)
        if exact_symbol:
            score += 320
            signals.append(f"symbol:{symbol}")
            covered.update(_split_identifier(symbol))
            content_hit_terms.update(_split_identifier(symbol))
        elif _has_term(symbol, file.symbol_terms):
            score += 180
            signals.append(f"symbol_term:{symbol}")
            covered.update(_split_identifier(symbol))
            content_hit_terms.update(_split_identifier(symbol))
        elif _has_term(symbol, file.content_terms):
            score += 90
            signals.append(f"content:{symbol_norm}")
            covered.update(_split_identifier(symbol))
            content_hit_terms.update(_split_identifier(symbol))
        elif _has_term(symbol, file.path_terms):
            score += 45
            signals.append(f"path:{symbol_norm}")
            covered.update(_split_identifier(symbol))

    for literal in prompt.quoted_literals:
        if _literal_in_file(literal, file):
            score += 260
            signals.append(f'quoted_literal:"{literal}"')
            covered.update(_split_identifier(literal))
            content_hit_terms.update(_split_identifier(literal))

    option_score, option_signals, option_covered, option_content_hits = _score_option_value_evidence(file, prompt)
    if option_score:
        score += option_score
        signals.extend(option_signals)
        covered.update(option_covered)
        content_hit_terms.update(option_content_hits)

    swift_score, swift_signals, swift_covered, swift_content_hits = _score_swift_screen_action_source(file, prompt)
    if swift_score:
        score += swift_score
        signals.extend(swift_signals)
        covered.update(swift_covered)
        content_hit_terms.update(swift_content_hits)

    synonym_score, synonym_signals, synonym_covered = _score_bounded_synonym_evidence(file, prompt)
    if synonym_score:
        score += synonym_score
        signals.extend(synonym_signals)
        covered.update(synonym_covered)

    for term in prompt.domain_terms:
        if _has_term(term, file.content_terms):
            score += 50
            signals.append(f"content:{term}")
            covered.add(term)
            content_hit_terms.add(term)
        if _has_term(term, file.path_terms):
            score += 38
            signals.append(f"path:{term}")
            covered.add(term)
        if _has_term(term, file.symbol_terms):
            score += 60
            signals.append(f"symbol_term:{term}")
            covered.add(term)
            content_hit_terms.add(term)

    for term in prompt.domain_terms:
        for value in file.strings:
            if _has_term(term, _tokens_from_text(value)):
                score += 18
                signals.append(f"string:{term}")
                content_hit_terms.add(term)
                break
        for value in file.routes:
            if _has_term(term, _tokens_from_text(value)):
                score += 22
                signals.append(f"route:{term}")
                content_hit_terms.add(term)
                break

    if len(content_hit_terms) >= 3:
        clustered = ",".join(sorted(content_hit_terms)[:6])
        score += min(140, 55 + (len(content_hit_terms) * 18))
        signals.append(f"content_cluster:{clustered}")

    if _docs_artifact_requested(prompt) and _is_docs_artifact_path(file):
        doc_terms = file.path_terms | file.content_terms | file.symbol_terms
        setup_terms = {"setup", "install", "instructions", "instruction", "troubleshooting", "diagnostic", "regression", "run", "output", "user", "guide", "readme", "docs"}
        matched_doc_terms = sorted(term for term in setup_terms if _has_term(term, doc_terms))
        if matched_doc_terms or file.role == "docs":
            lower_doc_path = file.path.lower()
            score += 360 + min(180, 28 * len(matched_doc_terms))
            if lower_doc_path == "readme.md" or lower_doc_path.startswith("docs/"):
                score += 330
                signals.append("artifact_surface:canonical_docs")
            elif (
                lower_doc_path.startswith("portfolio_evidence/")
                or "/raw_terminal_logs/" in lower_doc_path
                or "/captions/" in lower_doc_path
                or "manual_capture" in lower_doc_path
                or "evidence" in lower_doc_path
            ):
                score -= 360
                signals.append("artifact_surface:evidence_docs_downranked")
            signals.append("artifact_surface:docs_setup")
            if matched_doc_terms:
                signals.append("artifact_terms:" + ",".join(matched_doc_terms[:8]))
            covered.update({"docs", "instructions", "setup"})
            covered.update(matched_doc_terms)
            content_hit_terms.update(matched_doc_terms)

    if _report_artifact_requested(prompt) and _is_output_or_evidence_generator_path(file):
        report_terms = file.path_terms | file.content_terms | file.symbol_terms
        artifact_terms = {"report", "dashboard", "html", "output", "generated", "render", "evidence", "diagnostic", "actuator", "failure", "failed", "failures", "result"}
        matched_artifact_terms = sorted(term for term in artifact_terms if _has_term(term, report_terms))
        if matched_artifact_terms:
            score += 430 + min(220, 30 * len(matched_artifact_terms))
            signals.append("artifact_surface:report_output")
            signals.append("artifact_terms:" + ",".join(matched_artifact_terms[:8]))
            covered.update({"report", "output"})
            covered.update(matched_artifact_terms)
            content_hit_terms.update(matched_artifact_terms)

    if _behavior_prompt_requested(prompt):
        behavior_terms = _file_behavior_terms(file)
        domain_overlap = _file_prompt_domain_overlap(file, prompt)
        if behavior_terms and domain_overlap:
            behavior_boost = min(260, 60 + (len(behavior_terms) * 32) + (len(domain_overlap) * 18))
            score += behavior_boost
            signals.append("behavior_source:" + ",".join(sorted(behavior_terms)[:6]))
            covered.update(domain_overlap)
            covered.add("behavior")
            if "result_construction" in behavior_terms and set(prompt.behavior_terms) & {"report", "reporting"}:
                covered.update({"report", "reported", "reporting"})
            content_hit_terms.update(domain_overlap)

    for hint in prompt.surface_hints:
        role_match = (
            hint in {"docs", "readme"} and file.role == "docs"
            or hint in {"test"} and file.role == "test"
            or hint in {"config", "build"} and file.role == "config"
            or hint in {"api", "endpoint", "route"} and (_has_term(hint, file.path_terms) or _has_term(hint, file.content_terms))
            or hint in {"screen", "button", "view"} and (_has_term(hint, file.path_terms) or _has_term(hint, file.content_terms))
            or hint in {"cli", "command"} and (_has_term(hint, file.path_terms) or _has_term(hint, file.content_terms))
        )
        if role_match:
            score += 25
            signals.append(f"role:{hint}")
            covered.add(hint)

    if file.role == "docs" and _docs_requested(prompt):
        score += 90
        signals.append("role:docs")
        covered.update({"docs"})
    if file.role == "test" and _tests_requested(prompt):
        score += 90
        signals.append("role:test")
        covered.update({"test"})
    elif file.role == "test" and _tests_requested_for_verification(prompt):
        score += 35
        signals.append("role:test_verification")
        covered.update({"test", "regression"})
    if file.role == "config" and _config_requested(prompt):
        score += 100
        signals.append("role:config")
        covered.update({"config"})

    negative_set = set(prompt.negative_terms)
    if file.role == "test" and {"test", "tests"} & negative_set and not _tests_requested_for_verification(prompt):
        score -= 700
        signals.append("negative_constraint:tests_downranked")
    if file.role == "docs" and {"doc", "docs", "readme"} & negative_set:
        score -= 180
        signals.append("negative_constraint:docs_downranked")
    if file.role == "config" and {"config", "packaging", "package"} & negative_set:
        score -= 180
        signals.append("negative_constraint:config_downranked")

    if file.role == "test" and not _tests_requested(prompt) and not _tests_requested_for_verification(prompt):
        score -= 35
        signals.append("role:test_downranked")
    if file.role == "docs" and not _docs_requested(prompt):
        score -= 35
        signals.append("role:docs_downranked")
        direct_option_doc_evidence = _option_prompt_requested(prompt) and any(
            signal.startswith(("option_flag:", "option_decl:", "option_value_evidence:", "option_default:", "option_choices:"))
            for signal in signals
        )
        if _cli_prompt_requested(prompt) and not direct_option_doc_evidence:
            score -= 320
            signals.append("role:docs_downranked_for_cli_prompt")
        elif _cli_prompt_requested(prompt) and direct_option_doc_evidence:
            score += 160
            signals.append("option_docs_support_evidence")
    if file.role == "config" and not _config_requested(prompt):
        score -= 30
        signals.append("role:config_downranked")
    if file.role == "source" and _docs_requested(prompt) and not (
        any(signal.startswith(("explicit_path:", "symbol:", "quoted_literal:")) for signal in signals)
        or len(content_hit_terms) >= 3
    ):
        score -= 45
        signals.append("role:source_downranked_for_docs_prompt")

    cli_prompt = _cli_prompt_requested(prompt)
    if cli_prompt and _is_cli_entrypoint(file):
        score += 360
        signals.append("cli_entrypoint")
        covered.add("cli")
        content_hit_terms.add("cli")
    if _message_prompt_requested(prompt):
        message_terms = _message_surface_terms(file)
        requested_message_terms = message_terms & set(prompt.domain_terms)
        if message_terms:
            boost = 45 * len(message_terms)
            if "help" in requested_message_terms:
                boost += 70
            if "error" in requested_message_terms:
                boost += 50
            if {"status", "success"} & set(prompt.domain_terms) and "status" in message_terms:
                boost += 50
            score += min(300, boost)
            signals.append("message_surface:" + ",".join(sorted(message_terms)))
            covered.update(message_terms)
            content_hit_terms.update(message_terms)
    if cli_prompt and _is_runtime_node_without_cli_entrypoint(file):
        score -= 520
        signals.append("runtime_node_without_cli_entrypoint")
    elif (
        cli_prompt
        and file.role == "source"
        and not _is_cli_entrypoint(file)
        and not _config_requested(prompt)
        and not _has_term("cli", file.path_terms)
        and not any(signal.startswith(("explicit_path:", "symbol:", "quoted_literal:")) for signal in signals)
    ):
        score -= 620 if _message_prompt_requested(prompt) else 220
        signals.append("source_without_cli_entrypoint_for_cli_prompt")
    if _report_surface_without_prompt(file, prompt):
        score -= 900
        signals.append("report_surface_without_prompt")
    if cli_prompt and _message_prompt_requested(prompt) and _data_generation_surface_without_prompt(file, prompt):
        score -= 900
        signals.append("data_generation_surface_without_prompt")
    if _verification_script_without_prompt(file, prompt):
        score -= 420
        signals.append("verification_script_without_prompt")
    if _scenario_data_surface_for_behavior_prompt(file, prompt):
        score -= 180
        signals.append("scenario_data_surface_downranked_for_behavior_prompt")
    if _runtime_node_support_for_behavior_prompt(file, prompt):
        score -= 120
        signals.append("runtime_node_support_for_behavior_prompt")
    # Runtime/behavior fixes belong in executable behavior source, not in docs,
    # generated data/result artifacts, or output/evidence generators. For a
    # behavior prompt that does not ask for docs/data/report output, demote those
    # non-behavior surfaces and boost executable source that actually implements
    # result/timeout/runtime behavior.
    if (
        _behavior_prompt_requested(prompt)
        and not _docs_requested(prompt)
        and not _output_artifact_requested(prompt)
        and not _cli_prompt_requested(prompt)
        and not _message_prompt_requested(prompt)
    ):
        lower_behavior_path = file.path.lower()
        has_direct = any(sig.startswith(("explicit_path:", "symbol:", "quoted_literal:")) for sig in signals)
        file_behavior = _file_behavior_terms(file)
        runtime_behavior = bool(file_behavior & {"timeout_handling", "result_construction", "runtime_event"})
        is_output_generator = _is_output_or_evidence_generator_path(file)
        is_docs_surface = file.role == "docs" or lower_behavior_path.endswith((".md", ".rst"))
        is_data_artifact = lower_behavior_path.endswith((".json", ".csv")) and (
            lower_behavior_path.startswith(("results/", "sample_data/"))
            or "/results/" in lower_behavior_path
            or "/sample_data/" in lower_behavior_path
            or lower_behavior_path.endswith(("_result.json", "_results.json"))
        )
        if not has_direct and (is_docs_surface or is_data_artifact or is_output_generator):
            score -= 320
            signals.append("non_behavior_surface_downranked_for_behavior_prompt")
        elif runtime_behavior and _file_prompt_domain_overlap(file, prompt) and lower_behavior_path.endswith((".py", ".cpp", ".cc", ".c", ".rs", ".go")):
            score += 180
            signals.append("runtime_behavior_source_boost")

    if _is_generic_path(file.path) and not any(
        sig.startswith(("symbol:", "quoted_literal:", "content_cluster:")) for sig in signals
    ) and len(content_hit_terms) < 2:
        score -= 40
        signals.append("generic_filename_without_content_evidence")

    path_parts = set(file.path.lower().split("/"))
    if path_parts & {"util", "utils", "helper", "helpers"} and not any(
        sig.startswith(("explicit_path:", "symbol:", "quoted_literal:", "content_cluster:"))
        for sig in signals
    ) and not content_hit_terms:
        score -= 55
        signals.append("generic_helper_without_prompt_content")

    return score, _dedupe(signals), covered


def _confidence_for_file(score: int, signals: list[str]) -> str:
    if score >= 320 and any(sig.startswith(("explicit_path:", "symbol:", "quoted_literal:")) for sig in signals):
        return "high"
    if score >= 120:
        return "medium"
    return "low"


def _result_confidence(files: list[LocatedFile], covered: set[str], important: list[str]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not files:
        return "low", ["no_files_matched_prompt_evidence"]
    important_set = {_normalize_term(term) for term in important if _normalize_term(term)}
    coverage_ratio = len(covered) / max(1, len(important_set))
    top_terms = _terms_covered_by_file(files[0], list(important_set))
    top_ratio = len(top_terms) / max(1, len(important_set))
    top_gap = files[0].score - files[1].score if len(files) > 1 else files[0].score
    if len(files) > 1 and top_gap < 60:
        reasons.append("top_score_gap_small")
    if coverage_ratio >= 0.45 and top_ratio < min(0.6, coverage_ratio):
        reasons.append("terms_split_across_many_files")
    if all(_is_surface_only(file) for file in files[: min(3, len(files))]):
        reasons.append("only_surface_matches")
    if _is_generic_path(files[0].path) and not _has_transportable_content_evidence(files[0]):
        reasons.append("generic_filename_without_content_evidence")
    strong = _has_transportable_content_evidence(files[0])
    clustered_strong = [
        file for file in files[: min(4, len(files))]
        if any(sig.startswith("content_cluster:") for sig in file.matched_signals)
    ]
    if (
        coverage_ratio >= 0.6
        and len(clustered_strong) >= 2
        and files[0].score >= 450
        and not any(reason in reasons for reason in {"only_surface_matches", "generic_filename_without_content_evidence"})
    ):
        return "high", reasons
    if files[0].score >= 500 and any(sig.startswith("explicit_path:") for sig in files[0].matched_signals):
        return "high", reasons
    if coverage_ratio >= 0.65 and top_ratio >= 0.5 and strong and (len(files) == 1 or top_gap >= 80):
        return "high", reasons
    if (
        len(files) > 1
        and not any(_has_high_value_signal(file) for file in files[: min(3, len(files))])
        and any(reason in reasons for reason in {"top_score_gap_small", "terms_split_across_many_files"})
    ):
        return "low", reasons
    if coverage_ratio >= 0.35 or strong:
        if not reasons and len(files) > 1 and top_ratio < coverage_ratio:
            reasons.append("terms_split_across_many_files")
        return "medium", reasons
    if not reasons:
        reasons.append("only_surface_matches" if _is_surface_only(files[0]) else "matches_mostly_weak_path_or_role_evidence")
    return "low", reasons


# Severity weights for ambiguity reasons that genuinely undermine a confident
# single-target locate. Used to reconcile the confidence grade with the full set
# of ambiguity signals (previously confidence was graded before most reasons were
# even appended, so broad prompts reported "high" alongside heavy ambiguity).
_AMBIGUITY_SEVERITY = {
    "only_surface_matches": 3,
    "generic_filename_without_content_evidence": 3,
    "test_only_direct_evidence": 3,
    "terms_split_across_many_files": 2,
    "top_score_gap_small": 1,
    "dependency_cluster_split": 1,
    "primary_imports_unranked_dependency": 1,
    "multiple_related_helpers": 3,
    "proximity_only_support": 1,
    "result hit max_files cap": 1,
}


def _calibrate_confidence(
    base: str,
    ambiguity: list[str],
    files: list[LocatedFile],
    important_set: set[str],
) -> tuple[str, bool]:
    """Downgrade the base confidence when accumulated ambiguity reasons show real
    uncertainty. Returns (calibrated_confidence, downgraded?). Strong direct
    evidence (explicit path / quoted literal) with a clear score gap earns
    confidence back so precise locates are not over-penalized."""
    if base == "low" or not files:
        return base, False
    severity = sum(_AMBIGUITY_SEVERITY.get(reason, 0) for reason in set(ambiguity))
    uncovered = [r for r in ambiguity if r.startswith("uncovered_core_terms:")]
    core_count = max(1, len(important_set))
    uncovered_ratio = len(uncovered) / core_count
    if uncovered_ratio >= 0.5:
        severity += 2
    elif uncovered_ratio >= 0.34:
        severity += 1
    top = files[0]
    strong_direct = any(sig.startswith(("explicit_path:", "quoted_literal:")) for sig in top.matched_signals)
    gap_ok = len(files) < 2 or (files[0].score - files[1].score) >= 80
    if strong_direct and gap_ok:
        severity = max(0, severity - 3)

    if base == "high":
        if severity >= 9:
            return "low", True
        if severity >= 3:
            return "medium", True
        return "high", False
    # base == "medium"
    if severity >= 6:
        return "low", True
    return "medium", False


def _relation_signal_for_candidate(relation: FileRelation, anchor_path: str) -> str:
    if relation.relation == "imports":
        return f"imported_by:{anchor_path}"
    if relation.relation == "imported_by":
        return f"imports:{anchor_path}"
    if relation.relation == "adjacent_test":
        return f"adjacent_test:{anchor_path}"
    if relation.relation == "adjacent_source":
        return f"adjacent_source:{anchor_path}"
    if relation.relation == "same_stem":
        return f"same_stem:{_stem_key(anchor_path)}"
    if relation.relation == "same_directory":
        return f"same_directory_with:{anchor_path}"
    if relation.relation in {"route_helper", "component_state_helper"}:
        return f"{relation.relation}:{anchor_path}"
    return f"proximity_to_primary:{anchor_path}"


def _direct_anchor_paths(scored: dict[str, tuple[int, list[str], set[str]]]) -> list[str]:
    anchors: list[LocatedFile] = []
    for path, (score, signals, _) in scored.items():
        if score <= 0 or not signals:
            continue
        located = LocatedFile(path=path, score=score, role="", confidence="", matched_signals=signals)
        if _has_transportable_content_evidence(located) or score >= 150:
            anchors.append(located)
    anchors.sort(key=lambda file: (-file.score, file.path))
    return [file.path for file in anchors[:5]]


def _apply_proximity_boosts(
    scored: dict[str, tuple[int, list[str], set[str]]],
    relations: list[FileRelation],
    anchors: list[str],
) -> set[str]:
    proximity_only_paths: set[str] = set()
    anchor_set = set(anchors)
    relation_candidates: dict[str, list[FileRelation]] = {anchor: [] for anchor in anchors}
    for relation in relations:
        if relation.source in anchor_set:
            relation_candidates[relation.source].append(relation)

    for anchor_path, grouped in relation_candidates.items():
        grouped.sort(
            key=lambda relation: (
                -relation.strength,
                -(scored.get(relation.target, (0, [], set()))[0]),
                relation.target,
            )
        )
        for relation in grouped[:4]:
            current_score, current_signals, covered = scored.get(relation.target, (0, [], set()))
            had_direct = any(
                not signal.startswith(("negative_constraint:", "role:")) and not _is_proximity_signal(signal)
                for signal in current_signals
            )
            boost = relation.strength
            if not had_direct:
                boost = max(28, boost - 16)
                proximity_only_paths.add(relation.target)
            signal = _relation_signal_for_candidate(relation, anchor_path)
            current_signals.extend([signal, f"proximity_to_primary:{anchor_path}"])
            scored[relation.target] = (current_score + boost, _dedupe(current_signals), covered)
    return proximity_only_paths


def _selected_dependency_relations(relations: list[FileRelation], selected_paths: set[str]) -> list[FileRelation]:
    compact: list[FileRelation] = []
    for relation in relations:
        if relation.source in selected_paths and relation.target in selected_paths:
            compact.append(relation)
    compact.sort(key=lambda relation: (-relation.strength, relation.source, relation.target, relation.relation))
    return compact[:24]


def locate_files(repo_root: Path, prompt: str, *, max_files: int = 8, inventory_paths: list[str] | None = None) -> LocateResult:
    repo_root = Path(repo_root)
    evidence = extract_prompt_evidence(prompt)

    file_evidences: list[_FileEvidence] = []
    for path in _iter_repo_files(repo_root, inventory_paths):
        file = _file_evidence(repo_root, path)
        if file is None:
            continue
        file_evidences.append(file)
    evidence = _apply_typo_normalization(evidence, file_evidences)
    important_terms = _important_terms(evidence)

    direct_scores: dict[str, tuple[int, list[str], set[str]]] = {}
    file_by_path = {file.path: file for file in file_evidences}
    for file in file_evidences:
        direct_scores[file.path] = _score_file(file, evidence)

    relation_degraded_reasons: list[str] = []
    dependency_relations = _build_file_relations(
        file_evidences,
        important_terms,
        degraded_reasons=relation_degraded_reasons,
    )
    anchor_paths = _direct_anchor_paths(direct_scores)
    proximity_only_paths = _apply_proximity_boosts(direct_scores, dependency_relations, anchor_paths)

    scored: list[tuple[LocatedFile, set[str]]] = []
    for file in file_evidences:
        score, signals, covered = direct_scores[file.path]
        if score <= 0 or not signals:
            continue
        located = LocatedFile(
            path=file.path,
            score=score,
            role=file.role,
            confidence=_confidence_for_file(score, signals),
            matched_signals=signals,
        )
        scored.append((located, covered))

    scored.sort(key=lambda item: (-item[0].score, item[0].path))
    selected = scored[:max_files]
    files = [item[0] for item in selected]

    covered_terms: set[str] = set()
    for _, covered in selected:
        covered_terms.update(covered)
    normalized_important = {_normalize_term(term) for term in important_terms}
    covered_prompt_terms = sorted(term for term in normalized_important if _has_term(term, covered_terms))
    uncovered_prompt_terms = sorted(normalized_important - set(covered_prompt_terms))

    verification: list[LocatedFile] = []
    primary: list[LocatedFile] = []
    support: list[LocatedFile] = []
    cli_message_prompt = _cli_prompt_requested(evidence) and _message_prompt_requested(evidence)
    for file in files:
        primary_evidence = (
            _has_transportable_content_evidence(file)
            or _has_bounded_synonym_identity_evidence(file)
        ) and not _is_surface_only(file)
        requested_role_evidence = _has_direct_prompt_evidence(file) and not _is_surface_only(file)
        near_top = file.score >= max(files[0].score * 0.72, files[0].score - 120)
        if file.role == "test" and _tests_requested(evidence):
            if primary_evidence or requested_role_evidence:
                primary.append(file)
            else:
                verification.append(file)
        elif file.role == "test":
            verification.append(file)
        elif file.role == "docs" and _docs_requested(evidence) and requested_role_evidence and near_top:
            primary.append(file)
        elif file.role == "config" and _config_requested(evidence) and requested_role_evidence and near_top:
            primary.append(file)
        elif (
            cli_message_prompt
            and file.role == "source"
            and primary_evidence
            and file.score >= 520
            and "cli_entrypoint" in file.matched_signals
            and any(signal.startswith("message_surface:") for signal in file.matched_signals)
        ):
            primary.append(file)
        elif primary_evidence and (not primary or near_top):
            primary.append(file)
        else:
            support.append(file)

    # Keep generic helper files out of primary unless they have strong evidence.
    demoted: list[LocatedFile] = []
    kept_primary: list[LocatedFile] = []
    for file in primary:
        generic_reusable = Path(file.path).name.lower() in {"button.ts", "button.tsx", "handler.py", "index.py", "index.ts", "index.tsx"}
        if generic_reusable and not _has_transportable_content_evidence(file):
            demoted.append(file)
        else:
            kept_primary.append(file)
    primary = kept_primary
    if not primary and files:
        support_paths = {file.path for file in support}
        verification_paths = {file.path for file in verification}
        fallback = next(
            (
                file
                for file in files
                if file.path not in support_paths | verification_paths
                and _has_transportable_content_evidence(file)
                and not _is_surface_only(file)
            ),
            None,
        )
        if fallback is not None:
            primary = [fallback]
    support = demoted + support

    confidence, ambiguity = _result_confidence(files, set(covered_prompt_terms), important_terms)
    selected_paths = {file.path for file in files}
    selected_relations = _selected_dependency_relations(dependency_relations, selected_paths)
    proximity_selected = [file for file in files if file.path in proximity_only_paths or (_has_proximity_signal(file) and not _has_direct_prompt_evidence(file))]
    if proximity_selected:
        ambiguity.append("proximity_only_support")
    if len([file for file in support if _has_proximity_signal(file)]) > 1:
        ambiguity.append("multiple_related_helpers")
    if selected_relations and any(reason in {"terms_split_across_many_files", "top_score_gap_small"} for reason in ambiguity):
        ambiguity.append("dependency_cluster_split")
    selected_dependency_targets = {relation.target for relation in selected_relations}
    for relation in dependency_relations:
        if relation.source in anchor_paths and relation.relation == "imports" and relation.target not in selected_dependency_targets and relation.target in file_by_path:
            ambiguity.append("primary_imports_unranked_dependency")
            break
    if primary and all(file.role == "test" for file in primary) and any(file.role != "test" for file in files):
        ambiguity.append("test_only_direct_evidence")
    if uncovered_prompt_terms:
        ambiguity.extend(f"uncovered_core_terms:{term}" for term in uncovered_prompt_terms)
    if len(files) >= max_files:
        ambiguity.append("result hit max_files cap")

    # Reconcile the confidence grade with the FULL ambiguity set (many reasons are
    # appended above, after the initial grade). Broad prompts with heavy ambiguity
    # no longer report "high".
    important_set = {_normalize_term(term) for term in important_terms if _normalize_term(term)}
    confidence, _downgraded = _calibrate_confidence(confidence, ambiguity, files, important_set)
    if _downgraded:
        ambiguity.append("confidence_downgraded_by_ambiguity")

    return LocateResult(
        primary_files=primary,
        support_files=support,
        verification_files=verification,
        confidence=confidence,
        covered_prompt_terms=covered_prompt_terms,
        uncovered_prompt_terms=uncovered_prompt_terms,
        ambiguity_reasons=_dedupe(ambiguity),
        dependency_relations=selected_relations,
        typo_normalizations=evidence.typo_normalizations,
        relation_degraded_reasons=_dedupe(relation_degraded_reasons),
        metadata={
            "context_selection_mode": "normal_locator",
            "relation_degraded_reasons": _dedupe(relation_degraded_reasons),
        },
    )
