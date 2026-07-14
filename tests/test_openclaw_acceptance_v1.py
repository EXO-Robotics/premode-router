from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any

import pytest

import premode.openclaw_lifecycle as lifecycle
from premode.openclaw_adapter import qualify_openclaw_workspace
from premode.openclaw_contracts import OpenClawPreflightRequestV1, canonical_json_bytes
from premode.openclaw_preflight import run_openclaw_preflight
from premode.production_ranking import (
    ProductionRankingDecisionReceiptV1,
    ProductionRankingResultV1,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/openclaw_acceptance_v1.json"
FROZEN_FIXTURES_SHA256 = (
    "bf2065ef9124faf67ff7eac893ebaecf167312667729a5977b58ef4571f04657"
)


def _manifest() -> dict[str, Any]:
    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _ranking(task: dict[str, Any]) -> ProductionRankingResultV1:
    exact_task = str(task["task"])
    primary = tuple(str(path) for path in task["primary"])
    verify = tuple(str(path) for path in task["verify"])
    support = tuple(str(path) for path in task["support"])
    mode = str(task["mode"])
    receipt = ProductionRankingDecisionReceiptV1(
        exact_task_sha256=hashlib.sha256(exact_task.encode("utf-8")).hexdigest(),
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
        abstention_reason=None,
        decision_receipt=receipt,
    )


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


def test_acceptance_manifest_is_frozen_and_complete() -> None:
    manifest = _manifest()
    fixture_ids = [fixture["id"] for fixture in manifest["fixtures"]]
    tasks = [task for fixture in manifest["fixtures"] for task in fixture["tasks"]]

    assert manifest["schema_version"] == "pcodex.openclaw-acceptance.v1"
    assert manifest["frozen"] is True
    assert manifest["fixture_count"] == len(fixture_ids) == 10
    assert manifest["task_count"] == len(tasks) == 20
    assert len(fixture_ids) == len(set(fixture_ids))
    assert [task["id"] for task in tasks] == [f"T{index:02d}" for index in range(1, 21)]
    assert (
        hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
        == FROZEN_FIXTURES_SHA256
    )


def test_frozen_twenty_task_openclaw_acceptance_matrix(tmp_path: Path) -> None:
    manifest = _manifest()
    completed: list[str] = []
    for fixture in manifest["fixtures"]:
        workspace = tmp_path / str(fixture["id"]) / "workspace path Ω"
        workspace.mkdir(parents=True)
        if fixture["qualified"]:
            markers = (
                "AGENTS.md",
                "PROJECT/tasks.json",
                "PROJECT/AI/worker_start/WORKER_START_HERE.md",
            )
        elif fixture["id"] == "F07_missing_authority":
            markers = ("AGENTS.md", "PROJECT/tasks.json")
        else:
            markers = ("_claw_output/proof.json", "tools/symphony/readme.md")
        for marker in markers:
            _write(workspace, marker)
        for task in fixture["tasks"]:
            for path in (*task["primary"], *task["verify"], *task["support"]):
                _write(workspace, str(path))

        qualification = qualify_openclaw_workspace(workspace)
        assert qualification.qualified is bool(fixture["qualified"]), fixture["id"]
        home = tmp_path / str(fixture["id"]) / "home"
        home.mkdir()
        environ = {
            "HOME": str(home),
            "OPENCLAW_CONFIG_PATH": str(home / ".openclaw/openclaw.json"),
        }
        if not fixture["qualified"]:
            with pytest.raises(lifecycle.OpenClawLifecycleError):
                lifecycle.install_integration(workspace, environ=environ)
            completed.extend(str(task["id"]) for task in fixture["tasks"])
            continue

        lifecycle.install_integration(workspace, environ=environ)
        for task in fixture["tasks"]:
            before = _snapshot(tmp_path / str(fixture["id"]))
            exact_task = str(task["task"])

            def compile_runner(
                *_args: object, _task: dict[str, Any] = task, **_kwargs: object
            ) -> dict[str, Any]:
                return {"production_ranking": _ranking(_task).to_dict()}

            result = run_openclaw_preflight(
                workspace,
                OpenClawPreflightRequestV1(exact_task),
                compile_runner=compile_runner,
                environ=environ,
            ).result
            expected_mode = str(task.get("expected_mode") or task["mode"])
            assert result.routing_mode == expected_mode, task["id"]
            assert [item.path for item in result.ordered_likely_paths] == task[
                "expected_paths"
            ], task["id"]
            assert _snapshot(tmp_path / str(fixture["id"])) == before, task["id"]
            completed.append(str(task["id"]))

        lifecycle.uninstall_integration(workspace, environ=environ)

    assert completed == [f"T{index:02d}" for index in range(1, 21)]


def test_frozen_real_provider_measurement_is_stable_and_safe(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    latencies: list[float] = []
    expected_paths = 0
    recovered_paths = 0
    evaluated: list[str] = []
    forbidden_selected = 0
    misses: dict[str, dict[str, list[str]]] = {}
    for fixture in manifest["fixtures"]:
        if not fixture["qualified"]:
            continue
        workspace = tmp_path / str(fixture["id"]) / "workspace path Ω"
        workspace.mkdir(parents=True)
        for marker in (
            "AGENTS.md",
            "PROJECT/tasks.json",
            "PROJECT/AI/worker_start/WORKER_START_HERE.md",
        ):
            _write(workspace, marker)
        for task in fixture["tasks"]:
            for path in (*task["primary"], *task["verify"], *task["support"]):
                _write(workspace, str(path))
        home = tmp_path / str(fixture["id"]) / "home"
        home.mkdir()
        environ = {
            "HOME": str(home),
            "OPENCLAW_CONFIG_PATH": str(home / ".openclaw/openclaw.json"),
        }
        lifecycle.install_integration(workspace, environ=environ)
        for task in fixture["tasks"]:
            before = _snapshot(tmp_path / str(fixture["id"]))
            exact_task = str(task["task"])
            started = time.perf_counter()
            execution = run_openclaw_preflight(
                workspace,
                OpenClawPreflightRequestV1(exact_task),
                environ=environ,
            )
            latencies.append(time.perf_counter() - started)
            result = execution.result
            selected = [item.path for item in result.ordered_likely_paths[:5]]
            expected = [str(path) for path in task["expected_paths"]]
            expected_paths += len(expected)
            recovered_paths += len(set(expected).intersection(selected))
            if set(expected) - set(selected):
                misses[str(task["id"])] = {
                    "expected": expected,
                    "selected": selected,
                }
            forbidden_selected += sum(
                item.mutation_policy == "forbidden" and not item.explicitly_task_named
                for item in result.ordered_likely_paths
            )
            assert (
                result.exact_task_sha256
                == hashlib.sha256(exact_task.encode("utf-8")).hexdigest()
            )
            assert _snapshot(tmp_path / str(fixture["id"])) == before
            evaluated.append(str(task["id"]))
        lifecycle.uninstall_integration(workspace, environ=environ)

    p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
    recall = recovered_paths / expected_paths
    assert len(evaluated) == 16
    # This is a characterization receipt for the incumbent provider, not a
    # promotion threshold. The separate algorithm lane must supply a frozen
    # handoff before this measurement can be promoted as product evidence.
    assert (recovered_paths, expected_paths) == (13, 24), json.dumps(
        {"recall": recall, "misses": misses}, ensure_ascii=False, sort_keys=True
    )
    assert set(misses) == {
        "T01",
        "T02",
        "T03",
        "T07",
        "T08",
        "T15",
        "T16",
        "T17",
        "T18",
        "T20",
    }
    assert forbidden_selected == 0
    assert p95 < 1.0
