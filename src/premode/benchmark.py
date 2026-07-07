from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from .compiler import compile_prompt, estimate_tokens
from .config import premode_dir
from .review_patch import review_patch

LOW_LIKELY_FILE_PRECISION_THRESHOLD = 0.25
LOW_RELATED_TEST_PRECISION_THRESHOLD = 0.20
BROAD_SELECTED_LIKELY_FILE_THRESHOLD = 8
BROAD_SELECTED_TEST_THRESHOLD = 8


def _warning_category(code: str) -> str:
    if code in {'missing_expected_tests', 'null_related_test_hit_rate'}:
        return 'null_expected_tests_warning'
    if code in {'missing_expected_files', 'null_likely_file_hit_rate'}:
        return 'expectation_uncertainty_warning'
    if code in {'low_likely_file_precision', 'low_related_test_precision'}:
        return 'precision_warning'
    if code == 'broad_likely_file_selection':
        return 'broad_candidate_warning'
    if code == 'broad_related_test_selection':
        return 'related_test_anchor_warning'
    if code in {'fallback_only_related_tests', 'low_related_test_anchor_confidence'}:
        return 'fallback_related_test_warning'
    return 'simulation_expectation_warning'


def _docs_only_without_test_expectation(case: dict[str, Any], expected_files: list[str], expected_tests: list[str]) -> bool:
    if expected_tests or not expected_files:
        return False
    task_type = str(case.get('task_type') or case.get('name') or '').lower()
    prompt = str(case.get('prompt') or '').lower()
    if 'docs_only' not in task_type:
        return False
    return not any(term in prompt for term in ('test', 'coverage', 'validation', 'benchmark', 'expectation', 'regression'))


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


def _has_glob(pattern: str) -> bool:
    return any(ch in pattern for ch in '*?[')


def _path_exists(repo_root: Path, pattern: str) -> bool:
    text = str(pattern).replace('\\', '/').strip().lstrip('./')
    if not text:
        return False
    if _has_glob(text):
        return any(repo_root.glob(text))
    return (repo_root / text).exists()


def _matches_path(actual: str, expected: str) -> bool:
    actual_norm = actual.lower().replace('\\', '/').strip().lstrip('./')
    expected_norm = expected.lower().replace('\\', '/').strip().lstrip('./')
    if _has_glob(expected_norm):
        return fnmatch.fnmatch(actual_norm, expected_norm)
    return (
        actual_norm == expected_norm
        or actual_norm.endswith('/' + expected_norm)
        or (expected_norm.endswith('/') and actual_norm.startswith(expected_norm))
    )


def _match_expected(actual: list[str], expected: list[str]) -> dict[str, Any]:
    hits: list[str] = []
    misses: list[str] = []
    for exp in _dedupe(expected):
        matched = any(_matches_path(a, exp) for a in actual)
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


def _selection_quality(selected: list[str], expected: list[str], expected_match: dict[str, Any], *, selected_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    selected_paths = _dedupe(selected)
    expected_paths = _dedupe(expected)
    selected_hit_paths = [
        path for path in selected_paths
        if any(_matches_path(path, exp) for exp in expected_paths)
    ] if expected_paths else []
    selected_count = len(selected_paths)
    selected_hit_count = len(selected_hit_paths)
    fallback_only_count = 0
    if selected_items:
        fallback_only_count = sum(
            1
            for item in selected_items
            if isinstance(item, dict)
            and (
                item.get('related_test_fallback_warning') is True
                or item.get('related_test_resolution_reason') == 'fallback'
            )
        )
    return {
        'expected_count': len(expected_paths),
        'selected_count': selected_count,
        'selected_hit_count': selected_hit_count,
        'precision': round(selected_hit_count / selected_count, 4) if expected_paths and selected_count else None,
        'recall': expected_match.get('hit_rate') if expected_paths else None,
        'extra_count': selected_count - selected_hit_count if expected_paths else None,
        'fallback_only_count': fallback_only_count,
    }


def _case_expectation_paths(case: dict[str, Any], *keys: str) -> list[str]:
    items: list[str] = []
    for key in keys:
        items.extend(str(x) for x in case.get(key) or [])
    return _dedupe(items)


def _case_expectation_guard(
    repo_root: Path,
    case: dict[str, Any],
    *,
    expected_files: list[str],
    expected_tests: list[str],
    forbidden_files: list[str],
    likely_match: dict[str, Any],
    test_match: dict[str, Any],
    forbidden_match: dict[str, Any],
    likely_quality: dict[str, Any],
    test_quality: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    docs_only_without_tests = _docs_only_without_test_expectation(case, expected_files, expected_tests)

    def warn(code: str, message: str, paths: list[str] | None = None, **fields: Any) -> None:
        item: dict[str, Any] = {'code': code, 'message': message, 'warning_category': _warning_category(code)}
        if paths is not None:
            item['paths'] = paths
        item.update(fields)
        warnings.append(item)

    def fail(code: str, message: str, paths: list[str] | None = None) -> None:
        item: dict[str, Any] = {'code': code, 'message': message}
        if paths is not None:
            item['paths'] = paths
        failures.append(item)

    if not expected_files:
        warn('missing_expected_files', 'Benchmark case has no expected_files; likely-file hit rate is null.')
    if not expected_tests and not docs_only_without_tests:
        warn('missing_expected_tests', 'Benchmark case has no expected_tests; related-test hit rate is null.')
    if likely_match.get('hit_rate') is None:
        warn('null_likely_file_hit_rate', 'Likely-file hit rate is null because expected_files is empty.')
    if test_match.get('hit_rate') is None and not docs_only_without_tests:
        warn('null_related_test_hit_rate', 'Related-test hit rate is null because expected_tests is empty.')

    missing_expected_paths = [
        path for path in _dedupe(expected_files + expected_tests)
        if not _path_exists(repo_root, path)
    ]
    if missing_expected_paths:
        fail('missing_expected_paths', 'Expected benchmark paths are absent from the local fixture/repo.', missing_expected_paths)

    if likely_match.get('misses'):
        fail('expected_files_not_routed', 'Expected files were not present in likely_files.', list(likely_match.get('misses') or []))
    if test_match.get('misses'):
        fail('expected_tests_not_routed', 'Expected tests were not present in related_tests.', list(test_match.get('misses') or []))
    if forbidden_files and forbidden_match.get('hits'):
        fail('forbidden_primary_files_routed', 'Forbidden primary edit files appeared in likely_files.', list(forbidden_match.get('hits') or []))

    likely_precision = likely_quality.get('precision')
    if (
        expected_files
        and likely_precision is not None
        and float(likely_precision) < LOW_LIKELY_FILE_PRECISION_THRESHOLD
    ):
        warn(
            'low_likely_file_precision',
            'Likely-file precision is below the benchmark warning threshold.',
            precision=likely_precision,
            threshold=LOW_LIKELY_FILE_PRECISION_THRESHOLD,
            selected_count=likely_quality.get('selected_count'),
            extra_count=likely_quality.get('extra_count'),
        )
    related_precision = test_quality.get('precision')
    if (
        expected_tests
        and related_precision is not None
        and float(related_precision) < LOW_RELATED_TEST_PRECISION_THRESHOLD
    ):
        warn(
            'low_related_test_precision',
            'Related-test precision is below the benchmark warning threshold.',
            precision=related_precision,
            threshold=LOW_RELATED_TEST_PRECISION_THRESHOLD,
            selected_count=test_quality.get('selected_count'),
            extra_count=test_quality.get('extra_count'),
        )
    likely_selected_count = int(likely_quality.get('selected_count') or 0)
    if likely_selected_count > BROAD_SELECTED_LIKELY_FILE_THRESHOLD:
        warn(
            'broad_likely_file_selection',
            'Likely-file selected set is broader than the benchmark warning threshold.',
            selected_count=likely_selected_count,
            threshold=BROAD_SELECTED_LIKELY_FILE_THRESHOLD,
            extra_count=likely_quality.get('extra_count'),
        )
    test_selected_count = int(test_quality.get('selected_count') or 0)
    if test_selected_count > BROAD_SELECTED_TEST_THRESHOLD:
        warn(
            'broad_related_test_selection',
            'Related-test selected set is broader than the benchmark warning threshold.',
            selected_count=test_selected_count,
            threshold=BROAD_SELECTED_TEST_THRESHOLD,
            extra_count=test_quality.get('extra_count'),
        )

    fallback_only_count = int(test_quality.get('fallback_only_count') or 0)
    if fallback_only_count and fallback_only_count == int(test_quality.get('selected_count') or 0):
        warn(
            'fallback_only_related_tests',
            'Selected related tests are fallback-only; resolver could not find a direct package or source anchor.',
            selected_count=test_quality.get('selected_count'),
            fallback_only_count=fallback_only_count,
        )

    return {
        'benchmark_status': 'fail' if failures else ('warning' if warnings else 'pass'),
        'validation_warnings': warnings,
        'validation_failures': failures,
    }


def _compile_mode_report(
    repo_root: Path,
    prompt: str,
    *,
    mode: str,
    profile: str | None,
    use_repo_map: bool,
    snippet_budget_tokens: int,
) -> dict[str, Any]:
    if mode == 'standard_raw_prompt':
        return {
            'mode': mode,
            'packet_total_tokens': estimate_tokens(prompt),
            'model_facing_evidence_tokens': 0,
            'candidate_files': [],
            'support_files': [],
            'verification_files': [],
            'stable_prefix_hash': None,
            'dynamic_suffix_hash': None,
            'full_repo_reduction_percent': None,
        }
    if mode == 'v2_full_context_if_available':
        packet_version = 'v2'
    elif mode in {'v4_context_only_paths', 'v4_context_only_snippets'}:
        packet_version = 'v4'
    elif mode.startswith('v5_'):
        packet_version = 'v5'
    else:
        packet_version = 'v3'
    variant = None
    strategy = None
    if mode == 'v5_ranked_paths':
        variant = 'ranked_paths'
    elif mode == 'v5_ranked_snippets':
        variant = 'ranked_snippets'
    elif mode == 'v5_primary_tests_only':
        variant = 'primary_tests_only'
    elif mode == 'v5_top1_plus_tests':
        variant = 'top1_plus_tests'
    elif mode == 'v5_ranked_paths_plus_anchors':
        variant = 'ranked_paths_plus_anchors'
    elif mode == 'v5_ranked_paths_selective_snippets':
        variant = 'ranked_paths_selective_snippets'
    elif mode == 'v5_ranked_paths_no_support':
        variant = 'ranked_paths_no_support'
    elif mode == 'v5_ranked_paths_tests_first':
        variant = 'ranked_paths_tests_first'
    elif mode == 'v5_ranked_paths_top1':
        variant = 'ranked_paths_top1'
    elif mode == 'v5_tool_assisted_backbone':
        variant = 'tool_assisted_backbone'
    elif mode == 'v5_tool_assisted_backbone_no_task_class':
        variant = 'tool_assisted_backbone_no_task_class'
    elif mode == 'v5_tool_assisted_backbone_no_relations':
        variant = 'tool_assisted_backbone_no_relations'
    elif mode == 'v5_tool_assisted_anchors_internal':
        variant = 'tool_assisted_anchors_internal'
    elif mode.startswith('v5_tool_assisted_anchors_internal_'):
        variant = 'tool_assisted_anchors_internal'
        strategy = mode.removeprefix('v5_tool_assisted_anchors_internal_')
    detail_mode = 'evidence_snippets' if mode in {'v3_evidence_snippets', 'v4_context_only_snippets'} else 'paths_only'
    result = compile_prompt(
        repo_root,
        prompt,
        profile,
        use_repo_map=use_repo_map,
        packet_version=packet_version,
        packet_variant=variant,
        packet_strategy=strategy,
        packet_detail_mode=detail_mode,
        snippet_budget_tokens=snippet_budget_tokens,
        cache_optimized=(packet_version in {'v3', 'v4', 'v5'}),
        record_artifacts=False,
    )
    metrics = result.get('metrics') or {}
    return {
        'mode': mode,
        'packet_version': result.get('packet_version'),
        'packet_variant': result.get('packet_variant'),
        'packet_strategy': metrics.get('packet_strategy') or metrics.get('strategy_selected'),
        'packet_detail_mode': result.get('packet_detail_mode'),
        'packet_total_tokens': metrics.get('packet_total_tokens'),
        'model_facing_evidence_tokens': metrics.get('model_facing_evidence_tokens'),
        'candidate_files': _list_paths(result.get('candidate_edit_files')),
        'support_files': _list_paths(result.get('read_only_support_files')),
        'verification_files': _list_paths(result.get('related_tests') or result.get('suggested_tests')),
        'model_facing_leakage': (result.get('model_facing_leakage_check') or {}).get('model_facing_diagnostic_leakage'),
        'file_block_count': metrics.get('file_block_count'),
        'snippet_token_count': metrics.get('snippet_token_count'),
        'anchor_count': metrics.get('anchor_count'),
        'anchor_type_mix': metrics.get('anchor_type_mix'),
        'task_class': metrics.get('task_class'),
        'support_relation_count': metrics.get('support_relation_count'),
        'discovery_wall_ms': metrics.get('discovery_wall_ms'),
        'files_scanned_count': metrics.get('files_scanned_count'),
        'lines_scanned_count': metrics.get('lines_scanned_count'),
        'anchors_generated_count': metrics.get('anchors_generated_count'),
        'anchors_selected_count': metrics.get('anchors_selected_count'),
        'ranking_adjustment_count': metrics.get('ranking_adjustment_count'),
        'relations_generated_count': metrics.get('relations_generated_count'),
        'relations_selected_count': metrics.get('relations_selected_count'),
        'files_walked': metrics.get('files_walked'),
        'files_listed': metrics.get('files_listed'),
        'files_stat_checked': metrics.get('files_stat_checked'),
        'files_content_read': metrics.get('files_content_read'),
        'bytes_read': metrics.get('bytes_read'),
        'git_commands_run': metrics.get('git_commands_run'),
        'inventory_cache_hit': metrics.get('inventory_cache_hit'),
        'inventory_cache_miss': metrics.get('inventory_cache_miss'),
        'inventory_source': metrics.get('inventory_source'),
        'inventory_freshness': metrics.get('inventory_freshness'),
        'inventory_file_count': metrics.get('inventory_file_count'),
        'full_walk_performed': metrics.get('full_walk_performed'),
        'full_walk_reason': metrics.get('full_walk_reason'),
        'compile_ms': metrics.get('compile_ms'),
        'stable_prefix_hash': result.get('cacheable_prefix_sha256'),
        'dynamic_suffix_hash': result.get('dynamic_suffix_sha256'),
        'full_repo_reduction_percent': metrics.get('full_repo_reduction_percent'),
    }


def compile_mode_comparison(
    repo_root: Path,
    prompt: str,
    *,
    profile: str | None = 'lite',
    use_repo_map: bool = True,
    snippet_budget_tokens: int = 2000,
) -> list[dict[str, Any]]:
    modes = [
        'standard_raw_prompt',
        'v3_paths_only',
        'v3_evidence_snippets',
        'v4_context_only_paths',
        'v4_context_only_snippets',
        'v5_ranked_paths',
        'v5_ranked_snippets',
        'v5_primary_tests_only',
        'v5_top1_plus_tests',
        'v5_ranked_paths_plus_anchors',
        'v5_ranked_paths_selective_snippets',
        'v5_ranked_paths_no_support',
        'v5_ranked_paths_tests_first',
        'v5_ranked_paths_top1',
        'v5_tool_assisted_backbone',
        'v5_tool_assisted_backbone_no_task_class',
        'v5_tool_assisted_backbone_no_relations',
        'v5_tool_assisted_anchors_internal',
        'v5_tool_assisted_anchors_internal_literal_symbol',
        'v5_tool_assisted_anchors_internal_literal_symbol_test_names',
        'v5_tool_assisted_anchors_internal_literal_symbol_config',
        'v5_tool_assisted_anchors_internal_literal_symbol_config_gated',
        'v5_tool_assisted_anchors_internal_literal_symbol_docs',
        'v5_tool_assisted_anchors_internal_literal_symbol_docs_heading_gated',
        'v5_tool_assisted_anchors_internal_literal_symbol_cli_route',
        'v5_tool_assisted_anchors_internal_literal_symbol_import_boost',
        'v5_tool_assisted_anchors_internal_literal_symbol_import_rank_json_only',
        'v5_tool_assisted_anchors_internal_literal_symbol_collision_filter',
        'v5_tool_assisted_anchors_internal_literal_symbol_policy_by_prompt_type',
        'v5_tool_assisted_anchors_internal_tests_first_anchoring',
        'v5_tool_assisted_anchors_internal_top1_primary',
        'v5_tool_assisted_anchors_internal_policy_by_prompt_type',
        'v2_full_context_if_available',
    ]
    reports: list[dict[str, Any]] = []
    for mode in modes:
        try:
            reports.append(
                _compile_mode_report(
                    repo_root,
                    prompt,
                    mode=mode,
                    profile=profile,
                    use_repo_map=use_repo_map,
                    snippet_budget_tokens=snippet_budget_tokens,
                )
            )
        except Exception as exc:
            reports.append({'mode': mode, 'error': str(exc)})
    return reports


def _case_report(
    repo_root: Path,
    case: dict[str, Any],
    *,
    profile: str | None,
    use_repo_map: bool,
    cache_optimized: bool,
    packet_version: str | None,
    packet_variant: str | None = None,
    packet_strategy: str | None = None,
    packet_detail_mode: str = 'paths_only',
    snippet_budget_tokens: int = 2000,
    save_packets: bool = False,
    include_review: bool = False,
    review_against: str = 'main',
    review_since_compile: bool = False,
) -> dict[str, Any]:
    result = compile_prompt(
        repo_root,
        str(case['prompt']),
        profile,
        use_repo_map=use_repo_map,
        cache_optimized=cache_optimized,
        packet_version=packet_version,
        packet_variant=packet_variant,
        packet_strategy=packet_strategy,
        packet_detail_mode=packet_detail_mode,
        snippet_budget_tokens=snippet_budget_tokens,
        save=save_packets or include_review,
    )
    metrics = result.get('metrics') or {}
    impact = result.get('impact_map') if isinstance(result.get('impact_map'), dict) else {}
    likely_files = _list_paths(
        result.get('likely_edit_files')
        or result.get('candidate_edit_files')
        or impact.get('likely_files')
    )
    related_test_items = list(
        result.get('related_tests')
        or result.get('suggested_tests')
        or impact.get('related_tests')
        or []
    )
    related_tests = _list_paths(
        related_test_items
    )
    verification_order = [str((x or {}).get('command') if isinstance(x, dict) else x) for x in (impact.get('verification_order') or [])]
    eligible = int(metrics.get('eligible_readable_repo_tokens') or 0)
    packet_tokens = int(metrics.get('packet_total_tokens') or metrics.get('estimated_input_tokens') or 0)
    hard_budget = int((result.get('caps') or {}).get('hard_packet_token_budget') or 0)
    review_result = None
    if include_review:
        review_result = review_patch(repo_root, base_ref=review_against, since_compile=review_since_compile)
    expected_files = _case_expectation_paths(case, 'expected_files', 'expected_likely_files')
    expected_tests = _case_expectation_paths(case, 'expected_tests', 'expected_related_tests')
    forbidden_files = _case_expectation_paths(case, 'forbidden_files', 'forbidden_likely_files', 'forbidden_primary_files')
    likely_match = _match_expected(likely_files, expected_files)
    test_match = _match_expected(related_tests, expected_tests)
    forbidden_match = _match_expected(likely_files, forbidden_files)
    likely_quality = _selection_quality(likely_files, expected_files, likely_match)
    test_quality = _selection_quality(related_tests, expected_tests, test_match, selected_items=related_test_items)
    expectation_guard = _case_expectation_guard(
        repo_root,
        case,
        expected_files=expected_files,
        expected_tests=expected_tests,
        forbidden_files=forbidden_files,
        likely_match=likely_match,
        test_match=test_match,
        forbidden_match=forbidden_match,
        likely_quality=likely_quality,
        test_quality=test_quality,
    )
    warning_codes = {str(item.get('code') or '') for item in expectation_guard.get('validation_warnings') or []}
    expected_file_hit_but_low_precision = bool(
        likely_match.get('hit_count')
        and 'low_likely_file_precision' in warning_codes
    )
    expected_test_hit_but_low_precision = bool(
        test_match.get('hit_count')
        and 'low_related_test_precision' in warning_codes
    )
    precision_warnings = [
        item for item in expectation_guard.get('validation_warnings') or []
        if str(item.get('code') or '') in {'low_likely_file_precision', 'low_related_test_precision'}
    ]
    candidate_set_warnings = [
        item for item in expectation_guard.get('validation_warnings') or []
        if str(item.get('code') or '') == 'broad_likely_file_selection'
    ]
    related_test_warnings = [
        item for item in expectation_guard.get('validation_warnings') or []
        if str(item.get('code') or '') in {'broad_related_test_selection', 'fallback_only_related_tests', 'low_related_test_anchor_confidence'}
    ]
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
        'packet_variant': result.get('packet_variant'),
        'packet_strategy': metrics.get('packet_strategy') or metrics.get('strategy_selected'),
        'resource_profile': result.get('resource_profile'),
        'packet_mode': result.get('packet_mode'),
        'packet_detail_mode': result.get('packet_detail_mode'),
        'eligible_repo_tokens': eligible,
        'packet_tokens': packet_tokens,
        'estimated_savings_tokens': max(0, eligible - packet_tokens) if eligible and packet_tokens else None,
        'full_repo_reduction_percent': metrics.get('full_repo_reduction_percent'),
        'estimated_savings_vs_eligible_repo_percent': metrics.get('estimated_savings_vs_eligible_repo_percent'),
        'model_facing_evidence_tokens': metrics.get('model_facing_evidence_tokens'),
        'model_facing_diagnostic_leakage': metrics.get('model_facing_diagnostic_leakage'),
        'file_block_count': metrics.get('file_block_count'),
        'snippet_token_count': metrics.get('snippet_token_count'),
        'anchor_count': metrics.get('anchor_count'),
        'anchor_type_mix': metrics.get('anchor_type_mix'),
        'task_class': metrics.get('task_class'),
        'support_relation_count': metrics.get('support_relation_count'),
        'discovery_wall_ms': metrics.get('discovery_wall_ms'),
        'files_scanned_count': metrics.get('files_scanned_count'),
        'lines_scanned_count': metrics.get('lines_scanned_count'),
        'bytes_scanned_count': metrics.get('bytes_scanned_count'),
        'anchors_generated_count': metrics.get('anchors_generated_count'),
        'anchors_selected_count': metrics.get('anchors_selected_count'),
        'ranking_adjustment_count': metrics.get('ranking_adjustment_count'),
        'relations_generated_count': metrics.get('relations_generated_count'),
        'relations_selected_count': metrics.get('relations_selected_count'),
        'files_walked': metrics.get('files_walked'),
        'files_listed': metrics.get('files_listed'),
        'files_stat_checked': metrics.get('files_stat_checked'),
        'files_content_read': metrics.get('files_content_read'),
        'bytes_read': metrics.get('bytes_read'),
        'git_commands_run': metrics.get('git_commands_run'),
        'inventory_cache_hit': metrics.get('inventory_cache_hit'),
        'inventory_cache_miss': metrics.get('inventory_cache_miss'),
        'inventory_source': metrics.get('inventory_source'),
        'inventory_freshness': metrics.get('inventory_freshness'),
        'inventory_file_count': metrics.get('inventory_file_count'),
        'full_walk_performed': metrics.get('full_walk_performed'),
        'full_walk_reason': metrics.get('full_walk_reason'),
        'compile_ms': metrics.get('compile_ms'),
        'anchor_filter_reject_count': metrics.get('anchor_filter_reject_count'),
        'discovery_error_count': metrics.get('discovery_error_count'),
        'support_count': metrics.get('support_count'),
        'paths_only_packet_tokens': metrics.get('paths_only_packet_tokens'),
        'evidence_snippet_packet_tokens': metrics.get('evidence_snippet_packet_tokens'),
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
        'likely_file_match': likely_match,
        'related_test_match': test_match,
        'forbidden_file_match': forbidden_match,
        'likely_file_precision': likely_quality.get('precision'),
        'likely_file_recall': likely_quality.get('recall'),
        'related_test_precision': test_quality.get('precision'),
        'related_test_recall': test_quality.get('recall'),
        'likely_file_extra_count': likely_quality.get('extra_count'),
        'related_test_extra_count': test_quality.get('extra_count'),
        'related_test_fallback_only_count': test_quality.get('fallback_only_count'),
        'likely_file_selected_count': likely_quality.get('selected_count'),
        'related_test_selected_count': test_quality.get('selected_count'),
        'likely_file_selected_hit_count': likely_quality.get('selected_hit_count'),
        'related_test_selected_hit_count': test_quality.get('selected_hit_count'),
        'likely_file_expected_count': likely_quality.get('expected_count'),
        'related_test_expected_count': test_quality.get('expected_count'),
        'expected_file_hit_but_low_precision': expected_file_hit_but_low_precision,
        'expected_test_hit_but_low_precision': expected_test_hit_but_low_precision,
        'likely_file_precision_warning': 'low_likely_file_precision' in warning_codes,
        'related_test_precision_warning': 'low_related_test_precision' in warning_codes,
        'broad_likely_files_warning': 'broad_likely_file_selection' in warning_codes,
        'broad_related_tests_warning': 'broad_related_test_selection' in warning_codes,
        'precision_warnings': precision_warnings,
        'candidate_set_warnings': candidate_set_warnings,
        'related_test_warnings': related_test_warnings,
        'precision_summary': {
            'likely_file_precision': likely_quality.get('precision'),
            'likely_file_recall': likely_quality.get('recall'),
            'related_test_precision': test_quality.get('precision'),
            'related_test_recall': test_quality.get('recall'),
            'likely_file_extra_count': likely_quality.get('extra_count'),
            'related_test_extra_count': test_quality.get('extra_count'),
            'related_test_fallback_only_count': test_quality.get('fallback_only_count'),
        },
        **expectation_guard,
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
            'benchmark_status_counts': {},
            'benchmark_failure_count': 0,
            'benchmark_warning_count': 0,
            'macro_likely_file_precision': None,
            'macro_likely_file_recall': None,
            'micro_likely_file_precision': None,
            'micro_likely_file_recall': None,
            'macro_related_test_precision': None,
            'macro_related_test_recall': None,
            'micro_related_test_precision': None,
            'micro_related_test_recall': None,
            'average_likely_file_extra_count': None,
            'average_related_test_extra_count': None,
            'related_test_fallback_only_count': 0,
            'warning_category_counts': {},
            'max_likely_file_selected_count': 0,
            'max_related_test_selected_count': 0,
            'broad_likely_file_case_count': 0,
            'broad_related_test_case_count': 0,
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
    likely_precision_values = [float(c['likely_file_precision']) for c in cases if c.get('likely_file_precision') is not None]
    likely_recall_values = [float(c['likely_file_recall']) for c in cases if c.get('likely_file_recall') is not None]
    test_precision_values = [float(c['related_test_precision']) for c in cases if c.get('related_test_precision') is not None]
    test_recall_values = [float(c['related_test_recall']) for c in cases if c.get('related_test_recall') is not None]
    likely_extra_values = [int(c['likely_file_extra_count']) for c in cases if c.get('likely_file_extra_count') is not None]
    test_extra_values = [int(c['related_test_extra_count']) for c in cases if c.get('related_test_extra_count') is not None]
    warning_categories: dict[str, int] = {}
    for case in cases:
        for warning in case.get('validation_warnings') or []:
            category = str(warning.get('warning_category') or _warning_category(str(warning.get('code') or '')))
            warning_categories[category] = warning_categories.get(category, 0) + 1
    likely_expected_cases = [c for c in cases if int(c.get('likely_file_expected_count') or 0)]
    test_expected_cases = [c for c in cases if int(c.get('related_test_expected_count') or 0)]
    likely_selected_total = sum(int(c.get('likely_file_selected_count') or 0) for c in likely_expected_cases)
    likely_selected_hit_total = sum(int(c.get('likely_file_selected_hit_count') or 0) for c in likely_expected_cases)
    test_selected_total = sum(int(c.get('related_test_selected_count') or 0) for c in test_expected_cases)
    test_selected_hit_total = sum(int(c.get('related_test_selected_hit_count') or 0) for c in test_expected_cases)
    return {
        'prompt_count': len(cases),
        'average_packet_tokens': round(sum(packet_tokens) / len(packet_tokens), 2),
        'median_packet_tokens': sorted(packet_tokens)[len(packet_tokens) // 2],
        'max_packet_tokens': max(packet_tokens),
        'average_savings_percent': round(sum(savings) / len(savings), 4) if savings else None,
        'average_cacheable_prefix_tokens': round(sum(int(c.get('cacheable_prefix_tokens') or 0) for c in cases) / len(cases), 2),
        'average_dynamic_suffix_tokens': round(sum(int(c.get('dynamic_suffix_tokens') or 0) for c in cases) / len(cases), 2),
        'budget_exceeded_count': sum(1 for c in cases if c.get('budget_exceeded')),
        'benchmark_status_counts': {
            status: sum(1 for c in cases if c.get('benchmark_status') == status)
            for status in ('pass', 'warning', 'fail')
        },
        'benchmark_failure_count': sum(1 for c in cases if c.get('benchmark_status') == 'fail'),
        'benchmark_warning_count': sum(1 for c in cases if c.get('benchmark_status') == 'warning'),
        'validation_failure_count': sum(len(c.get('validation_failures') or []) for c in cases),
        'validation_warning_count': sum(len(c.get('validation_warnings') or []) for c in cases),
        'validation_failures': [
            {'case': c.get('name'), **failure}
            for c in cases
            for failure in (c.get('validation_failures') or [])
        ],
        'validation_warnings': [
            {'case': c.get('name'), **warning}
            for c in cases
            for warning in (c.get('validation_warnings') or [])
        ],
        'macro_likely_file_precision': round(sum(likely_precision_values) / len(likely_precision_values), 4) if likely_precision_values else None,
        'macro_likely_file_recall': round(sum(likely_recall_values) / len(likely_recall_values), 4) if likely_recall_values else None,
        'micro_likely_file_precision': round(likely_selected_hit_total / likely_selected_total, 4) if likely_selected_total else None,
        'micro_likely_file_recall': round(likely_hit_total / likely_expected_total, 4) if likely_expected_total else None,
        'macro_related_test_precision': round(sum(test_precision_values) / len(test_precision_values), 4) if test_precision_values else None,
        'macro_related_test_recall': round(sum(test_recall_values) / len(test_recall_values), 4) if test_recall_values else None,
        'micro_related_test_precision': round(test_selected_hit_total / test_selected_total, 4) if test_selected_total else None,
        'micro_related_test_recall': round(test_hit_total / test_expected_total, 4) if test_expected_total else None,
        'average_likely_file_extra_count': round(sum(likely_extra_values) / len(likely_extra_values), 2) if likely_extra_values else None,
        'average_related_test_extra_count': round(sum(test_extra_values) / len(test_extra_values), 2) if test_extra_values else None,
        'related_test_fallback_only_count': sum(int(c.get('related_test_fallback_only_count') or 0) for c in cases),
        'warning_category_counts': dict(sorted(warning_categories.items())),
        'max_likely_file_selected_count': max((int(c.get('likely_file_selected_count') or 0) for c in cases), default=0),
        'max_related_test_selected_count': max((int(c.get('related_test_selected_count') or 0) for c in cases), default=0),
        'broad_likely_file_case_count': sum(
            1 for c in cases
            if int(c.get('likely_file_selected_count') or 0) > BROAD_SELECTED_LIKELY_FILE_THRESHOLD
        ),
        'broad_related_test_case_count': sum(
            1 for c in cases
            if int(c.get('related_test_selected_count') or 0) > BROAD_SELECTED_TEST_THRESHOLD
        ),
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
    packet_variant: str | None = None,
    packet_strategy: str | None = None,
    packet_detail_mode: str = 'paths_only',
    snippet_budget_tokens: int = 2000,
    compile_modes: bool = False,
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
                packet_variant=packet_variant,
                packet_strategy=packet_strategy,
                packet_detail_mode=packet_detail_mode,
                snippet_budget_tokens=snippet_budget_tokens,
                save_packets=save_packets,
                include_review=include_review,
                review_against=review_against,
                review_since_compile=review_since_compile,
            ))
            if compile_modes:
                cases[-1]['compile_mode_comparison'] = compile_mode_comparison(
                    repo_root,
                    str(case['prompt']),
                    profile=profile,
                    use_repo_map=use_repo_map,
                    snippet_budget_tokens=snippet_budget_tokens,
                )
        except Exception as exc:
            cases.append({
                'name': str(case.get('name') or 'prompt'),
                'prompt': str(case.get('prompt') or ''),
                'error': str(exc),
                'benchmark_status': 'error',
            })
    summary = _summarize_cases([c for c in cases if not c.get('error')])
    error_count = sum(1 for c in cases if c.get('error'))
    if error_count or summary.get('benchmark_failure_count'):
        benchmark_status = 'fail'
    elif summary.get('benchmark_warning_count'):
        benchmark_status = 'warning'
    else:
        benchmark_status = 'pass'
    report = {
        'schema_version': 1,
        'benchmark_kind': 'premode_benchmark',
        'benchmark_status': benchmark_status,
        'repo_root': str(repo_root),
        'prompt_source': prompt_source,
        'profile': profile,
        'use_repo_map': bool(use_repo_map),
        'cache_optimized': bool(cache_optimized),
        'packet_version_requested': packet_version,
        'packet_variant_requested': packet_variant,
        'packet_strategy_requested': packet_strategy,
        'packet_detail_mode_requested': packet_detail_mode,
        'compile_modes': bool(compile_modes),
        'snippet_budget_tokens': snippet_budget_tokens,
        'include_review': bool(include_review),
        'review_against': review_against if include_review else None,
        'review_since_compile': bool(review_since_compile) if include_review else False,
        'summary': summary,
        'prompt_count': len(prompt_cases),
        'error_count': error_count,
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
        f"Likely precision/recall macro: {summary.get('macro_likely_file_precision')} / {summary.get('macro_likely_file_recall')}",
        f"Related-test precision/recall macro: {summary.get('macro_related_test_precision')} / {summary.get('macro_related_test_recall')}",
        f"Benchmark status: {report.get('benchmark_status', 'unknown')}",
        f"Expectation guard: failures={summary.get('validation_failure_count', 0)} warnings={summary.get('validation_warning_count', 0)}",
    ]
    failures = summary.get('validation_failures') or []
    if failures:
        lines.append('Expectation failures:')
        for item in failures[:8]:
            paths = ', '.join(item.get('paths') or [])
            suffix = f" ({paths})" if paths else ''
            lines.append(f"- {item.get('case')}: {item.get('code')}{suffix}")
    warnings = summary.get('validation_warnings') or []
    if warnings:
        lines.append('Expectation warnings:')
        for item in warnings[:8]:
            paths = ', '.join(item.get('paths') or [])
            suffix = f" ({paths})" if paths else ''
            lines.append(f"- {item.get('case')}: {item.get('code')}{suffix}")
    exceeded = summary.get('budget_exceeded_prompts') or []
    if exceeded:
        lines.append('Budget exceeded prompts:')
        for item in exceeded:
            lines.append(f"- {item.get('name')}: {item.get('packet_tokens')} / {item.get('budget')} tokens, over by {item.get('over_by')} ({item.get('likely_reason')})")
    readiness = summary.get('review_readiness_counts') or {}
    if readiness:
        lines.append('Review readiness: ' + ', '.join(f'{k}={v}' for k, v in sorted(readiness.items())))
    lines.append('')
    lines.append('case | status | packet_tokens | savings% | prefix | budget | likely_files | review')
    lines.append('--- | --- | ---: | ---: | ---: | --- | --- | ---')
    for case in report.get('cases') or []:
        if case.get('error'):
            lines.append(f"{case.get('name')} | error |  |  |  |  |  | {case.get('error')}")
            continue
        review = (case.get('review') or {}).get('merge_readiness') or '-'
        likely = ', '.join((case.get('likely_files') or [])[:3]) or '-'
        budget = 'over' if case.get('budget_exceeded') else 'ok'
        lines.append(
            f"{case.get('name')} | {case.get('benchmark_status')} | {case.get('packet_tokens')} | {case.get('estimated_savings_vs_eligible_repo_percent')} | "
            f"{case.get('cacheable_prefix_tokens')} | {budget} | {likely} | {review}"
        )
    if report.get('output_path'):
        lines.append('')
        lines.append(f"output: {report['output_path']}")
    return '\n'.join(lines)
