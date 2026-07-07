from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .config import init_project
from .indexer import index_project
from .compiler import inspect_prompt, compile_prompt
from .evidence_snippets import DEFAULT_SNIPPET_BUDGET_TOKENS, attach_snippets_to_files
from .locator import locate_files
from .codex_exec import CodexOptions, run_codex
from .doctor import doctor
from .fixture import run_fixture
from .stress import run_universal_stress, format_stress_table
from .plugin import install_local_plugin
from .metrics import read_metrics, summarize_savings, last_metric
from .adapters import detect_projects
from .hook import main as hook_main
from .mcp_server import serve as mcp_serve
from .repo_map import build_repo_map, compact_repo_map_summary, estimate_repo_map_json_bytes, limit_repo_map_files, summarize_repo_map
from .review_patch import review_patch, format_review_report
from .benchmark import run_benchmark, format_benchmark_report
from .launch_safety import RootGuardError, resolve_cli_repo
from .plugins import PluginAliasError, apply_packet_plugin
from .tuning import TuningProfileError


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def _guarded_repo(cwd: Path, explicit_repo: str | None = None, *, fail_on_root_escalation: bool = False) -> Path:
    try:
        return resolve_cli_repo(cwd, explicit_repo, fail_on_root_escalation=fail_on_root_escalation).repo
    except RootGuardError as exc:
        _print_json({"error": str(exc), "root_guard": exc.guard})
        raise SystemExit(2)


def _located_file_json(file, *, snippets: list[dict] | None = None) -> dict:
    return {
        "path": file.path,
        "score": file.score,
        "confidence": file.confidence,
        "matched_signals": list(file.matched_signals),
        "covered_terms": [],
        "uncovered_terms": [],
        "snippets": snippets or [],
    }


def _compile_receipt(result: dict, *, out: Path | None, json_out: Path | None) -> dict:
    metrics = result.get("metrics") or {}
    return {
        "status": "compiled",
        "packet_version": result.get("packet_version"),
        "packet_variant": result.get("packet_variant"),
        "packet_detail_mode": result.get("packet_detail_mode"),
        "packet_detail_mode_requested": result.get("packet_detail_mode_requested"),
        "packet_detail_mode_selected": result.get("packet_detail_mode_selected"),
        "packet_mode_selection_reasons": result.get("packet_mode_selection_reasons"),
        "packet_mode_selection_signals": result.get("packet_mode_selection_signals"),
        "support_edit_surface_risk_strength": result.get("support_edit_surface_risk_strength"),
        "multi_surface_risk_strength": result.get("multi_surface_risk_strength"),
        "auto_render_equivalent_to_forced_selected_mode": result.get("auto_render_equivalent_to_forced_selected_mode"),
        "forced_mode_compared": result.get("forced_mode_compared"),
        "auto_selected_mode_model_facing_equivalent": result.get("auto_selected_mode_model_facing_equivalent"),
        "auto_selected_mode_packet_diff_summary": result.get("auto_selected_mode_packet_diff_summary"),
        "auto_paths_only_model_facing_equivalent": result.get("auto_paths_only_model_facing_equivalent"),
        "auto_paths_only_packet_diff_summary": result.get("auto_paths_only_packet_diff_summary"),
        "resource_profile": result.get("resource_profile"),
        "context_boundary_mode": result.get("context_boundary_mode"),
        "packet_sha256": result.get("compiled_packet_sha256"),
        "cacheable_prefix_sha256": result.get("cacheable_prefix_sha256"),
        "dynamic_suffix_sha256": result.get("dynamic_suffix_sha256"),
        "packet_tokens": metrics.get("packet_total_tokens"),
        "hard_packet_token_budget": (result.get("caps") or {}).get("hard_packet_token_budget"),
        "budget_exceeded_by": metrics.get("budget_exceeded_by"),
        "out": str(out) if out else None,
        "json_out": str(json_out) if json_out else None,
        "show_raw_hint": "rerun with --show-raw to print the compiled packet to stdout",
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="premode")
    p.add_argument("--version", action="version", version=f"premode {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init")

    setup = sub.add_parser("setup")
    setup.add_argument("--skip-plugin", action="store_true")

    det = sub.add_parser("detect")
    det.add_argument("--json", action="store_true")
    det.add_argument("--explain", action="store_true")

    dbg = sub.add_parser("debug-env")
    dbg.add_argument("--json", action="store_true")

    ip = sub.add_parser("index")
    ip.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default=None)
    ip.add_argument("--incremental", action="store_true", help="Accepted for seamless runs; MVP rewrites the lightweight index.")

    insp = sub.add_parser("inspect")
    insp.add_argument("prompt")
    insp.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default=None)

    loc = sub.add_parser("locate")
    loc.add_argument("prompt")
    loc.add_argument("--repo", default=None)
    loc.add_argument("--fail-on-root-escalation", action="store_true")
    loc.add_argument("--max-files", type=int, default=8)
    loc.add_argument("--snippet-budget-tokens", type=int, default=DEFAULT_SNIPPET_BUDGET_TOKENS)
    loc.add_argument("--no-snippets", action="store_true")
    loc.add_argument("--json", action="store_true")

    comp = sub.add_parser("compile")
    comp.add_argument("prompt")
    comp.add_argument("--repo", default=None, help="Repository to compile. Defaults to the current repo root.")
    comp.add_argument("--fail-on-root-escalation", action="store_true")
    comp.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default=None)
    comp.add_argument("--out", default=None)
    comp.add_argument("--json-out", default=None)
    comp.add_argument("--json", action="store_true")
    comp.add_argument("--show-raw", action="store_true")
    comp.add_argument("--use-repo-map", action="store_true", help="Include deterministic repo-map summary and impact hints in the compiled packet.")
    comp.add_argument("--plugin", default=None, help="Resolve packet options from an installed Pre-mode plugin alias.")
    comp.add_argument("--tuning", default=None, help="Apply a validated pCodex repo tuning profile to internal ranking. Explicit opt-in only.")
    comp.add_argument("--packet-version", choices=["v2", "v3", "v4", "v5"], default=None, help="Compiled packet renderer version. v5 is ranked context only.")
    v5_variants = ["ranked_paths", "ranked_snippets", "primary_tests_only", "top1_plus_tests", "ranked_paths_plus_anchors", "ranked_paths_selective_snippets", "ranked_paths_no_support", "ranked_paths_tests_first", "ranked_paths_top1", "tool_assisted_backbone", "tool_assisted_backbone_no_task_class", "tool_assisted_backbone_no_relations", "tool_assisted_anchors_internal"]
    anchor_strategies = [
        "literal_symbol",
        "literal_symbol_test_names",
        "literal_symbol_config",
        "literal_symbol_config_gated",
        "literal_symbol_docs",
        "literal_symbol_docs_heading_gated",
        "literal_symbol_cli_route",
        "literal_symbol_import_boost",
        "literal_symbol_import_rank_json_only",
        "literal_symbol_collision_filter",
        "literal_symbol_policy_by_prompt_type",
        "tests_first_anchoring",
        "top1_primary",
        "policy_by_prompt_type",
    ]
    comp.add_argument("--packet-variant", choices=v5_variants, default=None, help="Packet V5 variant. Defaults to ranked_snippets.")
    comp.add_argument("--packet-strategy", choices=anchor_strategies, default=None, help="Internal V5 anchor strategy for tool_assisted_anchors_internal.")
    comp.add_argument("--packet-mode", choices=["auto", "paths-only", "evidence-snippets"], default="paths-only", help="Packet V3 detail mode.")
    comp.add_argument("--evidence-snippets", action="store_true", help="Shortcut for --packet-mode evidence-snippets.")
    comp.add_argument("--snippet-budget-tokens", type=int, default=DEFAULT_SNIPPET_BUDGET_TOKENS)
    comp.add_argument("--cache-optimized", action="store_true", help="Select cache-aware Packet V3 unless --packet-version v2 is explicitly set.")
    comp.add_argument("--context-only", action="store_true", help="Compile candidate context and safety boundaries without strong allowed-edit narrowing.")
    comp.add_argument("--save", action="store_true", help="Save last_packet artifacts under .premode/out/.")
    comp.add_argument("--no-record", action="store_true", help="Do not write .premode index, audit, metrics, or discovered-command artifacts.")
    comp.add_argument("--include-packet-debug-metadata", action="store_true", help="Opt in to selector diagnostics in the model-facing packet.")

    mp = sub.add_parser("map")
    mp.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default=None)
    mp.add_argument("--json", action="store_true")
    mp.add_argument("--summary-json", action="store_true")
    mp.add_argument("--compact-json", action="store_true")
    mp.add_argument("--max-files", type=int, default=None)
    mp.add_argument("--force-stdout", action="store_true")
    mp.add_argument("--out", default=None)

    cod = sub.add_parser("codex")
    cod.add_argument("prompt")
    cod.add_argument("--repo", default=None, help="Repository/worktree to launch from. Explicit paths are respected literally.")
    cod.add_argument("--fail-on-root-escalation", action="store_true")
    cod.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default=None)
    cod.add_argument("--dry-run", action="store_true")
    cod.add_argument("--execute", action="store_true", help="Explicitly execute Codex; default when --dry-run is absent.")
    cod.add_argument("--watch", action="store_true", help="Stream Codex stdout/stderr while the process runs.")
    cod.add_argument("--show-raw", action="store_true")
    cod.add_argument("--sandbox", default="workspace-write")
    cod.add_argument("--approval", default="on-request")
    cod.add_argument("--ephemeral", action=argparse.BooleanOptionalAction, default=True)
    cod.add_argument("--json", action="store_true")
    cod.add_argument("--output-last-message", default=None)
    cod.add_argument("--output-schema", default=None)
    cod.add_argument("--structured-final-report", action="store_true")
    cod.add_argument("--codex-profile", default=None)
    cod.add_argument("--add-dir", action="append", default=[])
    cod.add_argument("--skip-git-repo-check", action="store_true")
    cod.add_argument("--model", default=None)
    cod.add_argument("--oss", action="store_true")
    cod.add_argument("--no-repo-map", action="store_true", help="Disable repo-map summary and impact hints for the Codex path.")
    cod.add_argument("--packet-version", choices=["v2", "v3", "v4", "v5"], default=None, help="Compiled packet renderer version for the Codex path.")
    cod.add_argument("--packet-variant", choices=v5_variants, default=None, help="Packet V5 variant for the Codex path.")
    cod.add_argument("--packet-strategy", choices=anchor_strategies, default=None, help="Internal V5 anchor strategy for tool_assisted_anchors_internal.")
    cod.add_argument("--no-cache-optimized", action="store_true", help="Disable the default cache-aware Packet V3 Codex path.")
    cod.add_argument("--context-only", action="store_true", help="Compile candidate context and safety boundaries without strong allowed-edit narrowing.")
    cod.add_argument("--no-save", action="store_true", help="Do not write .premode packet, audit, metrics, or default final-output artifacts.")


    review = sub.add_parser("review-patch")
    review.add_argument("--against", default="main", help="Base ref to compare against. Defaults to main.")
    review.add_argument("--packet", default=None, help="Saved packet JSON path. Defaults to .premode/out/last_packet.json.")
    review.add_argument("--claims", "--claims-file", dest="claims", default=None, help="Optional agent report/claims file to inspect for validation claims.")
    review.add_argument("--json", action="store_true")
    review.add_argument("--out", default=None, help="Write machine-readable review report JSON to this path.")
    review.add_argument("--since-compile", action="store_true", help="Compare against the git HEAD captured when the saved packet was compiled and ignore unchanged preexisting dirty/untracked files.")

    bench = sub.add_parser("benchmark")
    bench.add_argument("--repo", default=None, help="Repository to benchmark. Defaults to the current repo root.")
    bench.add_argument("--fail-on-root-escalation", action="store_true")
    bench.add_argument("--prompts", default=None, help="JSON prompt suite. Accepts a list of strings or {prompts:[...]} with expected_files/expected_tests.")
    bench.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    bench.add_argument("--no-repo-map", action="store_true", help="Disable repo-map impact hints during benchmark compiles.")
    bench.add_argument("--no-cache-optimized", action="store_true", help="Disable cache-aware Packet V3 benchmark compiles.")
    bench.add_argument("--plugin", default=None, help="Resolve packet options from an installed Pre-mode plugin alias.")
    bench.add_argument("--packet-version", choices=["v2", "v3", "v4", "v5"], default=None)
    bench.add_argument("--packet-variant", choices=v5_variants, default=None)
    bench.add_argument("--packet-strategy", choices=anchor_strategies, default=None)
    bench.add_argument("--packet-mode", choices=["auto", "paths-only", "evidence-snippets"], default="paths-only")
    bench.add_argument("--cache-mode", choices=["strategy_isolated", "shared_cache"], default="strategy_isolated", help="Label benchmark cache discipline. Defaults to strategy-isolated rows.")
    bench.add_argument("--snippet-budget-tokens", type=int, default=DEFAULT_SNIPPET_BUDGET_TOKENS)
    bench.add_argument("--compile-modes", action="store_true", help="Include compile-only raw/v3 paths/v3 snippets/v2 mode comparisons.")
    bench.add_argument("--save-packets", action="store_true", help="Save last_packet artifacts while benchmarking. Off by default unless --include-review is used.")
    bench.add_argument("--include-review", action="store_true", help="Run review-patch after each compile to include pass/warning/blocked counts.")
    bench.add_argument("--against", default="main", help="Base ref for optional review-patch benchmark step.")
    bench.add_argument("--since-compile", action="store_true", help="Use review-patch --since-compile for optional review step.")
    bench.add_argument("--json", action="store_true")
    bench.add_argument("--out", default=None, help="Write benchmark JSON report to this path.")

    doc = sub.add_parser("doctor")
    doc.add_argument("--recommend-profile", action="store_true")

    sub.add_parser("run-fixture")

    stress = sub.add_parser("stress")
    stress.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    stress.add_argument("--json", action="store_true")
    stress.add_argument("--out", default=None)
    stress.add_argument("--keep", action="store_true", help="Keep generated fixture repos and include their base path in output.")

    plug = sub.add_parser("plugin", help="Experimental/deferred surface; not part of the primary MVP workflow.")
    plug_sub = plug.add_subparsers(dest="plugin_command", required=True)
    install = plug_sub.add_parser("install-local")
    install.add_argument("--scope", choices=["repo"], default="repo")

    stats = sub.add_parser("stats")
    stats.add_argument("--savings", action="store_true")
    stats.add_argument("--last", action="store_true")
    stats.add_argument("--json", action="store_true", help="Accepted for compatibility; stats output is JSON by default.")

    lab = sub.add_parser("lab", help="Experimental/deferred surface; not part of the primary MVP workflow.")
    lab_sub = lab.add_subparsers(dest="lab_command", required=True)
    compare = lab_sub.add_parser("compare")
    compare.add_argument("prompt")
    compare.add_argument("--provider", default="mock")
    compare.add_argument("--model", default=None)

    hook = sub.add_parser("hook", help="Experimental/deferred surface; not part of the primary MVP workflow.")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    ups = hook_sub.add_parser("user-prompt-submit")
    ups.add_argument("--mode", choices=["strict", "augment"], default="augment")

    sub.add_parser("mcp-server", help="Experimental/deferred surface; not part of the primary MVP workflow.")
    return p


def _apply_packet_plugin_or_exit(args: argparse.Namespace) -> dict[str, str | None] | None:
    try:
        packet_version, packet_variant, packet_strategy, resolution = apply_packet_plugin(
            getattr(args, "plugin", None),
            packet_version=getattr(args, "packet_version", None),
            packet_variant=getattr(args, "packet_variant", None),
            packet_strategy=getattr(args, "packet_strategy", None),
        )
    except PluginAliasError as exc:
        print(f"premode: error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    args.packet_version = packet_version
    args.packet_variant = packet_variant
    args.packet_strategy = packet_strategy
    return resolution


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = _guarded_repo(Path.cwd())

    if args.command == "init":
        _print_json(init_project(repo))
        return 0
    if args.command == "setup":
        setup_result = {"init": init_project(repo), "index": index_project(repo, None), "detect": detect_projects(repo), "plugin": None}
        if not args.skip_plugin:
            try:
                setup_result["plugin"] = install_local_plugin(repo, "repo")
            except Exception as exc:
                setup_result["plugin"] = {"warning": str(exc)}
        setup_result["next"] = ["Use: pcodex \"Fix the build\"", "Optional: open Codex /plugins and enable Pre-mode Router; review hooks with /hooks."]
        _print_json(setup_result)
        return 0
    if args.command == "detect":
        idx = load_index(repo) if False else None
        result = detect_projects(repo)
        _print_json(result)
        return 0
    if args.command == "debug-env":
        from . import compiler as compiler_module
        from . import locator as locator_module

        result = {
            "premode_import_path": str(Path(__file__).resolve()),
            "version": __version__,
            "compiler_path": str(Path(compiler_module.__file__).resolve()),
            "locator_path": str(Path(locator_module.__file__).resolve()),
            "locator_integration_enabled": hasattr(compiler_module, "locate_files") and hasattr(locator_module, "locate_files"),
            "dependency_proximity_enabled": hasattr(locator_module, "FileRelation"),
            "context_constraints_available": False,
            "package_root": str(Path(__file__).resolve().parents[2]),
        }
        try:
            from . import context_constraints as context_constraints_module

            result["context_constraints_available"] = True
            result["context_constraints_path"] = str(Path(context_constraints_module.__file__).resolve())
        except Exception as exc:
            result["context_constraints_error"] = str(exc)
        _print_json(result)
        return 0
    if args.command == "index":
        _print_json(index_project(repo, args.profile))
        return 0
    if args.command == "inspect":
        _print_json(inspect_prompt(repo, args.prompt, args.profile))
        return 0
    if args.command == "locate":
        locate_repo = _guarded_repo(Path.cwd(), args.repo, fail_on_root_escalation=args.fail_on_root_escalation) if args.repo else repo
        located = locate_files(locate_repo, args.prompt, max_files=max(1, int(args.max_files or 8)))
        primary_files = [_located_file_json(file) for file in located.primary_files]
        support_files = [_located_file_json(file) for file in located.support_files]
        verification_files = [_located_file_json(file) for file in located.verification_files]
        if not args.no_snippets:
            primary_with_snippets, _tokens = attach_snippets_to_files(
                locate_repo,
                located.primary_files,
                prompt=args.prompt,
                snippet_budget_tokens=args.snippet_budget_tokens,
                max_files=args.max_files,
            )
            snippets_by_path = {item["path"]: item.get("snippets") or [] for item in primary_with_snippets}
            for item in primary_files:
                item["snippets"] = snippets_by_path.get(item["path"], [])
        result = {
            "prompt": args.prompt,
            "primary_files": primary_files,
            "support_files": support_files,
            "verification_files": verification_files,
            "confidence": located.confidence,
            "ambiguity_reasons": list(located.ambiguity_reasons),
            "search_terms_if_expanding": list(located.uncovered_prompt_terms),
        }
        if args.json:
            _print_json(result)
        else:
            print("\n".join([file["path"] for file in primary_files]))
        return 0
    if args.command == "compile":
        compile_repo = _guarded_repo(Path.cwd(), args.repo, fail_on_root_escalation=args.fail_on_root_escalation) if args.repo else repo
        out = Path(args.out) if args.out else None
        json_out = Path(args.json_out) if args.json_out else None
        plugin_resolution = _apply_packet_plugin_or_exit(args)
        if args.tuning and str(args.packet_strategy or "").replace("-", "_").strip().lower() != "literal_symbol":
            print("premode: error: --tuning currently supports only --plugin literal_symbol / packet_strategy literal_symbol.", file=sys.stderr)
            return 2
        packet_mode = "evidence_snippets" if args.evidence_snippets or args.packet_mode == "evidence-snippets" else ("auto" if args.packet_mode == "auto" else "paths_only")
        try:
            result = compile_prompt(
                compile_repo,
                args.prompt,
                args.profile,
                out_path=out,
                json_out_path=json_out,
                use_repo_map=args.use_repo_map,
                packet_version=args.packet_version,
                packet_variant=args.packet_variant,
                packet_strategy=args.packet_strategy,
                packet_detail_mode=packet_mode,
                snippet_budget_tokens=args.snippet_budget_tokens,
                cache_optimized=args.cache_optimized,
                context_only=args.context_only,
                save=args.save,
                record_artifacts=not args.no_record,
                include_packet_debug_metadata=args.include_packet_debug_metadata,
                tuning_profile=Path(args.tuning) if args.tuning else None,
            )
        except TuningProfileError as exc:
            print(f"premode: error: {exc}", file=sys.stderr)
            return 2
        if plugin_resolution:
            result["plugin_alias_resolution"] = plugin_resolution
        if args.json:
            _print_json({k: v for k, v in result.items() if k != "packet"})
        elif out and json_out and not args.show_raw:
            _print_json(_compile_receipt(result, out=out, json_out=json_out))
        else:
            print(result["packet"])
            if args.show_raw:
                print("\n[raw prompt requested with --show-raw]")
                print(args.prompt)
        return 0

    if args.command == "map":
        out_path = Path(args.out) if args.out else None
        result = build_repo_map(repo, profile_name=args.profile, write=bool(out_path), out_path=out_path)
        if args.summary_json:
            _print_json(summarize_repo_map(result))
        elif args.compact_json:
            _print_json(compact_repo_map_summary(result, profile_name=args.profile or "standard", max_files=args.max_files))
        elif args.json:
            printable = limit_repo_map_files(result, args.max_files) if args.max_files else result
            estimated = estimate_repo_map_json_bytes(printable)
            stdout_limit = 1_000_000
            if estimated > stdout_limit and not args.force_stdout and not args.max_files:
                _print_json({
                    "status": "repo_map_stdout_too_large",
                    "estimated_json_bytes": estimated,
                    "repo_map_sha256": result.get("repo_map_sha256"),
                    "file_count": result.get("file_count"),
                    "edge_count": result.get("edge_count"),
                    "recommendation": "Use premode map --out .premode/out/repo_map.json, premode map --summary-json, or rerun with --force-stdout.",
                })
            else:
                _print_json(printable)
        else:
            lines = [
                f"Repo map: root={result.get('root', '.')} files={result.get('file_count')} edges={result.get('edge_count')} entrypoints={result.get('entrypoint_count')}",
                f"repo_map_sha256: {result.get('repo_map_sha256')}",
            ]
            if result.get("output_path"):
                lines.append(f"output: {result['output_path']}")
            else:
                lines.append("For full artifact output, use: premode map --out .premode/out/repo_map.json")
            print("\n".join(lines))
        return 0
    if args.command == "codex":
        launch_repo = _guarded_repo(Path.cwd(), args.repo, fail_on_root_escalation=args.fail_on_root_escalation) if args.repo else repo
        opts = CodexOptions(
            sandbox=args.sandbox,
            approval=args.approval,
            ephemeral=args.ephemeral,
            json=args.json,
            output_last_message=args.output_last_message,
            output_schema=args.output_schema,
            structured_final_report=args.structured_final_report,
            codex_profile=args.codex_profile,
            add_dir=args.add_dir,
            skip_git_repo_check=args.skip_git_repo_check,
            model=args.model,
            oss=args.oss,
            dry_run=args.dry_run,
            execute=args.execute,
            watch=args.watch,
            show_raw=args.show_raw,
            use_repo_map=not args.no_repo_map,
            cache_optimized=not args.no_cache_optimized,
            packet_version=args.packet_version,
            packet_variant=args.packet_variant,
            packet_strategy=args.packet_strategy,
            context_only=args.context_only,
            save=not args.no_save,
            record=not args.no_save,
        )
        result = run_codex(launch_repo, args.prompt, args.profile, opts)
        _print_json(result)
        return int(result.get("returncode", 0) or 0)

    if args.command == "review-patch":
        result = review_patch(
            repo,
            base_ref=args.against,
            packet_path=Path(args.packet) if args.packet else None,
            claims_path=Path(args.claims) if args.claims else None,
            out_path=Path(args.out) if args.out else None,
            since_compile=args.since_compile,
        )
        if args.json:
            _print_json(result)
        else:
            print(format_review_report(result))
        return 1 if result.get("error") else 0

    if args.command == "benchmark":
        bench_repo = _guarded_repo(Path.cwd(), args.repo, fail_on_root_escalation=args.fail_on_root_escalation) if args.repo else repo
        plugin_resolution = _apply_packet_plugin_or_exit(args)
        result = run_benchmark(
            bench_repo,
            prompts_path=Path(args.prompts) if args.prompts else None,
            profile=args.profile,
            use_repo_map=not args.no_repo_map,
            cache_optimized=not args.no_cache_optimized,
            packet_version=args.packet_version,
            packet_variant=args.packet_variant,
            packet_strategy=args.packet_strategy,
            packet_detail_mode="evidence_snippets" if args.packet_mode == "evidence-snippets" else ("auto" if args.packet_mode == "auto" else "paths_only"),
            snippet_budget_tokens=args.snippet_budget_tokens,
            compile_modes=args.compile_modes,
            save_packets=args.save_packets,
            include_review=args.include_review,
            review_against=args.against,
            review_since_compile=args.since_compile,
            out_path=Path(args.out) if args.out else None,
            cache_mode=args.cache_mode,
        )
        if plugin_resolution:
            result["plugin_alias_resolution"] = plugin_resolution
            if args.out:
                out_abs = Path(args.out)
                if not out_abs.is_absolute():
                    out_abs = bench_repo / out_abs
                out_abs.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.json:
            _print_json(result)
        else:
            print(format_benchmark_report(result))
        return 1 if result.get("error_count") else 0

    if args.command == "doctor":
        _print_json(doctor(repo, args.recommend_profile))
        return 0
    if args.command == "run-fixture":
        _print_json(run_fixture())
        return 0
    if args.command == "stress":
        out_path = Path(args.out) if args.out else None
        report = run_universal_stress(profile=args.profile, keep=args.keep, out_path=out_path)
        if args.json:
            _print_json(report)
        else:
            print(format_stress_table(report))
        return 0 if int(report.get("failed", 0) or 0) == 0 else 1
    if args.command == "plugin":
        if args.plugin_command == "install-local":
            _print_json(install_local_plugin(repo, args.scope))
            return 0
    if args.command == "stats":
        if args.last:
            _print_json(last_metric(repo))
        elif args.savings:
            _print_json(summarize_savings(repo))
        else:
            _print_json({"metrics": read_metrics(repo)})
        return 0
    if args.command == "lab":
        if args.lab_command == "compare":
            deterministic = compile_prompt(repo, args.prompt, None)
            report = {
                "status": "experimental",
                "provider": args.provider,
                "model": args.model,
                "local_assist_enabled": False,
                "deterministic_packet_sha256": deterministic["compiled_packet_sha256"],
                "deterministic_primary_intent": deterministic["primary_intent"],
                "assist_result": "mock comparison only; local model providers are not part of default setup",
                "recommendation": "deterministic",
            }
            _print_json(report)
            return 0
    if args.command == "hook":
        if args.hook_command == "user-prompt-submit":
            return hook_main(["--mode", args.mode])
    if args.command == "mcp-server":
        return mcp_serve()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


def pcodex_main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    bootstrap_commands = {
        "install",
        "doctor",
        "first-run",
        "status",
        "setup",
        "cleanup",
        "on",
        "off",
        "tuned",
        "tune",
        "mcp-server",
        "compile",
        "run",
    }
    if argv and argv[0] in bootstrap_commands:
        from .pcodex_bootstrap import main as pcodex_bootstrap_main

        return pcodex_bootstrap_main(argv)
    if argv and argv[0] in {"-h", "--help"}:
        from .pcodex_bootstrap import main as pcodex_bootstrap_main

        return pcodex_bootstrap_main(argv)
    if "--dry-run" not in argv and "--execute" not in argv:
        argv.append("--execute")
    if "--output-last-message" not in argv and "--no-save" not in argv:
        argv.extend(["--output-last-message", ".premode/out/final.md"])
    return main(["codex", *argv])
