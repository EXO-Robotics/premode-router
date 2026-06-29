from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .adapters import adapter_acceptance_checks

@dataclass(frozen=True)
class IntentRule:
    name: str
    keywords: tuple[str, ...]
    base: float


INTENT_RULES = [
    IntentRule("compile_repair", ("fix", "build", "compile", "compiler", "xcodebuild", "pytest", "test fail", "error", "failing", "cannot find", "missing type"), 0.35),
    IntentRule("test_failure", ("test failed", "failing test", "pytest", "unit test", "integration test", "coverage", "regression"), 0.30),
    IntentRule("controlled_patch", ("patch", "don't expand", "do not expand", "scope", "minimal", "smallest", "one focused", "no unrelated"), 0.30),
    IntentRule("feature_build", ("add feature", "implement", "build out", "new feature", "vertical slice", "day report", "receipt", "receipts"), 0.25),
    IntentRule("bug_fix", ("bug", "broken", "fix", "incorrect", "regression", "doesn't work"), 0.25),
    IntentRule("refactor", ("refactor", "cleanup", "rework", "simplify", "rename"), 0.22),
    IntentRule("ui_change", ("ui", "layout", "screen", "view", "figma", "design", "mockup", "style", "day report", "result screen", "report screen"), 0.24),
    IntentRule("documentation", ("readme", "docs", "documentation", "prompt", "changelog"), 0.18),
    IntentRule("branch_review", ("branch", "commit", "qwen", "opus", "diff", "merge", "review", "what changed", "audit changes"), 0.28),
    IntentRule("log_triage", ("log", "stacktrace", "traceback", "exception", "crash", "diagnose", "root cause"), 0.28),
    IntentRule("release_check", ("testflight", "release", "playtest", "qa", "ship", "acceptance", "verification", "smoke test"), 0.22),
    IntentRule("dependency_update", ("dependency", "dependencies", "package", "lockfile", "upgrade", "version bump"), 0.20),
    IntentRule("security_review", ("security", "secret", "vulnerability", "private key", "credential", "token leak"), 0.25),
]

PRIMARY_FALLBACK = "general_task"


def _normalize(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.lower()).strip()


def classify_task(prompt: str, repo_state: dict[str, Any] | None = None, log_state: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _normalize(prompt)
    matches: list[dict[str, Any]] = []
    for rule in INTENT_RULES:
        hits = [kw for kw in rule.keywords if kw in text]
        score = rule.base + min(0.55, 0.10 * len(hits))
        if hits:
            if rule.name in {"compile_repair", "test_failure"} and log_state and log_state.get("meaningful_errors"):
                score += 0.10
            if rule.name == "branch_review" and repo_state and repo_state.get("dirty_files"):
                score += 0.08
            matches.append({"name": rule.name, "confidence": round(min(score, 0.98), 2), "signals": hits[:8]})
    if not matches:
        matches.append({"name": PRIMARY_FALLBACK, "confidence": 0.50, "signals": []})
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    return {"primary_intent": matches[0]["name"], "intents": matches[:5]}


def tool_plan_for_intents(classification: dict[str, Any], project_detection: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    names = {i["name"] for i in classification.get("intents", [])}
    plan: list[dict[str, Any]] = []
    active = (project_detection or {}).get("active_project", {})
    if active:
        plan.append({"tool": "project adapter", "purpose": f"Use detected adapter `{active.get('project_kind', 'generic')}` for build/log/acceptance hints."})
    if "compile_repair" in names or "test_failure" in names:
        plan.extend([
            {"tool": "git status/diff", "purpose": "Understand uncommitted work before editing."},
            {"tool": "configured build/test command", "purpose": "Use .premode/commands.json command hints when verifying."},
            {"tool": "targeted file edit", "purpose": "Apply the smallest compile-safe repair."},
        ])
    if "log_triage" in names:
        plan.append({"tool": "log scanner", "purpose": "Use first meaningful errors and adapter log patterns before guessing."})
    if "branch_review" in names:
        plan.append({"tool": "git log/status", "purpose": "Check branch, recent commits, dirty files, and patch boundary."})
    if "controlled_patch" in names:
        plan.append({"tool": "scope guard", "purpose": "Reject broad rewrites and keep changes within the requested patch."})
    if "test_failure" in names:
        plan.append({"tool": "test runner", "purpose": "Reproduce and repair failing tests."})
    if "documentation" in names:
        plan.append({"tool": "docs/rules reader", "purpose": "Update documentation without touching unrelated source."})
    if not plan:
        plan.append({"tool": "repo inspection", "purpose": "Read selected context and make the smallest useful change."})
    return plan


def acceptance_checks_for_intents(classification: dict[str, Any], project_detection: dict[str, Any] | None = None) -> list[str]:
    names = {i["name"] for i in classification.get("intents", [])}
    checks = [
        "Explain files changed and why.",
        "Report commands run and exact pass/fail results.",
        "List remaining risks honestly.",
    ]
    if "compile_repair" in names:
        checks.insert(0, "Run the relevant build or test command that proves the compile repair.")
    if "test_failure" in names:
        checks.insert(0, "Reproduce or identify the failing test before changing behavior.")
    if "controlled_patch" in names:
        checks.insert(0, "Keep the patch focused; do not expand product scope or rewrite unrelated systems.")
    if "branch_review" in names:
        checks.insert(0, "Compare work against git status/diff before deciding what to change.")
    if "log_triage" in names:
        checks.insert(0, "Tie the fix to the first meaningful error or failure signature found in logs.")
    if "documentation" in names:
        checks.insert(0, "Keep docs changes accurate and scoped to requested updates.")
    for item in adapter_acceptance_checks(classification, project_detection or {}):
        if item not in checks:
            checks.insert(0, item)
    return checks


def scope_guardrails_for_intents(classification: dict[str, Any], project_detection: dict[str, Any] | None = None) -> list[str]:
    names = {i["name"] for i in classification.get("intents", [])}
    active = (project_detection or {}).get("active_project", {})
    guardrails = [
        "Do not request or rely on the original raw prompt; this compiled packet replaces it.",
        "Do not read ignored, binary, build output, vendor, asset, or secret-like files unless explicitly granted.",
        "Prefer minimal, reviewable edits over broad rewrites.",
    ]
    if active:
        guardrails.append(f"Use project-kind `{active.get('project_kind', 'generic')}` as a hint, not an absolute constraint.")
    if "controlled_patch" in names:
        guardrails.append("Treat the task as a bounded patch; avoid opportunistic refactors.")
    if "compile_repair" in names:
        guardrails.append("Fix the build failure first; defer feature expansion until the build/test gate passes.")
    return guardrails
