from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Iterable


TASK_INTENT_VERSION = "1.0.0"
PATH_RE = re.compile(r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9]+)?(?![\w-])")
SYMBOL_RE = re.compile(r"\b(?:[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]*)\b")
NEGATIVE_RE = re.compile(r"(?i)\b(?:do not|don't|dont|avoid|without|exclude|ignore)\b[^.;\n]*")


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").replace("\\", "/").strip().rstrip(".,;:!?)]}")
        while clean.startswith("./"):
            clean = clean[2:]
        key = clean.casefold()
        if clean and key not in seen:
            out.append(clean)
            seen.add(key)
    return tuple(out)


@dataclass(frozen=True)
class TaskIntentV1:
    version: str
    exact_task_sha256: str
    explicit_path_intent: tuple[str, ...]
    symbol_intent: tuple[str, ...]
    implementation_intent: bool
    verification_intent: bool
    configuration_intent: bool
    build_intent: bool
    documentation_intent: bool
    generated_content_intent: bool
    repository_wide_intent: bool
    negative_scope_intent: tuple[str, ...]
    cross_package_intent: bool
    media_lookup_intent: bool
    ambiguity_flags: tuple[str, ...]
    ranking_evidence: object = field(repr=False, compare=False)

    @property
    def explicit_paths(self) -> tuple[str, ...]:
        return self.explicit_path_intent

    def to_candidate_context(self, *, support_only: bool = False) -> dict[str, object]:
        return {
            "explicit_paths": list(self.explicit_path_intent),
            "generated_intent": self.generated_content_intent,
            "support_only": support_only,
            "task_intent_version": self.version,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "exact_task_sha256": self.exact_task_sha256,
            "explicit_path_intent": list(self.explicit_path_intent),
            "symbol_intent": list(self.symbol_intent),
            "implementation_intent": self.implementation_intent,
            "verification_intent": self.verification_intent,
            "configuration_intent": self.configuration_intent,
            "build_intent": self.build_intent,
            "documentation_intent": self.documentation_intent,
            "generated_content_intent": self.generated_content_intent,
            "repository_wide_intent": self.repository_wide_intent,
            "negative_scope_intent": list(self.negative_scope_intent),
            "cross_package_intent": self.cross_package_intent,
            "media_lookup_intent": self.media_lookup_intent,
            "ambiguity_flags": list(self.ambiguity_flags),
        }


def compute_task_intent(exact_task: str) -> TaskIntentV1:
    task = str(exact_task)
    lower = task.casefold()
    paths = _ordered_unique(PATH_RE.findall(task))
    symbols = _ordered_unique(SYMBOL_RE.findall(task))
    negative = _ordered_unique(match.group(0).strip() for match in NEGATIVE_RE.finditer(task))
    positive_task = NEGATIVE_RE.sub("", task)
    implementation = bool(re.search(r"(?i)\b(fix|change|update|implement|add|remove|rename|refactor|patch|modify)\b", positive_task))
    verification = bool(re.search(r"(?i)\b(test|tests|verify|verification|regression|validate|validation)\b", task))
    configuration = bool(re.search(r"(?i)\b(config|configuration|settings|manifest|toml|yaml|yml|json)\b", task))
    build = bool(re.search(r"(?i)\b(build|package|packaging|install|installer|command surface|cli|entry point|workflow|ci)\b", task))
    documentation = bool(re.search(r"(?i)\b(readme|docs|documentation|guide|changelog)\b", task))
    generated = bool(re.search(r"(?i)\b(generate|generated|generating|codegen|vendor|vendored|build output|derived data)\b", task))
    repository_wide = bool(re.search(r"(?i)\b(repository[- ]wide|whole repository|entire repository|review this repository|review the repository broadly|broad refactor|refactor broadly)\b", task))
    cross_package = bool(re.search(r"(?i)\b(cross[- ]package|workspace|monorepo|multiple packages|package boundary)\b", task)) or len({path.split("/")[1] for path in paths if path.startswith("packages/") and len(path.split("/")) > 2}) > 1
    media_lookup = bool(re.search(r"(?i)\b(find|locate|show|list|identify|where)\b", positive_task) and re.search(r"(?i)\b(png|jpe?g|webp|gif|svg|image|sprite|icon|texture|asset|blend|blender|media|render)\b", positive_task)) and not implementation
    ambiguity: list[str] = []
    if repository_wide and not paths and not symbols:
        ambiguity.append("repository_wide_without_target")
    basenames = [path.rsplit("/", 1)[-1].casefold() for path in paths]
    if len(basenames) != len(set(basenames)):
        ambiguity.append("duplicate_explicit_basename")
    if generated and not paths:
        ambiguity.append("generated_intent_without_path")
    if cross_package:
        ambiguity.append("cross_package_intent")
    # The incumbent lexical parser is invoked exactly once under TaskIntentV1
    # ownership. Downstream locator/ranker code consumes this same object and
    # never reparses the raw task.
    from .locator import extract_prompt_evidence
    ranking_evidence = extract_prompt_evidence(task)
    return TaskIntentV1(
        version=TASK_INTENT_VERSION,
        exact_task_sha256=hashlib.sha256(task.encode("utf-8")).hexdigest(),
        explicit_path_intent=paths,
        symbol_intent=symbols,
        implementation_intent=implementation,
        verification_intent=verification,
        configuration_intent=configuration,
        build_intent=build,
        documentation_intent=documentation,
        generated_content_intent=generated,
        repository_wide_intent=repository_wide,
        negative_scope_intent=negative,
        cross_package_intent=cross_package,
        media_lookup_intent=media_lookup,
        ambiguity_flags=tuple(ambiguity),
        ranking_evidence=ranking_evidence,
    )
