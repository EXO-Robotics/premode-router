from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compiler import compile_prompt
from .config import premode_dir
from .review_patch import review_patch


def _safe_load_json(path: Path) -> Any:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _coerce_prompt_cases(data: Any) -> list[dict[str, Any]]:
    """Accept a simple list of strings or a richer benchmark prompt suite."""
    if isinstance(data, dict):
        raw_cases = data.get('prompts') or data.get('cases') or []
    elif isinstance(data, list):
        raw_cases = data
    else:
        raw_cases = []
    cases: list[dict[str, Any]] = []
    for i, item in enumerate(raw_cases, start=1):
        if isinstance(item, str):
            cases.append({'name': f'prompt_{i}', 'prompt': item})
        elif isinstance(item, dict):
            prompt = str(item.get('prompt') or item.get('task') or '').strip()
            if prompt:
                case = dict(item)
                case.setdefault('name', f'prompt_{i}')
                case['prompt'] = prompt
                cases.append(case)
    return cases


def _builtin_prompt_cases(repo_root: Path) -> list[dict[str, Any]]:
    """Small universal prompt set for repos without a benchmark_prompts.json."""
    candidates = [
        ('python_cli', 'Fix the CLI argument validation without expanding scope.', ['src/', 'tests/']),
        ('build_repair', 'Fix the build or failing test using the smallest safe patch.', ['src/', 'tests/', 'package.json', 'pyproject.toml', 'go.mod', 'Cargo.toml', 'Package.swift']),
        ('docs_only', 'Update the README quickstart without changing source code.', ['README.md', 'docs/']),
    ]
    cases: list[dict[str, Any]] = []
    existing_paths = {p.as_posix() for p in repo_root.rglob('*') if p.is_file() and '.git/' not in p.as_posix()}
    for name, prompt, expected_prefixes in candidates:
        cases.append({
            'name': name,
            'prompt': prompt,
            'expected_files': [p for p in existing_paths if any(p == prefix.rstrip('/') or p.startswith(prefix.rstrip('/') + '/') for prefix in expected_prefixes)][:8],
        })
    return cases


def load_prompt_cases(repo_root: Path, prompts_path: Path | None = None) -> tuple[list[dict[str, Any]], str]:
    if prompts_path:
        path = prompts_path if prompts_path.is_absolute() else repo_root / prompts_path
        return _coerce_prompt_cases(_safe_load_json(path)), str(path)
    default = repo_root / 'benchmark_prompts.json'
    if default.exists():
        return _coerce_prompt_cases(_safe_load_json(default)), str(default)
    examples_default = repo_root / 'examples' / 'benchmark_prompts.json'
    if examples_default.exists():
        return _coerce_prompt_cases(_safe_load_json(examples_default)), str(examples_default)
    return _builtin_prompt_cases(repo_root), 'builtin_universal_prompts'


def _list_paths(items: Any) -> list[str]:
    out: list[str] = []
    for item in items or []:
        if isinstance(item, dict) and item.get('path'):
            out.append(str(item['path']))
        elif isinstance(item, str):
            out.append(item)
    return _dedupe(out)


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).replace('\\', '/').strip().lstrip('./')
        key = text.lower()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def _match_expected(actual: list[str], expected: list[str]) -> dict[str, Any]:
    actual_norm = {p.lower().lstrip('./') for p in actual}
    hits: list[str] = []
    misses: list[str] = []
    for exp in _dedupe(expected):
        low = exp.lower().lstrip('./')
        matched = any(a == low or a.endswith('/' + low) or low.endswith('/') and a.startswith(low) for a in actual_norm)
        if matched:
            hits.append(exp)
        else:
            misses.append(exp)
    return {
        'expected': _dedupe(expected),
        'hits': hits,
        'misses': misses,
        'hit_count': len(hits),
        'miss_count': len(misses),
        'hit_rate': round(len(hits) / max(1, len(_dedupe(expected))), 4) if expected else None,
    }


def _case_report(
    repo_root: Path,
    case: dict[str, Any],
    *,
    profile: str | None,
    use_repo_map: bool,
    cache_optimized: bool,
    packet_version: str | None,
    save_packets: bool,
    include_review: bool,
    review_against: str,
    review_since_compile: bool,
) -> dict[str, Any]:
    result = compile_prompt(
        repo_root,
        str(case['prompt']),
        profile,
        use_repo_map=use_repo_map,
        cache_optimized=cache_optimized,
        packet_version=packet_version,
        save=save_packets or include_review,
    )
    metrics = result.get('metrics') or {}
    impact = result.get('impact_map') if isinstance(result.get('impact_map'), dict) else {}
    likely_files = _list_paths(impact.get('likely_files'))
    related_tests = _list_paths(impact.get('related_tests'))
    verification_order = [str((x or {}).get('command') if isinstance(x, dict) else x) for x in (impact.get('verification_order') or [])]
    eligible = int(metrics.get('eligible_readable_repo_tokens') or 0)
    packet_tokens = int(metrics.get('packet_total_tokens') or metrics.get('estimated_input_tokens') or 0)
    hard_budget = int((result.get('caps') or {}).get('hard_packet_token_budget') or 0)
    review_result = None
    if include_review:
        review_result = review_patch(repo_root, base_ref=review_against, since_compile=review_since_compile)
    expected_files = _dedupe([str(x) for x in case.get('expected_files') or case.get('expected_likely_files') or []])
    expected_tests = _dedupe([str(x) for x in case.get('expected_tests') or case.get('expected_related_tests') or []])
    cacheable_prefix_tokens = int(result.get('cacheable_prefix_tokens') or 0)
    dynamic_suffix_tokens = int(result.get('dynamic_suffix_tokens') or 0)
    cache_split_total = cacheable_prefix_tokens + dynamic_suffix_tokens
    budget_exceeded_by = int(metrics.get('budget_exceeded_by') or 0)
    budget_exceeded = bool(budget_exceeded_by)
    if budget_exceeded and int(metrics.get('policy_metadata_tokens') or 0) >= int(metrics.get('selected_context_tokens') or 0):
        budget_reason = 'policy_metadata_or_packet_overhead'
    elif budget_exceeded:
        budget_reason = 'selected_context_or_repo_size'
    else:
        budget_reason = None
    return {
        'name': str(case.get('name') or 'prompt'),
        'prompt': str(case['prompt']),
        'packet_version': result.get('packet_version'),
        'resource_profile': result.get('resource_profile'),
        'packet_mode': result.get('packet_mode'),
        'eligible_repo_tokens': eligible,
        'packet_tokens': packet_tokens,
        'estimated_savings_tokens': max(0, eligible - packet_tokens) if eligible and packet_tokens else None,
        'estimated_savings_vs_eligible_repo_percent': metrics.get('estimated_savings_vs_eligible_repo_percent'),
        'selected_context_tokens': metrics.get('selected_context_tokens'),
        'policy_metadata_tokens': metrics.get('policy_metadata_tokens'),
        'cacheable_prefix_tokens': cacheable_prefix_tokens,
        'dynamic_suffix_tokens': dynamic_suffix_tokens,
        'cacheable_prefix_percent': round((cacheable_prefix_tokens / cache_split_total) * 100, 2) if cache_split_total else None,
        'dynamic_suffix_percent': round((dynamic_suffix_tokens / cache_split_total) * 100, 2) if cache_split_total else None,
        'cacheable_prefix_sha256': result.get('cacheable_prefix_sha256'),
        'dynamic_suffix_sha256': result.get('dynamic_suffix_sha256'),
        'repo_map_sha256': result.get('repo_map_sha256'),
        'packet_sha256': result.get('compiled_packet_sha256'),
        'budget_exceeded': budget_exceeded,
        'budget_exceeded_by': budget_exceeded_by,
        'hard_packet_token_budget': hard_budget,
        'budget_exceeded_reason': budget_reason,
        'likely_files': likely_files,
        'related_tests': related_tests,
        'verification_order': verification_order,
        'likely_file_match': _match_expected(likely_files, expected_files),
        'related_test_match': _match_expected(related_tests, expected_tests),
        'review': None if review_result is None else {
            'merge_readiness': review_result.get('merge_readiness'),
            'scope_compliance': review_result.get('scope_compliance'),
            'changed_files': review_result.get('changed_files'),
            'blocking_findings': review_result.get('blocking_findings'),
            'warning_findings': review_result.get('warning_findings'),
            'verification_status': (review_result.get('verification') or {}).get('verification_status'),
        },
    }


def _summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not cases:
        return {
            'prompt_count': 0,
            'average_packet_tokens': 0,
            'average_savings_percent': None,
            'budget_exceeded_count': 0,
            'review_readiness_counts': {},
        }
    packet_tokens = [int(c.get('packet_tokens') or 0) for c in cases]
    savings = [float(c.get('estimated_savings_vs_eligible_repo_percent')) for c in cases if c.get('estimated_savings_vs_eligible_repo_percent') is not None]
    readiness: dict[str, int] = {}
    for case in cases:
        review = case.get('review') or {}
        if review.get('merge_readiness'):
            key = str(review['merge_readiness'])
            readiness[key] = readiness.get(key, 0) + 1
    likely_expected_total = sum(len((c.get('likely_file_match') or {}).get('expected') or []) for c in cases)
    likely_hit_total = sum(int((c.get('likely_file_match') or {}).get('hit_count') or 0) for c in cases)
    test_expected_total = sum(len((c.get('related_test_match') or {}).get('expected') or []) for c in cases)
    test_hit_total = sum(int((c.get('related_test_match') or {}).get('hit_count') or 0) for c in cases)
    return {
        'prompt_count': len(cases),
        'average_packet_tokens': round(sum(packet_tokens) / len(packet_tokens), 2),
        'median_packet_tokens': sorted(packet_tokens)[len(packet_tokens) // 2],
        'max_packet_tokens': max(packet_tokens),
        'average_savings_percent': round(sum(savings) / len(savings), 4) if savings else None,
        'average_cacheable_prefix_tokens': round(sum(int(c.get('cacheable_prefix_tokens') or 0) for c in cases) / len(cases), 2),
        'average_dynamic_suffix_tokens': round(sum(int(c.get('dynamic_suffix_tokens') or 0) for c in cases) / len(cases), 2),
        'budget_exceeded_count': sum(1 for c in cases if c.get('budget_exceeded')),
        'budget_exceeded_prompts': [
            {
                'name': c.get('name'),
                'packet_tokens': c.get('packet_tokens'),
                'budget': c.get('hard_packet_token_budget'),
                'over_by': c.get('budget_exceeded_by'),
                'likely_reason': c.get('budget_exceeded_reason') or 'unknown',
            }
            for c in cases
            if c.get('budget_exceeded')
        ],
        'average_cacheable_prefix_percent': round(
            sum(float(c.get('cacheable_prefix_percent') or 0) for c in cases if c.get('cacheable_prefix_percent') is not None)
            / max(1, sum(1 for c in cases if c.get('cacheable_prefix_percent') is not None)),
            2,
        ) if any(c.get('cacheable_prefix_percent') is not None for c in cases) else None,
        'average_dynamic_suffix_percent': round(
            sum(float(c.get('dynamic_suffix_percent') or 0) for c in cases if c.get('dynamic_suffix_percent') is not None)
            / max(1, sum(1 for c in cases if c.get('dynamic_suffix_percent') is not None)),
            2,
        ) if any(c.get('dynamic_suffix_percent') is not None for c in cases) else None,
        'likely_file_expected_count': likely_expected_total,
        'likely_file_hit_count': likely_hit_total,
        'likely_file_hit_rate': round(likely_hit_total / max(1, likely_expected_total), 4) if likely_expected_total else None,
        'related_test_expected_count': test_expected_total,
        'related_test_hit_count': test_hit_total,
        'related_test_hit_rate': round(test_hit_total / max(1, test_expected_total), 4) if test_expected_total else None,
        'review_readiness_counts': readiness,
    }


def run_benchmark(
    repo_root: Path,
    *,
    prompts_path: Path | None = None,
    profile: str | None = 'lite',
    use_repo_map: bool = True,
    cache_optimized: bool = True,
    packet_version: str | None = None,
    save_packets: bool = False,
    include_review: bool = False,
    review_against: str = 'main',
    review_since_compile: bool = False,
    out_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    prompt_cases, prompt_source = load_prompt_cases(repo_root, prompts_path)
    cases: list[dict[str, Any]] = []
    for case in prompt_cases:
        try:
            cases.append(_case_report(
                repo_root,
                case,
                profile=profile,
                use_repo_map=use_repo_map,
                cache_optimized=cache_optimized,
                packet_version=packet_version,
                save_packets=save_packets,
                include_review=include_review,
                review_against=review_against,
                review_since_compile=review_since_compile,
            ))
        except Exception as exc:
            cases.append({
                'name': str(case.get('name') or 'prompt'),
                'prompt': str(case.get('prompt') or ''),
                'error': str(exc),
                'benchmark_status': 'error',
            })
    report = {
        'schema_version': 1,
        'benchmark_kind': 'premode_benchmark',
        'repo_root': str(repo_root),
        'prompt_source': prompt_source,
        'profile': profile,
        'use_repo_map': bool(use_repo_map),
        'cache_optimized': bool(cache_optimized),
        'packet_version_requested': packet_version,
        'include_review': bool(include_review),
        'review_against': review_against if include_review else None,
        'review_since_compile': bool(review_since_compile) if include_review else False,
        'summary': _summarize_cases([c for c in cases if not c.get('error')]),
        'prompt_count': len(prompt_cases),
        'error_count': sum(1 for c in cases if c.get('error')),
        'cases': cases,
    }
    if out_path:
        out_abs = out_path if out_path.is_absolute() else repo_root / out_path
        out_abs.parent.mkdir(parents=True, exist_ok=True)
        out_abs.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
        report['output_path'] = str(out_abs)
    return report


def format_benchmark_report(report: dict[str, Any]) -> str:
    summary = report.get('summary') or {}
    lines = [
        'Pre-mode benchmark',
        f"Prompts: {summary.get('prompt_count', 0)}",
        f"Average packet tokens: {summary.get('average_packet_tokens')}",
        f"Average savings vs eligible repo: {summary.get('average_savings_percent')}%",
        f"Average cacheable prefix tokens: {summary.get('average_cacheable_prefix_tokens')}",
        f"Average cache split: {summary.get('average_cacheable_prefix_percent')}% prefix / {summary.get('average_dynamic_suffix_percent')}% suffix",
        f"Budget exceeded: {summary.get('budget_exceeded_count', 0)}",
    ]
    exceeded = summary.get('budget_exceeded_prompts') or []
    if exceeded:
        lines.append('Budget exceeded prompts:')
        for item in exceeded:
            lines.append(f"- {item.get('name')}: {item.get('packet_tokens')} / {item.get('budget')} tokens, over by {item.get('over_by')} ({item.get('likely_reason')})")
    readiness = summary.get('review_readiness_counts') or {}
    if readiness:
        lines.append('Review readiness: ' + ', '.join(f'{k}={v}' for k, v in sorted(readiness.items())))
    lines.append('')
    lines.append('case | packet_tokens | savings% | prefix | budget | likely_files | review')
    lines.append('--- | ---: | ---: | ---: | --- | --- | ---')
    for case in report.get('cases') or []:
        if case.get('error'):
            lines.append(f"{case.get('name')} | error |  |  |  |  | {case.get('error')}")
            continue
        review = (case.get('review') or {}).get('merge_readiness') or '-'
        likely = ', '.join((case.get('likely_files') or [])[:3]) or '-'
        budget = 'over' if case.get('budget_exceeded') else 'ok'
        lines.append(
            f"{case.get('name')} | {case.get('packet_tokens')} | {case.get('estimated_savings_vs_eligible_repo_percent')} | "
            f"{case.get('cacheable_prefix_tokens')} | {budget} | {likely} | {review}"
        )
    if report.get('output_path'):
        lines.append('')
        lines.append(f"output: {report['output_path']}")
    return '\n'.join(lines)
