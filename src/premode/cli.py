from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .paths import find_repo_root
from .config import init_project
from .indexer import index_project
from .compiler import inspect_prompt, compile_prompt
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


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


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

    ip = sub.add_parser("index")
    ip.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default=None)
    ip.add_argument("--incremental", action="store_true", help="Accepted for seamless runs; MVP rewrites the lightweight index.")

    insp = sub.add_parser("inspect")
    insp.add_argument("prompt")
    insp.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default=None)

    comp = sub.add_parser("compile")
    comp.add_argument("prompt")
    comp.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default=None)
    comp.add_argument("--out", default=None)
    comp.add_argument("--json-out", default=None)
    comp.add_argument("--json", action="store_true")
    comp.add_argument("--show-raw", action="store_true")
    comp.add_argument("--use-repo-map", action="store_true", help="Include deterministic repo-map summary and impact hints in the compiled packet.")
    comp.add_argument("--packet-version", choices=["v2", "v3"], default=None, help="Compiled packet renderer version. v3 is cache-aware.")
    comp.add_argument("--cache-optimized", action="store_true", help="Select cache-aware Packet V3 unless --packet-version v2 is explicitly set.")
    comp.add_argument("--save", action="store_true", help="Save last_packet artifacts under .premode/out/.")

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
    cod.add_argument("--packet-version", choices=["v2", "v3"], default=None, help="Compiled packet renderer version for the Codex path.")
    cod.add_argument("--no-cache-optimized", action="store_true", help="Disable the default cache-aware Packet V3 Codex path.")


    review = sub.add_parser("review-patch")
    review.add_argument("--against", default="main", help="Base ref to compare against. Defaults to main.")
    review.add_argument("--packet", default=None, help="Saved packet JSON path. Defaults to .premode/out/last_packet.json.")
    review.add_argument("--claims", default=None, help="Optional agent report/claims file to inspect for test evidence.")
    review.add_argument("--json", action="store_true")
    review.add_argument("--out", default=None, help="Write machine-readable review report JSON to this path.")
    review.add_argument("--since-compile", action="store_true", help="Compare against the git HEAD captured when the saved packet was compiled and ignore unchanged preexisting dirty/untracked files.")

    bench = sub.add_parser("benchmark")
    bench.add_argument("--repo", default=None, help="Repository to benchmark. Defaults to the current repo root.")
    bench.add_argument("--prompts", default=None, help="JSON prompt suite. Accepts a list of strings or {prompts:[...]} with expected_files/expected_tests.")
    bench.add_argument("--profile", choices=["auto", "lite", "standard", "pro"], default="lite")
    bench.add_argument("--no-repo-map", action="store_true", help="Disable repo-map impact hints during benchmark compiles.")
    bench.add_argument("--no-cache-optimized", action="store_true", help="Disable cache-aware Packet V3 benchmark compiles.")
    bench.add_argument("--packet-version", choices=["v2", "v3"], default=None)
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

    plug = sub.add_parser("plugin")
    plug_sub = plug.add_subparsers(dest="plugin_command", required=True)
    install = plug_sub.add_parser("install-local")
    install.add_argument("--scope", choices=["repo"], default="repo")

    stats = sub.add_parser("stats")
    stats.add_argument("--savings", action="store_true")
    stats.add_argument("--last", action="store_true")
    stats.add_argument("--json", action="store_true", help="Accepted for compatibility; stats output is JSON by default.")

    lab = sub.add_parser("lab")
    lab_sub = lab.add_subparsers(dest="lab_command", required=True)
    compare = lab_sub.add_parser("compare")
    compare.add_argument("prompt")
    compare.add_argument("--provider", default="mock")
    compare.add_argument("--model", default=None)

    hook = sub.add_parser("hook")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    ups = hook_sub.add_parser("user-prompt-submit")
    ups.add_argument("--mode", choices=["strict", "augment"], default="augment")

    sub.add_parser("mcp-server")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = find_repo_root(Path.cwd())

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
    if args.command == "index":
        _print_json(index_project(repo, args.profile))
        return 0
    if args.command == "inspect":
        _print_json(inspect_prompt(repo, args.prompt, args.profile))
        return 0
    if args.command == "compile":
        out = Path(args.out) if args.out else None
        json_out = Path(args.json_out) if args.json_out else None
        result = compile_prompt(
            repo,
            args.prompt,
            args.profile,
            out_path=out,
            json_out_path=json_out,
            use_repo_map=args.use_repo_map,
            packet_version=args.packet_version,
            cache_optimized=args.cache_optimized,
            save=args.save,
        )
        if args.json:
            _print_json({k: v for k, v in result.items() if k != "packet"})
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
            save=True,
        )
        result = run_codex(repo, args.prompt, args.profile, opts)
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
        bench_repo = find_repo_root(Path(args.repo).resolve()) if args.repo else repo
        result = run_benchmark(
            bench_repo,
            prompts_path=Path(args.prompts) if args.prompts else None,
            profile=args.profile,
            use_repo_map=not args.no_repo_map,
            cache_optimized=not args.no_cache_optimized,
            packet_version=args.packet_version,
            save_packets=args.save_packets,
            include_review=args.include_review,
            review_against=args.against,
            review_since_compile=args.since_compile,
            out_path=Path(args.out) if args.out else None,
        )
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
    if "--dry-run" not in argv and "--execute" not in argv:
        argv.append("--execute")
    if "--output-last-message" not in argv:
        argv.extend(["--output-last-message", ".premode/out/final.md"])
    return main(["codex", *argv])
