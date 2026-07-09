from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import time


SOURCE_EXTENSIONS = {
    ".py", ".swift", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go",
    ".java", ".kt", ".ex", ".exs", ".php", ".rb", ".tf", ".c", ".cpp", ".h",
    ".hpp", ".cs", ".zig", ".hs", ".dart", ".vue", ".svelte", ".astro",
}
DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc", ".mdx"}
PACKAGE_MANIFEST_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "package.json", "cargo.toml",
    "go.mod", "package.swift", "pubspec.yaml", "gemfile", "pom.xml",
    "build.gradle", "build.gradle.kts",
}
WORKFLOW_NAMES = {
    "makefile", "justfile", "noxfile.py", "tox.ini", ".pre-commit-config.yaml",
    "jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml",
}
TEST_PATTERNS = (
    re.compile(r"(^|/)(tests?|testing|__tests__|integration_test|test_driver)(/|$)", re.I),
    re.compile(r"(^|/)[^/]+(_test|test|tests)\.(py|go|rs|swift|kt|java|cs|zig|hs)$", re.I),
    re.compile(r"(^|/)[^/]+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$", re.I),
)
SOURCE_ROOTS = ("src", "lib", "app", "cmd", "internal", "pkg", "sources")
EXAMPLE_ROOTS = ("examples", "example", "samples", "sample", "playground", "playgrounds", "fixtures")
VENDOR_ROOTS = (
    "vendor", "node_modules", "dist", "build", "target", "generated", "__generated__",
    ".dart_tool", ".next", "deriveddata", "coverage",
)
MEDIA_ASSET_EXTENSIONS = {
    ".blend", ".fbx", ".glb", ".gltf", ".obj", ".dae", ".abc", ".usd", ".usdz",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg",
    ".exr", ".hdr", ".ktx", ".dds", ".wav", ".mp3", ".ogg", ".flac", ".aiff",
}
MEDIA_ASSET_PATH_TERMS = {
    "asset", "assets", "media", "material", "materials", "texture", "textures",
    "sprite", "sprites", "icon", "icons", "mesh", "meshes", "model", "models",
    "catalog", "manifest", "image", "images", "audio", "cue", "cues", "sound",
    "sounds",
}
INTENT_V2_CLASSES = (
    "media_asset_lookup",
    "code_entrypoint_lookup",
    "symbol_lookup",
    "bugfix_runtime",
    "docs_only",
    "config_change",
    "workflow_change",
    "test_failure",
    "broad_repo_inspection",
    "large_repo_media_lookup",
    "unknown",
)
ROLE_BUCKETS = (
    "primary_edit",
    "primary_lookup",
    "support_context",
    "verification",
    "asset_support",
    "docs_support",
    "config_support",
    "ignore_or_noise",
)
SELECTOR_MATRIX_CLAIM_LEVEL = "Level 0 internal metric only"
INTENT_V2_ROLE_BUCKETS_VARIANT = "intent_v2_role_buckets"
WARM_INDEX_INVENTORY_VERSION = "warm-index-v1"


@dataclass(frozen=True)
class PathRole:
    path: str
    ecosystem: str
    role: str
    surface: str
    source_root_kind: str | None
    test_root_kind: str | None
    package_rootness: str
    entrypoint_likelihood: str
    workflow_likelihood: str
    manifest_likelihood: str
    docs_specificity: str
    generated_or_vendor_status: str
    is_test: bool
    is_docs: bool
    is_config: bool
    is_workflow: bool
    is_example: bool
    is_generated_or_vendor: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PromptIntent:
    intent: str
    primary_roles: tuple[str, ...]
    support_roles: tuple[str, ...]
    verification_roles: tuple[str, ...]
    negative_roles: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PromptIntentV2:
    intent: str
    confidence: float
    reasons: tuple[str, ...]
    bounded_selection: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RoleBucketDecision:
    path: str
    intent: str
    role_bucket: str
    role_bucket_reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SelectorCandidateDryRun:
    selector_variant: str
    candidate_selector_used: bool
    candidate_selector_fallback: bool
    candidate_selector_fallback_reason: str | None
    intent_v2: str
    intent_confidence: float
    role_bucket_summary: dict[str, int]
    selection_lock_hash: str
    selected_paths: tuple[str, ...]
    candidate_paths: tuple[str, ...]
    default_selected_paths: tuple[str, ...]
    content_reads: int = 0
    advisory_only: bool = True
    claim_level: str = SELECTOR_MATRIX_CLAIM_LEVEL
    warm_index_enabled: bool = False
    warm_index_hit: bool = False
    warm_index_miss: bool = False
    warm_index_fallback_reason: str | None = None
    warm_index_build_ms: float = 0.0
    warm_selector_ms: float = 0.0
    cold_selector_ms: float = 0.0
    disk_read_proxy_count: int = 0
    inventory_walk_count: int = 0
    stat_call_count: int = 0
    candidate_enumeration_count: int = 0
    warm_index_cache_key: str | None = None

    def to_dict(self, *, include_paths: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "selector_variant": self.selector_variant,
            "candidate_selector_used": self.candidate_selector_used,
            "candidate_selector_fallback": self.candidate_selector_fallback,
            "candidate_selector_fallback_reason": self.candidate_selector_fallback_reason,
            "intent_v2": self.intent_v2,
            "intent_confidence": self.intent_confidence,
            "role_bucket_summary": dict(self.role_bucket_summary),
            "selection_lock_hash": self.selection_lock_hash,
            "selected_path_count": len(self.selected_paths),
            "selected_path_hash": selection_lock_hash_for_paths(list(self.selected_paths), intent=self.intent_v2),
            "candidate_path_count": len(self.candidate_paths),
            "default_selected_path_count": len(self.default_selected_paths),
            "content_reads": self.content_reads,
            "advisory_only": self.advisory_only,
            "claim_level": self.claim_level,
            "warm_index_enabled": self.warm_index_enabled,
            "warm_index_hit": self.warm_index_hit,
            "warm_index_miss": self.warm_index_miss,
            "warm_index_fallback_reason": self.warm_index_fallback_reason,
            "warm_index_build_ms": self.warm_index_build_ms,
            "warm_selector_ms": self.warm_selector_ms,
            "cold_selector_ms": self.cold_selector_ms,
            "disk_read_proxy_count": self.disk_read_proxy_count,
            "inventory_walk_count": self.inventory_walk_count,
            "stat_call_count": self.stat_call_count,
            "candidate_enumeration_count": self.candidate_enumeration_count,
            "warm_index_cache_key": self.warm_index_cache_key,
        }
        if include_paths:
            payload["selected_paths"] = list(self.selected_paths)
            payload["candidate_paths"] = list(self.candidate_paths)
            payload["default_selected_paths"] = list(self.default_selected_paths)
        return payload


@dataclass(frozen=True)
class WarmPathMetadata:
    path: str
    suffix: str
    basename: str
    path_segments: tuple[str, ...]
    path_tokens: tuple[str, ...]
    role: PathRole
    is_media_asset_shape: bool
    is_archive_or_legacy: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "suffix": self.suffix,
            "basename": self.basename,
            "path_segments": list(self.path_segments),
            "path_tokens": list(self.path_tokens),
            "role": self.role.to_dict(),
            "is_media_asset_shape": self.is_media_asset_shape,
            "is_archive_or_legacy": self.is_archive_or_legacy,
        }


@dataclass(frozen=True)
class RepoWarmIndex:
    paths: tuple[str, ...]
    path_metadata: tuple[WarmPathMetadata, ...]
    cache_key: str
    inventory_version: str = WARM_INDEX_INVENTORY_VERSION
    repo_root: str = ""
    git_head: str = ""
    dirty_state_hash: str = ""
    include_exclude_hash: str = ""
    ignore_file_hash: str = ""
    path_fingerprint: str = ""
    build_ms: float = 0.0
    content_reads: int = 0

    @classmethod
    def build(
        cls,
        paths: list[str] | tuple[str, ...],
        *,
        repo_root: str = "",
        git_head: str = "",
        dirty_state_hash: str = "",
        include_exclude_hash: str = "",
        ignore_file_hash: str = "",
        inventory_version: str = WARM_INDEX_INVENTORY_VERSION,
    ) -> "RepoWarmIndex":
        start = time.perf_counter()
        normalized = _normalize_path_list(paths)
        metadata = tuple(_warm_metadata_for_path(path) for path in normalized)
        fingerprint = _warm_index_path_fingerprint(normalized)
        cache_payload = {
            "repo_root": repo_root,
            "git_head": git_head,
            "dirty_state_hash": dirty_state_hash,
            "include_exclude_hash": include_exclude_hash,
            "ignore_file_hash": ignore_file_hash,
            "inventory_version": inventory_version,
            "path_fingerprint": fingerprint,
            "platform_path_normalization": "posix-slash-v1",
        }
        cache_key = hashlib.sha256(json.dumps(cache_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return cls(
            paths=normalized,
            path_metadata=metadata,
            cache_key=cache_key,
            inventory_version=inventory_version,
            repo_root=repo_root,
            git_head=git_head,
            dirty_state_hash=dirty_state_hash,
            include_exclude_hash=include_exclude_hash,
            ignore_file_hash=ignore_file_hash,
            path_fingerprint=fingerprint,
            build_ms=round((time.perf_counter() - start) * 1000, 3),
        )

    def validate_for_paths(
        self,
        paths: list[str] | tuple[str, ...],
        *,
        inventory_version: str = WARM_INDEX_INVENTORY_VERSION,
    ) -> tuple[bool, str | None]:
        if self.inventory_version != inventory_version:
            return False, "selector_inventory_version_changed"
        if self.content_reads != 0:
            return False, "warm_index_contains_content_reads"
        if len(self.paths) != len(self.path_metadata):
            return False, "corrupt_index_metadata"
        if any(not metadata.path for metadata in self.path_metadata):
            return False, "missing_required_fields"
        if _warm_index_path_fingerprint(_normalize_path_list(paths)) != self.path_fingerprint:
            return False, "file_set_changed"
        return True, None

    def to_dict(self, *, include_paths: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "cache_key": self.cache_key,
            "inventory_version": self.inventory_version,
            "path_count": len(self.paths),
            "path_fingerprint": self.path_fingerprint,
            "build_ms": self.build_ms,
            "content_reads": self.content_reads,
            "metadata_only": True,
            "cached_fields": [
                "path",
                "suffix",
                "basename",
                "path_segments",
                "path_tokens",
                "classification_flags",
                "role_hints",
            ],
        }
        if include_paths:
            payload["paths"] = list(self.paths)
        return payload


def _parts(path: str) -> list[str]:
    return [part for part in path.replace("\\", "/").strip("/").split("/") if part]


def _name(path: str) -> str:
    return Path(path.replace("\\", "/")).name.lower()


def _suffix(path: str) -> str:
    return Path(path.replace("\\", "/")).suffix.lower()


def _path_has_media_asset_shape(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/").lower()
    parts = set(_parts(normalized))
    name = _name(normalized)
    suffix = _suffix(normalized)
    name_terms = set(re.findall(r"[a-z0-9]+", Path(name).stem))
    if suffix in MEDIA_ASSET_EXTENSIONS:
        return True
    if parts & MEDIA_ASSET_PATH_TERMS:
        return True
    if suffix in {".json", ".yaml", ".yml", ".toml"} and name_terms & MEDIA_ASSET_PATH_TERMS:
        return True
    return bool(
        ("asset" in normalized or "media" in normalized)
        and name in {"manifest.json", "asset_manifest.json", "index.json", "catalog.json"}
    )


def _is_archive_or_legacy_path(path: str) -> bool:
    lowered = [part.lower() for part in _parts(path)]
    name = _name(path)
    return bool(
        any(part in {"archive", "archived", "legacy", "history", "old"} for part in lowered)
        or any(term in name for term in ("archive", "archived", "legacy", "old_"))
    )


def _ecosystem(path: str) -> str:
    lower = path.lower()
    name = _name(path)
    suffix = _suffix(path)
    if name in {"pyproject.toml", "setup.py", "setup.cfg"} or suffix == ".py":
        return "python"
    if name == "package.json" or suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro"}:
        return "node"
    if name == "cargo.toml" or suffix == ".rs":
        return "rust"
    if name == "go.mod" or suffix == ".go":
        return "go"
    if name == "package.swift" or suffix == ".swift":
        return "swift"
    if name == "pubspec.yaml" or suffix == ".dart" or "flutter" in lower:
        return "flutter"
    if suffix in {".kt", ".java", ".gradle"} or name.endswith(".gradle.kts"):
        return "jvm"
    return "generic"


def _source_root_kind(parts: list[str]) -> str | None:
    lowered = [part.lower() for part in parts]
    if len(lowered) >= 3 and lowered[0] == "packages" and lowered[2] in {"src", "lib"}:
        return "packages_src"
    if len(lowered) >= 3 and lowered[0] == "crates" and lowered[2] == "src":
        return "crates_src"
    if len(lowered) >= 2 and lowered[0] == "sources":
        return "swift_sources"
    if len(lowered) >= 2 and lowered[0] in {"lib", "app"} and any(part.endswith(".dart") for part in lowered):
        return "flutter_lib"
    for root in SOURCE_ROOTS:
        if root in lowered:
            return root
    return None


def _test_root_kind(parts: list[str]) -> str | None:
    lowered = [part.lower() for part in parts]
    for root in ("tests", "test", "testing", "__tests__", "integration_test", "test_driver"):
        if root in lowered:
            return root
    if "tests" in parts:
        return "swift_tests"
    return None


def _package_rootness(path: str, parts: list[str]) -> str:
    name = _name(path)
    lowered = [part.lower() for part in parts]
    if name in PACKAGE_MANIFEST_NAMES:
        if len(parts) == 1:
            return "repo_root"
        if "packages" in lowered or "crates" in lowered or "examples" in lowered or "samples" in lowered:
            return "package_root"
        return "nested_package_root"
    if len(lowered) >= 3 and lowered[0] in {"packages", "crates"}:
        return "package_member"
    return "none"


def classify_path_role(path: str) -> PathRole:
    normalized = path.replace("\\", "/").strip("/")
    parts = _parts(normalized)
    lowered = [part.lower() for part in parts]
    name = _name(normalized)
    suffix = _suffix(normalized)
    ecosystem = _ecosystem(normalized)
    generated = bool(any(part in VENDOR_ROOTS for part in lowered) or ".generated." in normalized.lower() or ".gen." in normalized.lower())
    is_example = bool(any(part in EXAMPLE_ROOTS for part in lowered))
    is_workflow = bool(
        normalized.lower().startswith(".github/workflows/")
        or normalized.lower().startswith("github/workflows/")
        or name in WORKFLOW_NAMES
        or (len(parts) >= 2 and parts[0].lower() == "scripts" and re.search(r"(smoke|test|check|validate|ci)", name))
    )
    is_test = bool(any(pattern.search(normalized) for pattern in TEST_PATTERNS))
    is_docs = bool(
        suffix in DOC_EXTENSIONS
        or any(part in {"docs", "doc", "guide", "guides", "tutorial", "tutorials", "handbook"} for part in lowered)
        or normalized.lower().startswith("content/docs/")
    )
    is_config = bool(name in PACKAGE_MANIFEST_NAMES or name in WORKFLOW_NAMES or suffix in {".toml", ".yaml", ".yml", ".ini", ".cfg", ".json", ".xml", ".gradle"})
    if generated:
        role = "generated"
    elif is_test:
        role = "test"
    elif is_workflow:
        role = "workflow"
    elif name in PACKAGE_MANIFEST_NAMES:
        role = "config"
    elif is_docs:
        role = "docs"
    elif is_example and suffix in SOURCE_EXTENSIONS:
        role = "example"
    elif suffix in SOURCE_EXTENSIONS:
        role = "source"
    elif is_config:
        role = "config"
    else:
        role = "support"

    source_root_kind = _source_root_kind(parts)
    test_root_kind = _test_root_kind(parts)
    package_rootness = _package_rootness(normalized, parts)
    lower = normalized.lower()
    entrypoint_likelihood = "none"
    if role in {"source", "example"}:
        if name in {"main.py", "__main__.py", "cli.py", "main.rs", "main.go", "main.swift", "main.dart", "index.ts", "index.tsx", "index.js"}:
            entrypoint_likelihood = "high"
        elif any(term in lower for term in ("/cmd/", "/cli", "/command", "/bin/", "/app.", "/app/")):
            entrypoint_likelihood = "medium"
        elif source_root_kind:
            entrypoint_likelihood = "low"
    workflow_likelihood = "high" if normalized.lower().startswith((".github/workflows/", "github/workflows/")) else ("medium" if is_workflow else "none")
    manifest_likelihood = "high" if name in PACKAGE_MANIFEST_NAMES and len(parts) == 1 else ("medium" if name in PACKAGE_MANIFEST_NAMES else "none")
    if name.startswith("readme"):
        docs_specificity = "readme"
    elif (
        any(part in {"usage", "guide", "guides", "tutorial", "tutorials", "quickstart", "getting-started", "getting_started", "install", "installation", "introduction", "intro", "basics", "troubleshooting", "troubleshoot", "faq", "how-to", "how_to", "howto"} for part in lowered)
        or any(term in lower for term in ("usage", "guide", "tutorial", "quickstart", "getting-started", "getting_started", "installation", "introduction", "basics", "troubleshooting", "troubleshoot", "faq", "how-to", "how_to", "howto"))
    ):
        docs_specificity = "specific"
    elif is_docs:
        docs_specificity = "generic"
    else:
        docs_specificity = "none"
    if generated:
        generated_status = "generated_or_vendor"
    elif is_example:
        generated_status = "example_or_fixture"
    else:
        generated_status = "clean"
    surface = "entrypoint" if entrypoint_likelihood == "high" else role
    return PathRole(
        path=normalized,
        ecosystem=ecosystem,
        role=role,
        surface=surface,
        source_root_kind=source_root_kind,
        test_root_kind=test_root_kind,
        package_rootness=package_rootness,
        entrypoint_likelihood=entrypoint_likelihood,
        workflow_likelihood=workflow_likelihood,
        manifest_likelihood=manifest_likelihood,
        docs_specificity=docs_specificity,
        generated_or_vendor_status=generated_status,
        is_test=is_test,
        is_docs=is_docs,
        is_config=is_config,
        is_workflow=is_workflow,
        is_example=is_example,
        is_generated_or_vendor=generated,
    )


def _warm_metadata_for_path(path: str) -> WarmPathMetadata:
    normalized = path.replace("\\", "/").strip("/")
    parts = tuple(_parts(normalized))
    return WarmPathMetadata(
        path=normalized,
        suffix=_suffix(normalized),
        basename=_name(normalized),
        path_segments=parts,
        path_tokens=tuple(sorted(_expanded_match_tokens(normalized))),
        role=classify_path_role(normalized),
        is_media_asset_shape=_path_has_media_asset_shape(normalized),
        is_archive_or_legacy=_is_archive_or_legacy_path(normalized),
    )


def _warm_index_path_fingerprint(paths: list[str] | tuple[str, ...]) -> str:
    normalized = _normalize_path_list(paths)
    payload = {"paths": list(normalized), "normalization": "posix-slash-v1"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def infer_prompt_intent(raw_prompt: str) -> PromptIntent:
    text = (raw_prompt or "").lower()
    negative_roles: list[str] = []
    if re.search(
        r"\bwithout\s+changing\s+(?:(?:runtime|production)\s+)?source\b"
        r"|\bwithout\s+changing\s+(?:production\s+)?code\b"
        r"|\bdo not\s+(?:touch|change|edit)\s+(?:(?:runtime|production)\s+)?source\b"
        r"|\bdo not\s+(?:touch|change|edit)\s+(?:production\s+)?code\b",
        text,
    ):
        negative_roles.append("source")
    if re.search(r"\bwithout\s+changing\s+public\s+cli\s+flags\b", text):
        negative_roles.append("cli")
    if re.search(
        r"\bwithout\s+changing\s+(?:package\s+metadata|project\s+configuration|config(?:uration)?)\b"
        r"|\bdo not\s+(?:touch|change|edit)\s+(?:package\s+metadata|project\s+configuration|config(?:uration)?)\b",
        text,
    ):
        negative_roles.append("config")
    if re.search(r"\bdocs?\s+as\s+support\b|\bwithout\s+changing\s+docs?\b", text):
        negative_roles.append("docs")

    test_edit = bool(re.search(r"\b(add|write|create|update)\b[^\n.;]{0,80}\b(regression\s+)?(tests?|coverage)\b", text))
    docs = bool(re.search(r"\b(readme|docs?|documentation|guide|quickstart|usage|tutorial|handbook|troubleshoot(?:ing)?|faq|how-to|how_to|howto)\b", text))
    config = bool(re.search(r"\b(package|packaging|project)\s+metadata\b|\bmanifest\b|\bpyproject\b|\bpackage\.json\b|\bcargo\.toml\b|\bgo\.mod\b|\bpackage\.swift\b|\bpubspec\b|\bconfiguration\b", text))
    if "config" in negative_roles:
        config = False
    workflow = bool(re.search(r"\b(ci|workflow|github actions?|smoke test|smoke validation|regression guard|pre-commit)\b", text))
    if not workflow and "local validation" in text:
        workflow = bool(re.search(r"\b(checks?|workflow|script|ci-style|ci|smoke|guard)\b", text))
    runtime = bool(re.search(r"\b(fix|change|adjust|improve|refactor|recover|trace)\b[^\n.;]{0,120}\b(runtime|behavior|source|entrypoint|command|cli|flag|option|view|screen|state|module|compiler|routing)\b", text))
    example = bool(re.search(r"\b(example|sample|playground)\b", text))

    if test_edit and ("source" in negative_roles or re.search(r"\bproduction\s+code\b", text)):
        return PromptIntent("test_edit", ("test",), ("source", "config"), ("test",), tuple(negative_roles))
    if workflow:
        return PromptIntent("workflow", ("workflow",), ("config", "source"), ("test", "workflow"), tuple(negative_roles))
    if config:
        return PromptIntent("config", ("config",), ("source", "docs"), ("test",), tuple(negative_roles))
    if docs and not runtime:
        return PromptIntent("docs", ("docs",), ("source", "config"), ("test",), tuple(negative_roles))
    if example:
        return PromptIntent("example", ("example", "source"), ("config", "docs"), ("test",), tuple(negative_roles))
    return PromptIntent("runtime", ("source",), ("test", "docs", "config"), ("test",), tuple(negative_roles))


def infer_prompt_intent_v2(raw_prompt: str) -> PromptIntentV2:
    text = re.sub(r"\s+", " ", (raw_prompt or "").lower()).strip()
    reasons: list[str] = []

    media_terms = re.search(
        r"\b(asset|assets|media|material|materials|texture|textures|sprite|sprites|"
        r"icon|icons|image|images|model|models|mesh|meshes|audio|cue|cues|sound|sounds|"
        r"blend|blender|catalog|manifest)\b",
        text,
    )
    media_ext = re.search(r"\.(png|jpe?g|webp|gif|svg|blend|fbx|glb|gltf|obj|wav|mp3|ogg)\b", text)
    lookup_terms = re.search(r"\b(find|locate|lookup|where|identify|select|list|show)\b", text)
    entrypoint_terms = re.search(
        r"\b(entrypoint|entry point|startup|start up|bootstrap|lifecycle|routing|route|"
        r"handler|command entry|cli entry|main module|main file)\b",
        text,
    )
    runtime_terms = re.search(r"\b(fix|failing|failure|runtime|behavior|bug|crash|error|exception|regression|broken)\b", text)
    test_terms = re.search(r"\b(failing test|test failure|pytest|unit test|integration test|regression test)\b", text)
    docs_terms = re.search(r"\b(readme|docs?|documentation|guide|changelog|tutorial|explain|usage)\b", text)
    config_terms = re.search(
        r"\b(config|configuration|settings|manifest|package metadata|pyproject|package\.json|"
        r"cargo\.toml|go\.mod|package\.swift|pubspec|schema)\b",
        text,
    )
    workflow_terms = re.search(r"\b(ci|workflow|github actions?|build pipeline|release|script|process|smoke)\b", text)
    broad_terms = re.search(r"\b(overview|audit|map|understand|inspect|survey|orientation|onboarding|repo)\b", text)
    symbol_terms = re.search(r"\b(symbol|function|class|method|definition|where is .* defined|declaration)\b", text)
    large_terms = re.search(r"\b(large repo|large repository|many assets|asset library|media library)\b", text)
    negative_runtime_boundary = re.search(
        r"\b(avoid|without|do not|don't|unrelated|not|exclude|keep)\b[^\n.;]{0,80}\b(runtime|source|code|implementation|files?)\b"
        r"|\b(runtime|source|code|implementation)\b[^\n.;]{0,80}\b(out of scope|out of primary|not the target)\b",
        text,
    )

    if media_terms and lookup_terms and not entrypoint_terms and (not runtime_terms or negative_runtime_boundary):
        reasons.append("media_lookup_language")
        if negative_runtime_boundary:
            reasons.append("runtime_boundary_negative")
        if large_terms:
            return PromptIntentV2("large_repo_media_lookup", 0.82, tuple(reasons + ["large_media_scope"]))
        return PromptIntentV2("media_asset_lookup", 0.88 if media_ext else 0.82, tuple(reasons))
    if entrypoint_terms and lookup_terms and not runtime_terms:
        return PromptIntentV2("code_entrypoint_lookup", 0.86, ("entrypoint_lookup_language",))
    if workflow_terms and (lookup_terms or runtime_terms or re.search(r"\b(update|change|tighten|adjust)\b", text)):
        return PromptIntentV2("workflow_change", 0.82, ("workflow_change_language",))
    if test_terms and not re.search(r"\b(runtime|behavior|bug|crash)\b", text):
        return PromptIntentV2("test_failure", 0.78, ("test_failure_language",))
    if docs_terms and negative_runtime_boundary and not (config_terms or workflow_terms):
        return PromptIntentV2("docs_only", 0.78, ("docs_only_with_runtime_boundary",))
    if runtime_terms:
        return PromptIntentV2("bugfix_runtime", 0.76, ("runtime_bugfix_language",))
    if docs_terms and not (runtime_terms or config_terms or workflow_terms):
        return PromptIntentV2("docs_only", 0.80, ("docs_only_language",))
    if config_terms and not workflow_terms:
        return PromptIntentV2("config_change", 0.78, ("config_change_language",))
    if symbol_terms:
        return PromptIntentV2("symbol_lookup", 0.72, ("symbol_lookup_language",))
    if broad_terms:
        return PromptIntentV2("broad_repo_inspection", 0.70, ("broad_repo_inspection_language",))
    return PromptIntentV2("unknown", 0.35, ("low_confidence_unknown",), bounded_selection=True)


def role_bucket_for_path(
    path: str,
    intent: str | PromptIntentV2,
    *,
    linked: bool = False,
) -> RoleBucketDecision:
    intent_name = intent.intent if isinstance(intent, PromptIntentV2) else str(intent or "unknown")
    normalized = path.replace("\\", "/").strip("/")
    role = classify_path_role(normalized)
    is_asset = _path_has_media_asset_shape(normalized)
    is_archive_or_legacy = _is_archive_or_legacy_path(normalized)

    bucket = "support_context"
    reason = f"{role.role}_support"

    if role.is_generated_or_vendor:
        return RoleBucketDecision(normalized, intent_name, "ignore_or_noise", "generated_or_vendor")

    if intent_name in {"media_asset_lookup", "large_repo_media_lookup"}:
        if is_asset and is_archive_or_legacy:
            bucket, reason = "ignore_or_noise", "archived_media_asset_noise"
        elif is_asset:
            bucket, reason = "primary_lookup", "media_asset_lookup_primary"
        elif role.role == "source":
            bucket, reason = ("support_context", "source_support_only_for_media_lookup") if linked else ("ignore_or_noise", "source_unlinked_for_media_lookup")
        elif role.role == "test":
            bucket, reason = "ignore_or_noise", "test_unlinked_for_media_lookup"
        elif role.role == "docs":
            bucket, reason = ("docs_support", "linked_docs_for_media_lookup") if linked else ("support_context", "docs_metadata_for_media_lookup")
        elif role.role == "config":
            bucket, reason = "config_support", "metadata_or_manifest_for_media_lookup"
    elif intent_name == "code_entrypoint_lookup":
        if role.role == "source" and (
            role.entrypoint_likelihood in {"high", "medium"}
            or any(term in _name(normalized) for term in ("entry", "bootstrap", "route", "server", "main", "cli"))
        ):
            bucket, reason = "primary_lookup", "entrypoint_source_lookup"
        elif role.role == "source":
            bucket, reason = "support_context", "source_support_for_entrypoint_lookup"
        elif is_asset:
            bucket, reason = "asset_support", "asset_support_only_for_entrypoint_lookup"
        elif role.role == "test":
            bucket, reason = ("verification", "linked_test_for_entrypoint_lookup") if linked else ("ignore_or_noise", "test_unlinked_for_entrypoint_lookup")
        elif role.role == "config":
            bucket, reason = "config_support", "config_bootstrap_support"
        elif role.role == "docs":
            bucket, reason = "docs_support", "docs_support_for_entrypoint_lookup"
    elif intent_name == "bugfix_runtime":
        if role.role == "source":
            bucket, reason = "primary_edit", "runtime_source_primary"
        elif role.role == "test":
            bucket, reason = "verification", "runtime_test_verification"
        elif is_asset:
            bucket, reason = ("asset_support", "linked_asset_for_runtime") if linked else ("ignore_or_noise", "asset_unlinked_for_runtime")
        elif role.role == "config":
            bucket, reason = ("config_support", "linked_config_for_runtime") if linked else ("ignore_or_noise", "unlinked_config_for_runtime")
        elif role.role == "docs":
            bucket, reason = ("support_context", "linked_docs_for_runtime") if linked else ("ignore_or_noise", "unlinked_docs_for_runtime")
    elif intent_name == "docs_only":
        if role.role == "docs":
            bucket, reason = ("support_context", "readme_support_for_specific_docs") if _name(normalized) == "readme.md" and not linked else ("primary_edit", "docs_primary")
        elif role.role == "source":
            bucket, reason = ("support_context", "linked_source_for_docs") if linked else ("ignore_or_noise", "source_unlinked_for_docs")
        elif role.role in {"test", "workflow"} or is_asset:
            bucket, reason = "ignore_or_noise", "unlinked_non_docs_for_docs"
        elif role.role == "config":
            bucket, reason = ("config_support", "linked_config_for_docs") if linked else ("ignore_or_noise", "config_unlinked_for_docs")
    elif intent_name == "config_change":
        if is_asset and not linked:
            bucket, reason = "ignore_or_noise", "unlinked_asset_config_for_config"
        elif role.role == "config":
            bucket, reason = "primary_edit", "config_primary"
        elif role.role == "docs":
            bucket, reason = ("docs_support", "linked_docs_for_config") if linked else ("ignore_or_noise", "unlinked_docs_for_config")
        elif role.role == "source":
            bucket, reason = ("support_context", "linked_source_for_config") if linked else ("ignore_or_noise", "unlinked_source_for_config")
        else:
            bucket, reason = "ignore_or_noise", "unlinked_non_config_for_config"
    elif intent_name == "workflow_change":
        if role.role == "workflow" or normalized.lower().startswith((".github/workflows/", "scripts/")):
            bucket, reason = "primary_edit", "workflow_primary"
        elif role.role == "config":
            bucket, reason = ("primary_edit", "linked_workflow_config_primary") if linked else ("config_support", "workflow_config_support")
        elif role.role == "test":
            bucket, reason = ("verification", "workflow_test_verification") if linked else ("ignore_or_noise", "test_unlinked_for_workflow")
        elif role.role == "docs":
            bucket, reason = ("docs_support", "linked_docs_for_workflow") if linked else ("ignore_or_noise", "unlinked_docs_for_workflow")
        elif role.role == "source":
            bucket, reason = ("support_context", "linked_source_for_workflow") if linked else ("ignore_or_noise", "unlinked_source_for_workflow")
        else:
            bucket, reason = "ignore_or_noise", "unlinked_non_workflow_for_workflow"
    elif intent_name == "broad_repo_inspection":
        lower = normalized.lower()
        if lower in {"ai_start_here.md", "agents.md", "premode.ai.json"}:
            bucket, reason = "primary_lookup", "repo_orientation_surface"
        elif role.role in {"docs", "config"} or role.entrypoint_likelihood in {"high", "medium"}:
            bucket, reason = "support_context", "bounded_repo_context"
        else:
            bucket, reason = "ignore_or_noise", "bounded_repo_inspection_noise"
    elif intent_name == "test_failure":
        if role.role == "test":
            bucket, reason = "primary_edit", "test_failure_primary"
        elif role.role == "source":
            bucket, reason = "support_context", "source_support_for_test_failure"
        elif role.role == "config":
            bucket, reason = "config_support", "config_support_for_test_failure"
    elif intent_name == "symbol_lookup":
        if role.role == "source":
            bucket, reason = "primary_lookup", "symbol_source_lookup"
        elif role.role == "test":
            bucket, reason = "verification", "symbol_test_context"
    else:
        if role.role in {"docs", "config"} or role.entrypoint_likelihood in {"high", "medium"}:
            bucket, reason = "support_context", "unknown_bounded_support"
        else:
            bucket, reason = "ignore_or_noise", "unknown_bounded_noise"

    return RoleBucketDecision(normalized, intent_name, bucket, reason)


def intent_v2_path_score(path: str, intent: str | PromptIntentV2, *, linked: bool = False) -> int:
    decision = role_bucket_for_path(path, intent, linked=linked)
    role = classify_path_role(path)
    intent_name = intent.intent if isinstance(intent, PromptIntentV2) else str(intent or "unknown")
    lowered = [part.lower() for part in _parts(path)]
    bucket_scores = {
        "primary_edit": 900,
        "primary_lookup": 850,
        "verification": 650,
        "config_support": 500,
        "docs_support": 450,
        "asset_support": 420,
        "support_context": 350,
        "ignore_or_noise": -500,
    }
    score = bucket_scores.get(decision.role_bucket, 0)
    if intent_name == "code_entrypoint_lookup":
        name = _name(path)
        if role.entrypoint_likelihood == "high":
            score += 120
        elif role.entrypoint_likelihood == "medium":
            score += 80
        if any(term in name for term in ("entry", "bootstrap", "route", "server", "main", "cli")):
            score += 120
    elif intent_name in {"bugfix_runtime", "test_failure"}:
        if role.entrypoint_likelihood == "high" and not linked:
            score -= 80
        elif role.entrypoint_likelihood == "medium" and not linked:
            score -= 40
    elif role.entrypoint_likelihood == "high":
        score += 60
    elif role.entrypoint_likelihood == "medium":
        score += 30
    if role.manifest_likelihood == "high":
        score += 80
    if role.docs_specificity in {"readme", "specific"}:
        score += 40
    if role.is_generated_or_vendor:
        score -= 800
    if _is_archive_or_legacy_path(path):
        score -= 700
    return score


def selection_lock_hash_for_paths(paths: list[str], *, intent: str | None = None) -> str:
    cleaned = sorted(dict.fromkeys(path.replace("\\", "/").strip("/") for path in paths if path))
    payload = {"intent": intent or "", "paths": cleaned}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _expanded_match_tokens(text: str) -> set[str]:
    normalized = re.sub(r"[/_.:-]+", " ", (text or "").lower())
    tokens = {tok for tok in re.findall(r"[a-z0-9]+", normalized) if len(tok) > 2}
    expanded = set(tokens)
    for token in tokens:
        if token.endswith("ies") and len(token) > 4:
            expanded.add(token[:-3] + "y")
        if token.endswith("s") and len(token) > 3:
            expanded.add(token[:-1])
    return expanded


def _path_prompt_overlap_score(path: str, prompt_tokens: set[str]) -> int:
    return len(_expanded_match_tokens(path) & prompt_tokens)


def _intent_v2_bucket_limits(intent_name: str, max_paths: int) -> dict[str, int]:
    base = {
        "primary_edit": max_paths,
        "primary_lookup": max_paths,
        "verification": 1,
        "support_context": 1,
        "asset_support": 1,
        "docs_support": 1,
        "config_support": 1,
        "ignore_or_noise": 0,
    }
    if intent_name in {"media_asset_lookup", "large_repo_media_lookup", "code_entrypoint_lookup"}:
        base["primary_lookup"] = 2
    elif intent_name == "bugfix_runtime":
        base["primary_edit"] = 1
        base["verification"] = 1
        base["asset_support"] = 0
    elif intent_name == "test_failure":
        base["primary_edit"] = 1
        base["verification"] = 1
    elif intent_name in {"docs_only", "config_change", "workflow_change"}:
        base["primary_edit"] = 2
    elif intent_name == "broad_repo_inspection":
        base["primary_lookup"] = 2
        base["support_context"] = 2
    return base


def rank_intent_v2_paths(paths: list[str], raw_prompt: str, *, max_paths: int | None = None) -> list[RoleBucketDecision]:
    """Rank paths for the opt-in IntentV2 selector without reading file contents."""
    intent = infer_prompt_intent_v2(raw_prompt)
    intent_name = intent.intent
    cap_defaults = {
        "media_asset_lookup": 2,
        "large_repo_media_lookup": 2,
        "code_entrypoint_lookup": 2,
        "bugfix_runtime": 3,
        "docs_only": 2,
        "config_change": 3,
        "workflow_change": 3,
        "test_failure": 3,
        "broad_repo_inspection": 3,
        "symbol_lookup": 4,
        "unknown": 3,
    }
    limit = max_paths if max_paths is not None else cap_defaults.get(intent_name, 4)
    prompt_tokens = _expanded_match_tokens(raw_prompt)
    scored: list[tuple[int, str, RoleBucketDecision]] = []
    for raw_path in paths:
        path = raw_path.replace("\\", "/").strip("/")
        if not path:
            continue
        overlap = _path_prompt_overlap_score(path, prompt_tokens)
        linked = overlap > 0
        decision = role_bucket_for_path(path, intent, linked=linked)
        if decision.role_bucket == "ignore_or_noise":
            continue
        score = intent_v2_path_score(path, intent, linked=linked) + overlap * 100
        score -= min(path.count("/"), 5) * 8
        role = classify_path_role(path)
        if intent_name in {"media_asset_lookup", "large_repo_media_lookup"} and _path_has_media_asset_shape(path):
            score += 220
            if path.lower().startswith(("assets/", "audio/", "ui/assets/", "mega_assets/")):
                score += 40
            if _is_archive_or_legacy_path(path):
                score -= 900
        if intent_name == "code_entrypoint_lookup" and role.role == "source":
            name = _name(path)
            if any(term in name for term in ("entry", "bootstrap", "route", "server", "main", "cli")):
                score += 180
        if intent_name == "bugfix_runtime" and role.role == "source":
            score += 140 if linked else -80
        if intent_name == "test_failure" and role.role == "test":
            score += 220
        if intent_name == "docs_only" and role.role == "docs":
            score += 180 if linked else 40
        if intent_name == "config_change" and role.role == "config":
            score += 180 if linked else 40
        if intent_name == "workflow_change" and (role.role == "workflow" or path.lower().startswith((".github/workflows/", "scripts/"))):
            score += 220 if linked else 80
        if intent_name == "broad_repo_inspection" and path.lower() in {"ai_start_here.md", "agents.md", "premode.ai.json", "readme.md"}:
            score += 220
        scored.append((score, path, decision))

    scored.sort(key=lambda item: (-item[0], item[1]))
    bucket_limits = _intent_v2_bucket_limits(intent_name, limit)
    bucket_counts = {bucket: 0 for bucket in ROLE_BUCKETS}
    selected: list[RoleBucketDecision] = []
    seen: set[str] = set()
    for _score, path, decision in scored:
        if path in seen:
            continue
        if bucket_counts.get(decision.role_bucket, 0) >= bucket_limits.get(decision.role_bucket, 0):
            continue
        selected.append(decision)
        seen.add(path)
        bucket_counts[decision.role_bucket] = bucket_counts.get(decision.role_bucket, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def _normalize_path_list(paths: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw_path in paths or ():
        path = str(raw_path or "").replace("\\", "/").strip("/")
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return tuple(out)


def _role_bucket_summary(decisions: list[RoleBucketDecision]) -> dict[str, int]:
    summary = {bucket: 0 for bucket in ROLE_BUCKETS}
    for decision in decisions:
        summary[decision.role_bucket] = summary.get(decision.role_bucket, 0) + 1
    return {bucket: count for bucket, count in summary.items() if count}


def _dry_run_fallback_result(
    *,
    selector_variant: str,
    fallback_reason: str,
    intent: PromptIntentV2,
    default_selected_paths: tuple[str, ...],
    candidate_decisions: list[RoleBucketDecision] | None = None,
    warm_stats: dict[str, object] | None = None,
) -> SelectorCandidateDryRun:
    candidate_paths = tuple(decision.path for decision in candidate_decisions or [])
    role_summary = _role_bucket_summary(candidate_decisions or [])
    selection_hash = selection_lock_hash_for_paths(list(default_selected_paths), intent="default_current")
    warm = warm_stats or {}
    return SelectorCandidateDryRun(
        selector_variant=selector_variant,
        candidate_selector_used=False,
        candidate_selector_fallback=True,
        candidate_selector_fallback_reason=fallback_reason,
        intent_v2=intent.intent,
        intent_confidence=intent.confidence,
        role_bucket_summary=role_summary,
        selection_lock_hash=selection_hash,
        selected_paths=default_selected_paths,
        candidate_paths=candidate_paths,
        default_selected_paths=default_selected_paths,
        warm_index_enabled=bool(warm.get("warm_index_enabled", False)),
        warm_index_hit=bool(warm.get("warm_index_hit", False)),
        warm_index_miss=bool(warm.get("warm_index_miss", False)),
        warm_index_fallback_reason=warm.get("warm_index_fallback_reason") if isinstance(warm.get("warm_index_fallback_reason"), str) else None,
        warm_index_build_ms=float(warm.get("warm_index_build_ms") or 0.0),
        warm_selector_ms=float(warm.get("warm_selector_ms") or 0.0),
        cold_selector_ms=float(warm.get("cold_selector_ms") or 0.0),
        disk_read_proxy_count=int(warm.get("disk_read_proxy_count") or 0),
        inventory_walk_count=int(warm.get("inventory_walk_count") or 0),
        stat_call_count=int(warm.get("stat_call_count") or 0),
        candidate_enumeration_count=int(warm.get("candidate_enumeration_count") or 0),
        warm_index_cache_key=warm.get("warm_index_cache_key") if isinstance(warm.get("warm_index_cache_key"), str) else None,
    )


def dry_run_selector_candidate(
    paths: list[str],
    raw_prompt: str,
    *,
    selector_candidate: str | None = None,
    default_selected_paths: list[str] | tuple[str, ...] | None = None,
    forbidden_paths: list[str] | tuple[str, ...] | None = None,
    max_paths: int | None = None,
    warm_index_enabled: bool = False,
    warm_index: RepoWarmIndex | None = None,
    build_warm_index: bool = True,
    selector_inventory_version: str = WARM_INDEX_INVENTORY_VERSION,
) -> SelectorCandidateDryRun:
    """Evaluate a selector candidate as explicit dry-run metadata only.

    The returned candidate can be inspected by callers, but this function does
    not mutate default routing behavior and does not read file contents.
    """
    default_paths = _normalize_path_list(default_selected_paths)
    intent = infer_prompt_intent_v2(raw_prompt)
    selector = selector_candidate or "default_current"
    warm_stats: dict[str, object] = {
        "warm_index_enabled": warm_index_enabled,
        "warm_index_hit": False,
        "warm_index_miss": False,
        "warm_index_fallback_reason": None,
        "warm_index_build_ms": 0.0,
        "warm_selector_ms": 0.0,
        "cold_selector_ms": 0.0,
        "disk_read_proxy_count": len(_normalize_path_list(paths)) if not warm_index_enabled else 0,
        "inventory_walk_count": 1 if not warm_index_enabled else 0,
        "stat_call_count": 0,
        "candidate_enumeration_count": len(_normalize_path_list(paths)),
        "warm_index_cache_key": None,
    }
    if selector_candidate is None:
        return _dry_run_fallback_result(
            selector_variant=selector,
            fallback_reason="candidate_not_requested",
            intent=intent,
            default_selected_paths=default_paths,
            warm_stats=warm_stats,
        )
    if selector_candidate != INTENT_V2_ROLE_BUCKETS_VARIANT:
        return _dry_run_fallback_result(
            selector_variant=selector,
            fallback_reason="unsupported_selector_candidate",
            intent=intent,
            default_selected_paths=default_paths,
            warm_stats=warm_stats,
        )
    if intent.intent == "unknown" or intent.confidence < 0.50:
        return _dry_run_fallback_result(
            selector_variant=selector,
            fallback_reason="low_confidence_or_unknown",
            intent=intent,
            default_selected_paths=default_paths,
            warm_stats=warm_stats,
        )

    selector_paths: list[str] | tuple[str, ...] = paths
    if warm_index_enabled:
        if warm_index is not None:
            valid, reason = warm_index.validate_for_paths(paths, inventory_version=selector_inventory_version)
            if valid:
                selector_paths = warm_index.paths
                warm_stats.update(
                    {
                        "warm_index_hit": True,
                        "disk_read_proxy_count": 0,
                        "inventory_walk_count": 0,
                        "candidate_enumeration_count": len(warm_index.paths),
                        "warm_index_cache_key": warm_index.cache_key,
                    }
                )
            else:
                warm_stats.update(
                    {
                        "warm_index_fallback_reason": reason or "warm_index_invalid",
                        "disk_read_proxy_count": len(_normalize_path_list(paths)),
                        "inventory_walk_count": 1,
                    }
                )
        elif build_warm_index:
            built_index = RepoWarmIndex.build(paths, inventory_version=selector_inventory_version)
            selector_paths = built_index.paths
            warm_stats.update(
                {
                    "warm_index_miss": True,
                    "warm_index_build_ms": built_index.build_ms,
                    "disk_read_proxy_count": len(built_index.paths),
                    "inventory_walk_count": 1,
                    "candidate_enumeration_count": len(built_index.paths),
                    "warm_index_cache_key": built_index.cache_key,
                }
            )
        else:
            warm_stats.update(
                {
                    "warm_index_fallback_reason": "missing_index",
                    "disk_read_proxy_count": len(_normalize_path_list(paths)),
                    "inventory_walk_count": 1,
                }
            )

    selector_start = time.perf_counter()
    candidate_decisions = rank_intent_v2_paths(list(selector_paths), raw_prompt, max_paths=max_paths)
    selector_ms = round((time.perf_counter() - selector_start) * 1000, 3)
    if warm_index_enabled and warm_stats.get("warm_index_fallback_reason") is None:
        warm_stats["warm_selector_ms"] = selector_ms
    else:
        warm_stats["cold_selector_ms"] = selector_ms
    primary_count = sum(1 for decision in candidate_decisions if decision.role_bucket in {"primary_edit", "primary_lookup"})
    if primary_count == 0:
        return _dry_run_fallback_result(
            selector_variant=selector,
            fallback_reason="empty_primary_selection",
            intent=intent,
            default_selected_paths=default_paths,
            candidate_decisions=candidate_decisions,
            warm_stats=warm_stats,
        )
    forbidden = set(_normalize_path_list(forbidden_paths))
    if forbidden and any(decision.path in forbidden for decision in candidate_decisions):
        return _dry_run_fallback_result(
            selector_variant=selector,
            fallback_reason="forbidden_risk_detected",
            intent=intent,
            default_selected_paths=default_paths,
            candidate_decisions=candidate_decisions,
            warm_stats=warm_stats,
        )

    candidate_paths = tuple(decision.path for decision in candidate_decisions)
    return SelectorCandidateDryRun(
        selector_variant=selector,
        candidate_selector_used=True,
        candidate_selector_fallback=False,
        candidate_selector_fallback_reason=None,
        intent_v2=intent.intent,
        intent_confidence=intent.confidence,
        role_bucket_summary=_role_bucket_summary(candidate_decisions),
        selection_lock_hash=selection_lock_hash_for_paths(list(candidate_paths), intent=intent.intent),
        selected_paths=candidate_paths,
        candidate_paths=candidate_paths,
        default_selected_paths=default_paths,
        warm_index_enabled=bool(warm_stats.get("warm_index_enabled", False)),
        warm_index_hit=bool(warm_stats.get("warm_index_hit", False)),
        warm_index_miss=bool(warm_stats.get("warm_index_miss", False)),
        warm_index_fallback_reason=warm_stats.get("warm_index_fallback_reason") if isinstance(warm_stats.get("warm_index_fallback_reason"), str) else None,
        warm_index_build_ms=float(warm_stats.get("warm_index_build_ms") or 0.0),
        warm_selector_ms=float(warm_stats.get("warm_selector_ms") or 0.0),
        cold_selector_ms=float(warm_stats.get("cold_selector_ms") or 0.0),
        disk_read_proxy_count=int(warm_stats.get("disk_read_proxy_count") or 0),
        inventory_walk_count=int(warm_stats.get("inventory_walk_count") or 0),
        stat_call_count=int(warm_stats.get("stat_call_count") or 0),
        candidate_enumeration_count=int(warm_stats.get("candidate_enumeration_count") or 0),
        warm_index_cache_key=warm_stats.get("warm_index_cache_key") if isinstance(warm_stats.get("warm_index_cache_key"), str) else None,
    )


def path_role_rank(path: str, intent: PromptIntent, *, for_related_test: bool = False) -> int:
    role = classify_path_role(path)
    score = 0
    if for_related_test:
        if role.is_test:
            score += 600
        if role.test_root_kind:
            score += 100
        if role.is_generated_or_vendor or role.is_example:
            score -= 250
        return score
    if role.role in intent.primary_roles:
        score += 700
    if role.role in intent.support_roles:
        score += 120
    if role.role in intent.negative_roles:
        score -= 500
    if role.role == "source":
        if "cli" in intent.negative_roles and (
            role.entrypoint_likelihood in {"high", "medium"}
            or any(term in role.path.lower() for term in ("/cli", "/cmd/", "/bin/", "command"))
        ):
            score -= 900
        if role.entrypoint_likelihood == "high":
            score += 320
        elif role.entrypoint_likelihood == "medium":
            score += 160
        elif role.source_root_kind:
            score += 70
    if role.role == "config":
        if role.manifest_likelihood == "high":
            score += 340
        elif role.manifest_likelihood == "medium":
            score += 120
    if role.role == "workflow":
        if role.workflow_likelihood == "high":
            score += 260
        elif role.workflow_likelihood == "medium":
            score += 130
    if role.role == "docs":
        if role.docs_specificity == "readme":
            score += 300
        elif role.docs_specificity == "specific":
            score += 160
    if role.role == "test" and intent.intent == "test_edit":
        score += 260
    if role.is_generated_or_vendor:
        score -= 800
    if role.is_example and intent.intent != "example":
        score -= 180
    return score
