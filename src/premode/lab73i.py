from __future__ import annotations

import json
import math
import statistics
import subprocess
import tempfile
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .live_ledger import parse_command_ledger_from_jsonl
from .review_patch import review_patch

_LAB_ROOT = Path(tempfile.gettempdir()) / "premode_labs"
LAB_73H_ROOT = _LAB_ROOT / "clean_auto_live"
LAB_73I_ROOT = _LAB_ROOT / "validation_claims_command_audit"
LAB_73J_ROOT = _LAB_ROOT / "parallel_multi_prompt_cache_harness"

PROTECTED_BRANCH_PATTERNS = (
    "main",
    "master",
    "develop",
    "dev",
    "release/*",
    "stable/*",
    "prod/*",
    "production/*",
    "v*",
)

CLEANUP_CANDIDATE_PATTERNS = (
    "lab-*",
    "lab_*",
    "test-*",
    "test_*",
    "tmp-*",
    "tmp_*",
    "experiment-*",
    "experiment_*",
    "codex-*",
    "codex_*",
    "premode-lab-*",
    "premode_lab_*",
    "v73*",
    "v7-3*",
    "7.3*",
    "7-3*",
)


def run_lab73i(
    *,
    lab73h_root: Path = LAB_73H_ROOT,
    lab73i_root: Path = LAB_73I_ROOT,
    lab73j_root: Path = LAB_73J_ROOT,
    premode_repo: Path | None = None,
    delete_branches: bool = True,
) -> dict[str, Any]:
    lab73i_root.mkdir(parents=True, exist_ok=True)
    lab73j_root.mkdir(parents=True, exist_ok=True)
    results_path = lab73h_root / "LAB_7_3H_CLEAN_AUTO_LIVE_RESULTS.json"
    metadata_path = next((lab73h_root.glob("run_*/run_metadata.json")), None)
    if metadata_path is None:
        raise FileNotFoundError(f"Missing run_metadata.json under {lab73h_root}")
    lab73h_results = _load_json(results_path)
    metadata = _load_json(metadata_path)

    claims_dir = lab73i_root / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    lane_results = analyze_lab73h_lanes(lab73h_results, metadata, claims_dir=claims_dir)

    harness = build_lab73j_harness_config(metadata, lab73j_root)
    write_harness_artifacts(harness, lab73j_root)

    cleanup_repos = discover_cleanup_repos(metadata, premode_repo=premode_repo)
    cleanup = cleanup_lab_branches(cleanup_repos, dry_run=not delete_branches)

    results = {
        "lab": "7.3I",
        "source_lab73h_results": str(results_path),
        "source_lab73h_metadata": str(metadata_path),
        "no_live_codex_executed": True,
        "claims_dir": str(claims_dir),
        "lanes": lane_results,
        "comparisons": compare_standard_auto(lane_results),
        "exampleservice_auto_loss_inference": infer_exampleservice_auto_loss(lane_results),
        "harness": harness,
        "branch_cleanup": cleanup,
    }
    (lab73i_root / "LAB_7_3I_VALIDATION_CLAIMS_COMMAND_AUDIT_RESULTS.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (lab73i_root / "LAB_7_3I_VALIDATION_CLAIMS_COMMAND_AUDIT_REPORT.md").write_text(
        render_lab73i_report(results),
        encoding="utf-8",
    )
    (lab73i_root / "BRANCH_CLEANUP_RESULTS.json").write_text(
        json.dumps(cleanup, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (lab73i_root / "BRANCH_CLEANUP_REPORT.md").write_text(render_branch_cleanup_report(cleanup), encoding="utf-8")
    return results


def analyze_lab73h_lanes(lab73h_results: dict[str, Any], metadata: dict[str, Any], *, claims_dir: Path) -> dict[str, Any]:
    lanes: dict[str, Any] = {}
    raw_results = lab73h_results.get("results") if isinstance(lab73h_results.get("results"), dict) else {}
    for lane_id, lane in raw_results.items():
        if not isinstance(lane, dict):
            continue
        jsonl = Path(str(lane.get("codex_jsonl") or ""))
        ledger = parse_command_ledger_from_jsonl(jsonl)
        result = dict(lane)
        result["command_ledger"] = ledger
        result["commands_after_last_edit"] = ledger.get("commands_after_last_edit")
        result["validation_commands_after_last_edit"] = ledger.get("validation_commands_after_last_edit")
        result["status_diff_commands_after_last_edit"] = ledger.get("status_diff_commands_after_last_edit")
        result["possible_command_loop_cause"] = infer_command_loop_cause(result)
        if lane.get("lane") == "auto" and lane.get("worktree"):
            claims_path = claims_dir / f"{lane_id}_claims.json"
            claims_payload = build_lane_claims(lane)
            claims_path.write_text(json.dumps(claims_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            worktree = Path(str(lane["worktree"]))
            packet = Path(str(lane.get("packet_json") or worktree / ".premode" / "out" / "last_packet.json"))
            before = review_patch(worktree, base_ref=str(lane.get("baseline_head") or "HEAD"), packet_path=packet)
            after = review_patch(worktree, base_ref=str(lane.get("baseline_head") or "HEAD"), packet_path=packet, claims_path=claims_path)
            result["claims_file"] = str(claims_path)
            result["claims_payload"] = claims_payload
            result["review_patch_before_claims"] = _compact_review(before)
            result["review_patch_after_claims"] = _compact_review(after)
            result["validation_evidence_binding_result"] = {
                "validation_evidence": after.get("validation_evidence") or [],
                "verification_status_before": (before.get("verification") or {}).get("verification_status"),
                "verification_status_after": (after.get("verification") or {}).get("verification_status"),
                "merge_readiness_changed": before.get("merge_readiness") != after.get("merge_readiness"),
                "warnings_removed": sorted(set(before.get("warning_findings") or []) - set(after.get("warning_findings") or [])),
                "warnings_preserved": after.get("warning_findings") or [],
            }
        lanes[lane_id] = result
    return lanes


def build_lane_claims(lane: dict[str, Any]) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    for item in lane.get("lightweight_validation_results") or []:
        parsed = _claim_from_lightweight_validation(str(item))
        if parsed:
            claims.append(parsed)
    for message in lane.get("final_agent_messages") or []:
        claims.extend(_claims_from_final_message(str(message)))
    return {
        "source": "live_harness",
        "trusted_as_execution_proof": False,
        "lane": lane.get("lane"),
        "task": lane.get("task"),
        "worktree": lane.get("worktree"),
        "claims": _dedupe_claims(claims),
    }


def _claim_from_lightweight_validation(text: str) -> dict[str, Any] | None:
    if ":" not in text:
        return None
    command, result = text.split(":", 1)
    command = command.strip()
    result = result.strip()
    if not command or any(term in result.lower() for term in ("not run", "unavailable", "blocked")):
        return None
    if command == "git diff --cached --quiet":
        return None
    if command.startswith("model-reported "):
        command = "python3 " + command.removeprefix("model-reported ").strip()
    return {
        "command": command,
        "claimed_result": result,
        "source": "harness_lightweight_validation",
        "trusted_as_execution_proof": False,
    }


def _claims_from_final_message(text: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for line in text.splitlines():
        lower = line.lower()
        if "not run" in lower or "blocked" in lower or "unavailable" in lower:
            continue
        if "passed:" not in lower and "pass:" not in lower and "summary:" not in lower:
            continue
        command = _backtick_command(line)
        if command:
            result = line.split("`")[-1].strip(" -:") or "pass"
            claims.append({
                "command": command,
                "claimed_result": result if result else "pass",
                "source": "model_final_message",
                "trusted_as_execution_proof": False,
            })
    return claims


def _backtick_command(line: str) -> str | None:
    parts = line.split("`")
    if len(parts) < 3:
        return None
    command = parts[1].strip()
    prefixes = ("python", "python3", "pytest", "npm", "pnpm", "yarn", "bun", "cargo", "go", "swift", "swiftc", "xcodebuild", "git")
    if command.startswith(prefixes):
        return command
    return None


def compare_standard_auto(lanes: dict[str, Any]) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    tasks = sorted({lane.get("task") for lane in lanes.values() if lane.get("task")})
    for task in tasks:
        standard = lanes.get(f"{task}_standard")
        auto = lanes.get(f"{task}_auto")
        if not standard or not auto:
            continue
        std_value = standard.get("cache_adjusted_input_tokens")
        auto_value = auto.get("cache_adjusted_input_tokens")
        delta = _number(auto_value) - _number(std_value) if std_value is not None and auto_value is not None else None
        comparisons[str(task)] = {
            "standard_cache_adjusted_input_tokens": std_value,
            "auto_cache_adjusted_input_tokens": auto_value,
            "cache_adjusted_delta": delta,
            "cache_adjusted_delta_percent": (delta / _number(std_value) * 100.0) if delta is not None and _number(std_value) else None,
            "standard_command_count": standard.get("command_count"),
            "auto_command_count": auto.get("command_count"),
            "command_count_delta": _optional_delta(auto.get("command_count"), standard.get("command_count")),
            "standard_explicit_file_read_count": standard.get("explicit_file_read_count"),
            "auto_explicit_file_read_count": auto.get("explicit_file_read_count"),
            "explicit_file_read_delta": _optional_delta(auto.get("explicit_file_read_count"), standard.get("explicit_file_read_count")),
            "selected_auto_mode": auto.get("selected_packet_mode"),
        }
    return comparisons


def infer_exampleservice_auto_loss(lanes: dict[str, Any]) -> dict[str, Any]:
    standard = lanes.get("exampleservice_standard") or {}
    auto = lanes.get("exampleservice_auto") or {}
    delta = _optional_delta(auto.get("cache_adjusted_input_tokens"), standard.get("cache_adjusted_input_tokens"))
    if delta is None or delta <= 0:
        return {"inference": "not_applicable", "evidence": "exampleservice auto did not lose on cache-adjusted input"}
    return {
        "inference": "unclear_but_packet_selection_is_unlikely_primary",
        "confidence": "low_to_medium",
        "evidence": {
            "selected_packet_mode": auto.get("selected_packet_mode"),
            "packet_total_tokens": auto.get("packet_total_tokens"),
            "auto_render_equivalence_status": auto.get("auto_render_equivalence_status"),
            "explicit_file_read_delta": _optional_delta(auto.get("explicit_file_read_count"), standard.get("explicit_file_read_count")),
            "command_count_delta": _optional_delta(auto.get("command_count"), standard.get("command_count")),
            "uncached_input_delta": _optional_delta(auto.get("uncached_input_tokens"), standard.get("uncached_input_tokens")),
            "cached_input_delta": _optional_delta(auto.get("cached_input_tokens"), standard.get("cached_input_tokens")),
            "output_token_delta": _optional_delta(auto.get("output_tokens"), standard.get("output_tokens")),
            "reasoning_output_delta": _optional_delta(auto.get("reasoning_output_tokens"), standard.get("reasoning_output_tokens")),
        },
        "notes": [
            "Auto used paths_only with a small packet and render equivalence held, so packet selection alone is not supported as the likely cause.",
            "Auto read fewer explicit files but spent more uncached input/output/reasoning tokens, which points toward patch-strategy or command/output inflation.",
            "The logs do not prove causality; cache/order variance remains possible.",
        ],
    }


def infer_command_loop_cause(lane: dict[str, Any]) -> dict[str, Any]:
    ledger = lane.get("command_ledger") or {}
    repeated = ledger.get("repeated_commands") or []
    after_edit = int(ledger.get("commands_after_last_edit") or 0)
    validation_after = int(ledger.get("validation_commands_after_last_edit") or 0)
    status_after = int(ledger.get("status_diff_commands_after_last_edit") or 0)
    causes: list[str] = []
    if repeated:
        causes.append("repeated exact commands")
    if after_edit >= 8:
        causes.append("many commands after last edit")
    if validation_after + status_after >= 4:
        causes.append("post-edit validation/status churn")
    return {
        "inference": "; ".join(causes) if causes else "no strong command-loop signal",
        "marked_as_inference": True,
        "commands_after_last_edit": after_edit,
        "validation_commands_after_last_edit": validation_after,
        "status_diff_commands_after_last_edit": status_after,
        "repeated_command_count": len(repeated),
    }


def build_lab73j_harness_config(metadata: dict[str, Any], lab73j_root: Path = LAB_73J_ROOT) -> dict[str, Any]:
    tasks = metadata.get("tasks") if isinstance(metadata.get("tasks"), dict) else {}
    prompts = build_lab73j_prompts(metadata)
    runs: list[dict[str, Any]] = []
    for repo, repo_prompts in prompts.items():
        task_meta = tasks.get(repo) if isinstance(tasks.get(repo), dict) else {}
        baseline = str(task_meta.get("baseline") or "")
        baseline_commit = _repo_baseline_commit(task_meta)
        if not baseline_commit:
            raise ValueError(f"Missing baseline commit for {repo}")
        for prompt in repo_prompts:
            prompt_id = prompt["prompt_id"]
            if prompt.get("canary"):
                for repeat in (1, 2, 3):
                    order = ["standard", "v3_auto"] if repeat in {1, 3} else ["v3_auto", "standard"]
                    runs.extend(_runs_for_order(lab73j_root, repo, baseline, baseline_commit, prompt, repeat, order))
                forced_order = ["v3_paths_only", "v3_evidence_snippets"]
                runs.extend(_runs_for_order(lab73j_root, repo, baseline, baseline_commit, prompt, 1, forced_order, forced_control=True))
            else:
                numeric = int(str(prompt_id).split("_p")[-1])
                order = ["standard", "v3_auto"] if numeric % 2 else ["v3_auto", "standard"]
                runs.extend(_runs_for_order(lab73j_root, repo, baseline, baseline_commit, prompt, 1, order))
    return {
        "lab": "7.3J",
        "name": "Lab 7.3J - Parallel Multi-Prompt Cache Harness",
        "purpose": "Measure whether V3 auto has a structural advantage across multiple prompts and repeated canaries while separating cache/order effects from signal.",
        "no_live_codex_executed_by_setup": True,
        "fresh_worktree_required_per_prompt_lane_repeat": True,
        "forced_controls_policy": "canary_prompts_only",
        "parent_spawned_token_accounting": {
            "parent_pcodex_tokens": None,
            "spawned_codex_tokens": None,
            "total_live_run_tokens": None,
            "null_reason": "No live runs executed during harness preparation; fields are observable only after execution logs exist.",
        },
        "prompts": prompts,
        "runs": runs,
        "reporting": {
            "per_prompt": ["standard_vs_auto_cache_adjusted_delta", "selected_auto_mode", "explicit_read_delta", "command_count_delta", "review_validation_status"],
            "per_repo": ["total_delta", "median_delta", "mean_delta", "win_loss_count", "canary_variance", "forced_control_comparison"],
            "aggregate": ["total_delta", "median_prompt_delta", "win_loss_count", "outliers", "lane_order_cache_effect_notes", "comparison_against_7_3H"],
        },
    }


def build_lab73j_prompts(metadata: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    tasks = metadata.get("tasks") if isinstance(metadata.get("tasks"), dict) else {}
    canaries = {repo: str((tasks.get(repo) or {}).get("prompt") or "") for repo in tasks}
    prompt_sets = {
        "exampleservice": [
            ("canary", canaries.get("exampleservice") or "Improve CLI wording for the diagnostic demo flow without changing behavior.", "canary"),
            ("narrow_obvious_file_task", "Clarify one help sentence in tools/run_diagnostic_batch.py without changing command behavior.", "narrow"),
            ("ambiguous_multi_surface_task", "Improve diagnostic output wording where users see both batch output and demo output summaries.", "ambiguous"),
            ("docs_help_copy_task", "Update README wording that describes running the demo outputs, without touching runtime code.", "docs"),
            ("validation_test_related_task", "Add or adjust lightweight regression wording around diagnostic batch validation without changing classifications.", "validation"),
            ("support_context_heavy_task", "Explain how generated sample data, expected classifications, and report output relate in the portfolio evidence flow.", "support"),
        ],
        "examplegame": [
            ("canary", canaries.get("examplegame") or "Improve Homestead next-action clarity from the Today Plan or Homestead surface.", "canary"),
            ("narrow_obvious_file_task", "Clarify one visible next-action label in the Today Plan view.", "narrow"),
            ("ambiguous_multi_surface_task", "Improve the player-facing Homestead guidance that may appear in both view and view-model surfaces.", "ambiguous"),
            ("docs_help_copy_task", "Update handoff documentation describing the Homestead next-action polish scope.", "docs"),
            ("validation_test_related_task", "Add a source-level parse-safe check plan for touched Swift UI files without running Xcode.", "validation"),
            ("support_context_heavy_task", "Trace how Today Plan, Homestead navigation, and report-line context connect before choosing edit files.", "support"),
        ],
        "example_cli": [
            ("canary", canaries.get("example_cli") or "Improve CLI help text for choosing an output theme.", "canary"),
            ("narrow_obvious_file_task", "Clarify the --theme help text in the CLI entrypoint only.", "narrow"),
            ("ambiguous_multi_surface_task", "Improve theme error/help wording across CLI parsing and any nearby tests.", "ambiguous"),
            ("docs_help_copy_task", "Update README help copy for choosing an output theme.", "docs"),
            ("validation_test_related_task", "Add or adjust a focused help-output regression test for allowed theme values.", "validation"),
            ("support_context_heavy_task", "Use CLI, README, and tests as context to explain theme handling without changing rendering behavior.", "support"),
        ],
    }
    out: dict[str, list[dict[str, Any]]] = {}
    for repo, rows in prompt_sets.items():
        out[repo] = [
            {
                "prompt_id": f"{repo}_p{index}",
                "prompt_text": text,
                "prompt_type": kind,
                "canary": label == "canary",
            }
            for index, (label, text, kind) in enumerate(rows, start=1)
        ]
    return out


def _runs_for_order(
    lab_root: Path,
    repo: str,
    baseline: str,
    baseline_commit: str,
    prompt: dict[str, Any],
    repeat: int,
    order: list[str],
    *,
    forced_control: bool = False,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for position, lane in enumerate(order, start=1):
        worktree_path = lab_root / "worktrees" / repo / str(prompt["prompt_id"]) / f"repeat_{repeat}" / lane
        runs.append({
            "repo": repo,
            "baseline_repo": baseline,
            "baseline_commit": baseline_commit,
            "prompt_id": prompt["prompt_id"],
            "prompt_text": prompt["prompt_text"],
            "lane": lane,
            "repeat_index": repeat,
            "lane_order": order,
            "lane_order_position": position,
            "forced_control": forced_control,
            "worktree_path": str(worktree_path),
            "fresh_worktree_from_baseline_required": True,
            "worktree_started_from_baseline_confirmation": None,
            "parent_pcodex_tokens": None,
            "spawned_codex_tokens": None,
            "total_live_run_tokens": None,
            "token_accounting_null_reason": "No live run executed during setup.",
        })
    return runs


def write_harness_artifacts(harness: dict[str, Any], lab73j_root: Path = LAB_73J_ROOT) -> None:
    lab73j_root.mkdir(parents=True, exist_ok=True)
    (lab73j_root / "HARNESS_CONFIG.json").write_text(json.dumps(harness, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (lab73j_root / "PROMPTS.json").write_text(json.dumps(harness["prompts"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (lab73j_root / "HARNESS_PLAN.md").write_text(render_harness_plan(harness), encoding="utf-8")
    (lab73j_root / "README.md").write_text(render_harness_readme(harness), encoding="utf-8")


def discover_cleanup_repos(metadata: dict[str, Any], *, premode_repo: Path | None = None) -> list[Path]:
    repos: list[Path] = []
    if premode_repo:
        repos.append(Path(premode_repo))
    elif metadata.get("premode_source"):
        repos.append(Path(str(metadata["premode_source"])))
    tasks = metadata.get("tasks") if isinstance(metadata.get("tasks"), dict) else {}
    for task in tasks.values():
        if isinstance(task, dict) and task.get("baseline"):
            repos.append(Path(str(task["baseline"])))
    return _dedupe_paths([repo for repo in repos if repo.exists()])


def cleanup_lab_branches(repos: list[Path], *, dry_run: bool = True) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "protected_patterns": list(PROTECTED_BRANCH_PATTERNS),
        "candidate_patterns": list(CLEANUP_CANDIDATE_PATTERNS),
        "repos": [inspect_and_cleanup_repo(repo, dry_run=dry_run) for repo in repos],
    }


def inspect_and_cleanup_repo(repo: Path, *, dry_run: bool = True) -> dict[str, Any]:
    repo = Path(repo)
    current_branch = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    head = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    status = _git(repo, ["status", "--short"]).stdout.splitlines()
    branches = _local_branches(repo)
    active_branches = _active_worktree_branches(repo)
    protected_bases = [branch["name"] for branch in branches if is_protected_branch(branch["name"])]
    deleted: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    protected_skipped: list[str] = []
    for branch in branches:
        name = branch["name"]
        if not is_cleanup_candidate_branch(name):
            continue
        reason = select_branch_cleanup_action(
            repo,
            name,
            current_branch=current_branch,
            active_branches=active_branches,
            protected_bases=protected_bases,
        )
        if reason["action"] == "delete":
            if dry_run:
                deleted.append({**reason, "branch": name, "dry_run": True})
            else:
                completed = _git(repo, ["branch", "-D", name])
                deleted.append({**reason, "branch": name, "dry_run": False, "delete_returncode": completed.returncode, "delete_stderr": completed.stderr.strip()})
        elif reason["action"] == "protected_skip":
            protected_skipped.append(name)
            preserved.append({**reason, "branch": name})
        else:
            preserved.append({**reason, "branch": name})
    prune = _git(repo, ["worktree", "prune", "--dry-run"])
    return {
        "repo_path": str(repo),
        "current_branch": current_branch,
        "head_commit": head,
        "git_status_short": status,
        "local_branches": branches,
        "active_worktree_branches": sorted(active_branches),
        "protected_branches_skipped": sorted(set(protected_skipped)),
        "deleted_branches": deleted,
        "preserved_branches": preserved,
        "branches_preserved_due_to_unique_commits": [item for item in preserved if item.get("reason") == "unique_commits"],
        "worktree_prune_dry_run": prune.stdout.splitlines(),
        "worktree_prune_executed": False,
        "no_staged_changes_confirmation": _git(repo, ["diff", "--cached", "--quiet"]).returncode == 0,
    }


def select_branch_cleanup_action(
    repo: Path,
    branch: str,
    *,
    current_branch: str,
    active_branches: set[str],
    protected_bases: list[str],
) -> dict[str, Any]:
    if is_protected_branch(branch):
        return {"action": "protected_skip", "reason": "protected_branch_pattern"}
    if branch == current_branch:
        return {"action": "preserve", "reason": "current_branch"}
    if branch in active_branches:
        return {"action": "preserve", "reason": "checked_out_in_worktree"}
    if not is_cleanup_candidate_branch(branch):
        return {"action": "preserve", "reason": "name_not_cleanup_candidate"}
    base = _first_existing_base(repo, protected_bases)
    if not base:
        return {"action": "preserve", "reason": "no_protected_base_for_merge_check"}
    unique = _git(repo, ["log", "--oneline", f"{base}..{branch}", "--"]).stdout.splitlines()
    if unique:
        return {"action": "preserve", "reason": "unique_commits", "base": base, "unique_commits": unique[:10]}
    return {"action": "delete", "reason": "disposable_candidate_with_no_unique_commits", "base": base}


def is_protected_branch(branch: str) -> bool:
    return any(fnmatch(branch, pattern) for pattern in PROTECTED_BRANCH_PATTERNS)


def is_cleanup_candidate_branch(branch: str) -> bool:
    return any(fnmatch(branch, pattern) for pattern in CLEANUP_CANDIDATE_PATTERNS)


def render_lab73i_report(results: dict[str, Any]) -> str:
    lines = [
        "# Lab 7.3I Validation Claims Command Audit Report",
        "",
        "## 1. Executive summary",
        "",
        "- Re-analyzed Lab 7.3H logs offline; no live Codex runs were executed.",
        "- Generated structured untrusted validation-claims files for auto lanes and reran review-patch before/after claims binding.",
        "- Added command-category ledgers for every 7.3H lane.",
        "- Prepared the Lab 7.3J multi-prompt cache harness configuration without executing it.",
        "- Ran conservative branch cleanup selection; uncertain/current/protected/active/unique branches were preserved.",
        "",
        "## 2. Why 7.3H was mixed",
        "",
    ]
    for repo, comparison in (results.get("comparisons") or {}).items():
        delta = comparison.get("cache_adjusted_delta")
        percent = comparison.get("cache_adjusted_delta_percent")
        lines.append(f"- {repo}: auto delta {delta:.1f} cache-adjusted tokens ({percent:.1f}%) with command delta {comparison.get('command_count_delta')}.")
    lines.extend([
        "",
        "## 3. Validation claims binding",
        "",
    ])
    for lane_id, lane in (results.get("lanes") or {}).items():
        if not lane_id.endswith("_auto"):
            continue
        binding = lane.get("validation_evidence_binding_result") or {}
        lines.append(f"- {lane_id}: before `{(lane.get('review_patch_before_claims') or {}).get('merge_readiness')}`, after `{(lane.get('review_patch_after_claims') or {}).get('merge_readiness')}`, evidence entries {len(binding.get('validation_evidence') or [])}.")
        if binding.get("warnings_removed"):
            lines.append(f"  - Removed warnings: {', '.join(binding['warnings_removed'])}")
        if binding.get("warnings_preserved"):
            lines.append(f"  - Preserved warnings: {', '.join(binding['warnings_preserved'])}")
    lines.extend([
        "",
        "## 4. Command loop audit",
        "",
    ])
    for lane_id, lane in (results.get("lanes") or {}).items():
        ledger = lane.get("command_ledger") or {}
        cause = lane.get("possible_command_loop_cause") or {}
        lines.append(f"- {lane_id}: total {ledger.get('total')}, reads {ledger.get('file_read_commands')}, search {ledger.get('search_commands')}, edit {ledger.get('edit_commands')}, validation {ledger.get('validation_commands')}, status/diff {ledger.get('status_diff_commands')}, build/parse {ledger.get('build_or_parse_commands')}, other {ledger.get('other_commands')}; after last edit {ledger.get('commands_after_last_edit')}. Inference: {cause.get('inference')}.")
    lines.extend([
        "",
        "## 5. Offline re-analysis of 7.3H logs",
        "",
    ])
    for lane_id, lane in (results.get("lanes") or {}).items():
        lines.append(f"- {lane_id}: cache-adjusted {lane.get('cache_adjusted_input_tokens')}, uncached {lane.get('uncached_input_tokens')}, cached {lane.get('cached_input_tokens')}, output {lane.get('output_tokens')}, reasoning {lane.get('reasoning_output_tokens')}, explicit reads {lane.get('explicit_file_read_count')}, deprecated all-referenced {lane.get('all_referenced_file_count')}.")
    lines.extend([
        "",
        "## 6. Review-patch before/after claims binding",
        "",
    ])
    for lane_id, lane in (results.get("lanes") or {}).items():
        if lane_id.endswith("_auto"):
            lines.append(f"- {lane_id}: `{lane.get('claims_file')}`")
    lines.extend([
        "",
        "## 7. Command-category comparison",
        "",
        "See `LAB_7_3I_VALIDATION_CLAIMS_COMMAND_AUDIT_RESULTS.json` for full category ledgers and repeated/failed command lists.",
        "",
        "## 8. 7.3J harness setup",
        "",
        f"- Harness runs configured: {len((results.get('harness') or {}).get('runs') or [])}.",
        "- Fresh worktree path is specified for each prompt/lane/repeat.",
        "- Forced controls are present only for canary prompts.",
        "",
        "## 9. Harness prompt/config summary",
        "",
        f"- Harness artifacts: `{LAB_73J_ROOT / 'HARNESS_PLAN.md'}`, `{LAB_73J_ROOT / 'HARNESS_CONFIG.json'}`, `{LAB_73J_ROOT / 'PROMPTS.json'}`, `{LAB_73J_ROOT / 'README.md'}`.",
        "",
        "## 10. Branch cleanup summary",
        "",
        f"- Cleanup repos inspected: {len((results.get('branch_cleanup') or {}).get('repos') or [])}.",
        f"- Dry run: {(results.get('branch_cleanup') or {}).get('dry_run')}.",
        "",
        "## 11. Files changed",
        "",
        "- `src/premode/review_patch.py`",
        "- `src/premode/live_ledger.py`",
        "- `src/premode/lab73i.py`",
        "- focused tests under `tests/`",
        "",
        "## 12. Tests added/updated",
        "",
        "- Claims binding tests",
        "- Command ledger tests",
        "- 7.3J harness config tests",
        "- Branch cleanup dry-run tests",
        "",
        "## 13. Residual limitations",
        "",
        "- Command-loop causes are inference from event order and repeated commands, not proven agent intent.",
        "- Parent pcodex vs spawned Codex token separation is null until a future live run exposes those fields.",
        "- Branch cleanup is intentionally conservative; active worktree branches are preserved.",
        "",
        "## 14. Recommendation for 7.3J execution",
        "",
        "Proceed with 7.3J only after reviewing `HARNESS_CONFIG.json`; run live lanes later under explicit approval and keep forced controls limited to canaries.",
        "",
        "## ExampleService auto-loss inference",
        "",
        json.dumps(results.get("exampleservice_auto_loss_inference"), indent=2, sort_keys=True),
        "",
    ])
    return "\n".join(lines)


def render_harness_plan(harness: dict[str, Any]) -> str:
    lines = [
        "# Lab 7.3J - Parallel Multi-Prompt Cache Harness",
        "",
        "This is a prepared harness only. Do not execute live Codex from this setup step.",
        "",
        "## Rules",
        "",
        "- Fresh isolated worktree per prompt/lane/repeat.",
        "- Standard and v3_auto run for every prompt.",
        "- v3_paths_only and v3_evidence_snippets forced controls run only for canary prompts.",
        "- Lane order is balanced deterministically.",
        "- Parent pcodex/spawned Codex token fields remain null until live execution exposes them.",
        "",
        "## Run Count",
        "",
        f"- Planned runs: {len(harness.get('runs') or [])}.",
    ]
    return "\n".join(lines) + "\n"


def render_harness_readme(harness: dict[str, Any]) -> str:
    return (
        "# Lab 7.3J Harness Artifacts\n\n"
        "Files in this directory define the offline-prepared multi-prompt cache harness. "
        "They do not contain live run results.\n\n"
        "- `HARNESS_CONFIG.json`: full run matrix and metric schema.\n"
        "- `PROMPTS.json`: prompt definitions by repo.\n"
        "- `HARNESS_PLAN.md`: execution rules and lane ordering.\n"
    )


def render_branch_cleanup_report(cleanup: dict[str, Any]) -> str:
    lines = ["# Branch Cleanup Report", "", f"Dry run: {cleanup.get('dry_run')}", ""]
    for repo in cleanup.get("repos") or []:
        lines.extend([
            f"## {repo.get('repo_path')}",
            "",
            f"- Current branch: `{repo.get('current_branch')}`",
            f"- HEAD: `{repo.get('head_commit')}`",
            f"- Deleted branches: {len(repo.get('deleted_branches') or [])}",
            f"- Preserved branches: {len(repo.get('preserved_branches') or [])}",
            f"- No staged changes: {repo.get('no_staged_changes_confirmation')}",
            "",
        ])
        for item in repo.get("deleted_branches") or []:
            lines.append(f"- Delete `{item.get('branch')}`: {item.get('reason')}")
        for item in repo.get("preserved_branches") or []:
            lines.append(f"- Preserve `{item.get('branch')}`: {item.get('reason')}")
        if repo.get("worktree_prune_dry_run"):
            lines.append("")
            lines.append("Worktree prune dry-run output:")
            lines.extend(f"- {line}" for line in repo["worktree_prune_dry_run"])
        lines.append("")
    return "\n".join(lines)


def _compact_review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "merge_readiness": review.get("merge_readiness"),
        "scope_compliance": review.get("scope_compliance"),
        "warning_findings": review.get("warning_findings") or [],
        "blocking_findings": review.get("blocking_findings") or [],
        "info_findings": review.get("info_findings") or [],
        "validation_evidence": review.get("validation_evidence") or [],
        "verification_status": (review.get("verification") or {}).get("verification_status"),
    }


def _repo_baseline_commit(task_meta: dict[str, Any]) -> str | None:
    lanes = task_meta.get("lanes") if isinstance(task_meta.get("lanes"), dict) else {}
    for lane in lanes.values():
        if isinstance(lane, dict) and lane.get("baseline_head"):
            return str(lane["baseline_head"])
    return None


def _local_branches(repo: Path) -> list[dict[str, Any]]:
    output = _git(repo, ["branch", "--format=%(refname:short)|%(objectname:short)|%(HEAD)|%(subject)"]).stdout
    branches: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        name, commit, head_marker, subject = parts
        if name == "(no branch)":
            continue
        branches.append({"name": name, "commit": commit, "current": head_marker == "*", "subject": subject})
    return branches


def _active_worktree_branches(repo: Path) -> set[str]:
    output = _git(repo, ["worktree", "list", "--porcelain"]).stdout
    active: set[str] = set()
    for line in output.splitlines():
        if line.startswith("branch refs/heads/"):
            active.add(line.removeprefix("branch refs/heads/").strip())
    return active


def _first_existing_base(repo: Path, protected_bases: list[str]) -> str | None:
    for base in protected_bases:
        if _git(repo, ["rev-parse", "--verify", base]).returncode == 0:
            return base
    for base in ("main", "master", "develop", "dev"):
        if _git(repo, ["rev-parse", "--verify", base]).returncode == 0:
            return base
    return None


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        command = str(claim.get("command") or "")
        result = str(claim.get("claimed_result") or "")
        key = (command, result)
        if command and key not in seen:
            out.append(claim)
            seen.add(key)
    return out


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            out.append(path)
            seen.add(key)
    return out


def _optional_delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return _number(left) - _number(right)


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number):
        return 0.0
    return number


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean": None, "median": None, "min": None, "max": None, "stddev": None, "cv": None}
    mean = statistics.mean(values)
    stddev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        "mean": mean,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "stddev": stddev,
        "cv": stddev / mean if mean else None,
    }
