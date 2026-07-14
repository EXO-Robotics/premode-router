from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/premode"
RESEARCH_NAMES = {
    "live_token_harness",
    "sharded_runner",
}
PRODUCTION_ROOTS = {
    "adapter_policy",
    "codex_plugin",
    "compiler",
    "context_contracts",
    "core_packet",
    "managed_state",
    "no_write",
    "pcodex_bootstrap",
    "pcodex_subagent",
    "product_contract",
    "production_ranking",
    "production_ranking_incumbent",
}


def _top_level_local_imports(module: str) -> set[str]:
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports


def _all_local_imports(module: str, available: set[str]) -> set[str]:
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            dependency = node.module.split(".", 1)[0]
            if dependency in available:
                imports.add(dependency)
    return imports


def _transitive_local_imports(roots: set[str]) -> set[str]:
    available = {path.stem for path in SOURCE.glob("*.py")}
    graph = {module: _all_local_imports(module, available) for module in available}
    reached: set[str] = set()
    pending = list(roots)
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        pending.extend(graph.get(module, set()) - reached)
    return reached


def _is_forbidden_research_module(module: str) -> bool:
    lowered = module.casefold()
    return (
        module in RESEARCH_NAMES
        or lowered.startswith("lab73")
        or "observer" in lowered
        or "qwen" in lowered
    )


def test_production_import_graph_has_no_research_observer_or_qwen_modules() -> None:
    reached = _transitive_local_imports(PRODUCTION_ROOTS)
    forbidden = sorted(module for module in reached if _is_forbidden_research_module(module))
    assert forbidden == []


def test_product_boundaries_have_no_top_level_cross_adapter_imports() -> None:
    assert "openclaw_adapter" not in _top_level_local_imports("compiler")
    assert "openclaw_adapter" not in _top_level_local_imports("adapter_policy")
    assert "openclaw_adapter" not in _top_level_local_imports("codex_plugin")
    assert "codex_plugin" not in _top_level_local_imports("openclaw_adapter")


def test_research_module_classifier_covers_required_prefixes() -> None:
    for module in ("lab73x", "observer_bridge", "qwen_harness", *RESEARCH_NAMES):
        assert _is_forbidden_research_module(module)


def test_openclaw_policy_is_lazy_and_selected_only_by_adapter() -> None:
    sys.modules.pop("premode.openclaw_adapter", None)
    policy_module = importlib.reload(importlib.import_module("premode.adapter_policy"))

    assert policy_module.adapter_policy_from_detection(
        {"active_project": {"adapter": "python"}}
    ) is None
    assert "premode.openclaw_adapter" not in sys.modules

    policy = policy_module.adapter_policy_from_detection(
        {"active_project": {"adapter": "openclaw_control_plane"}}
    )
    assert policy is not None
    assert policy["authority_model"] == "proof_governed_control_plane"
    assert "premode.openclaw_adapter" in sys.modules


def test_release_source_excludes_raw_research_harnesses() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    policy = (ROOT / "release/artifact-allowlist.json").read_text(encoding="utf-8")
    for module in ("live_token_harness.py", "sharded_runner.py"):
        assert f"exclude src/premode/{module}" in manifest
        assert f'"src/premode/{module}"' in policy
    assert "recursive-exclude src/premode lab73*.py" in manifest
