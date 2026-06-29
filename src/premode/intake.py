from __future__ import annotations

from pathlib import Path
from typing import Any


def _norm(path: str) -> str:
    return path.replace('\\', '/').strip('/').lower()


def _display(path: str) -> str:
    return path.replace('\\', '/').strip('/') or '.'


def _matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    p = _norm(path)
    return any(p == pref.strip('/').lower() or p.startswith(pref.strip('/').lower() + '/') for pref in prefixes)


def _matches_any_name(path: str, names: set[str]) -> bool:
    return Path(path).name.lower() in names


ROOT_MARKER_NAMES = {
    'pyproject.toml', 'package.json', 'cargo.toml', 'go.mod', 'package.swift',
    'pom.xml', 'build.gradle', 'settings.gradle', 'build.gradle.kts', 'settings.gradle.kts',
    'project.godot', 'mix.exs', 'composer.json', 'gemfile', 'deno.json', 'bun.lockb',
    'sconstruct', 'scsub', 'cmakelists.txt', 'meson.build', 'build.bazel', 'workspace',
}
AUTHORITY_NAMES = {
    'agents.md', 'workflow.md', 'codex.md', 'claude.md', 'contributing.md',
    'architecture.md', 'runbook.md', 'rules.md', 'playbook.md',
}
CURRENT_STATE_NAMES = {
    'latest.json', 'current.json', 'state.json', 'task_queue_normalized_latest.json',
    'path_authority_latest.json', 'artifact_authority_latest.json', 'tasks.json',
}
GENERATED_DIR_PREFIXES = (
    'artifacts/generated', 'generated', 'dist', 'build', '_output', '_claw_output',
    'reports', 'proof', 'proofs', 'logs', 'coverage', '.next', '.nuxt', 'target',
)
HISTORICAL_DIR_PREFIXES = ('history', 'archive', 'archives', 'state/history', 'state/archive', 'project/state/history', 'project/state/archive')
BINARY_ASSET_PREFIXES = ('assets', 'content', 'resources', 'images', 'audio', 'media', 'projectsettings')
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.psd', '.ai', '.mp3', '.m4a', '.wav', '.ogg',
    '.mp4', '.mov', '.blend', '.fbx', '.uasset', '.umap', '.unity', '.prefab', '.xcassets',
}
INFRA_MARKERS = {
    'main.tf', 'variables.tf', 'terraform.tfvars', 'terragrunt.hcl', 'chart.yaml',
    'kustomization.yaml', 'ansible.cfg', 'playbook.yml', 'playbook.yaml', 'docker-compose.yml',
}
INFRA_DIRS = ('terraform', 'helm', 'charts', 'k8s', 'kubernetes', 'ansible', 'pulumi')
CI_DIRS = ('.github/workflows', '.gitlab-ci', '.circleci')
CI_MARKERS = {'jenkinsfile', '.gitlab-ci.yml', '.github/workflows/ci.yml'}
MIGRATION_DIRS = ('migrations', 'migration', 'alembic', 'db/migrations', 'database/migrations', 'prisma/migrations')
SCHEMA_MARKERS = {'schema.prisma', 'openapi.yaml', 'openapi.yml', 'swagger.yaml', 'swagger.yml', 'graphql.schema', 'schema.graphql'}
EXECUTOR_HINTS = ('executor', 'executors', 'runner', 'runners', 'worker', 'workers', 'agent', 'agents', 'bot', 'gamebot')


POLICY_PACKS: dict[str, dict[str, Any]] = {
    'proof_governed_control_plane': {
        'traits': ['proof_governed_candidate', 'control_plane_candidate'],
        'packet_policy_notes': [
            'Prefer current authority surfaces over generated, historical, archived, or proof-output artifacts.',
            'Treat proof/log/history outputs as evidence only unless the user explicitly asks to mutate them.',
            'Do not claim runtime proof from static files, browser screenshots, or historical proof artifacts alone.',
        ],
        'authority_score_bonus': 420,
        'evidence_only_score_delta': -160,
        'dangerous_mutation_notes': ['State queues, authority snapshots, generated proof, bridge/executor outputs, and runtime-control files require explicit authorization.'],
        'command_safety_notes': ['Run validators/tests in read-only mode when possible; avoid mutation/writeback executor commands by default.'],
    },
    'generated_artifact_heavy': {
        'traits': ['generated_artifact_heavy'],
        'packet_policy_notes': ['Generated outputs should usually be manifest-only or summary-only; edit source/schema/config that generates them instead.'],
        'authority_score_bonus': 0,
        'evidence_only_score_delta': -120,
        'dangerous_mutation_notes': ['Do not manually edit generated artifacts unless explicitly requested.'],
        'command_safety_notes': [],
    },
    'nested_executor': {
        'traits': ['nested_executor_present'],
        'packet_policy_notes': ['Nested executor/helper package markers must not hijack the active repo root when root authority/project markers exist.'],
        'authority_score_bonus': 0,
        'evidence_only_score_delta': 0,
        'dangerous_mutation_notes': ['Executor/worker write commands require explicit authorization unless the task is specifically about the executor.'],
        'command_safety_notes': ['Prefer help/dry-run/validation commands for nested executors.'],
    },
    'binary_asset_heavy': {
        'traits': ['binary_asset_heavy'],
        'packet_policy_notes': ['Binary/game/media assets should stay manifest-only; use metadata and source references instead of raw content.'],
        'authority_score_bonus': 0,
        'evidence_only_score_delta': -220,
        'dangerous_mutation_notes': ['Avoid mutating binary assets, game maps, or engine artifacts without explicit user approval.'],
        'command_safety_notes': [],
    },
    'ci_sensitive': {
        'traits': ['ci_sensitive'],
        'packet_policy_notes': ['CI workflow files can affect verification/release behavior, but they are not infrastructure mutation surfaces by themselves.'],
        'authority_score_bonus': 80,
        'evidence_only_score_delta': 0,
        'dangerous_mutation_notes': ['Changing CI workflow behavior should be justified, especially for release, deploy, or credential-handling jobs.'],
        'command_safety_notes': ['Prefer local build/test commands before editing CI workflow files.'],
    },
    'infra_sensitive': {
        'traits': ['infra_sensitive'],
        'packet_policy_notes': ['Infrastructure repos require plan/review before apply, delete, destroy, or deploy actions.'],
        'authority_score_bonus': 180,
        'evidence_only_score_delta': 0,
        'dangerous_mutation_notes': ['apply/destroy/delete/deploy commands are destructive or environment-mutating.'],
        'command_safety_notes': ['Suggest plan/validate/lint commands before any apply/destroy/delete command.'],
    },
    'migration_sensitive': {
        'traits': ['migration_sensitive'],
        'packet_policy_notes': ['Existing migrations are ordered history; prefer additive forward migrations over editing committed migrations.'],
        'authority_score_bonus': 140,
        'evidence_only_score_delta': 0,
        'dangerous_mutation_notes': ['Existing migration files and production schema changes require explicit justification.'],
        'command_safety_notes': ['Prefer dry-run/status commands before applying migrations.'],
    },

    'native_engine': {
        'traits': ['native_engine_repo', 'scons_build'],
        'packet_policy_notes': ['Native engine repos are source/build-system heavy; helper Python scripts should not dominate project detection.'],
        'authority_score_bonus': 80,
        'evidence_only_score_delta': 0,
        'dangerous_mutation_notes': ['Avoid broad engine/platform build rewrites unless explicitly requested.'],
        'command_safety_notes': ['Prefer configured SCons/CMake/Ninja validation commands.'],
    },
    'docs_authoritative': {
        'traits': ['docs_authoritative'],
        'packet_policy_notes': ['Docs/spec/rule files may be authority surfaces, but stale archive/history docs should be downgraded.'],
        'authority_score_bonus': 220,
        'evidence_only_score_delta': -80,
        'dangerous_mutation_notes': ['Public-facing or policy docs should be reviewed before publication.'],
        'command_safety_notes': [],
    },
}


def _root_for_marker(path: str) -> str:
    p = _display(path)
    if '/' not in p:
        return '.'
    return p.rsplit('/', 1)[0] or '.'


def _path_under_hint(path: str, hints: tuple[str, ...]) -> bool:
    parts = _norm(path).split('/')
    return any(part in hints for part in parts[:-1])


def _select_policy_packs(traits: list[str]) -> dict[str, dict[str, Any]]:
    trait_set = set(traits)
    packs: dict[str, dict[str, Any]] = {}
    for pack_id, pack in POLICY_PACKS.items():
        if trait_set.intersection(pack.get('traits', [])):
            packs[pack_id] = pack
    return packs


def build_intake_report(repo_root: Path, rel_paths: list[str] | None = None) -> dict[str, Any]:
    """Build a generic repo-intake report before adapter-specific decisions.

    The report deliberately models repo traits instead of named products. Project-specific
    profiles such as OpenClaw can still add stronger marker policy on top of these traits.
    """
    if rel_paths is None:
        rel_paths = []
        for p in repo_root.rglob('*'):
            try:
                rel_paths.append(p.relative_to(repo_root).as_posix())
            except ValueError:
                pass
    paths = sorted({_display(p) for p in rel_paths if p})
    lower_map = {_norm(p): p for p in paths}
    lowers = sorted(lower_map)

    root_markers: list[dict[str, Any]] = []
    nested_project_markers: list[dict[str, Any]] = []
    active_roots: dict[str, dict[str, Any]] = {}
    authority_surfaces: list[str] = []
    historical_surfaces: list[str] = []
    generated_surfaces: list[str] = []
    generated_dirs: set[str] = set()
    evidence_only_dirs: set[str] = set()
    binary_asset_dirs: set[str] = set()
    dangerous_zones: set[str] = set()
    explicit_auth: set[str] = set()
    safe_validators: list[dict[str, str]] = []
    dangerous_command_patterns: list[dict[str, str]] = []
    language_frameworks: list[dict[str, Any]] = []

    for lower in lowers:
        original = lower_map[lower]
        name = Path(lower).name
        suffix = Path(lower).suffix.lower()
        root = _root_for_marker(original)
        if name in ROOT_MARKER_NAMES or name.endswith(('.xcodeproj', '.xcworkspace')) or lower in {'assets', 'projectsettings'} or lower.endswith('/assets') or lower.endswith('/projectsettings'):
            marker = {'path': original, 'root': root, 'name': Path(original).name}
            if root == '.':
                root_markers.append(marker)
            else:
                nested_project_markers.append(marker)
            info = active_roots.setdefault(root, {'root': root, 'markers': [], 'score': 0})
            info['markers'].append(original)
            info['score'] += 2 if root == '.' else 1

        if name in AUTHORITY_NAMES or lower.endswith('/agents.md') or lower.endswith('/workflow.md'):
            authority_surfaces.append(original)
        if name in CURRENT_STATE_NAMES or 'latest' in name and suffix in {'.json', '.yaml', '.yml', '.md'}:
            authority_surfaces.append(original)
        if _matches_prefix(lower, HISTORICAL_DIR_PREFIXES) or '/history/' in lower or '/archive/' in lower:
            historical_surfaces.append(original)
            evidence_only_dirs.add(original.split('/history/', 1)[0] + '/history' if '/history/' in original.lower() else original.split('/archive/', 1)[0] + '/archive' if '/archive/' in original.lower() else original.split('/')[0])
        if _matches_prefix(lower, GENERATED_DIR_PREFIXES) or '/generated/' in lower or lower.startswith('_') and ('output' in lower or 'artifact' in lower):
            generated_surfaces.append(original)
            first_two = '/'.join(original.split('/')[:2]) if '/' in original else original
            generated_dirs.add(first_two)
            evidence_only_dirs.add(first_two)
        if _matches_prefix(lower, BINARY_ASSET_PREFIXES) or suffix in BINARY_EXTENSIONS:
            first = original.split('/')[0]
            binary_asset_dirs.add(first)
            if suffix in {'.uasset', '.umap', '.blend', '.unity'}:
                dangerous_zones.add(original)
                explicit_auth.add(original)
        if _matches_prefix(lower, CI_DIRS) or lower in CI_MARKERS or lower.startswith('.github/workflows/'):
            # CI workflows are mutation-sensitive, but they are not Terraform/Kubernetes/Helm infra by themselves.
            dangerous_zones.add(original)
            explicit_auth.add(original)
        if name in INFRA_MARKERS or _matches_prefix(lower, INFRA_DIRS) or suffix == '.tf' or lower.endswith(('.tfvars', '.hcl')):
            dangerous_command_patterns.extend([
                {'pattern': 'terraform apply', 'reason': 'infrastructure mutation'},
                {'pattern': 'terraform destroy', 'reason': 'destructive infrastructure mutation'},
                {'pattern': 'kubectl delete', 'reason': 'cluster mutation/destruction'},
                {'pattern': 'helm upgrade', 'reason': 'deployment mutation'},
            ])
            safe_validators.extend([
                {'command': 'terraform plan', 'reason': 'review infrastructure changes before apply'},
                {'command': 'terraform validate', 'reason': 'non-mutating validation'},
                {'command': 'kubectl diff', 'reason': 'review Kubernetes changes before apply when configured'},
            ])
        if _matches_prefix(lower, MIGRATION_DIRS) or name in {'alembic.ini', 'schema.prisma'}:
            dangerous_zones.add(original if _matches_prefix(lower, MIGRATION_DIRS) else 'migrations/*')
            explicit_auth.add(original if _matches_prefix(lower, MIGRATION_DIRS) else 'migrations/*')
        if name in SCHEMA_MARKERS or 'schema' in name and suffix in {'.json', '.yaml', '.yml', '.graphql', '.prisma'}:
            authority_surfaces.append(original)

    if any(p.endswith('.py') for p in lowers) or 'pyproject.toml' in lowers:
        language_frameworks.append({'kind': 'python', 'evidence': [p for p in paths if p.endswith('.py')][:5]})
    if any(Path(p).name.lower() == 'package.json' for p in paths) or any(p.endswith(('.ts', '.tsx', '.js', '.jsx')) for p in lowers):
        language_frameworks.append({'kind': 'node_web', 'evidence': [p for p in paths if Path(p).name.lower() == 'package.json'][:5]})
    if any(p.endswith('.swift') for p in lowers) or any(p.endswith(('.xcodeproj', '.xcworkspace')) for p in lowers) or 'package.swift' in lowers:
        language_frameworks.append({'kind': 'swift_ios', 'evidence': [p for p in paths if p.endswith('.swift') or p.endswith(('.xcodeproj', '.xcworkspace'))][:5]})
    if any(p.endswith(('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.hxx')) for p in lowers) or any(Path(p).name.lower() in {'sconstruct', 'scsub', 'cmakelists.txt', 'meson.build', 'build.bazel', 'workspace'} for p in lowers):
        language_frameworks.append({'kind': 'native_cpp', 'evidence': [p for p in paths if p.endswith(('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.hxx')) or Path(p).name.lower() in {'sconstruct', 'scsub', 'cmakelists.txt', 'meson.build'}][:5]})
    if any(p.endswith('.tf') for p in lowers) or any(_matches_prefix(p, INFRA_DIRS) for p in lowers):
        language_frameworks.append({'kind': 'infra', 'evidence': [p for p in paths if p.endswith('.tf') or _matches_prefix(p, INFRA_DIRS)][:5]})
    if any(_matches_prefix(p, CI_DIRS) or p.startswith('.github/workflows/') or Path(p).name.lower() in CI_MARKERS for p in lowers):
        language_frameworks.append({'kind': 'ci', 'evidence': [p for p in paths if _matches_prefix(p, CI_DIRS) or p.lower().startswith('.github/workflows/') or Path(p).name.lower() in CI_MARKERS][:5]})

    traits: list[str] = []
    if nested_project_markers:
        traits.append('nested_project_present')
    if any(_path_under_hint(p, EXECUTOR_HINTS) and Path(p).name.lower() in ROOT_MARKER_NAMES | {'package.json'} for p in lowers):
        traits.append('nested_executor_present')
    has_authority = len(set(authority_surfaces)) >= 2
    has_state = any('/state/' in p.lower() or Path(p).name.lower() in CURRENT_STATE_NAMES for p in authority_surfaces + paths)
    has_history_or_generated = bool(historical_surfaces or generated_surfaces)
    if has_authority:
        traits.append('authority_surface_driven')
    if has_authority and has_state and has_history_or_generated:
        traits.append('proof_governed_candidate')
    if has_authority and (has_state or any('task' in p.lower() or 'queue' in p.lower() for p in paths)) and (generated_surfaces or nested_project_markers):
        traits.append('control_plane_candidate')
    if generated_surfaces or generated_dirs:
        traits.append('generated_artifact_heavy')
    if binary_asset_dirs:
        traits.append('binary_asset_heavy')
    if any(_matches_prefix(p, CI_DIRS) or p.startswith('.github/workflows/') or Path(p).name.lower() in CI_MARKERS for p in lowers):
        traits.append('ci_sensitive')
    if any(Path(p).name.lower() in INFRA_MARKERS or _matches_prefix(p, INFRA_DIRS) or p.endswith('.tf') or p.endswith('.tfvars') or p.endswith('.hcl') for p in lowers):
        traits.append('infra_sensitive')
    native_marker_names = {'sconstruct', 'scsub', 'cmakelists.txt', 'meson.build', 'build.bazel', 'workspace'}
    engine_top_dirs = {'core', 'scene', 'modules', 'platform', 'servers', 'drivers'}
    engine_hits = sum(1 for p in lowers if p.split('/', 1)[0] in engine_top_dirs)
    cpp_hits = sum(1 for p in lowers if p.endswith(('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.hxx')))
    if any(Path(p).name.lower() in native_marker_names for p in lowers) or (engine_hits >= 4 and cpp_hits >= 4):
        traits.append('native_engine_repo')
    if any(Path(p).name.lower() in {'sconstruct', 'scsub'} for p in lowers):
        traits.append('scons_build')
    if any(_matches_prefix(p, MIGRATION_DIRS) or Path(p).name.lower() in {'alembic.ini', 'schema.prisma'} for p in lowers):
        traits.append('migration_sensitive')
    if any(Path(p).name.lower() in SCHEMA_MARKERS for p in lowers):
        traits.append('schema_authority_candidate')
    docs_paths = [p for p in paths if p.lower().startswith(('docs/', 'specs/', 'policies/')) or Path(p).suffix.lower() in {'.md', '.rst'}]
    source_paths = [p for p in paths if Path(p).suffix.lower() in {'.py', '.swift', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java', '.kt'}]
    if len(docs_paths) >= 3 and (not source_paths or len(docs_paths) >= len(source_paths)):
        traits.append('docs_authoritative')

    traits = sorted(set(traits))
    policy_packs = _select_policy_packs(traits)

    if 'infra_sensitive' in traits:
        dangerous_zones.update(['terraform apply', 'terraform destroy', 'kubectl delete', 'helm upgrade'])
        explicit_auth.update(['terraform apply', 'terraform destroy', 'kubectl delete', 'helm upgrade'])
    if 'nested_executor_present' in traits:
        explicit_auth.update(['tools/*executor*', '*/executor/*', '*/worker/*', '*/runner/*'])
    if 'proof_governed_candidate' in traits or 'control_plane_candidate' in traits:
        dangerous_zones.update(['state/*', '*/state/*', 'artifacts/generated/*', 'proof/*', 'proofs/*'])
        explicit_auth.update(['state/*', '*/state/*', 'artifacts/generated/*', 'proof/*', 'proofs/*'])

    warnings: list[dict[str, str]] = []
    if 'nested_executor_present' in traits:
        warnings.append({'type': 'nested_executor_present', 'message': 'Nested executor/helper project markers were detected; do not let them hijack the active root without task evidence.'})
    if 'proof_governed_candidate' in traits:
        warnings.append({'type': 'proof_governed_candidate', 'message': 'Current authority/state surfaces should outrank historical/generated proof artifacts.'})
    if 'generated_artifact_heavy' in traits:
        warnings.append({'type': 'generated_artifact_heavy', 'message': 'Generated or proof-output artifacts were downgraded to evidence-only surfaces by default.'})
    if 'ci_sensitive' in traits:
        warnings.append({'type': 'ci_sensitive', 'message': 'CI workflow files were detected; treat release/deploy/credential workflow changes as justification-required, but do not infer Terraform/Kubernetes infra risk from CI alone.'})
    if 'infra_sensitive' in traits:
        warnings.append({'type': 'infra_sensitive', 'message': 'Infrastructure mutation commands such as apply/destroy/delete require explicit authorization.'})
    if 'migration_sensitive' in traits:
        warnings.append({'type': 'migration_sensitive', 'message': 'Existing migration history is mutation-sensitive; prefer forward/additive migrations.'})
    if 'native_engine_repo' in traits:
        warnings.append({'type': 'native_engine_repo', 'message': 'Native engine/build markers detected; do not let helper Python scripts under platform/tools dominate project detection.'})

    authority_kind = 'none'
    if 'control_plane_candidate' in traits:
        authority_kind = 'control_plane'
    elif 'proof_governed_candidate' in traits:
        authority_kind = 'proof_governed'
    elif 'authority_surface_driven' in traits or 'docs_authoritative' in traits:
        authority_kind = 'docs_guided'

    return {
        'schema_version': 1,
        'repo_shape': {
            'root_markers': root_markers[:40],
            'nested_project_markers': nested_project_markers[:80],
            'likely_monorepo': bool(nested_project_markers and (root_markers or len({m['root'] for m in nested_project_markers}) > 1)),
            'active_root_candidates': sorted(active_roots.values(), key=lambda x: (-int(x.get('score', 0)), x.get('root', '.')))[:10],
        },
        'language_frameworks': language_frameworks,
        'traits': traits,
        'policy_packs': policy_packs,
        'authority_model': {
            'kind': authority_kind,
            'authority_surfaces': sorted(set(authority_surfaces))[:80],
            'historical_surfaces': sorted(set(historical_surfaces))[:80],
            'generated_surfaces': sorted(set(generated_surfaces))[:80],
        },
        'artifact_model': {
            'generated_dirs': sorted(generated_dirs)[:80],
            'binary_asset_dirs': sorted(binary_asset_dirs)[:80],
            'evidence_only_dirs': sorted(evidence_only_dirs)[:80],
        },
        'mutation_model': {
            'dangerous_zones': sorted(dangerous_zones)[:80],
            'requires_explicit_authorization': sorted(explicit_auth)[:80],
        },
        'command_model': {
            'safe_validators': _dedupe_dicts(safe_validators),
            'dangerous_command_patterns': _dedupe_dicts(dangerous_command_patterns),
        },
        'intake_warnings': warnings,
    }


def _dedupe_dicts(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        key = tuple(sorted((str(k), str(v)) for k, v in item.items()))
        if key in seen:
            continue
        out.append(item)
        seen.add(key)
    return out


def intake_score_delta(path: str, intake_report: dict[str, Any] | None) -> tuple[int, list[str]]:
    """Return generic intake score hints for context selection."""
    if not intake_report:
        return 0, []
    lower = _norm(path)
    flags: list[str] = []
    score = 0
    authority = { _norm(p) for p in intake_report.get('authority_model', {}).get('authority_surfaces', []) }
    evidence_dirs = [_norm(p) for p in intake_report.get('artifact_model', {}).get('evidence_only_dirs', [])]
    generated_dirs = [_norm(p) for p in intake_report.get('artifact_model', {}).get('generated_dirs', [])]
    binary_dirs = [_norm(p) for p in intake_report.get('artifact_model', {}).get('binary_asset_dirs', [])]
    packs = intake_report.get('policy_packs') or {}
    authority_bonus = max([int(pack.get('authority_score_bonus', 0) or 0) for pack in packs.values()] or [0])
    evidence_delta = min([int(pack.get('evidence_only_score_delta', 0) or 0) for pack in packs.values()] or [0])
    if lower in authority or any(lower.endswith('/' + a) for a in authority):
        score += max(180, authority_bonus)
        flags.append('intake_authority_surface')
    if any(lower == d or lower.startswith(d.rstrip('/') + '/') for d in evidence_dirs + generated_dirs if d):
        score += evidence_delta or -100
        flags.append('intake_evidence_only')
    if any(lower == d or lower.startswith(d.rstrip('/') + '/') for d in binary_dirs if d):
        score -= 220
        flags.append('intake_binary_asset_surface')
    return score, flags


def intake_policy_from_detection(detection: dict[str, Any]) -> dict[str, Any] | None:
    report = detection.get('intake_report') if isinstance(detection, dict) else None
    if not isinstance(report, dict):
        return None
    packs = report.get('policy_packs') or {}
    if not packs:
        return None
    notes: list[str] = []
    dangerous: list[str] = []
    command_notes: list[str] = []
    for pack in packs.values():
        notes.extend(pack.get('packet_policy_notes') or [])
        dangerous.extend(pack.get('dangerous_mutation_notes') or [])
        command_notes.extend(pack.get('command_safety_notes') or [])
    return {
        'authority_model': report.get('authority_model', {}).get('kind', 'none'),
        'traits': report.get('traits', []),
        'policy_packs': sorted(packs),
        'authority_surfaces': report.get('authority_model', {}).get('authority_surfaces', []),
        'evidence_only_patterns': report.get('artifact_model', {}).get('evidence_only_dirs', []),
        'dangerous_mutation_zones': report.get('mutation_model', {}).get('dangerous_zones', []),
        'requires_explicit_authorization': report.get('mutation_model', {}).get('requires_explicit_authorization', []),
        'notes': _dedupe_strings(notes),
        'dangerous_mutation_notes': _dedupe_strings(dangerous),
        'command_safety_notes': _dedupe_strings(command_notes),
    }


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out
