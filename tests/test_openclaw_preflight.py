from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

import premode.openclaw_lifecycle as lifecycle
from premode.openclaw_contracts import OpenClawPreflightRequestV1
from premode.openclaw_preflight import (
    openclaw_preflight_backend,
    run_openclaw_preflight,
)
from premode.production_ranking import (
    ProductionRankingDecisionReceiptV1,
    ProductionRankingResultV1,
)
from premode.write_policy import ADVISORY


def _write(root: Path, relative: str, content: str = "{}\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "workspace"
    root.mkdir()
    for path in (
        "AGENTS.md",
        "PROJECT/tasks.json",
        "PROJECT/AI/worker_start/WORKER_START_HERE.md",
        "src/app.py",
        "tests/test_app.py",
        "PROJECT/state/history/old.json",
        "Content/Maps/World.umap",
    ):
        _write(root, path)
    home = tmp_path / "home"
    home.mkdir()
    return root, {
        "HOME": str(home),
        "OPENCLAW_CONFIG_PATH": str(home / ".openclaw/openclaw.json"),
    }


@pytest.fixture(autouse=True)
def _supported_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lifecycle,
        "openclaw_compatibility",
        lambda: {
            "installed": True,
            "version": "2026.4.14",
            "supported": True,
            "reason": "supported",
        },
    )
    monkeypatch.setattr(
        lifecycle, "_installed_helper_authority_available", lambda _path: True
    )


def _ranking(
    task: str,
    *,
    mode: str = "narrow",
    primary: tuple[str, ...] = ("src/app.py",),
    verify: tuple[str, ...] = ("tests/test_app.py",),
    support: tuple[str, ...] = ("PROJECT/tasks.json",),
    reason: str | None = None,
) -> ProductionRankingResultV1:
    receipt = ProductionRankingDecisionReceiptV1(
        exact_task_sha256=hashlib.sha256(task.encode("utf-8")).hexdigest(),
        routing_mode=mode,
        primary_path_count=len(primary),
        verify_path_count=len(verify),
        support_path_count=len(support),
        source_contract="pcodex.routing-decision.v1",
    )
    return ProductionRankingResultV1(
        routing_mode=mode,
        primary_paths=primary,
        verify_paths=verify,
        support_paths=support,
        abstention_reason=reason,
        decision_receipt=receipt,
    )


def _install(workspace: Path, environ: dict[str, str]) -> None:
    lifecycle.install_integration(workspace, environ=environ)


def test_preflight_uses_frozen_provider_once_and_returns_content_free_result(
    tmp_path: Path,
) -> None:
    workspace, environ = _workspace(tmp_path)
    _install(workspace, environ)
    task = "Fix src/app.py and verify its test"
    calls: list[tuple[Path, str, str, object]] = []

    def compile_runner(
        root: Path, exact_task: str, profile: str, *, write_policy: object
    ) -> dict[str, Any]:
        calls.append((root, exact_task, profile, write_policy))
        return {"production_ranking": _ranking(exact_task).to_dict()}

    execution = run_openclaw_preflight(
        workspace,
        OpenClawPreflightRequestV1(task),
        compile_runner=compile_runner,
        environ=environ,
    )

    assert calls == [(workspace, task, "lite", ADVISORY)]
    result = execution.result
    assert result.routing_mode == "narrow"
    assert [item.path for item in result.ordered_likely_paths] == [
        "src/app.py",
        "tests/test_app.py",
        "PROJECT/tasks.json",
    ]
    assert result.ordered_likely_paths[0].authority_class == "authored_source"
    assert result.ordered_likely_paths[1].authority_class == "validation_surface"
    assert result.ordered_likely_paths[2].authority_class == "current_authority"
    assert [item.path for item in result.expected_validation_surfaces] == [
        "tests/test_app.py"
    ]
    assert task not in result.canonical_bytes().decode("utf-8")
    assert execution.receipt.receipt_id == result.receipt_id


def test_unmentioned_historical_provider_path_is_removed_without_reranking(
    tmp_path: Path,
) -> None:
    workspace, environ = _workspace(tmp_path)
    _install(workspace, environ)
    task = "Investigate current app behavior"

    def compile_runner(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "production_ranking": _ranking(
                task,
                primary=("PROJECT/state/history/old.json", "src/app.py"),
                verify=(),
                support=(),
            ).to_dict()
        }

    result = run_openclaw_preflight(
        workspace,
        OpenClawPreflightRequestV1(task),
        compile_runner=compile_runner,
        environ=environ,
    ).result

    assert [item.path for item in result.ordered_likely_paths] == ["src/app.py"]


def test_exact_named_history_remains_read_only_evidence(tmp_path: Path) -> None:
    workspace, environ = _workspace(tmp_path)
    _install(workspace, environ)
    path = "PROJECT/state/history/old.json"
    task = f"Compare {path} to current authority"

    def compile_runner(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "production_ranking": _ranking(
                task, primary=(path,), verify=(), support=()
            ).to_dict()
        }

    item = run_openclaw_preflight(
        workspace,
        OpenClawPreflightRequestV1(task),
        compile_runner=compile_runner,
        environ=environ,
    ).result.ordered_likely_paths[0]

    assert item.authority_class == "historical_evidence"
    assert item.mutation_policy == "read_only"
    assert item.explicitly_task_named is True


def test_direct_binary_asset_mutation_abstains(tmp_path: Path) -> None:
    workspace, environ = _workspace(tmp_path)
    _install(workspace, environ)
    path = "Content/Maps/World.umap"
    task = f"Modify {path} directly"

    def compile_runner(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "production_ranking": _ranking(
                task, primary=(path,), verify=(), support=()
            ).to_dict()
        }

    result = run_openclaw_preflight(
        workspace,
        OpenClawPreflightRequestV1(task),
        compile_runner=compile_runner,
        environ=environ,
    ).result

    assert result.routing_mode == "abstain"
    assert result.abstention_reason == "conservative_safety_boundary"
    assert result.ordered_likely_paths == ()


def test_fallback_provider_result_never_exposes_paths(tmp_path: Path) -> None:
    workspace, environ = _workspace(tmp_path)
    _install(workspace, environ)
    task = "Broad ambiguous task"

    def compile_runner(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "production_ranking": _ranking(
                task,
                mode="fallback",
                primary=(),
                verify=(),
                support=(),
            ).to_dict()
        }

    result = run_openclaw_preflight(
        workspace,
        OpenClawPreflightRequestV1(task),
        compile_runner=compile_runner,
        environ=environ,
    ).result

    assert result.routing_mode == "fallback"
    assert result.ordered_likely_paths == ()


def test_backend_projection_contains_no_task_or_absolute_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, environ = _workspace(tmp_path)
    _install(workspace, environ)
    task = "Fix src/app.py"
    import premode.openclaw_preflight as service

    def compile_runner(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {"production_ranking": _ranking(task).to_dict()}

    monkeypatch.setattr(service, "_default_compile_runner", compile_runner)
    monkeypatch.setenv("HOME", environ["HOME"])
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", environ["OPENCLAW_CONFIG_PATH"])
    result = openclaw_preflight_backend(workspace, task, "openclaw")

    rendered = repr(result)
    assert task not in rendered
    assert str(workspace) not in rendered
    assert result["receipt_id"].startswith("ocpr_")
