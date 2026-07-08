from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re


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
    "catalog", "manifest", "image", "images",
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
    if suffix in MEDIA_ASSET_EXTENSIONS:
        return True
    if parts & MEDIA_ASSET_PATH_TERMS:
        return True
    return bool(
        ("asset" in normalized or "media" in normalized)
        and name in {"manifest.json", "asset_manifest.json", "index.json", "catalog.json"}
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
        r"icon|icons|image|images|model|models|mesh|meshes|blend|blender|catalog|manifest)\b",
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
        r"\b(avoid|without|do not|don't|unrelated)\b[^\n.;]{0,60}\b(runtime|source|code|implementation)\b",
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
    if test_terms and not re.search(r"\b(runtime|behavior|source|bug|crash)\b", text):
        return PromptIntentV2("test_failure", 0.78, ("test_failure_language",))
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

    bucket = "support_context"
    reason = f"{role.role}_support"

    if role.is_generated_or_vendor:
        return RoleBucketDecision(normalized, intent_name, "ignore_or_noise", "generated_or_vendor")

    if intent_name in {"media_asset_lookup", "large_repo_media_lookup"}:
        if is_asset:
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
        if role.role == "source" and role.entrypoint_likelihood in {"high", "medium"}:
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
        elif role.role in {"docs", "config"}:
            bucket, reason = ("support_context", f"linked_{role.role}_for_runtime") if linked else ("ignore_or_noise", f"unlinked_{role.role}_for_runtime")
    elif intent_name == "docs_only":
        if role.role == "docs":
            bucket, reason = "primary_edit", "docs_primary"
        elif role.role == "source":
            bucket, reason = ("support_context", "linked_source_for_docs") if linked else ("ignore_or_noise", "source_unlinked_for_docs")
        elif role.role in {"test", "workflow"} or is_asset:
            bucket, reason = "ignore_or_noise", "unlinked_non_docs_for_docs"
        elif role.role == "config":
            bucket, reason = ("config_support", "linked_config_for_docs") if linked else ("ignore_or_noise", "config_unlinked_for_docs")
    elif intent_name == "config_change":
        if role.role == "config":
            bucket, reason = "primary_edit", "config_primary"
        elif role.role in {"source", "docs"}:
            bucket, reason = ("support_context", f"linked_{role.role}_for_config") if linked else ("ignore_or_noise", f"unlinked_{role.role}_for_config")
        else:
            bucket, reason = "ignore_or_noise", "unlinked_non_config_for_config"
    elif intent_name == "workflow_change":
        if role.role == "workflow" or normalized.lower().startswith((".github/workflows/", "scripts/")):
            bucket, reason = "primary_edit", "workflow_primary"
        elif role.role == "config":
            bucket, reason = "primary_edit", "workflow_config_primary"
        elif role.role == "test":
            bucket, reason = ("verification", "workflow_test_verification") if linked else ("ignore_or_noise", "test_unlinked_for_workflow")
        elif role.role in {"docs", "source"}:
            bucket, reason = ("support_context", f"linked_{role.role}_for_workflow") if linked else ("ignore_or_noise", f"unlinked_{role.role}_for_workflow")
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
    if role.entrypoint_likelihood == "high":
        score += 120
    elif role.entrypoint_likelihood == "medium":
        score += 60
    if role.manifest_likelihood == "high":
        score += 80
    if role.docs_specificity in {"readme", "specific"}:
        score += 40
    if role.is_generated_or_vendor:
        score -= 800
    if any(part in {"archive", "archived", "legacy", "history"} for part in lowered) or "archive" in _name(path):
        score -= 350
    return score


def selection_lock_hash_for_paths(paths: list[str], *, intent: str | None = None) -> str:
    cleaned = sorted(dict.fromkeys(path.replace("\\", "/").strip("/") for path in paths if path))
    payload = {"intent": intent or "", "paths": cleaned}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
