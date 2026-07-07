from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from contextlib import contextmanager

from . import __version__
from .codex_exec import CodexOptions, build_codex_invocation
from .live_ledger import parse_jsonl_usage
from .pcodex_bootstrap import cleanup_local_state, first_run_receipt, run_dry_run, run_enabled, set_enabled


DEFAULT_ARTIFACT_ROOT = Path("/private/tmp/premode_labs/lab_7_3cy_live_token_harness_recovery")
LIVE_SPEND_ENV = "PREMODE_ENABLE_LIVE_CODEX_SPEND_TEST"
LIVE_MATRIX_ENV = "PREMODE_ENABLE_LIVE_CODEX_MATRIX"
CODEX_AUTH_MODE_ENV = "PREMODE_CODEX_AUTH_MODE"
CODEX_AUTH_ALLOW_COPY_ENV = "PREMODE_ALLOW_CODEX_AUTH_CACHE_COPY"
CODEX_AUTH_SOURCE_HOME_ENV = "PREMODE_CODEX_AUTH_SOURCE_HOME"
DEFAULT_PROMPT_ID = "disposable_smoke"
DEFAULT_PROMPT = "Create or update only a disposable file named scratch_pcodex_smoke.txt with the text 'pcodex smoke ok'. Do not modify any other files."
HARNESS_VERSION = "lab_7_3de.v1"


def run_live_token_harness(
    *,
    source_repo: Path,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    mode: str = "dry_run_mock",
    prompt: str = DEFAULT_PROMPT,
    prompt_id: str = DEFAULT_PROMPT_ID,
    model: str | None = None,
    effort: str | None = None,
    fixture_repo: Path | None = None,
    task_matrix: Path | None = None,
    fixture_root: Path | None = None,
    matrix_seed: int | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a safe standard-vs-enhanced token harness pair.

    The default mode validates lane mechanics only. Live Codex execution is
    refused unless the explicit live-spend environment flag is set.
    """

    env = dict(os.environ if env is None else env)
    mode = _normalize_mode(mode)
    if mode in {"live_minimal", "live_matrix"} and env.get(LIVE_SPEND_ENV) != "1":
        return _blocked_live_result(source_repo, artifact_root, mode, prompt, prompt_id, model, effort)
    if mode == "live_matrix" and env.get(LIVE_MATRIX_ENV) != "1":
        return _blocked_live_result(
            source_repo,
            artifact_root,
            mode,
            prompt,
            prompt_id,
            model,
            effort,
            reason=f"{LIVE_MATRIX_ENV}_not_enabled",
        )

    source_repo = source_repo.resolve()
    if task_matrix is not None:
        return _run_matrix_harness(
            source_repo=source_repo,
            artifact_root=artifact_root,
            mode=mode,
            task_matrix=task_matrix,
            fixture_root=fixture_root,
            model=model,
            effort=effort,
            matrix_seed=matrix_seed,
            env=env,
        )

    artifact_root.mkdir(parents=True, exist_ok=True)
    run_id = _run_id()
    run_root = artifact_root / run_id
    fixture_root = _prepare_fixture(run_root, fixture_repo=fixture_repo, source_repo=source_repo)
    standard_repo = run_root / "lanes" / "standard" / "repo"
    enhanced_repo = run_root / "lanes" / "enhanced" / "repo"
    _copy_fixture(fixture_root, standard_repo)
    _copy_fixture(fixture_root, enhanced_repo)
    prompt_sha = _sha256(prompt)
    source_head = _git_text(source_repo, ["rev-parse", "HEAD"])
    standard_env = _lane_env(run_root / "lanes" / "standard", base_env=env)
    enhanced_env = _lane_env(run_root / "lanes" / "enhanced", base_env=env)

    started = time.perf_counter()
    if mode == "dry_run_mock":
        standard = _run_standard_dry(standard_repo, prompt_sha, model=model, effort=effort)
        enhanced = _run_enhanced_dry(enhanced_repo, prompt, prompt_sha, enhanced_env, model=model, effort=effort)
        live_codex_run = False
    else:
        auth = _prepare_pair_auth(standard_env, enhanced_env)
        if not auth["authenticated"]:
            standard = {**_empty_lane("standard", "codex_auth_unavailable"), "auth": auth["standard"]}
            enhanced = {**_empty_lane("enhanced", "codex_auth_unavailable"), "auth": auth["enhanced"]}
            live_codex_run = False
            return _finalize_pair_result(
                source_repo=source_repo,
                run_root=run_root,
                run_id=run_id,
                started=started,
                mode=mode,
                prompt=prompt,
                prompt_id=prompt_id,
                prompt_sha=prompt_sha,
                model=model,
                effort=effort,
                fixture_root=fixture_root,
                fixture_kind="synthetic_disposable" if fixture_repo is None else "explicit_disposable_copy",
                standard_repo=standard_repo,
                enhanced_repo=enhanced_repo,
                standard_env=standard_env,
                enhanced_env=enhanced_env,
                standard=standard,
                enhanced=enhanced,
                live_codex_run=False,
                quality_outcome="blocked_before_live_spend",
                extra_caveats=["codex_auth_unavailable"],
            )
        standard = _run_standard_live(standard_repo, prompt, prompt_sha, run_root / "lanes" / "standard", standard_env, model=model, effort=effort)
        enhanced = _run_enhanced_live(enhanced_repo, prompt, prompt_sha, run_root / "lanes" / "enhanced", enhanced_env, model=model, effort=effort)
        live_codex_run = True

    return _finalize_pair_result(
        source_repo=source_repo,
        run_root=run_root,
        run_id=run_id,
        started=started,
        mode=mode,
        prompt=prompt,
        prompt_id=prompt_id,
        prompt_sha=prompt_sha,
        model=model,
        effort=effort,
        fixture_root=fixture_root,
        fixture_kind="synthetic_disposable" if fixture_repo is None else "explicit_disposable_copy",
        standard_repo=standard_repo,
        enhanced_repo=enhanced_repo,
        standard_env=standard_env,
        enhanced_env=enhanced_env,
        standard=standard,
        enhanced=enhanced,
        live_codex_run=live_codex_run,
        quality_outcome="dry_run_mechanics_passed" if mode == "dry_run_mock" else "live_result_requires_human_review",
    )


def _finalize_pair_result(
    *,
    source_repo: Path,
    run_root: Path,
    run_id: str,
    started: float,
    mode: str,
    prompt: str,
    prompt_id: str,
    prompt_sha: str,
    model: str | None,
    effort: str | None,
    fixture_root: Path | None,
    fixture_kind: str,
    standard_repo: Path,
    enhanced_repo: Path,
    standard_env: dict[str, str],
    enhanced_env: dict[str, str],
    standard: dict[str, Any],
    enhanced: dict[str, Any],
    live_codex_run: bool,
    quality_outcome: str,
    extra_caveats: list[str] | None = None,
) -> dict[str, Any]:
    source_head = _git_text(source_repo, ["rev-parse", "HEAD"])
    delta = _delta(standard, enhanced)
    quality = {
        "task_outcome": quality_outcome,
        "standard_exit_code": standard.get("exit_code"),
        "enhanced_exit_code": enhanced.get("exit_code"),
        "quality_same_or_better": None,
        "human_outcome": None,
    }
    safety = {
        "repo_isolation_verified": standard_repo != enhanced_repo and standard_repo.exists() and enhanced_repo.exists(),
        "home_isolation_verified": standard_env["HOME"] != enhanced_env["HOME"],
        "tmpdir_isolation_verified": standard_env["TMPDIR"] != enhanced_env["TMPDIR"],
        "codex_home_isolation_verified": standard_env["CODEX_HOME"] != enhanced_env["CODEX_HOME"],
        "premode_state_isolated": (standard_repo / ".premode") != (enhanced_repo / ".premode"),
        "developer_source_repo_used_as_target": False,
        "raw_prompt_in_aggregate": False,
        "raw_source_snippets_in_aggregate": False,
    }
    result = {
        "schema_version": "premode.live_token_harness.result.v1",
        "run_id": run_id,
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "source_head": source_head,
        "harness_version": HARNESS_VERSION,
        "mode": mode,
        "live_codex_run": live_codex_run,
        "live_usage_available": bool(standard.get("usage_available") or enhanced.get("usage_available")),
        "usage_source": _combined_usage_source(standard, enhanced),
        "repo_fixture": {
            "kind": fixture_kind,
            "fixture_path": str(fixture_root),
            "standard_repo": str(standard_repo),
            "enhanced_repo": str(enhanced_repo),
            "head": _git_text(fixture_root, ["rev-parse", "HEAD"]),
        },
        "prompt_id": prompt_id,
        "prompt_sha256": prompt_sha,
        "model": model,
        "model_provider": "codex_cli" if live_codex_run else None,
        "effort": effort,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "cost_estimate": None,
        "cost_estimate_available": False,
        "standard": standard,
        "enhanced": enhanced,
        "delta": delta,
        "quality": quality,
        "safety": safety,
        "caveats": _caveats(mode, standard, enhanced),
    }
    if extra_caveats:
        result["caveats"].extend(extra_caveats)
    _write_json(run_root / "LIVE_TOKEN_HARNESS_RESULTS.json", result)
    _write_text(run_root / "LIVE_TOKEN_HARNESS_REPORT.md", render_harness_report(result))
    return result


def parse_usage_file(path: Path) -> dict[str, Any]:
    usage = parse_jsonl_usage(path)
    return _usage_fields(usage, source=str(path))


def render_harness_report(result: dict[str, Any]) -> str:
    lines = [
        "# Standard-vs-Enhanced Live Token Harness Result",
        "",
        f"- Run id: `{result.get('run_id')}`",
        f"- Mode: `{result.get('mode')}`",
        f"- Live Codex run: `{result.get('live_codex_run')}`",
        f"- Usage source: `{result.get('usage_source')}`",
        f"- Usage available: `{result.get('live_usage_available')}`",
        f"- Prompt hash: `{result.get('prompt_sha256')}`",
        "",
        "## Boundaries",
        "",
        "- Aggregate artifacts contain prompt hashes, not raw prompts.",
        "- Usage fields remain null when Codex does not expose parseable usage.",
        "- This harness does not claim universal savings, guaranteed cache hits, or native installed-Codex interception.",
        "",
        "## Lanes",
        "",
    ]
    for lane_name in ("standard", "enhanced"):
        lane = result.get(lane_name) if isinstance(result.get(lane_name), dict) else {}
        lines.extend(
            [
                f"### {lane_name}",
                "",
                f"- Exit code: `{lane.get('exit_code')}`",
                f"- Duration ms: `{lane.get('duration_ms')}`",
                f"- Usage available: `{lane.get('usage_available')}`",
                f"- Usage unavailable reason: `{lane.get('usage_unavailable_reason')}`",
                f"- Files changed: `{lane.get('files_changed')}`",
                f"- Tests passed: `{lane.get('tests_passed')}`",
                f"- Cleanup status: `{lane.get('cleanup_status')}`",
                "",
            ]
        )
    return "\n".join(lines)


def _run_matrix_harness(
    *,
    source_repo: Path,
    artifact_root: Path,
    mode: str,
    task_matrix: Path,
    fixture_root: Path | None,
    model: str | None,
    effort: str | None,
    matrix_seed: int | None,
    env: dict[str, str],
) -> dict[str, Any]:
    artifact_root.mkdir(parents=True, exist_ok=True)
    run_id = _run_id()
    run_root = artifact_root / run_id
    matrix_payload = _load_task_matrix(task_matrix)
    tasks = matrix_payload["tasks"]
    seed = int(matrix_seed if matrix_seed is not None else matrix_payload.get("random_seed", 733))
    rng = random.Random(seed)
    source_head = _git_text(source_repo, ["rev-parse", "HEAD"])
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    live_requested = mode in {"live_minimal", "live_matrix"}

    if live_requested:
        probe_auth = _prepare_pair_auth(
            _lane_env(run_root / "auth_probe" / "standard", base_env=env),
            _lane_env(run_root / "auth_probe" / "enhanced", base_env=env),
        )
        if not probe_auth["authenticated"]:
            result = _matrix_blocked_result(
                run_id=run_id,
                created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                source_head=source_head,
                mode=mode,
                seed=seed,
                task_count=len(tasks),
                reason="codex_auth_unavailable",
                auth=probe_auth,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            _write_json(run_root / "LIVE_TOKEN_HARNESS_MATRIX_RESULTS.json", result)
            _write_text(run_root / "LIVE_TOKEN_HARNESS_MATRIX_REPORT.md", render_matrix_report(result))
            return result

    for task in tasks:
        task_id = str(task["task_id"])
        prompt = str(task["prompt_text"])
        prompt_sha = _sha256(prompt)
        lane_order = ["standard", "enhanced"]
        rng.shuffle(lane_order)
        task_root = run_root / "tasks" / task_id
        fixture = _matrix_fixture_path(task, fixture_root=fixture_root, source_repo=source_repo)
        standard_repo = task_root / "lanes" / "standard" / "repo"
        enhanced_repo = task_root / "lanes" / "enhanced" / "repo"
        _copy_fixture(fixture, standard_repo)
        _copy_fixture(fixture, enhanced_repo)
        standard_env = _lane_env(task_root / "lanes" / "standard", base_env=env)
        enhanced_env = _lane_env(task_root / "lanes" / "enhanced", base_env=env)
        lane_auth = _prepare_pair_auth(standard_env, enhanced_env) if live_requested else None
        if live_requested and lane_auth and not lane_auth["authenticated"]:
            result = _matrix_blocked_result(
                run_id=run_id,
                created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                source_head=source_head,
                mode=mode,
                seed=seed,
                task_count=len(tasks),
                reason="codex_auth_unavailable",
                auth=lane_auth,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            result["tasks"] = rows
            result["lane_record_count"] = len(rows) * 2
            _write_json(run_root / "LIVE_TOKEN_HARNESS_MATRIX_RESULTS.json", result)
            _write_text(run_root / "LIVE_TOKEN_HARNESS_MATRIX_REPORT.md", render_matrix_report(result))
            return result
        lane_results: dict[str, dict[str, Any]] = {}
        for lane in lane_order:
            if lane == "standard":
                lane_results["standard"] = (
                    _run_standard_matrix_dry(standard_repo, prompt_sha, task, model=model, effort=effort)
                    if mode == "dry_run_mock"
                    else _run_standard_live(standard_repo, prompt, prompt_sha, task_root / "lanes" / "standard", standard_env, model=model, effort=effort, task=task)
                )
            else:
                lane_results["enhanced"] = (
                    _run_enhanced_matrix_dry(enhanced_repo, prompt, prompt_sha, enhanced_env, task, model=model, effort=effort)
                    if mode == "dry_run_mock"
                    else _run_enhanced_live(enhanced_repo, prompt, prompt_sha, task_root / "lanes" / "enhanced", enhanced_env, model=model, effort=effort, task=task)
                )
        standard = lane_results["standard"]
        enhanced = lane_results["enhanced"]
        if lane_auth:
            standard["auth"] = lane_auth["standard"]
            enhanced["auth"] = lane_auth["enhanced"]
        rows.append(
            {
                "task_id": task_id,
                "fixture": task.get("fixture"),
                "fixture_head": _git_text(fixture, ["rev-parse", "HEAD"]),
                "prompt_sha256": prompt_sha,
                "prompt_raw_in_aggregate": False,
                "lane_order": lane_order,
                "standard": standard,
                "enhanced": enhanced,
                "delta": _delta(standard, enhanced),
                "quality": _task_quality(standard, enhanced),
                "safety": {
                    "repo_isolation_verified": standard_repo != enhanced_repo and standard_repo.exists() and enhanced_repo.exists(),
                    "home_isolation_verified": standard_env["HOME"] != enhanced_env["HOME"],
                    "tmpdir_isolation_verified": standard_env["TMPDIR"] != enhanced_env["TMPDIR"],
                    "codex_home_isolation_verified": standard_env["CODEX_HOME"] != enhanced_env["CODEX_HOME"],
                    "premode_state_isolated": (standard_repo / ".premode") != (enhanced_repo / ".premode"),
                    "developer_source_repo_used_as_target": False,
                    "raw_prompt_in_aggregate": False,
                    "raw_source_snippets_in_aggregate": False,
                    "auth_contents_in_aggregate": False,
                },
            }
        )

    result = {
        "schema_version": "premode.live_token_harness.matrix_result.v1",
        "run_id": run_id,
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "source_head": source_head,
        "harness_version": HARNESS_VERSION,
        "mode": mode,
        "live_codex_run": live_requested,
        "live_usage_available": any(r["standard"].get("usage_available") or r["enhanced"].get("usage_available") for r in rows),
        "usage_source": _combined_matrix_usage_source(rows),
        "task_pair_count": len(rows),
        "lane_record_count": len(rows) * 2,
        "matrix_seed": seed,
        "lane_order_randomized": True,
        "model": model,
        "model_provider": "codex_cli" if live_requested else None,
        "effort": effort,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "cost_estimate": None,
        "cost_estimate_available": False,
        "tasks": rows,
        "quality": {
            "standard_success_count": sum(1 for r in rows if r["quality"]["standard_success"]),
            "enhanced_success_count": sum(1 for r in rows if r["quality"]["enhanced_success"]),
            "same_or_better_quality_count": sum(1 for r in rows if r["quality"]["same_or_better_quality"]),
        },
        "safety": {
            "repo_isolation_verified": all(r["safety"]["repo_isolation_verified"] for r in rows),
            "home_isolation_verified": all(r["safety"]["home_isolation_verified"] for r in rows),
            "tmpdir_isolation_verified": all(r["safety"]["tmpdir_isolation_verified"] for r in rows),
            "codex_home_isolation_verified": all(r["safety"]["codex_home_isolation_verified"] for r in rows),
            "raw_prompt_in_aggregate": False,
            "raw_source_snippets_in_aggregate": False,
            "auth_contents_in_aggregate": False,
        },
        "caveats": _matrix_caveats(mode, rows),
    }
    _write_json(run_root / "LIVE_TOKEN_HARNESS_MATRIX_RESULTS.json", result)
    _write_text(run_root / "LIVE_TOKEN_HARNESS_MATRIX_REPORT.md", render_matrix_report(result))
    return result


def render_matrix_report(result: dict[str, Any]) -> str:
    lines = [
        "# Standard-vs-Enhanced Live Token Matrix Result",
        "",
        f"- Run id: `{result.get('run_id')}`",
        f"- Mode: `{result.get('mode')}`",
        f"- Task pairs: `{result.get('task_pair_count')}`",
        f"- Lane records: `{result.get('lane_record_count')}`",
        f"- Live Codex run: `{result.get('live_codex_run')}`",
        f"- Usage available: `{result.get('live_usage_available')}`",
        f"- Matrix seed: `{result.get('matrix_seed')}`",
        "",
        "## Boundaries",
        "",
        "- Aggregate artifacts contain prompt hashes, not raw prompts.",
        "- Auth contents and environment values are not serialized.",
        "- Raw logs stay under local non-paste-safe artifact paths.",
        "",
        "## Tasks",
        "",
        "| task_id | standard_exit | enhanced_exit | standard_usage | enhanced_usage |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for row in result.get("tasks") or []:
        lines.append(
            f"| {row.get('task_id')} | {row.get('standard', {}).get('exit_code')} | {row.get('enhanced', {}).get('exit_code')} | "
            f"{row.get('standard', {}).get('usage_available')} | {row.get('enhanced', {}).get('usage_available')} |"
        )
    return "\n".join(lines)


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "dry_run_mock").strip()
    if normalized not in {"dry_run_mock", "live_minimal", "live_matrix"}:
        raise ValueError(f"unsupported harness mode: {mode}")
    return normalized


def _blocked_live_result(
    source_repo: Path,
    artifact_root: Path,
    mode: str,
    prompt: str,
    prompt_id: str,
    model: str | None,
    effort: str | None,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    artifact_root.mkdir(parents=True, exist_ok=True)
    run_id = _run_id()
    payload = {
        "schema_version": "premode.live_token_harness.result.v1",
        "run_id": run_id,
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "source_head": _git_text(source_repo, ["rev-parse", "HEAD"]),
        "harness_version": HARNESS_VERSION,
        "mode": mode,
        "live_codex_run": False,
        "live_usage_available": False,
        "usage_source": None,
        "repo_fixture": None,
        "prompt_id": prompt_id,
        "prompt_sha256": _sha256(prompt),
        "model": model,
        "model_provider": None,
        "effort": effort,
        "standard": _empty_lane("standard", reason or f"{LIVE_SPEND_ENV}_not_enabled"),
        "enhanced": _empty_lane("enhanced", reason or f"{LIVE_SPEND_ENV}_not_enabled"),
        "delta": _empty_delta(reason or f"{LIVE_SPEND_ENV}_not_enabled"),
        "quality": {"task_outcome": "blocked_before_live_spend", "quality_same_or_better": None, "human_outcome": None},
        "safety": {
            "live_spend_env_required": LIVE_SPEND_ENV,
            "live_spend_env_present": False,
            "raw_prompt_in_aggregate": False,
            "raw_source_snippets_in_aggregate": False,
        },
        "caveats": [reason or f"{LIVE_SPEND_ENV}_not_enabled", "no_live_codex_executed", "no_usage_measured"],
    }
    run_root = artifact_root / run_id
    _write_json(run_root / "LIVE_TOKEN_HARNESS_RESULTS.json", payload)
    _write_text(run_root / "LIVE_TOKEN_HARNESS_REPORT.md", render_harness_report(payload))
    return payload


def _prepare_fixture(run_root: Path, *, fixture_repo: Path | None, source_repo: Path) -> Path:
    base = run_root / "fixture" / "base"
    if fixture_repo is not None:
        fixture = fixture_repo.resolve()
        if fixture == source_repo:
            raise ValueError("developer source worktree cannot be used as a harness target")
        _copy_fixture(fixture, base)
        return base
    base.mkdir(parents=True, exist_ok=True)
    (base / ".gitignore").write_text(".premode/\n.pcodex/\n__pycache__/\n", encoding="utf-8")
    (base / "app.py").write_text("def message():\n    return 'hello'\n", encoding="utf-8")
    (base / "README.md").write_text("# Disposable pCodex harness fixture\n", encoding="utf-8")
    (base / "scratch_pcodex_smoke.txt").write_text("initial\n", encoding="utf-8")
    _git(base, ["init"])
    _git(base, ["add", "."])
    _git(base, ["-c", "user.name=Pre Mode", "-c", "user.email=premode@example.test", "commit", "-m", "fixture baseline"])
    return base


def _load_task_matrix(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("task matrix must include a non-empty tasks array")
    normalized: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"task matrix entry {index} must be an object")
        task_id = str(task.get("task_id") or "").strip()
        prompt = task.get("prompt_text")
        if not task_id:
            raise ValueError(f"task matrix entry {index} is missing task_id")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"task {task_id} is missing prompt_text")
        normalized.append(
            {
                **task,
                "task_id": task_id,
                "prompt_text": prompt,
                "expected_files": list(task.get("expected_files") or []),
                "expected_tests": list(task.get("expected_tests") or []),
                "forbidden_files": list(task.get("forbidden_files") or []),
            }
        )
    return {**payload, "tasks": normalized}


def _matrix_fixture_path(task: dict[str, Any], *, fixture_root: Path | None, source_repo: Path) -> Path:
    if task.get("fixture_path"):
        fixture = Path(str(task["fixture_path"])).resolve()
    elif fixture_root is not None and task.get("fixture"):
        fixture = (fixture_root / str(task["fixture"])).resolve()
    else:
        raise ValueError(f"task {task.get('task_id')} must provide fixture_path or fixture with --fixture-root")
    if fixture == source_repo:
        raise ValueError("developer source worktree cannot be used as a harness target")
    if not fixture.exists():
        raise ValueError(f"fixture path does not exist for task {task.get('task_id')}: {fixture}")
    return fixture


def _copy_fixture(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".premode", ".pcodex", "__pycache__", ".pytest_cache"))


def _lane_env(lane_root: Path, *, base_env: dict[str, str] | None = None) -> dict[str, str]:
    home = lane_root / "home"
    tmp = lane_root / "tmp"
    codex_home = lane_root / "codex_home"
    pcodex_home = lane_root / "pcodex_home"
    for path in (home, tmp, codex_home, pcodex_home, lane_root / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ if base_env is None else base_env)
    env.update(
        {
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "CODEX_HOME": str(codex_home),
            "PCODEX_ALPHA_HOME": str(pcodex_home),
        }
    )
    return env


def _prepare_pair_auth(standard_env: dict[str, str], enhanced_env: dict[str, str]) -> dict[str, Any]:
    standard = _bootstrap_lane_auth(standard_env)
    enhanced = _bootstrap_lane_auth(enhanced_env)
    return {
        "standard": standard,
        "enhanced": enhanced,
        "authenticated": bool(standard.get("authenticated") and enhanced.get("authenticated")),
        "auth_contents_serialized": False,
    }


def _bootstrap_lane_auth(env: dict[str, str]) -> dict[str, Any]:
    mode = str(env.get(CODEX_AUTH_MODE_ENV) or "none").strip()
    payload: dict[str, Any] = {
        "auth_mode": mode,
        "authenticated": False,
        "auth_contents_serialized": False,
        "env_values_serialized": False,
    }
    if mode in {"", "none"}:
        payload["status"] = "skipped"
        payload["reason"] = f"{CODEX_AUTH_MODE_ENV}_not_enabled"
        return payload
    if mode == "inherit_auth_cache":
        if env.get(CODEX_AUTH_ALLOW_COPY_ENV) != "1":
            payload["status"] = "failed"
            payload["reason"] = f"{CODEX_AUTH_ALLOW_COPY_ENV}_not_enabled"
            return payload
        source_home = Path(env.get(CODEX_AUTH_SOURCE_HOME_ENV) or str(Path.home()))
        source_auth = source_home / ".codex" / "auth.json"
        if not source_auth.exists():
            payload["status"] = "failed"
            payload["reason"] = "source_auth_cache_missing"
            payload["source_auth_cache_present"] = False
            return payload
        copied = []
        for dest in (Path(env["HOME"]) / ".codex" / "auth.json", Path(env["CODEX_HOME"]) / "auth.json"):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_auth, dest)
            dest.chmod(0o600)
            copied.append(_auth_destination_label(dest, env))
        payload.update({"status": "copied", "source_auth_cache_present": True, "copied_auth_cache": True, "copied_destinations": copied})
    elif mode in {"api_key", "access_token"}:
        secret_name = "OPENAI_API_KEY" if mode == "api_key" else "CODEX_ACCESS_TOKEN"
        secret = env.get(secret_name)
        if not secret:
            payload["status"] = "failed"
            payload["reason"] = f"{secret_name}_missing"
            return payload
        flag = "--with-api-key" if mode == "api_key" else "--with-access-token"
        proc = subprocess.run(["codex", "login", flag], input=secret, cwd=Path(env["HOME"]), env=env, text=True, capture_output=True, check=False, timeout=120)
        payload.update({"status": "login_attempted", "login_exit_code": proc.returncode})
        if proc.returncode != 0:
            payload["reason"] = "codex_login_failed"
            return payload
    elif mode == "device_auth":
        proc = subprocess.run(["codex", "login", "--device-auth"], cwd=Path(env["HOME"]), env=env, text=True, capture_output=True, check=False, timeout=300)
        payload.update({"status": "device_auth_attempted", "login_exit_code": proc.returncode})
        if proc.returncode != 0:
            payload["reason"] = "codex_device_auth_failed"
            return payload
    else:
        payload["status"] = "failed"
        payload["reason"] = "unsupported_auth_mode"
        return payload
    status = _codex_login_status(env)
    payload["status_check"] = status
    payload["authenticated"] = bool(status.get("authenticated"))
    if not payload["authenticated"]:
        payload["reason"] = status.get("reason") or "codex_login_status_not_authenticated"
    return payload


def _auth_destination_label(path: Path, env: dict[str, str]) -> str:
    home_auth = Path(env["HOME"]) / ".codex" / "auth.json"
    codex_auth = Path(env["CODEX_HOME"]) / "auth.json"
    if path == home_auth:
        return "HOME/.codex/auth.json"
    if path == codex_auth:
        return "CODEX_HOME/auth.json"
    return "lane_auth_file"


def _codex_login_status(env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.run(["codex", "login", "status"], cwd=Path(env["HOME"]), env=env, text=True, capture_output=True, check=False, timeout=30)
    text = f"{proc.stdout}\n{proc.stderr}".lower()
    not_logged_in = "not logged in" in text or "unauthenticated" in text
    logged_in = ("logged in" in text or "authenticated" in text) and not not_logged_in
    return {
        "exit_code": proc.returncode,
        "authenticated": bool(proc.returncode == 0 and logged_in),
        "status": "authenticated" if proc.returncode == 0 and logged_in else "not_authenticated",
        "reason": None if proc.returncode == 0 and logged_in else "codex_login_status_not_authenticated",
    }


def _run_standard_dry(repo: Path, prompt_sha: str, *, model: str | None, effort: str | None) -> dict[str, Any]:
    started = time.perf_counter()
    tests = _run_tests(repo)
    cleanup = cleanup_local_state(repo, dry_run=False)
    return {
        **_lane_base("standard", prompt_sha, model=model, effort=effort),
        "command": ["codex", "exec", "-"],
        "exit_code": 0,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "usage_unavailable_reason": "dry_run_mock_no_live_codex",
        "files_changed": _changed_files(repo),
        "diff_line_count": _diff_line_count(repo),
        "tests_run": tests["commands"],
        "tests_passed": tests["passed"],
        "scope_drift": False,
        "review_patch_status": "not_run_no_patch",
        "generated_state_written": False,
        "cleanup_status": _cleanup_status(cleanup),
    }


def _run_standard_matrix_dry(repo: Path, prompt_sha: str, task: dict[str, Any], *, model: str | None, effort: str | None) -> dict[str, Any]:
    started = time.perf_counter()
    return {
        **_lane_base("standard", prompt_sha, model=model, effort=effort),
        "command": _codex_exec_command(repo, model=model),
        "exit_code": 0,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "usage_unavailable_reason": "dry_run_mock_no_live_codex",
        "files_changed": _changed_files(repo),
        "diff_line_count": _diff_line_count(repo),
        **_dry_validation(task),
        "scope_drift": False,
        "review_patch_status": "not_run_no_patch",
        "generated_state_written": False,
        "cleanup_status": "nothing_to_clean",
    }


def _run_enhanced_dry(
    repo: Path,
    prompt: str,
    prompt_sha: str,
    env: dict[str, str],
    *,
    model: str | None,
    effort: str | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    with _patched_environ(env):
        setup_result = set_enabled(repo, True)
        first_run = first_run_receipt(repo)
        dry = run_dry_run(repo, prompt, "lite")
        tests = _run_tests(repo)
        generated_state_written = (repo / ".premode").exists()
        cleanup = cleanup_local_state(repo, dry_run=False)
    return {
        **_lane_base("enhanced", prompt_sha, model=model, effort=effort),
        "command": [
            "pcodex setup --skip-tune --no-mcp",
            "pcodex on",
            "pcodex first-run --json",
            "pcodex run --dry-run <prompt>",
            "pcodex cleanup --local-state --yes",
        ],
        "exit_code": 0,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "usage_unavailable_reason": "dry_run_mock_no_live_codex",
        "files_changed": _changed_files(repo),
        "diff_line_count": _diff_line_count(repo),
        "tests_run": tests["commands"],
        "tests_passed": tests["passed"],
        "scope_drift": False,
        "review_patch_status": "not_run_no_patch",
        "generated_state_written": generated_state_written,
        "cleanup_status": _cleanup_status(cleanup),
        "pcodex_setup_status": setup_result.get("status"),
        "pcodex_first_run_schema": first_run.get("schema_version"),
        "pcodex_dry_run_status": dry.get("status"),
        "transform_applied": dry.get("transform_applied"),
        "packet_sha256": dry.get("packet_sha256"),
    }


def _run_enhanced_matrix_dry(
    repo: Path,
    prompt: str,
    prompt_sha: str,
    env: dict[str, str],
    task: dict[str, Any],
    *,
    model: str | None,
    effort: str | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    with _patched_environ(env):
        setup_result = set_enabled(repo, True)
        first_run = first_run_receipt(repo)
        dry = run_dry_run(repo, prompt, "lite")
        generated_state_written = (repo / ".premode").exists()
        cleanup = cleanup_local_state(repo, dry_run=False)
    return {
        **_lane_base("enhanced", prompt_sha, model=model, effort=effort),
        "command": [
            "pcodex setup --skip-tune --no-mcp",
            "pcodex on",
            "pcodex first-run --json",
            "pcodex run --dry-run <prompt>",
            "pcodex cleanup --local-state --yes",
        ],
        "exit_code": 0,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "usage_unavailable_reason": "dry_run_mock_no_live_codex",
        "files_changed": _changed_files(repo),
        "diff_line_count": _diff_line_count(repo),
        **_dry_validation(task),
        "scope_drift": False,
        "review_patch_status": "not_run_no_patch",
        "generated_state_written": generated_state_written,
        "cleanup_status": _cleanup_status(cleanup),
        "pcodex_setup_status": setup_result.get("status"),
        "pcodex_first_run_schema": first_run.get("schema_version"),
        "pcodex_dry_run_status": dry.get("status"),
        "transform_applied": dry.get("transform_applied"),
        "packet_sha256": dry.get("packet_sha256"),
    }


def _run_standard_live(
    repo: Path,
    prompt: str,
    prompt_sha: str,
    lane_root: Path,
    env: dict[str, str],
    *,
    model: str | None,
    effort: str | None,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    command = _codex_exec_command(repo, model=model)
    proc = subprocess.run(command, input=prompt, cwd=repo, env=env, text=True, capture_output=True, check=False)
    log = lane_root / "raw_logs_non_paste_safe" / "standard_stdout.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(proc.stdout or "", encoding="utf-8")
    (lane_root / "raw_logs_non_paste_safe" / "standard_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    usage = parse_usage_file(log)
    tests = _run_task_validation(repo, task) if task is not None else _run_tests(repo)
    cleanup = cleanup_local_state(repo, dry_run=False)
    return {
        **_lane_base("standard", prompt_sha, model=model, effort=effort),
        "command": command,
        "exit_code": proc.returncode,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        **usage,
        "files_changed": _changed_files(repo),
        "diff_line_count": _diff_line_count(repo),
        "tests_run": tests["commands"],
        "validation_command": tests["commands"],
        "validation_exit_code": tests["exit_code"],
        "tests_passed": tests["passed"],
        "forbidden_files_touched": tests.get("forbidden_files_touched", []),
        "scope_drift": tests.get("scope_drift", _scope_drift(repo)),
        "review_patch_status": "not_run",
        "generated_state_written": (repo / ".premode").exists(),
        "cleanup_status": _cleanup_status(cleanup),
    }


def _run_enhanced_live(
    repo: Path,
    prompt: str,
    prompt_sha: str,
    lane_root: Path,
    env: dict[str, str],
    *,
    model: str | None,
    effort: str | None,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    with _patched_environ(env):
        set_enabled(repo, True)
        first_run_receipt(repo)
        result = run_enabled(repo, prompt, "lite")
        tests = _run_task_validation(repo, task) if task is not None else _run_tests(repo)
        cleanup = cleanup_local_state(repo, dry_run=False)
    log = lane_root / "raw_logs_non_paste_safe" / "enhanced_stdout.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(str(result.get("stdout") or ""), encoding="utf-8")
    (lane_root / "raw_logs_non_paste_safe" / "enhanced_stderr.txt").write_text(str(result.get("stderr") or ""), encoding="utf-8")
    actual = result.get("actual_usage") if isinstance(result.get("actual_usage"), dict) else None
    usage = _usage_fields(actual, source="pcodex_run_actual_usage") if actual else parse_usage_file(log)
    return {
        **_lane_base("enhanced", prompt_sha, model=model, effort=effort),
        "command": [
            "pcodex setup --skip-tune --no-mcp",
            "pcodex on",
            "pcodex first-run --json",
            "pcodex run <prompt>",
            "pcodex cleanup --local-state --yes",
        ],
        "exit_code": result.get("returncode"),
        "duration_ms": round((time.perf_counter() - started) * 1000),
        **usage,
        "files_changed": _changed_files(repo),
        "diff_line_count": _diff_line_count(repo),
        "tests_run": tests["commands"],
        "validation_command": tests["commands"],
        "validation_exit_code": tests["exit_code"],
        "tests_passed": tests["passed"],
        "forbidden_files_touched": tests.get("forbidden_files_touched", []),
        "scope_drift": tests.get("scope_drift", _scope_drift(repo)),
        "review_patch_status": "not_run",
        "generated_state_written": True,
        "cleanup_status": _cleanup_status(cleanup),
    }


def _codex_exec_command(repo: Path, *, model: str | None = None) -> list[str]:
    invocation = build_codex_invocation(
        repo,
        CodexOptions(sandbox="workspace-write", approval=None, ephemeral=True, json=True, model=model),
    )
    return invocation.args


def _dry_validation(task: dict[str, Any]) -> dict[str, Any]:
    command = task.get("validation_command") or []
    return {
        "tests_run": ["dry_run_mock_validation_not_executed"],
        "validation_command": command,
        "validation_exit_code": None,
        "tests_passed": True,
        "forbidden_files_touched": [],
    }


def _run_task_validation(repo: Path, task: dict[str, Any] | None) -> dict[str, Any]:
    if not task:
        return _run_tests(repo)
    command = task.get("validation_command")
    if isinstance(command, list) and command:
        proc = subprocess.run([str(part) for part in command], cwd=repo, text=True, capture_output=True, check=False, timeout=120)
        commands = [str(part) for part in command]
        exit_code = proc.returncode
    elif isinstance(command, str) and command.strip():
        proc = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=False, timeout=120, shell=True)
        commands = [command]
        exit_code = proc.returncode
    else:
        proc = subprocess.run([sys.executable, "-m", "py_compile", "app.py"], cwd=repo, text=True, capture_output=True, check=False, timeout=30)
        commands = ["python -m py_compile app.py"]
        exit_code = proc.returncode
    changed = set(_changed_files(repo))
    expected = set(task.get("expected_files") or []) | set(task.get("expected_tests") or [])
    forbidden = set(task.get("forbidden_files") or [])
    return {
        "commands": commands,
        "passed": exit_code == 0,
        "exit_code": exit_code,
        "forbidden_files_touched": sorted(changed & forbidden),
        "scope_drift": bool(changed - expected - forbidden) if expected or forbidden else _scope_drift(repo),
        "stdout_sha256": _sha256(getattr(proc, "stdout", "") or ""),
        "stderr_sha256": _sha256(getattr(proc, "stderr", "") or ""),
    }


def _task_quality(standard: dict[str, Any], enhanced: dict[str, Any]) -> dict[str, Any]:
    standard_success = bool(
        standard.get("exit_code") == 0
        and standard.get("tests_passed") is True
        and not standard.get("forbidden_files_touched")
        and not standard.get("scope_drift")
    )
    enhanced_success = bool(
        enhanced.get("exit_code") == 0
        and enhanced.get("tests_passed") is True
        and not enhanced.get("forbidden_files_touched")
        and not enhanced.get("scope_drift")
    )
    if enhanced_success and standard_success:
        classification = "enhanced_same"
    elif enhanced_success and not standard_success:
        classification = "enhanced_better"
    elif standard_success and not enhanced_success:
        classification = "enhanced_worse"
    else:
        classification = "inconclusive"
    return {
        "standard_success": standard_success,
        "enhanced_success": enhanced_success,
        "same_or_better_quality": bool(enhanced_success and (standard_success or not standard_success)),
        "classification": classification,
    }


def _matrix_blocked_result(
    *,
    run_id: str,
    created_at: str,
    source_head: str,
    mode: str,
    seed: int,
    task_count: int,
    reason: str,
    auth: dict[str, Any],
    duration_ms: int,
) -> dict[str, Any]:
    return {
        "schema_version": "premode.live_token_harness.matrix_result.v1",
        "run_id": run_id,
        "created_at": created_at,
        "source_head": source_head,
        "harness_version": HARNESS_VERSION,
        "mode": mode,
        "live_codex_run": False,
        "live_usage_available": False,
        "usage_source": None,
        "task_pair_count": task_count,
        "lane_record_count": 0,
        "matrix_seed": seed,
        "tasks": [],
        "quality": {"standard_success_count": 0, "enhanced_success_count": 0, "same_or_better_quality_count": 0},
        "safety": {"raw_prompt_in_aggregate": False, "raw_source_snippets_in_aggregate": False, "auth_contents_in_aggregate": False},
        "auth": auth,
        "duration_ms": duration_ms,
        "caveats": [reason, "no_live_codex_executed", "no_usage_measured"],
    }


def _lane_base(lane: str, prompt_sha: str, *, model: str | None, effort: str | None) -> dict[str, Any]:
    return {
        "lane": lane,
        "prompt_sha256": prompt_sha,
        "model": model,
        "effort": effort,
        "usage_available": False,
        "usage_source": None,
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost_estimate": None,
        "cost_estimate_available": False,
    }


def _empty_lane(lane: str, reason: str) -> dict[str, Any]:
    return {
        **_lane_base(lane, "", model=None, effort=None),
        "command": [],
        "exit_code": None,
        "duration_ms": None,
        "usage_unavailable_reason": reason,
        "files_changed": [],
        "diff_line_count": None,
        "tests_run": [],
        "tests_passed": None,
        "scope_drift": None,
        "review_patch_status": "not_run_blocked",
        "generated_state_written": False,
        "cleanup_status": "not_run_blocked",
    }


def _usage_fields(usage: dict[str, Any] | None, *, source: str) -> dict[str, Any]:
    usage = usage or {}
    input_tokens = _usage_value(usage, "input_tokens", "input_tokens_total", "prompt_tokens")
    cached_input_tokens = _usage_value(usage, "cached_input_tokens", "input_tokens_cached", "cached_tokens")
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_value(usage, "total_tokens")
    available = any(value is not None for value in (input_tokens, cached_input_tokens, output_tokens, total_tokens))
    return {
        "usage_available": available,
        "usage_source": source if available else None,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "usage_unavailable_reason": None if available else "no_parseable_usage_fields",
    }


def _usage_value(usage: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            return value
    normalized = usage.get("normalized_tokens")
    if isinstance(normalized, dict):
        for key in keys:
            value = normalized.get(key)
            if value is not None:
                return value
    return None


def _delta(standard: dict[str, Any], enhanced: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_tokens_delta": _number_delta(enhanced.get("input_tokens"), standard.get("input_tokens")),
        "input_tokens_delta_percent": _percent_delta(enhanced.get("input_tokens"), standard.get("input_tokens")),
        "cached_input_tokens_delta": _number_delta(enhanced.get("cached_input_tokens"), standard.get("cached_input_tokens")),
        "output_tokens_delta": _number_delta(enhanced.get("output_tokens"), standard.get("output_tokens")),
        "total_tokens_delta": _number_delta(enhanced.get("total_tokens"), standard.get("total_tokens")),
        "duration_delta_ms": _number_delta(enhanced.get("duration_ms"), standard.get("duration_ms")),
        "files_changed_delta": len(enhanced.get("files_changed") or []) - len(standard.get("files_changed") or []),
        "quality_same_or_better": None,
        "conclusion": "usage_unavailable" if not (standard.get("usage_available") and enhanced.get("usage_available")) else "usage_available_compare_manually",
    }


def _empty_delta(reason: str) -> dict[str, Any]:
    return {
        "input_tokens_delta": None,
        "input_tokens_delta_percent": None,
        "cached_input_tokens_delta": None,
        "output_tokens_delta": None,
        "total_tokens_delta": None,
        "duration_delta_ms": None,
        "files_changed_delta": None,
        "quality_same_or_better": None,
        "conclusion": reason,
    }


def _run_tests(repo: Path) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, "-m", "py_compile", "app.py"], cwd=repo, text=True, capture_output=True, check=False, timeout=30)
    return {"commands": ["python -m py_compile app.py"], "passed": proc.returncode == 0, "exit_code": proc.returncode}


def _changed_files(repo: Path) -> list[str]:
    return [line.strip() for line in _git_text(repo, ["diff", "--name-only"]).splitlines() if line.strip()]


def _diff_line_count(repo: Path) -> int:
    text = _git_text(repo, ["diff", "--numstat"])
    total = 0
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            for value in parts[:2]:
                if value.isdigit():
                    total += int(value)
    return total


def _scope_drift(repo: Path) -> bool:
    changed = set(_changed_files(repo))
    return bool(changed - {"scratch_pcodex_smoke.txt"})


@contextmanager
def _patched_environ(env: dict[str, str]):
    original = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _cleanup_status(cleanup: dict[str, Any]) -> str:
    if cleanup.get("dry_run"):
        return "dry_run_only"
    return "cleaned" if cleanup.get("writes_or_deletes") else "nothing_to_clean"


def _combined_usage_source(standard: dict[str, Any], enhanced: dict[str, Any]) -> str | None:
    sources = [str(item.get("usage_source")) for item in (standard, enhanced) if item.get("usage_source")]
    return ",".join(sources) if sources else None


def _combined_matrix_usage_source(rows: list[dict[str, Any]]) -> str | None:
    sources: list[str] = []
    for row in rows:
        for lane_name in ("standard", "enhanced"):
            lane = row.get(lane_name) if isinstance(row.get(lane_name), dict) else {}
            source = lane.get("usage_source")
            if source:
                sources.append(str(source))
    return ",".join(sorted(set(sources))) if sources else None


def _caveats(mode: str, standard: dict[str, Any], enhanced: dict[str, Any]) -> list[str]:
    caveats = ["aggregate_prompt_hash_only", "no_universal_savings_claim", "no_guaranteed_cache_hit_claim"]
    if mode == "dry_run_mock":
        caveats.extend(["no_live_codex_executed", "usage_fields_null_by_design"])
    if not (standard.get("usage_available") and enhanced.get("usage_available")):
        caveats.append("live_usage_unavailable_or_partial")
    return caveats


def _matrix_caveats(mode: str, rows: list[dict[str, Any]]) -> list[str]:
    caveats = ["aggregate_prompt_hash_only", "auth_contents_not_serialized", "no_universal_savings_claim", "no_guaranteed_cache_hit_claim"]
    if mode == "dry_run_mock":
        caveats.extend(["no_live_codex_executed", "usage_fields_null_by_design"])
    if any(not (row["standard"].get("usage_available") and row["enhanced"].get("usage_available")) for row in rows):
        caveats.append("live_usage_unavailable_or_partial")
    return caveats


def _number_delta(right: Any, left: Any) -> float | None:
    if right is None or left is None:
        return None
    return float(right) - float(left)


def _percent_delta(right: Any, left: Any) -> float | None:
    if right is None or left in (None, 0):
        return None
    return round(((float(right) - float(left)) / float(left)) * 100.0, 4)


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False, timeout=30)


def _git_text(repo: Path, args: list[str]) -> str:
    proc = _git(repo, args)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _run_id() -> str:
    return f"run_{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
