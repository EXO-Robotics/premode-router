from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from contextlib import contextmanager

from . import __version__
from .live_ledger import parse_jsonl_usage
from .pcodex_bootstrap import cleanup_local_state, first_run_receipt, run_dry_run, run_enabled, set_enabled


DEFAULT_ARTIFACT_ROOT = Path("/private/tmp/premode_labs/lab_7_3cy_live_token_harness_recovery")
LIVE_SPEND_ENV = "PREMODE_ENABLE_LIVE_CODEX_SPEND_TEST"
LIVE_MATRIX_ENV = "PREMODE_ENABLE_LIVE_CODEX_MATRIX"
DEFAULT_PROMPT_ID = "disposable_smoke"
DEFAULT_PROMPT = "Create or update only a disposable file named scratch_pcodex_smoke.txt with the text 'pcodex smoke ok'. Do not modify any other files."
HARNESS_VERSION = "lab_7_3cy.v1"


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
    standard_env = _lane_env(run_root / "lanes" / "standard")
    enhanced_env = _lane_env(run_root / "lanes" / "enhanced")

    started = time.perf_counter()
    if mode == "dry_run_mock":
        standard = _run_standard_dry(standard_repo, prompt_sha, model=model, effort=effort)
        enhanced = _run_enhanced_dry(enhanced_repo, prompt, prompt_sha, enhanced_env, model=model, effort=effort)
        live_codex_run = False
    else:
        standard = _run_standard_live(standard_repo, prompt, prompt_sha, run_root / "lanes" / "standard", standard_env, model=model, effort=effort)
        enhanced = _run_enhanced_live(enhanced_repo, prompt, prompt_sha, run_root / "lanes" / "enhanced", enhanced_env, model=model, effort=effort)
        live_codex_run = True

    delta = _delta(standard, enhanced)
    quality = {
        "task_outcome": "dry_run_mechanics_passed" if mode == "dry_run_mock" else "live_result_requires_human_review",
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
            "kind": "synthetic_disposable" if fixture_repo is None else "explicit_disposable_copy",
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


def _copy_fixture(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".premode", ".pcodex", "__pycache__", ".pytest_cache"))


def _lane_env(lane_root: Path) -> dict[str, str]:
    home = lane_root / "home"
    tmp = lane_root / "tmp"
    codex_home = lane_root / "codex_home"
    pcodex_home = lane_root / "pcodex_home"
    for path in (home, tmp, codex_home, pcodex_home, lane_root / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "CODEX_HOME": str(codex_home),
            "PCODEX_ALPHA_HOME": str(pcodex_home),
        }
    )
    return env


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


def _run_standard_live(
    repo: Path,
    prompt: str,
    prompt_sha: str,
    lane_root: Path,
    env: dict[str, str],
    *,
    model: str | None,
    effort: str | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(["codex", "exec", "-"], input=prompt, cwd=repo, env=env, text=True, capture_output=True, check=False)
    log = lane_root / "raw_logs_non_paste_safe" / "standard_stdout.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(proc.stdout or "", encoding="utf-8")
    usage = parse_usage_file(log)
    tests = _run_tests(repo)
    cleanup = cleanup_local_state(repo, dry_run=False)
    return {
        **_lane_base("standard", prompt_sha, model=model, effort=effort),
        "command": ["codex", "exec", "-"],
        "exit_code": proc.returncode,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        **usage,
        "files_changed": _changed_files(repo),
        "diff_line_count": _diff_line_count(repo),
        "tests_run": tests["commands"],
        "tests_passed": tests["passed"],
        "scope_drift": _scope_drift(repo),
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
) -> dict[str, Any]:
    started = time.perf_counter()
    with _patched_environ(env):
        set_enabled(repo, True)
        first_run_receipt(repo)
        result = run_enabled(repo, prompt, "lite")
        tests = _run_tests(repo)
        cleanup = cleanup_local_state(repo, dry_run=False)
    log = lane_root / "raw_logs_non_paste_safe" / "enhanced_stdout.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(str(result.get("stdout") or ""), encoding="utf-8")
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
        "tests_passed": tests["passed"],
        "scope_drift": _scope_drift(repo),
        "review_patch_status": "not_run",
        "generated_state_written": True,
        "cleanup_status": _cleanup_status(cleanup),
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
    available = any(usage.get(key) is not None for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"))
    return {
        "usage_available": available,
        "usage_source": source if available else None,
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "usage_unavailable_reason": None if available else "no_parseable_usage_fields",
    }


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


def _caveats(mode: str, standard: dict[str, Any], enhanced: dict[str, Any]) -> list[str]:
    caveats = ["aggregate_prompt_hash_only", "no_universal_savings_claim", "no_guaranteed_cache_hit_claim"]
    if mode == "dry_run_mock":
        caveats.extend(["no_live_codex_executed", "usage_fields_null_by_design"])
    if not (standard.get("usage_available") and enhanced.get("usage_available")):
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
