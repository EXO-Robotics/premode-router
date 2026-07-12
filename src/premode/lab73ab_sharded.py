from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from .sharded_runner import (
    ShardedRunnerConfig,
    build_run_plan,
    plan_from_path,
    resume_report,
    write_dry_run_plan,
)


DEFAULT_ARTIFACT_ROOT = Path(tempfile.gettempdir()) / "premode_labs" / "measurement_harness"
DEFAULT_PROMPTS = [
    "click_shell_completion_runtime",
    "yargs_validation_test_only",
    "fd_cargo_metadata",
    "cobra_user_guide_docs",
    "vite_config_runtime",
    "tca_package_metadata",
]
DEFAULT_LANES = [
    "standard",
    "v3_auto",
    "v4_context_only",
    "v5_ranked_snippets",
    "v5_ranked_paths",
    "v5_primary_tests_only",
    "v5_top1_plus_tests",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lab 7.3AB sharded public live runner planning utility")
    parser.add_argument("--parallel-mode", choices=["sharded"], default="sharded")
    parser.add_argument("--shard-count", type=int, default=2)
    parser.add_argument("--per-shard-max-workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-plan", type=Path)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args(argv)

    config = ShardedRunnerConfig(
        artifact_root=args.artifact_root,
        shard_count=args.shard_count,
        per_shard_max_workers=args.per_shard_max_workers,
    )
    if args.run_plan and args.run_plan.exists():
        plan = plan_from_path(args.run_plan)
    else:
        plan = build_run_plan(_default_public_matrix_units(args.repeat), config)
    if args.dry_run_plan:
        summary = write_dry_run_plan(plan, args.artifact_root)
        print(json.dumps(summary, sort_keys=True))
    if args.resume:
        report = resume_report(plan, args.artifact_root)
        print(json.dumps(report, sort_keys=True))
    if not args.dry_run_plan and not args.resume:
        parser.error("this lab-local entrypoint currently supports --dry-run-plan and --resume")
    return 0


def _default_public_matrix_units(repeat: int) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for repeat_index in range(1, repeat + 1):
        for prompt_id in DEFAULT_PROMPTS:
            for lane in DEFAULT_LANES:
                packet_version, packet_variant = _lane_packet(lane)
                raw_task_hash = hashlib.sha256(f"{prompt_id}:public-live-task".encode("utf-8")).hexdigest()
                run_id = f"{prompt_id}_{lane}_r{repeat_index}"
                units.append({
                    "run_id": run_id,
                    "prompt_id": prompt_id,
                    "lane": lane,
                    "packet_version": packet_version,
                    "packet_variant": packet_variant,
                    "repeat": repeat_index,
                    "raw_task_hash": raw_task_hash,
                    "fixture_source": f"/example/public_fixtures/{prompt_id}",
                })
    return units


def _lane_packet(lane: str) -> tuple[str | None, str | None]:
    if lane == "standard":
        return None, None
    if lane == "v3_auto":
        return "v3", None
    if lane == "v4_context_only":
        return "v4", "context_only"
    if lane.startswith("v5_"):
        return "v5", lane.removeprefix("v5_")
    return None, None


if __name__ == "__main__":
    raise SystemExit(main())
