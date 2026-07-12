from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from .config import premode_dir
from .ignore import IgnoreMatcher
from .indexer import index_project, load_index
from .profiles import resolve_profile
from .context_constraints import classify_path_for_routing, is_restricted_edit_bucket_path
from .role_core import classify_path_role, infer_prompt_intent, path_role_rank
from .safe_reader import safe_read
from .timeutil import timestamp_iso

SOURCE_EXTENSIONS = {'.py', '.swift', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.rs', '.go', '.java', '.kt', '.ex', '.exs', '.php', '.rb', '.tf', '.c', '.cpp', '.h', '.hpp', '.cs', '.zig', '.hs'}
CONFIG_EXTENSIONS = {'.json', '.toml', '.yaml', '.yml', '.plist'}
IGNORE_BOUNDARY_SEGMENTS = {
    '_external_references',
    'node_modules',
    'vendor',
    'staging',
    'third_party',
    '.venv',
    'venv',
    'env',
    'build',
    'dist',
    'deriveddatacache',
    'saved',
    'intermediate',
    'binaries',
    '_claw_output',
    '_output',
    '_evidence',
    '_integration_staging',
    '_run_captures',
    'generated',
    'gen',
    'artifacts',
    'proof',
    'proofs',
    'state',
    'target',
    'out',
    '.dart_tool',
    '.terraform',
    'tmp',
    'cache',
    '.cache',
}
NEGATIVE_BOUNDARY_TERMS = (
    'avoid external references',
    'external references',
    'avoid node_modules',
    'node_modules',
    'avoid generated',
    'generated files',
    'avoid build outputs',
    'build outputs',
    'avoid caches',
    'avoid binaries',
)

SWIFT_SOURCE_PROMPT_RE = re.compile(r"(?i)\b(swiftui|swift|ios|xcode|tutorial|overlay|state|ui shell|view model|viewmodel|views?|screens?|surface|ui|user interface|source)\b")
SWIFTUI_TUTORIAL_SCOPE_RE = re.compile(r"(?i)\b(swiftui|ui shell|tutorial|overlay|guidance|onboarding)\b")
SWIFT_SCREEN_ACTION_RE = re.compile(r"(?i)\b(screens?|surface|ui|user interface|views?)\b")
SWIFT_SOURCE_PATH_HINTS = (
    '/views/',
    '/viewmodels/',
    '/models/',
    '/systems/',
    '/features/',
    '/screens/',
)
IN_REPO_PLANNING_ART_SEGMENTS = {
    'planning_bundles',
    'artsource',
    'animal',
    'animals',
    'npc_models',
    'system_bibles',
    'finalplanning',
}
IN_REPO_PLANNING_ART_NAMES = {
    'patch_notes.md',
    'patch_notes.txt',
}
IN_REPO_PLANNING_ART_TERMS = (
    'patch_notes',
    'app_reality_alignment',
    'app reality alignment',
)
ART_SOURCE_MANIFEST_TERMS = (
    'animal',
    'sprite',
    'pose',
    'crop',
    'art',
    'artsource',
    'art_source',
    'art-source',
    'npc_model',
    'npc_models',
    'asset',
    'assets',
    'source',
    'source_art',
    'source-art',
    'generated',
)
IN_REPO_PLANNING_ART_PROMPT_TERMS = (
    'avoid docs',
    'avoid doc',
    'docs',
    'avoid planning_bundles',
    'planning_bundles',
    'avoid artsource',
    'artsource',
    'art source',
    'art-source',
    'animal folders',
    'avoid assets',
    'assets.xcassets',
)

NEGATIVE_INTENT_RE = re.compile(r"(?i)\b(?:do not|don't|dont|must not|never|avoid|without|leave)\b[^\n;]*(?:touch|edit|modify|mutate|change|alter|write|touching)[^\n;]*")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()


def _safe_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _is_ignore_boundary_path(path: str) -> bool:
    parts = [p.lower() for p in str(path).replace('\\', '/').strip('/').split('/') if p]
    lower = str(path).replace('\\', '/').lower().strip('/')
    name = Path(lower).name
    return (
        bool(set(parts) & IGNORE_BOUNDARY_SEGMENTS)
        or any(part.startswith('bazel-') for part in parts)
        or name.endswith('.pb.go')
        or name.endswith('.g.dart')
        or '.generated.' in lower
        or '.gen.' in lower
        or '_generated.' in lower
    )


def _prompt_has_negative_boundary(raw_prompt: str) -> bool:
    prompt = raw_prompt.lower()
    return any(term in prompt for term in NEGATIVE_BOUNDARY_TERMS)


def _prompt_is_swift_source_task(raw_prompt: str) -> bool:
    return bool(SWIFT_SOURCE_PROMPT_RE.search(raw_prompt or ''))


def _prompt_mentions_swift_context(raw_prompt: str) -> bool:
    return bool(re.search(r"(?i)\b(swiftui|swift|ios|xcode)\b", raw_prompt or ""))


def _prompt_is_swiftui_tutorial_scope_task(raw_prompt: str) -> bool:
    prompt = raw_prompt or ''
    return bool(SWIFTUI_TUTORIAL_SCOPE_RE.search(prompt)) and _prompt_is_swift_source_task(prompt)


def _prompt_is_swift_screen_action_task(raw_prompt: str) -> bool:
    prompt = raw_prompt or ''
    if not _prompt_is_swift_source_task(prompt):
        return False
    intent_terms = bool(re.search(r"(?i)\b(next|today|action|task|plan|priority|important|obvious|clear|clearer)\b", prompt))
    return bool(SWIFT_SCREEN_ACTION_RE.search(prompt)) and intent_terms


def _swiftui_tutorial_scope_score(path: str) -> int:
    lower = str(path).replace('\\', '/').lower().strip('/')
    if not lower.endswith('.swift'):
        return 0
    name = Path(lower).name
    score = 0
    if lower.endswith((
        '/views/bottombarview.swift',
        '/views/mainmenuview.swift',
        '/viewmodels/gamesessionviewmodel+homesteadnavigation.swift',
    )):
        score += 1000
    in_views = '/views/' in lower
    in_viewmodels = '/viewmodels/' in lower
    if in_views:
        score += 260
    elif in_viewmodels:
        score += 100
    if any(term in lower for term in ('tutorial', 'overlay', 'guidance', 'onboarding')):
        score += 360
    homestead_map_location_score = sum(
        weight for term, weight in (('homestead', 180), ('map', 140), ('location', 240)) if term in lower
    )
    if homestead_map_location_score:
        score += homestead_map_location_score
    if in_views and homestead_map_location_score:
        score += 260
    if any(term in lower for term in ('homesteadnavigation', 'tutorialstate', 'tutorial_state', 'session', 'state')):
        score += 80
    if any(term in lower for term in ('bottom', 'bar', 'mainmenu', 'main_menu', 'menu', 'shell')):
        score += 260
    if 'viewmodel' in lower:
        score += 60
    if any(term in lower for term in ('devtools/', 'frontierrisk/', 'riskresolver', 'founderselectview', 'eventcardview')):
        score -= 500
    if lower.endswith('tests.swift') or '/tests/' in lower:
        score -= 200
    return score


def _prompt_excludes_in_repo_planning_art(raw_prompt: str) -> bool:
    prompt = (raw_prompt or '').lower()
    return any(term in prompt for term in IN_REPO_PLANNING_ART_PROMPT_TERMS)


def _is_in_repo_planning_art_path(path: str) -> bool:
    lower = str(path).replace('\\', '/').lower().strip('/')
    parts = [p for p in lower.split('/') if p]
    name = Path(lower).name
    return (
        bool(set(parts) & IN_REPO_PLANNING_ART_SEGMENTS)
        or name in IN_REPO_PLANNING_ART_NAMES
        or _is_art_source_manifest_path(lower)
        or any(term in lower for term in IN_REPO_PLANNING_ART_TERMS)
        or lower.startswith('docs/planning_bundles/')
        or lower.startswith('artsource/')
    )


def _is_art_source_manifest_path(path: str) -> bool:
    lower = str(path).replace('\\', '/').lower().strip('/')
    name = Path(lower).name
    if Path(lower).suffix != '.json' or 'manifest' not in name:
        return False
    return any(term in lower for term in ART_SOURCE_MANIFEST_TERMS)


def _is_prompt_excluded_docs_path(path: str, raw_prompt: str) -> bool:
    lower = str(path).replace('\\', '/').lower().strip('/')
    return lower.startswith('docs/') and _prompt_excludes_in_repo_planning_art(raw_prompt)


def _is_swift_source_recovery_candidate(path: str, info: dict[str, Any]) -> bool:
    lower = str(path).replace('\\', '/').lower().strip('/')
    if not lower.endswith('.swift'):
        return False
    if _is_ignore_boundary_path(lower) or _is_in_repo_planning_art_path(lower):
        return False
    if any(part in lower for part in (
        '.xcassets/',
        '.xcodeproj/',
        '.xcworkspace/',
        'deriveddata/',
        '/ci/',
        '/.github/',
        'package.resolved',
    )):
        return False
    language = str(info.get('language') or '')
    return language in {'', 'swift'}


def _path_matches_any(path: str, candidates: set[str]) -> bool:
    lower = path.lower().strip("/")
    for candidate in candidates:
        c = str(candidate).lower().strip("/")
        if c and (lower == c or lower.endswith("/" + c) or lower.startswith(c.rstrip("/") + "/")):
            return True
    return False


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    name = Path(path).name.lower()
    if suffix == '.py':
        return 'python'
    if suffix == '.rs':
        return 'rust'
    if suffix in {'.ts', '.tsx'}:
        return 'typescript'
    if suffix in {'.js', '.jsx', '.mjs', '.cjs'}:
        return 'javascript'
    if suffix == '.swift':
        return 'swift'
    if suffix == '.go':
        return 'go'
    if suffix in {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx'}:
        return 'cpp'
    if suffix in {'.java', '.kt', '.kts'}:
        return 'jvm'
    if suffix == '.cs':
        return 'dotnet'
    if suffix == '.zig':
        return 'zig'
    if suffix == '.hs':
        return 'haskell'
    if suffix in {'.ex', '.exs'}:
        return 'elixir'
    if suffix == '.php':
        return 'php'
    if suffix == '.rb':
        return 'ruby'
    if suffix in {'.tf', '.tfvars'}:
        return 'terraform'
    if suffix in {'.md', '.rst'} or name in {'readme', 'readme.md', 'agents.md'}:
        return 'markdown'
    if suffix == '.json':
        return 'json'
    if suffix == '.toml':
        return 'toml'
    if suffix in {'.yaml', '.yml'}:
        return 'yaml'
    return suffix.lstrip('.') or 'text'


def _first_nonempty_line(text: str, limit: int = 180) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return ''


def _python_symbols(text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {
            'parse_error': str(exc),
            'imports': [],
            'import_details': [],
            'classes': [],
            'functions': [],
            'methods': [],
            'test_functions': [],
        }
    imports: list[str] = []
    import_details: list[dict[str, Any]] = []
    classes: list[str] = []
    functions: list[str] = []
    methods: list[str] = []
    test_functions: list[str] = []

    # Walk the full AST, not only module top level. Real-world packages often
    # hide optional CLI imports inside try/except ImportError blocks or
    # TYPE_CHECKING guards. This remains deterministic and never executes code.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                import_details.append({'type': 'import', 'module': alias.name, 'name': alias.name, 'asname': alias.asname, 'level': 0})
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            display = ('.' * int(node.level or 0)) + base
            imports.append(display or '.')
            for alias in node.names:
                import_details.append({
                    'type': 'from',
                    'module': base,
                    'name': alias.name,
                    'asname': alias.asname,
                    'level': int(node.level or 0),
                })
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(f'{node.name}.{sub.name}')
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            if node.name.startswith('test_'):
                test_functions.append(node.name)
    return {
        'imports': sorted({x for x in imports if x})[:120],
        'import_details': import_details[:200],
        'classes': sorted(set(classes), key=classes.index)[:80],
        'functions': sorted(set(functions), key=functions.index)[:160],
        'methods': sorted(set(methods), key=methods.index)[:180],
        'test_functions': sorted(set(test_functions), key=test_functions.index)[:160],
    }


def _rust_symbols(text: str) -> dict[str, Any]:
    imports = re.findall(r'^\s*use\s+([^;]+);', text, flags=re.M)
    functions = re.findall(r'^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', text, flags=re.M)
    structs = re.findall(r'^\s*(?:pub\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)\b', text, flags=re.M)
    enums = re.findall(r'^\s*(?:pub\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)\b', text, flags=re.M)
    mods = re.findall(r'^\s*(?:pub\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\b', text, flags=re.M)
    test_functions = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if '#[test]' in line or '#[tokio::test]' in line:
            window = '\n'.join(lines[idx:idx + 4])
            m = re.search(r'fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', window)
            if m:
                test_functions.append(m.group(1))
    return {
        'imports': sorted({x.strip() for x in imports if x.strip()})[:80],
        'classes': structs[:80] + enums[:80],
        'functions': functions[:160],
        'methods': [],
        'modules': mods[:80],
        'test_functions': test_functions[:120],
    }


def _js_ts_symbols(text: str) -> dict[str, Any]:
    imports = re.findall(r"^\s*import\s+(?:.+?\s+from\s+)?['\"]([^'\"]+)['\"]", text, flags=re.M)
    imports.extend(re.findall(r"require\(['\"]([^'\"]+)['\"]\)", text))
    functions = re.findall(r'^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', text, flags=re.M)
    classes = re.findall(r'^\s*(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\b', text, flags=re.M)
    exports = re.findall(r'^\s*export\s+(?:const|let|var|type|interface)\s+([A-Za-z_][A-Za-z0-9_]*)\b', text, flags=re.M)
    test_functions = [x for x in re.findall(r"\b(?:it|test)\(['\"]([^'\"]+)", text)][:80]
    return {
        'imports': sorted({x for x in imports if x})[:80],
        'classes': classes[:80],
        'functions': (functions + exports)[:160],
        'methods': [],
        'test_functions': test_functions[:120],
    }



def _go_symbols(text: str) -> dict[str, Any]:
    imports: list[str] = []
    single_imports = re.findall(r'^\s*import\s+"([^"]+)"', text, flags=re.M)
    imports.extend(single_imports)
    block_match = re.findall(r'import\s*\((.*?)\)', text, flags=re.S)
    for block in block_match:
        imports.extend(re.findall(r'"([^"]+)"', block))
    functions = re.findall(r'^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(', text, flags=re.M)
    flag_names = []
    flag_names.extend(re.findall(r'\b(?:String|Bool|Int|Duration|Float64|StringVar|BoolVar|IntVar|PersistentFlags\(\)\.(?:String|Bool|Int)|Flags\(\)\.(?:String|Bool|Int))\s*\(\s*["\']([^"\']+)["\']', text))
    flag_names.extend(re.findall(r'\b(?:StringVar|BoolVar|IntVar)P?\s*\([^,]+,\s*["\']([^"\']+)["\']', text))
    structs = re.findall(r'^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+struct\b', text, flags=re.M)
    interfaces = re.findall(r'^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+interface\b', text, flags=re.M)
    test_functions = [name for name in functions if name.startswith('Test') or name.startswith('Benchmark')]
    return {
        'imports': sorted({x for x in imports if x})[:80],
        'classes': (structs + interfaces)[:120],
        'functions': functions[:160],
        'methods': [],
        'test_functions': test_functions[:120],
        'flag_names': sorted(set(flag_names))[:120],
    }


def _cpp_symbols(text: str) -> dict[str, Any]:
    includes = re.findall(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', text, flags=re.M)
    functions = re.findall(r'^\s*(?:[A-Za-z_][A-Za-z0-9_:<>*&\s]+\s+)+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:\{|$)', text, flags=re.M)
    classes = re.findall(r'^\s*(?:class|struct)\s+([A-Za-z_][A-Za-z0-9_]*)\b', text, flags=re.M)
    return {
        'imports': sorted(set(includes))[:80],
        'classes': classes[:120],
        'functions': functions[:160],
        'methods': [],
        'test_functions': [f for f in functions if f.lower().startswith('test')][:120],
    }

def _swift_symbols(text: str) -> dict[str, Any]:
    imports = re.findall(r'^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)', text, flags=re.M)
    types = re.findall(r'^\s*(?:public\s+|private\s+|internal\s+|fileprivate\s+)?(?:final\s+)?(?:class|struct|enum|protocol|actor)\s+([A-Za-z_][A-Za-z0-9_]*)\b', text, flags=re.M)
    functions = re.findall(r'^\s*(?:public\s+|private\s+|internal\s+|fileprivate\s+)?func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', text, flags=re.M)
    test_functions = [f for f in functions if f.startswith('test')]
    return {'imports': sorted(set(imports))[:80], 'classes': types[:120], 'functions': functions[:160], 'methods': [], 'test_functions': test_functions[:120]}


def _markdown_summary(text: str) -> dict[str, Any]:
    headings = [line.strip() for line in text.splitlines() if line.lstrip().startswith('#')]
    return {'headings': headings[:80], 'first_nonempty_line': _first_nonempty_line(text)}


def _config_summary(path: str, text: str) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    if suffix == '.json':
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {'top_level_keys': list(data.keys())[:80]}
            return {'top_level_type': type(data).__name__, 'length': len(data) if isinstance(data, list) else None}
        except Exception as exc:
            return {'parse_error': str(exc), 'first_nonempty_line': _first_nonempty_line(text)}
    if suffix == '.toml':
        try:
            data = tomllib.loads(text)
            return {'top_level_keys': list(data.keys())[:80]}
        except Exception as exc:
            return {'parse_error': str(exc), 'first_nonempty_line': _first_nonempty_line(text)}
    if suffix in {'.yaml', '.yml'}:
        keys = []
        for line in text.splitlines():
            if line.startswith(' ') or line.startswith('\t') or not line.strip() or line.lstrip().startswith('#'):
                continue
            m = re.match(r'^([A-Za-z0-9_.-]+)\s*:', line)
            if m:
                keys.append(m.group(1))
        return {'top_level_keys': keys[:80], 'first_nonempty_line': _first_nonempty_line(text)}
    return {'first_nonempty_line': _first_nonempty_line(text)}


def _symbols_for(path: str, text: str) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    if suffix == '.py':
        return _python_symbols(text)
    if suffix == '.rs':
        return _rust_symbols(text)
    if suffix in {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'}:
        return _js_ts_symbols(text)
    if suffix == '.swift':
        return _swift_symbols(text)
    if suffix == '.go':
        return _go_symbols(text)
    if suffix in {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx'}:
        return _cpp_symbols(text)
    if suffix in {'.md', '.rst'} or Path(path).name.lower() in {'readme', 'readme.md', 'agents.md'}:
        return _markdown_summary(text)
    if suffix in CONFIG_EXTENSIONS:
        return _config_summary(path, text)
    return {'first_nonempty_line': _first_nonempty_line(text)}


def _module_names_for_path(path: str) -> set[str]:
    p = path.replace('\\', '/').strip('/')
    suffix = Path(p).suffix
    without = p[:-len(suffix)] if suffix else p
    candidates = {without.replace('/', '.')}
    parts = without.split('/')
    if parts and parts[0] in {'src', 'lib', 'app'}:
        candidates.add('.'.join(parts[1:]))
    candidates.add(Path(without).name)
    if p.endswith('/__init__.py'):
        pkg = p[:-len('/__init__.py')]
        candidates.add(pkg.replace('/', '.'))
        if pkg.startswith('src/'):
            candidates.add(pkg[4:].replace('/', '.'))
    return {c for c in candidates if c}


def _match_import_to_path(import_name: str, module_index: dict[str, str]) -> str | None:
    imp = import_name.strip().strip('.')
    if not imp:
        return None
    candidates = [imp]
    if '.' in imp:
        parts = imp.split('.')
        candidates.extend('.'.join(parts[:i]) for i in range(len(parts) - 1, 0, -1))
    candidates.append(imp.split('.')[0])
    for candidate in candidates:
        if candidate in module_index:
            return module_index[candidate]
    return None


def _python_module_for_path(path: str) -> str | None:
    p = path.replace('\\', '/').strip('/')
    if not p.endswith('.py'):
        return None
    if p.startswith('src/'):
        p = p[4:]
    if p.endswith('/__init__.py'):
        p = p[:-len('/__init__.py')]
    else:
        p = p[:-3]
    return p.replace('/', '.') or None


def _python_package_for_path(path: str) -> str | None:
    module = _python_module_for_path(path)
    if not module:
        return None
    if path.replace('\\', '/').endswith('/__init__.py'):
        return module
    if '.' in module:
        return module.rsplit('.', 1)[0]
    return ''


def _resolve_relative_python_import(from_path: str, detail: dict[str, Any]) -> list[str]:
    module = str(detail.get('module') or '')
    name = str(detail.get('name') or '')
    level = int(detail.get('level') or 0)
    if level <= 0:
        base = module
        return [c for c in (base, f'{base}.{name}' if base and name and name != '*' else '') if c]

    package = _python_package_for_path(from_path)
    if package is None:
        return []
    parts = package.split('.') if package else []
    # level=1 means current package, level=2 parent package, etc.
    keep = max(0, len(parts) - (level - 1))
    prefix = '.'.join(parts[:keep])
    base = '.'.join(x for x in [prefix, module] if x)
    candidates = [base] if base else []
    if name and name != '*':
        candidates.append('.'.join(x for x in [base, name] if x))
    return [c for c in candidates if c]


def _resolve_import_detail_to_path(from_path: str, detail: dict[str, Any], module_index: dict[str, str]) -> str | None:
    for candidate in _resolve_relative_python_import(from_path, detail):
        target = _match_import_to_path(candidate, module_index)
        if target:
            return target
    return None



def _with_known_js_extensions(base: str) -> list[str]:
    suffixes = ['', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '/index.ts', '/index.tsx', '/index.js', '/index.jsx']
    return [base + suffix for suffix in suffixes]


def _resolve_relative_js_import(from_path: str, imp: str, files: dict[str, dict[str, Any]]) -> str | None:
    if not imp.startswith('.'):
        return None
    base = (Path(from_path).parent / imp).as_posix()
    # Collapse simple .. and . segments without requiring the file to exist locally.
    parts: list[str] = []
    for part in base.split('/'):
        if part in {'', '.'}:
            continue
        if part == '..':
            if parts:
                parts.pop()
            continue
        parts.append(part)
    normalized = '/'.join(parts)
    for candidate in _with_known_js_extensions(normalized):
        if candidate in files:
            return candidate
    return None


def _resolve_rust_module_path(from_path: str, module: str, files: dict[str, dict[str, Any]]) -> str | None:
    p = Path(from_path)
    parent = p.parent.as_posix()
    candidates: list[str] = []
    if p.name in {'main.rs', 'lib.rs', 'mod.rs'}:
        candidates.extend([f'{parent}/{module}.rs', f'{parent}/{module}/mod.rs'])
    else:
        candidates.extend([f'{parent}/{module}.rs', f'{parent}/{module}/mod.rs'])
    for candidate in candidates:
        candidate = candidate.strip('/')
        if candidate in files:
            return candidate
    return None

def _normalize_prompt_path_token(token: str) -> str:
    cleaned = token.strip().strip("`'\"()[]{}<>").strip('.,;!')
    cleaned = cleaned.replace('\\', '/')
    parts = cleaned.split(':')
    if len(parts) > 1 and Path(parts[0]).suffix:
        cleaned = parts[0]
    return cleaned.lstrip('/')


def _is_test_file(path: str, info: dict[str, Any] | None = None) -> bool:
    lower = path.lower().replace('\\', '/')
    name = Path(lower).name
    if classify_path_role(path).is_test:
        return True
    return bool(
        (info or {}).get('test_functions')
        or lower.startswith('tests/')
        or '/tests/' in lower
        or name.startswith('test_')
        or name.endswith('_test.py')
        or name.endswith('_test.go')
        or name.endswith('_test.rs')
        or name.endswith('.spec.ts')
        or name.endswith('.spec.tsx')
        or name.endswith('.spec.js')
        or '.test.' in name
        or name.endswith('tests.swift')
        or name.endswith('_test.exs')
        or name.endswith('test.php')
        or name.endswith('_spec.rb')
        or name.endswith('_test.rb')
        or name.endswith('tests.cs')
        or name.endswith('test.cs')
        or name.endswith('_test.zig')
        or name.endswith('test.zig')
        or name.endswith('spec.hs')
        or name.endswith('test.hs')
    )


def _source_test_name_candidates(path: str) -> set[str]:
    p = path.replace('\\', '/').strip('/')
    stem = Path(p).stem
    parent = Path(p).parent.name
    c = {
        f'test_{stem}', f'{stem}_test', f'test_{parent}', f'{parent}_test',
        f'{stem}test', f'{parent}test', f'{stem}tests', f'{parent}tests',
        f'{stem}_spec', f'{parent}_spec', f'{stem}spec', f'{parent}spec',
    }
    if stem.startswith('_'):
        c.add(f'test_{stem[1:]}')
        c.add(f'{stem[1:]}_test')
    return {x.lower() for x in c if x}


def _test_matches_source_path(test_path: str, source_path: str) -> bool:
    test_stem = Path(test_path).stem.lower()
    test_name = Path(test_path).name.lower()
    candidates = _source_test_name_candidates(source_path)
    if test_stem in candidates:
        return True
    if any(candidate in test_name for candidate in candidates):
        return True
    source_stem = Path(source_path).stem.lower()
    if source_stem in {'cli', 'main', 'app'} and any(token in test_name for token in {'cli', 'main', 'app'}):
        return True
    return False


def _prompt_mentioned_repo_paths(raw_prompt: str, files: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    indexed = {p.lower(): p for p in files}
    basename: dict[str, list[str]] = {}
    for p in files:
        basename.setdefault(Path(p).name.lower(), []).append(p)
    mentioned: list[str] = []
    for raw in re.findall(r'[A-Za-z0-9_./\\:-]+', raw_prompt):
        token = _normalize_prompt_path_token(raw)
        lower = token.lower()
        if not lower:
            continue
        if lower in indexed:
            mentioned.append(indexed[lower])
            continue
        if '/' in lower:
            for candidate_lower, original in indexed.items():
                if candidate_lower == lower or candidate_lower.endswith('/' + lower):
                    mentioned.append(original)
        elif Path(lower).suffix:
            mentioned.extend(basename.get(Path(lower).name.lower(), []))
    out=[]; seen=set()
    for item in mentioned:
        if item not in seen:
            out.append(item); seen.add(item)
    tests = [p for p in out if _is_test_file(p, files.get(p) or {})]
    sources = [p for p in out if p not in tests]
    return sources, tests


def _prompt_mentioned_existing_paths(raw_prompt: str, repo_root: Path | None, files: dict[str, dict[str, Any]]) -> list[str]:
    if repo_root is None:
        return []
    indexed = {p.lower() for p in files}
    out: list[str] = []
    seen: set[str] = set()
    try:
        resolved_root = repo_root.resolve()
    except OSError:
        return []
    for raw in re.findall(r'[A-Za-z0-9_./\\:-]+', raw_prompt):
        token = _normalize_prompt_path_token(raw)
        if not token or token.lower() in indexed or '/' not in token:
            continue
        candidate = repo_root / token
        try:
            resolved = candidate.resolve()
            rel = resolved.relative_to(resolved_root).as_posix()
        except (OSError, ValueError):
            continue
        if resolved.is_file() and rel not in seen:
            out.append(rel)
            seen.add(rel)
    return out


def _prompt_forbidden_repo_paths(raw_prompt: str, files: dict[str, dict[str, Any]], repo_root: Path | None) -> set[str]:
    forbidden: set[str] = set()
    for match in NEGATIVE_INTENT_RE.finditer(raw_prompt or ""):
        clause = match.group(0)
        sources, tests = _prompt_mentioned_repo_paths(clause, files)
        forbidden.update(sources)
        forbidden.update(tests)
        forbidden.update(_prompt_mentioned_existing_paths(clause, repo_root, files))
    return forbidden


def _related_tests_for(path: str, all_paths: set[str]) -> list[str]:
    p = path.replace('\\', '/').strip('/')
    stem = Path(p).stem
    suffix = Path(p).suffix.lower()
    candidates: set[str] = set()
    if suffix == '.py':
        candidates.update({
            f'tests/test_{stem}.py',
            f'test_{stem}.py',
            f'tests/{stem}_test.py',
            p.replace('/src/', '/tests/').replace(f'{stem}.py', f'test_{stem}.py'),
        })
        if p.startswith('src/'):
            candidates.add('tests/test_' + p[4:])
    elif suffix == '.rs':
        candidates.update({f'tests/{stem}.rs', f'tests/{stem}_test.rs', 'tests/tests.rs'})
        if p in {'src/main.rs', 'src/app.rs'} or 'cli' in stem or 'app' in stem or 'main' in stem:
            candidates.add('tests/cli.rs')
    elif suffix == '.go':
        candidates.update({p.replace('.go', '_test.go'), f'{Path(p).parent.as_posix()}/{stem}_test.go'})
    elif suffix in {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'}:
        candidates.update({p.replace(suffix, f'.test{suffix}'), p.replace(suffix, f'.spec{suffix}'), f'tests/{stem}.test{suffix}'})
        parent = Path(p).parent.as_posix()
        candidates.add(f'{parent}/__tests__/{stem}.spec.ts')
        candidates.add(f'{parent}/__tests__/{stem}.test.ts')
    elif suffix == '.swift':
        candidates.update({f'Tests/{stem}Tests.swift', f'{stem}Tests.swift'})
    elif suffix == '.ex':
        candidates.update({p.replace('/lib/', '/test/').replace('.ex', '_test.exs'), f'test/{stem}_test.exs'})
    elif suffix == '.php':
        candidates.update({
            p.replace('plugins/', 'tests/PHPUnit/Plugins/').replace('.php', 'Test.php'),
            p.replace('core/', 'tests/PHPUnit/Core/').replace('.php', 'Test.php'),
            p.replace('src/', 'tests/').replace('.php', 'Test.php'),
            f'tests/PHPUnit/{stem}Test.php',
        })
    elif suffix == '.rb':
        candidates.update({
            p.replace('app/', 'spec/').replace('.rb', '_spec.rb'),
            p.replace('lib/', 'spec/lib/').replace('.rb', '_spec.rb'),
            p.replace('app/', 'test/').replace('.rb', '_test.rb'),
            f'spec/{stem}_spec.rb',
            f'test/{stem}_test.rb',
        })
    elif suffix == '.kt':
        candidates.update({
            p.replace('/src/main/', '/src/test/').replace('.kt', 'Test.kt'),
            p.replace('/src/main/', '/src/androidTest/').replace('.kt', 'Test.kt'),
        })
    elif suffix == '.cs':
        candidates.update({
            p.replace('/src/', '/tests/').replace('.cs', 'Tests.cs'),
            p.replace('/src/', '/test/').replace('.cs', 'Tests.cs'),
            f'tests/{stem}Tests.cs',
            f'test/{stem}Tests.cs',
        })
        parts = p.split('/')
        if len(parts) >= 3 and parts[0] in {'src', 'app', 'lib'}:
            project = parts[1]
            rel_tail = '/'.join(parts[2:])
            candidates.add(f'tests/{project}.Tests/{rel_tail}'.replace('.cs', 'Tests.cs'))
            candidates.add(f'test/{project}.Tests/{rel_tail}'.replace('.cs', 'Tests.cs'))
    elif suffix == '.zig':
        candidates.update({
            p.replace('/src/', '/test/').replace('.zig', '_test.zig'),
            p.replace('/src/', '/tests/').replace('.zig', '_test.zig'),
            f'test/{stem}_test.zig',
            f'tests/{stem}_test.zig',
        })
    elif suffix == '.hs':
        candidates.update({
            p.replace('src/', 'test/').replace('.hs', 'Spec.hs'),
            p.replace('src/', 'test/').replace('.hs', 'Test.hs'),
            p.replace('app/', 'test/').replace('.hs', 'Spec.hs'),
            f'test/{stem}Spec.hs',
            f'test/{stem}Test.hs',
        })
    return sorted(c for c in candidates if c in all_paths)[:40]


def _path_depth(path: str) -> int:
    return len([part for part in str(path).replace('\\', '/').split('/') if part])


def _role_model_hints(raw_prompt: str, files: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    intent = infer_prompt_intent(raw_prompt)
    prompt_words = {
        _normalize_task_token(token)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", raw_prompt or "")
    }
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for path, info in files.items():
        role = info.get('role_model') if isinstance(info.get('role_model'), dict) else classify_path_role(path).to_dict()
        if _is_benchmark_prompt_file(path) and not _prompt_mentions_benchmark_prompts(raw_prompt):
            continue
        if role.get('is_generated_or_vendor'):
            continue
        if role.get('is_example') and intent.intent != 'example':
            continue
        score = path_role_rank(path, intent)
        normalized_path = _normalize_task_token(path)
        prompt_path_overlap = sum(1 for word in prompt_words if word and word in normalized_path)
        if prompt_path_overlap:
            score += min(240, 80 * prompt_path_overlap)
        if (
            intent.intent == 'runtime'
            and role.get('role') == 'source'
            and role.get('entrypoint_likelihood') == 'low'
            and prompt_path_overlap == 0
        ):
            continue
        if score > 0:
            ranked.append((score, path, role))
    ranked.sort(key=lambda item: (-item[0], _path_depth(item[1]), item[1].lower()))
    likely: list[dict[str, Any]] = []
    related: list[dict[str, Any]] = []
    primary_limit = (
        3 if intent.intent == 'workflow'
        else 1 if intent.intent == 'test_edit'
        else 2 if intent.intent in {'docs', 'config'}
        else 4 if intent.intent == 'runtime'
        else 4
    )
    for score, path, role in ranked[:primary_limit]:
        if role.get('role') == 'test' and intent.intent != 'test_edit':
            related.append({
                'path': path,
                'source': 'cross_ecosystem_role_model',
                'reason': 'role_model_test_verification_candidate',
                'role_model_score': score,
                'related_test_resolution_reason': 'fallback',
                'related_test_anchor_confidence': 'low',
            })
            continue
        likely.append({
            'path': path,
            'kind': f"role_model_{role.get('role')}",
            'source': 'cross_ecosystem_role_model',
            'reason': f"prompt intent `{intent.intent}` selected {role.get('role')} role",
            'role_model_score': score,
            'role_model': role,
        })
    docs_prompt_needs_tests = bool(re.search(r"\b(tests?|coverage|validation|benchmark|expectation|regression)\b", raw_prompt or "", re.IGNORECASE))
    if 'test' in intent.verification_roles and not (intent.intent == 'docs' and not docs_prompt_needs_tests):
        tests: list[tuple[int, str]] = []
        for path, info in files.items():
            role = info.get('role_model') if isinstance(info.get('role_model'), dict) else classify_path_role(path).to_dict()
            if not role.get('is_test') or role.get('is_generated_or_vendor'):
                continue
            if _is_docs_fixture_test_path(path):
                continue
            score = path_role_rank(path, intent, for_related_test=True)
            lower = path.lower()
            if any(term in lower for term in ('local_validation', 'smoke', 'workflow', 'package', 'metadata', 'layout', 'cli', 'command')):
                score += 150
            if lower in {'tests/__init__.py', 'test/__init__.py'}:
                score += 180
            tests.append((score, path))
        tests.sort(key=lambda item: (-item[0], _path_depth(item[1]), item[1].lower()))
        related_limit = 1 if intent.intent in {'test_edit', 'docs'} else 2 if intent.intent in {'config', 'workflow'} else 3
        for score, path in tests[:related_limit]:
            related.append({
                'path': path,
                'source': 'cross_ecosystem_role_model',
                'reason': f"prompt intent `{intent.intent}` requested verification role",
                'role_model_score': score,
                'related_test_resolution_reason': 'fallback',
                'related_test_anchor_confidence': 'low',
            })
    diagnostics = {
        'prompt_intent': intent.to_dict(),
        'role_model_ranked_candidate_count': len(ranked),
        'role_model_likely_count': len(likely),
        'role_model_related_count': len(related),
    }
    return likely, related, diagnostics


def _cargo_entrypoints(repo_root: Path, all_paths: set[str]) -> list[dict[str, Any]]:
    path = repo_root / 'Cargo.toml'
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    package_name = (data.get('package') or {}).get('name')
    for item in data.get('bin') or []:
        if not isinstance(item, dict):
            continue
        rel = item.get('path') or 'src/main.rs'
        if rel in all_paths or (repo_root / rel).exists():
            out.append({'path': rel, 'name': item.get('name') or package_name, 'kind': 'binary', 'source': 'Cargo.toml [[bin]]'})
    if not out and 'src/main.rs' in all_paths:
        out.append({'path': 'src/main.rs', 'name': package_name, 'kind': 'binary', 'source': 'Cargo.toml default src/main.rs'})
    lib = data.get('lib') or {}
    lib_path = lib.get('path') if isinstance(lib, dict) else None
    if lib_path and (lib_path in all_paths or (repo_root / lib_path).exists()):
        out.append({'path': lib_path, 'name': lib.get('name') or package_name, 'kind': 'library', 'source': 'Cargo.toml [lib]'})
    elif 'src/lib.rs' in all_paths:
        out.append({'path': 'src/lib.rs', 'name': package_name, 'kind': 'library', 'source': 'Cargo.toml default src/lib.rs'})
    workspace = data.get('workspace') or {}
    if isinstance(workspace, dict):
        for member in workspace.get('members') or []:
            if isinstance(member, str):
                candidate = f'{member.strip("/")}/src/main.rs'
                if candidate in all_paths:
                    out.append({'path': candidate, 'name': Path(member).name, 'kind': 'workspace_binary_candidate', 'source': 'Cargo.toml [workspace].members'})
    return out[:80]


def _package_json_entrypoints(repo_root: Path, all_paths: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    package_paths = sorted(p for p in all_paths if Path(p).name == 'package.json')
    for package_rel in package_paths:
        path = repo_root / package_rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
        except Exception:
            continue
        base = str(Path(package_rel).parent.as_posix())
        if base == '.':
            base = ''

        def join(rel: str) -> str:
            rel = rel.lstrip('./')
            return f'{base}/{rel}'.strip('/') if base else rel

        for key in ('main', 'module', 'types'):
            rel = data.get(key)
            if isinstance(rel, str):
                candidate = join(rel)
                if candidate in all_paths:
                    out.append({'path': candidate, 'name': data.get('name') or key, 'kind': key, 'source': f'{package_rel} {key}', 'package_root': base or '.'})
        bin_value = data.get('bin')
        if isinstance(bin_value, str):
            candidate = join(bin_value)
            if candidate in all_paths:
                out.append({'path': candidate, 'name': data.get('name'), 'kind': 'cli_binary', 'source': f'{package_rel} bin', 'package_root': base or '.'})
        elif isinstance(bin_value, dict):
            for name, rel in bin_value.items():
                if isinstance(rel, str):
                    candidate = join(rel)
                    if candidate in all_paths:
                        out.append({'path': candidate, 'name': name, 'kind': 'cli_binary', 'source': f'{package_rel} bin', 'package_root': base or '.'})
        scripts = data.get('scripts') or {}
        if isinstance(scripts, dict):
            for script_name, command in scripts.items():
                if not isinstance(command, str):
                    continue
                for token in re.findall(r'(?:src|app|bin|cli|scripts)/[A-Za-z0-9_./-]+\.(?:js|ts|tsx|jsx|mjs|cjs)', command):
                    candidate = join(token)
                    if candidate in all_paths:
                        out.append({'path': candidate, 'name': script_name, 'kind': 'script_target', 'source': f'{package_rel} scripts.{script_name}', 'package_root': base or '.'})
    return out[:160]

def _pyproject_entrypoints(repo_root: Path, all_paths: set[str]) -> list[dict[str, Any]]:
    path = repo_root / 'pyproject.toml'
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    scripts = (data.get('project') or {}).get('scripts') or {}
    if isinstance(scripts, dict):
        for name, target in scripts.items():
            if not isinstance(target, str):
                continue
            module_target, _, symbol_target = target.partition(':')
            mod = module_target.replace('.', '/')
            candidates = [f'src/{mod}.py', f'{mod}.py', f'src/{mod}/__init__.py', f'{mod}/__init__.py']
            for rel in candidates:
                if rel in all_paths:
                    out.append({
                        'path': rel,
                        'name': name,
                        'kind': 'console_script',
                        'source': 'pyproject.toml [project.scripts]',
                        'target': target,
                        'module': module_target,
                        'symbol': symbol_target or None,
                    })
                    break
    tool = data.get('tool') or {}
    pytest_cfg = tool.get('pytest') or {}
    if pytest_cfg and 'tests' in all_paths:
        out.append({'path': 'tests', 'name': 'pytest', 'kind': 'test_root', 'source': 'pyproject.toml tool.pytest'})
    return out[:80]


def _package_swift_entrypoints(repo_root: Path, all_paths: set[str]) -> list[dict[str, Any]]:
    path = repo_root / 'Package.swift'
    if not path.exists():
        return []
    text = path.read_text(encoding='utf-8', errors='replace')[:200000]
    out: list[dict[str, Any]] = []
    target_names = re.findall(r'\.target\s*\(\s*name:\s*"([^"]+)"', text)
    executable_names = re.findall(r'\.executableTarget\s*\(\s*name:\s*"([^"]+)"', text)
    for name in executable_names + target_names:
        candidates = [f'Sources/{name}/main.swift', f'Sources/{name}/{name}.swift', f'Sources/{name}.swift']
        for rel in candidates:
            if rel in all_paths:
                out.append({'path': rel, 'name': name, 'kind': 'swift_target', 'source': 'Package.swift target'})
                break
    return out[:80]



def detect_package_manager(repo_root: Path, all_paths: set[str] | None = None) -> str:
    all_paths = all_paths or {p.relative_to(repo_root).as_posix() for p in repo_root.rglob('*') if p.is_file()}
    if 'pnpm-lock.yaml' in all_paths or 'pnpm-workspace.yaml' in all_paths:
        return 'pnpm'
    if 'yarn.lock' in all_paths:
        return 'yarn'
    if 'bun.lockb' in all_paths or 'bun.lock' in all_paths:
        return 'bun'
    if 'package-lock.json' in all_paths or 'package.json' in all_paths:
        return 'npm'
    return 'none'

def discover_entrypoints(repo_root: Path, all_paths: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    out.extend(_cargo_entrypoints(repo_root, all_paths))
    out.extend(_package_json_entrypoints(repo_root, all_paths))
    out.extend(_pyproject_entrypoints(repo_root, all_paths))
    out.extend(_package_swift_entrypoints(repo_root, all_paths))
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        key = f"{item.get('path')}|{item.get('name')}|{item.get('source')}"
        if item.get('path') and key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped[:160]


def _repo_map_file(repo_map: dict[str, Any], path: str) -> dict[str, Any]:
    return dict((repo_map.get('files') or {}).get(path) or {})


def _related_tests_for_paths(
    repo_map: dict[str, Any],
    paths: list[str],
    *,
    explicit_tests: list[str] | None = None,
) -> list[dict[str, Any]]:
    files = repo_map.get('files') or {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for test_path in explicit_tests or []:
        if test_path in files and test_path not in seen:
            out.append({
                'path': test_path,
                'source': 'prompt',
                'reason': 'prompt_mentioned_test_file',
                'related_test_resolution_reason': 'prompt_explicit_test',
                'related_test_anchor_confidence': 'high',
            })
            seen.add(test_path)

    for path in paths:
        info = files.get(path) or {}
        if path in files and _is_test_file(path, info) and path not in seen:
            out.append({
                'path': path,
                'source': path,
                'reason': 'test_candidate_mirrored_to_related_tests',
                'related_test_resolution_reason': 'test_candidate_mirrored',
                'related_test_anchor_confidence': 'high',
            })
            seen.add(path)
        for test_path in info.get('related_tests') or []:
            if test_path not in seen and test_path in files:
                out.append({
                    'path': test_path,
                    'source': path,
                    'reason': 'repo_map related_tests',
                    'related_test_resolution_reason': 'source_adjacent_test',
                    'related_test_anchor_confidence': 'medium',
                })
                seen.add(test_path)
        for candidate, candidate_info in files.items():
            if candidate in seen or not _is_test_file(candidate, candidate_info):
                continue
            if candidate in (info.get('referenced_by') or []):
                out.append({
                    'path': candidate,
                    'source': path,
                    'reason': 'test imports impacted source',
                    'related_test_resolution_reason': 'source_adjacent_test',
                    'related_test_anchor_confidence': 'medium',
                })
                seen.add(candidate)
                continue
            if _test_matches_source_path(candidate, path):
                out.append({
                    'path': candidate,
                    'source': path,
                    'reason': 'test path matches impacted source name',
                    'related_test_resolution_reason': 'same_basename',
                    'related_test_anchor_confidence': 'high',
                })
                seen.add(candidate)
    return out[:40]


def _related_test_prompt_score(path: str, raw_prompt: str) -> int:
    prompt = (raw_prompt or "").lower()
    lower = path.lower()
    score = 0
    phrase_scores = [
        (("packet-mode", "packet mode", "cli help", "help text"), ("codex_cli", "cli_compat"), 520),
        (("repo-map", "repo map", "candidate ranking"), ("repo_map", "impact"), 520),
        (("package metadata", "packaging", "package layout", "project metadata"), ("package_layout", "metadata_root"), 560),
        (("local validation", "smoke validation", "smoke test", "ci-style", "workflow"), ("local_validation", "v266", "smoke"), 560),
        (("source recovery", "swiftui", "viewmodels", "views"), ("swift_source_recovery", "v2615"), 520),
        (("review-patch", "review patch", "patch review", "merge readiness"), ("review_patch", "v260"), 520),
        (("benchmark", "expectation"), ("benchmark", "v263"), 360),
    ]
    for prompt_terms, path_terms, value in phrase_scores:
        if any(term in prompt for term in prompt_terms) and any(term in lower for term in path_terms):
            score += value
    prompt_words = {_normalize_task_token(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", prompt)}
    path_norm = _normalize_task_token(path)
    score += min(180, 30 * sum(1 for word in prompt_words if word and word in path_norm))
    return score


def _is_docs_fixture_test_path(path: str) -> bool:
    lower = str(path).replace("\\", "/").lower()
    suffix = Path(lower).suffix
    return (
        suffix in {".md", ".rst", ".txt", ".mdx"}
        or lower.startswith(("fixtures/", "fixture/", "examples/", "samples/"))
        or "/fixtures/" in lower
        or "/fixture/" in lower
        or "/testdata/" in lower
        or "/test-data/" in lower
        or "/__snapshots__/" in lower
        or "/snapshots/" in lower
        or "/docs_src/" in lower
        or lower.startswith(("docs_src/", "agents/", ".agents/", "claude/", ".claude/"))
        or "/skills/" in lower
        or lower.endswith("/readme.md")
        or lower.endswith("/readme.rst")
    )


def _package_affinity_prefix(path: str) -> str:
    parts = [part for part in str(path).replace("\\", "/").split("/") if part]
    if len(parts) >= 2 and parts[0] in {"packages", "crates", "examples", "samples"}:
        return "/".join(parts[:2])
    if len(parts) >= 2 and parts[0] == "Sources":
        return f"swift:{parts[1].lower()}"
    if len(parts) >= 2 and parts[0] == "Tests":
        package = parts[1].lower()
        package = re.sub(r"(tests?|test)$", "", package)
        return f"swift:{package}" if package else "Tests"
    if len(parts) >= 2 and parts[0] in {"src", "lib", "app", "cmd", "internal", "pkg", "Sources", "Tests"}:
        return parts[0]
    return ""


def _related_test_resolution_reason(item: dict[str, Any], raw_prompt: str, likely_paths: list[str]) -> str:
    path = str(item.get("path") or "")
    reason = str(item.get("reason") or "")
    source = str(item.get("source") or "")
    if reason == "prompt_mentioned_test_file":
        return "prompt_explicit_test"
    if reason == "test_candidate_mirrored_to_related_tests":
        return "test_candidate_mirrored"
    if "package_layout_test" in reason:
        return "config_layout_test"
    if "root_test_anchor" in reason:
        return "root_layout_test"
    if "workflow_prompt_routes" in reason or re.search(r"(?i)(local_validation|smoke|workflow|ci)", path):
        return "workflow_validation_test"
    if "path matches impacted source name" in reason:
        return "same_basename"
    if "same directory" in reason:
        return "same_directory"
    if "test imports impacted source" in reason or "repo_map related_tests" in reason:
        return "source_adjacent_test"
    path_prefix = _package_affinity_prefix(path)
    source_prefix = _package_affinity_prefix(source)
    likely_prefixes = {_package_affinity_prefix(candidate) for candidate in likely_paths if _package_affinity_prefix(candidate)}
    if path_prefix and source_prefix and path_prefix == source_prefix:
        return "same_package"
    if path_prefix and path_prefix in likely_prefixes:
        return "same_package"
    if path_prefix and likely_prefixes and any(path_prefix.split(":", 1)[0] == prefix.split(":", 1)[0] for prefix in likely_prefixes):
        return "same_workspace"
    return "fallback"


def _rank_related_tests(
    repo_map: dict[str, Any],
    raw_prompt: str,
    likely_paths: list[str],
    related_tests: list[dict[str, Any]],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    intent = infer_prompt_intent(raw_prompt)
    if intent.intent == "test_edit":
        limit = min(limit, 2)
    elif intent.intent in {"config", "workflow", "docs"}:
        limit = min(limit, 2)
    else:
        limit = min(limit, 3)
    if intent.intent == "docs" and not re.search(r"\b(tests?|coverage|validation|benchmark|expectation|regression)\b", raw_prompt or "", re.IGNORECASE):
        return [
            {
                **item,
                "related_test_demotion_reason": "docs_prompt_without_verification_terms",
            }
            for item in related_tests
            if str(item.get("reason") or "") == "prompt_mentioned_test_file"
        ][:1]
    files = repo_map.get("files") or {}
    likely_set = {str(path) for path in likely_paths}
    likely_prefixes = {_package_affinity_prefix(path) for path in likely_paths if _package_affinity_prefix(path)}

    def score(item: dict[str, Any]) -> tuple[int, str]:
        path = str(item.get("path") or "")
        source = str(item.get("source") or "")
        reason = str(item.get("reason") or "")
        value = _related_test_prompt_score(path, raw_prompt)
        if reason == "prompt_mentioned_test_file":
            value += 2000
        if reason == "test_candidate_mirrored_to_related_tests":
            value += 1800
        if "package_layout_test" in reason:
            value += 1700
        if "root_test_anchor" in reason:
            value += 1550
        if "path matches impacted source name" in reason:
            value += 1200
        if "test imports impacted source" in reason:
            value += 720
        if "repo_map related_tests" in reason:
            value += 560
        if source in likely_set:
            value += 120
        info = files.get(path) or {}
        if path in likely_set and _is_test_file(path, info):
            value += 900
        prefix = _package_affinity_prefix(path)
        if prefix and prefix in likely_prefixes:
            value += 620
        elif prefix and likely_prefixes and prefix not in likely_prefixes:
            value -= 260
        if _is_docs_fixture_test_path(path):
            value -= 1200
        if path.lower() in {"tests/__init__.py", "test/__init__.py"}:
            value += 260
        return (-value, path)

    ranked = sorted(related_tests, key=score)
    strong = [
        item for item in ranked
        if _related_test_prompt_score(str(item.get("path") or ""), raw_prompt) >= 500
        or str(item.get("reason") or "") in {"prompt_mentioned_test_file", "test_candidate_mirrored_to_related_tests"}
        or "path matches impacted source name" in str(item.get("reason") or "")
        or "root_test_anchor" in str(item.get("reason") or "")
        or "package_layout_test" in str(item.get("reason") or "")
    ]
    selected = (strong or ranked)[:limit]
    selected_paths = {str(item.get("path") or "") for item in selected}
    trimmed_count = sum(1 for item in ranked if str(item.get("path") or "") not in selected_paths)
    fallback_only = bool(selected) and all(
        _related_test_resolution_reason(item, raw_prompt, likely_paths) == "fallback"
        for item in selected
    )
    annotated: list[dict[str, Any]] = []
    likely_prefixes = {_package_affinity_prefix(path) for path in likely_paths if _package_affinity_prefix(path)}
    for item in selected:
        path = str(item.get("path") or "")
        existing_resolution = str(item.get("related_test_resolution_reason") or "")
        inferred_resolution = _related_test_resolution_reason(item, raw_prompt, likely_paths)
        resolution = inferred_resolution if not existing_resolution or existing_resolution == "fallback" else existing_resolution
        affinity = _package_affinity_prefix(path)
        if resolution == "fallback":
            confidence = "low"
        elif resolution in {"prompt_explicit_test", "test_candidate_mirrored", "same_basename", "config_layout_test", "root_layout_test", "workflow_validation_test"}:
            confidence = "high"
        else:
            confidence = "medium"
        annotated_item = {
            **item,
            "related_test_resolution_reason": resolution,
            "related_test_package_affinity": {
                "test_prefix": affinity,
                "likely_prefixes": sorted(likely_prefixes),
                "same_package": bool(affinity and affinity in likely_prefixes),
            },
            "related_test_anchor_confidence": str(item.get("related_test_anchor_confidence") or confidence),
        }
        if resolution == "fallback":
            annotated_item["related_test_fallback_warning"] = True
        if _is_docs_fixture_test_path(path):
            annotated_item["related_test_demotion_reason"] = "docs_fixture_or_generated_test_penalized"
        if fallback_only:
            annotated_item["related_test_fallback_warning"] = True
            annotated_item["related_test_demotion_reason"] = annotated_item.get("related_test_demotion_reason") or "fallback_only_related_test_selection"
        annotated.append(annotated_item)
    selected = annotated
    if trimmed_count:
        selected = [
            {
                **item,
                "related_test_ranking": "ranked_direct_or_prompt_relevant",
                "related_tests_trimmed_count": trimmed_count,
            }
            for item in selected
        ]
    return selected


def _dependency_slices(repo_map: dict[str, Any], paths: list[str], *, limit: int = 24) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    edges = repo_map.get('edges') or []
    path_set = set(paths)
    deps: list[dict[str, str]] = []
    dependents: list[dict[str, str]] = []
    for edge in edges:
        src = str(edge.get('from') or '')
        dst = str(edge.get('to') or '')
        kind = str(edge.get('kind') or 'reference')
        if src in path_set and dst:
            deps.append({'from': src, 'to': dst, 'kind': kind})
        if dst in path_set and src:
            dependents.append({'from': src, 'to': dst, 'kind': kind})
    return deps[:limit], dependents[:limit]


def _nearest_project_file(repo_map: dict[str, Any], path: str, suffix: str, *, root_dir: str | None = None) -> str | None:
    files = repo_map.get('files') or {}
    normalized = path.replace('\\', '/').strip('/')
    path_parts = normalized.split('/')
    candidates = [
        candidate
        for candidate in files
        if candidate.lower().endswith(suffix.lower())
        and (root_dir is None or candidate == root_dir or candidate.startswith(root_dir.rstrip('/') + '/'))
    ]
    best: tuple[int, str] | None = None
    for candidate in candidates:
        candidate_parts = candidate.replace('\\', '/').strip('/').split('/')
        common = 0
        for left, right in zip(path_parts, candidate_parts):
            if left.lower() != right.lower():
                break
            common += 1
        score = common * 100 - abs(len(candidate_parts) - len(path_parts))
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else None


def _verification_order(repo_map: dict[str, Any], likely_paths: list[str], related_tests: list[dict[str, Any]]) -> list[dict[str, str]]:
    files = repo_map.get('files') or {}
    languages = {str((files.get(path) or {}).get('language') or '') for path in likely_paths}
    commands: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(command: str, reason: str) -> None:
        if command and command not in seen:
            commands.append({'command': command, 'reason': reason})
            seen.add(command)

    for item in related_tests[:6]:
        path = str(item.get('path') or '')
        if not path:
            continue
        suffix = Path(path).suffix.lower()
        if suffix == '.py':
            add(f'python -m pytest {path}', 'targeted related Python test from repo map')
        elif suffix in {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'}:
            pm = str(repo_map.get('package_manager') or 'none')
            if pm != 'none':
                add(f'{pm} test -- {path}', 'targeted related JS/TS test from repo map')
        elif suffix == '.go':
            add(f'go test ./{str(Path(path).parent.as_posix())}', 'targeted related Go test from repo map')
        elif suffix == '.swift':
            add('swift test', 'Swift related test detected; run package tests or project-specific xcodebuild test')
        elif suffix == '.rs':
            stem = Path(path).stem
            if path.startswith('tests/') and stem not in {'test', 'tests'}:
                add(f'cargo test --test {stem}', 'targeted Rust integration test from repo map')
        elif suffix == '.exs':
            add(f'mix test {path}', 'targeted related Elixir test from repo map')
        elif suffix == '.php':
            add(f'vendor/bin/phpunit {path}', 'targeted related PHPUnit test from repo map')
        elif suffix == '.rb':
            if '/spec/' in f'/{path}' or path.startswith('spec/'):
                add(f'bundle exec rspec {path}', 'targeted related RSpec test from repo map')
            else:
                add(f'bin/rails test {path}', 'targeted related Ruby/Rails test from repo map')
        elif suffix in {'.java', '.kt'}:
            if path.startswith('app/src/test/') or path.startswith('app/src/androidTest/'):
                add('./gradlew :app:testDebugUnitTest', 'targeted Android/Kotlin related test from repo map')
        elif suffix == '.cs':
            project = _nearest_project_file(repo_map, path, '.csproj', root_dir='tests') or _nearest_project_file(repo_map, path, '.csproj', root_dir='test')
            add(f'dotnet test {project}' if project else 'dotnet test', 'targeted related .NET/C# test from repo map')
        elif suffix == '.zig':
            add(f'zig test {path}', 'targeted related Zig test from repo map')
        elif suffix == '.hs':
            if 'stack.yaml' in files:
                add('stack test', 'targeted related Haskell test from repo map')
            else:
                add('cabal test', 'targeted related Haskell test from repo map')
    if 'rust' in languages:
        add('cargo check', 'Rust impacted files detected')
        add('cargo test', 'Rust impacted files detected')
    if 'python' in languages:
        add('python -m pytest', 'Python impacted files detected')
    if 'swift' in languages:
        add('swift test', 'Swift impacted files detected')
    if 'go' in languages:
        add('go test ./...', 'Go impacted files detected')
    if 'elixir' in languages:
        add('mix test', 'Elixir impacted files detected')
        add('mix compile', 'Elixir impacted files detected')
    if 'php' in languages:
        add('vendor/bin/phpunit', 'PHP impacted files detected')
    if 'ruby' in languages:
        add('bundle exec rspec', 'Ruby impacted files detected')
    if 'terraform' in languages:
        add('terraform fmt -check', 'Terraform impacted files detected')
        add('terraform validate', 'Terraform impacted files detected')
    if 'dotnet' in languages:
        add('dotnet test', '.NET/C# impacted files detected')
        add('dotnet build', '.NET/C# impacted files detected')
    if 'zig' in languages:
        add('zig build test', 'Zig impacted files detected')
    if 'haskell' in languages:
        if 'stack.yaml' in files:
            add('stack test', 'Haskell impacted files detected')
            add('stack build', 'Haskell impacted files detected')
        else:
            add('cabal test', 'Haskell impacted files detected')
            add('cabal build', 'Haskell impacted files detected')
    if 'jvm' in languages and any(path.startswith('app/src/') for path in likely_paths):
        add('./gradlew :app:testDebugUnitTest', 'Android/Kotlin impacted app module detected')
        add('./gradlew :app:assembleDebug', 'Android/Kotlin impacted app module detected')
    if {'typescript', 'javascript'} & languages:
        pm = str(repo_map.get('package_manager') or 'none')
        if pm != 'none':
            add(f'{pm} test', 'JS/TS impacted files detected')
    return commands[:12]


def _filter_routing_paths(
    raw_prompt: str,
    items: list[dict[str, Any]],
    explicit_paths: set[str],
    *,
    path_key: str = 'path',
    prompt_forbidden_paths: set[str] | None = None,
    include_read_only_manifests: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    strict = _prompt_has_negative_boundary(raw_prompt)
    kept: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for item in items:
        path = str(item.get(path_key) or '')
        safety = classify_path_for_routing(
            path,
            raw_prompt,
            explicit_paths=explicit_paths,
            prompt_forbidden_paths=prompt_forbidden_paths or set(),
        ) if path else {"category": "editable_source_or_support", "reason": "editable_candidate", "editable": True}
        if path and (
            _is_ignore_boundary_path(path)
            or (
                safety["category"] != "editable_source_or_support"
                and (include_read_only_manifests or safety["category"] != "read_only_manifest")
                and not safety.get("editable")
            )
        ) and path not in explicit_paths:
            filtered.append({
                'path': path,
                'reason': safety.get('reason') or 'ignored_reference_generated_boundary',
                'safety_category': safety.get('category'),
                'strict_negative_prompt': strict,
            })
            continue
        kept.append(item)
    return kept, filtered


def _filter_dependency_edges(edges: list[dict[str, str]], explicit_paths: set[str], raw_prompt: str = "", prompt_forbidden_paths: set[str] | None = None) -> tuple[list[dict[str, str]], int]:
    kept: list[dict[str, str]] = []
    removed = 0
    for edge in edges:
        src = str(edge.get('from') or '')
        dst = str(edge.get('to') or '')
        src_restricted = _is_ignore_boundary_path(src) or is_restricted_edit_bucket_path(
            src,
            raw_prompt,
            explicit_paths=explicit_paths,
            prompt_forbidden_paths=prompt_forbidden_paths or set(),
        )
        dst_restricted = _is_ignore_boundary_path(dst) or is_restricted_edit_bucket_path(
            dst,
            raw_prompt,
            explicit_paths=explicit_paths,
            prompt_forbidden_paths=prompt_forbidden_paths or set(),
        )
        if ((src_restricted and src not in explicit_paths) or (dst_restricted and dst not in explicit_paths)):
            removed += 1
            continue
        kept.append(edge)
    return kept, removed


def _resolve_console_script_implementation(ep: dict[str, Any], repo_map: dict[str, Any], *, max_depth: int = 2) -> list[dict[str, Any]]:
    files = repo_map.get('files') or {}
    start = str(ep.get('path') or '')
    symbol = str(ep.get('symbol') or '')
    if not start or start not in files or not symbol:
        return []

    resolved: list[dict[str, Any]] = []
    queue: list[tuple[str, int]] = [(start, 0)]
    seen: set[str] = {start}
    while queue:
        path, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        info = files.get(path) or {}
        for detail in info.get('import_details') or []:
            name = str(detail.get('name') or '')
            asname = str(detail.get('asname') or '')
            if symbol not in {name, asname or name}:
                continue
            for candidate_module in _resolve_relative_python_import(path, detail):
                target = _match_import_to_path(candidate_module, {mod: p for p in files for mod in _module_names_for_path(p)})
                if target and target in files and target not in seen:
                    item = {
                        'path': target,
                        'name': ep.get('name'),
                        'kind': 'console_script_implementation',
                        'source': 'console_script_reexport',
                        'reason': f"{start} re-exports {symbol} from {target}",
                        'facade_path': start,
                        'target': ep.get('target'),
                    }
                    resolved.append(item)
                    seen.add(target)
                    queue.append((target, depth + 1))
    return resolved[:8]



def _normalize_task_token(value: str) -> str:
    value = value.strip().lstrip('-').lower()
    value = re.sub(r'[^a-z0-9]+', '', value)
    return value

def _prompt_command_terms(raw_prompt: str) -> set[str]:
    words = {w.lower() for w in re.findall(r'--?[A-Za-z0-9_-]{2,}|[A-Za-z_][A-Za-z0-9_-]{2,}', raw_prompt)}
    stop = {'change', 'modify', 'update', 'patch', 'safe', 'argument', 'arguments', 'validation', 'option', 'parsing', 'command', 'commands', 'flag', 'flags', 'tests', 'test', 'run', 'present', 'only', 'touch', 'edit'}
    out = set()
    for w in words:
        raw = w.lstrip('-')
        if raw in stop:
            continue
        out.add(raw.replace('-', '_'))
        norm = _normalize_task_token(raw)
        if norm:
            out.add(norm)
    return out


def _add_likely(likely: list[dict[str, Any]], files: dict[str, dict[str, Any]], path: str, *, kind: str, source: str, reason: str, **extra: Any) -> None:
    if path in files:
        likely.append({'path': path, 'kind': kind, 'source': source, 'reason': reason, **extra})


def _expand_likely_with_edges(likely: list[dict[str, Any]], repo_map: dict[str, Any], raw_prompt: str) -> None:
    files = repo_map.get('files') or {}
    edges = repo_map.get('edges') or []
    prompt = raw_prompt.lower()
    cliish = any(term in prompt for term in ['cli', 'argument', 'arguments', 'flag', 'flags', 'command-line', 'command line', 'option', 'options'])
    current = {str(item.get('path')) for item in likely if item.get('path')}
    for edge in edges:
        src = str(edge.get('from') or '')
        dst = str(edge.get('to') or '')
        kind = str(edge.get('kind') or '')
        if src in current and dst in files and dst not in current:
            dst_info = files.get(dst) or {}
            if kind in {'rust_mod', 'js_relative_import'} and (cliish or dst_info.get('language') in {'rust', 'typescript', 'javascript'}):
                likely.append({'path': dst, 'kind': f'{kind}_dependency', 'source': src, 'reason': f'{src} references {dst} via {kind}'})
                current.add(dst)


def _go_command_folder_hints(raw_prompt: str, files: dict[str, dict[str, Any]], likely: list[dict[str, Any]]) -> None:
    terms = _prompt_command_terms(raw_prompt)
    normalized_terms = {_normalize_task_token(t) for t in terms}
    for term in terms:
        folder = term.replace('_', '-')
        for candidate in (f'{term}/{term}.go', f'{folder}/{folder}.go', f'cmd/{term}.go', f'cmd/{term}_test.go', f'cmd/{term}/main.go', f'{term}/main.go'):
            if candidate in files and not candidate.endswith('_test.go'):
                likely.append({'path': candidate, 'kind': 'go_command_file', 'source': 'prompt_command_folder', 'reason': f'prompt mentions Go command `{term}` and repo has {candidate}'})
    for path, info in files.items():
        if info.get('language') != 'go':
            continue
        symbols = set(info.get('functions') or []) | set(info.get('classes') or []) | set(info.get('flag_names') or [])
        path_norm = _normalize_task_token(path)
        symbol_norms = {_normalize_task_token(s) for s in symbols}
        if normalized_terms & symbol_norms or any(t and t in path_norm for t in normalized_terms):
            likely.append({'path': path, 'kind': 'go_cli_flag_file', 'source': 'prompt_flag_symbol_match', 'reason': 'prompt flag/command term matches Go flag/function/path symbol'})


DOMAIN_KEYWORD_HINTS = {
    'repo-map': ['src/premode/repo_map.py', 'tests/test_v250_repo_map.py'],
    'repo map': ['src/premode/repo_map.py', 'tests/test_v250_repo_map.py'],
    'source recovery': ['src/premode/repo_map.py', 'src/premode/compiler.py', 'tests/test_v2615_swift_source_recovery.py'],
    'source candidates': ['src/premode/repo_map.py', 'src/premode/compiler.py'],
    'views and viewmodels': ['src/premode/repo_map.py', 'src/premode/compiler.py'],
    'candidate ranking': ['src/premode/repo_map.py', 'tests/test_v250_repo_map.py'],
    'impact hints': ['src/premode/repo_map.py'],
    'task impact': ['src/premode/repo_map.py'],
    'map output': ['src/premode/repo_map.py', 'src/premode/cli.py'],
    'benchmark expectation': ['src/premode/benchmark.py', 'tests/test_v263_benchmark.py'],
    'benchmark report': ['src/premode/benchmark.py', 'tests/test_v263_benchmark.py'],
    'benchmark summary': ['src/premode/benchmark.py', 'tests/test_v263_benchmark.py'],
    'expectation failures': ['src/premode/benchmark.py', 'tests/test_v263_benchmark.py'],
    'expectation validation': ['src/premode/benchmark.py', 'tests/test_v263_benchmark.py'],
    'context receipt': ['src/premode/compiler.py', 'tests/test_v253_output_hardening.py'],
    'receipt': ['src/premode/compiler.py', 'tests/test_v253_output_hardening.py'],
    'why-included': ['src/premode/compiler.py', 'tests/test_v253_output_hardening.py'],
    'why included': ['src/premode/compiler.py', 'tests/test_v253_output_hardening.py'],
    'packet': ['src/premode/compiler.py', 'src/premode/packet_schema.py'],
    'context packet': ['src/premode/compiler.py'],
    'compile prompt': ['src/premode/compiler.py'],
    'model-facing packet': ['src/premode/compiler.py'],
    'candidate buckets': ['src/premode/compiler.py'],
    'support buckets': ['src/premode/compiler.py'],
    'verification buckets': ['src/premode/compiler.py'],
    'compile output': ['src/premode/compiler.py', 'src/premode/cli.py'],
    'review-patch': ['src/premode/review_patch.py', 'tests/test_v260_review_patch.py'],
    'review patch': ['src/premode/review_patch.py', 'tests/test_v260_review_patch.py'],
    'patch review': ['src/premode/review_patch.py', 'tests/test_v260_review_patch.py'],
    'scope compliance': ['src/premode/review_patch.py'],
    'merge readiness': ['src/premode/review_patch.py'],
    'validation evidence': ['src/premode/review_patch.py'],
    'log parsing': ['src/premode/log_scanner.py'],
    'log scanner': ['src/premode/log_scanner.py'],
    'codex jsonl': ['src/premode/log_scanner.py'],
    'jsonl': ['src/premode/log_scanner.py'],
    'live ledger': ['src/premode/live_ledger.py'],
    'command ledger': ['src/premode/live_ledger.py'],
    'token ledger': ['src/premode/live_ledger.py'],
}

def _domain_keyword_hints(raw_prompt: str, files: dict[str, dict[str, Any]], likely: list[dict[str, Any]]) -> None:
    prompt = raw_prompt.lower()
    for phrase, paths in DOMAIN_KEYWORD_HINTS.items():
        if phrase in prompt:
            for path in paths:
                if path in files:
                    likely.append({'path': path, 'kind': 'semantic_module_alias', 'source': 'semantic_module_alias', 'reason': f'prompt mentions `{phrase}`'})


PACKAGE_METADATA_FILENAMES = {
    'pyproject.toml',
    'setup.py',
    'setup.cfg',
    'package.json',
    'cargo.toml',
    'go.mod',
    'package.swift',
    'pom.xml',
    'composer.json',
    'gemfile',
}


def _package_metadata_prompt(raw_prompt: str) -> bool:
    text = (raw_prompt or "").lower()
    return bool(re.search(r"\b(package|packaging|project)\s+metadata\b|\bmetadata\b[^\n.;]{0,80}\b(package|packaging|project)\b|\bpython\s+package\b", text))


def _prompt_requests_test_edit(raw_prompt: str) -> bool:
    text = re.sub(
        r"\b(?:avoid|do not|don't|dont|without)\b[^\n.;]*",
        " ",
        raw_prompt or "",
        flags=re.IGNORECASE,
    )
    return bool(re.search(
        r"\b(?:add|write|create|update|change|repair|adjust|fix)\b[^\n.;]{0,80}\b(?:tests?|coverage|assertions?|expectations?)\b|\badd\s+coverage\b",
        text,
        re.IGNORECASE,
    ))


def _cli_edit_prompt(raw_prompt: str) -> bool:
    text = re.sub(
        r"\b(?:avoid|do not|don't|dont|without|keeping|keep)\b[^\n.;]*",
        " ",
        raw_prompt or "",
        flags=re.IGNORECASE,
    ).lower()
    return bool(re.search(r"\b(cli|argument|arguments|arg|args|flag|flags|command-line|command line|subcommand|option|options)\b", text))


def _prompt_mentions_benchmark_prompts(raw_prompt: str) -> bool:
    return bool(re.search(r"\bbenchmark[_ -]?prompts(?:\.json)?\b|\bbenchmark\s+examples?\b", raw_prompt or "", re.IGNORECASE))


def _is_benchmark_prompt_file(path: str) -> bool:
    return Path(str(path).replace("\\", "/")).name.lower() == "benchmark_prompts.json"


def _manifest_candidate_rank(path: str, raw_prompt: str) -> int:
    role = classify_path_role(path)
    name = Path(path).name.lower()
    score = 0
    if _is_benchmark_prompt_file(path) and not _prompt_mentions_benchmark_prompts(raw_prompt):
        return -10000
    if name in PACKAGE_METADATA_FILENAMES:
        score += 800
    if role.package_rootness == "repo_root":
        score += 500
    elif role.package_rootness == "package_root":
        score += 140
    elif role.package_rootness == "nested_package_root":
        score += 60
    preferred = {
        "pyproject.toml": 90,
        "package.json": 85,
        "cargo.toml": 80,
        "go.mod": 75,
        "package.swift": 70,
        "pubspec.yaml": 65,
        "setup.cfg": 50,
        "setup.py": 45,
    }
    score += preferred.get(name, 0)
    prompt_norm = _normalize_task_token(raw_prompt or "")
    path_norm = _normalize_task_token(path)
    if any(term in prompt_norm for term in ("workspace", "crate", "example", "sample")) and any(term in path_norm for term in ("packages", "crates", "examples", "samples")):
        score += 160
    return score


def _manifest_candidate_rank_reason(path: str, raw_prompt: str) -> str:
    role = classify_path_role(path)
    if _is_benchmark_prompt_file(path) and not _prompt_mentions_benchmark_prompts(raw_prompt):
        return "benchmark_prompts_excluded_from_package_metadata"
    if role.package_rootness == "repo_root":
        return "root_manifest_preferred_for_package_metadata"
    if role.package_rootness in {"package_root", "nested_package_root"}:
        return "nested_manifest_requires_explicit_package_scope"
    return "manifest_ranked_by_package_metadata_specificity"


def _workflow_candidate_rank(path: str, raw_prompt: str) -> int:
    lower = str(path).replace("\\", "/").lower()
    name = Path(lower).name
    score = 0
    if _is_benchmark_prompt_file(path) and not _prompt_mentions_benchmark_prompts(raw_prompt):
        return -10000
    if lower.startswith((".github/workflows/", "github/workflows/")):
        score += 700
    if lower.startswith("scripts/") and re.search(r"(smoke|test|check|validate|validation|ci)", name):
        score += 640
    if name in {"makefile", "justfile", "noxfile.py", "tox.ini"}:
        score += 520
    if re.search(r"(ci|test|tests|build|lint|check|validation|smoke)", name):
        score += 420
    if re.search(r"(release|publish|deploy|stale|label|triage|issue|backport|changelog|docs?)", name):
        score -= 360
    if re.search(r"\bdocs?\s+workflow\b|\bdocs?\s+(?:deploy|build)\b", raw_prompt or "", re.IGNORECASE) and "doc" in name:
        score += 500
    prompt_words = {_normalize_task_token(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", raw_prompt or "")}
    path_norm = _normalize_task_token(path)
    score += min(180, 45 * sum(1 for word in prompt_words if word and word in path_norm))
    return score


def _workflow_candidate_rank_reason(path: str, raw_prompt: str) -> str:
    score = _workflow_candidate_rank(path, raw_prompt)
    lower = str(path).lower()
    if score < 0:
        return "workflow_demoted_as_release_docs_or_issue_management"
    if re.search(r"(ci|test|tests|build|lint|check|validation|smoke)", lower):
        return "workflow_ranked_by_ci_test_validation_name"
    return "workflow_ranked_by_generic_workflow_adjacency"


def _add_package_metadata_hints(raw_prompt: str, files: dict[str, dict[str, Any]], likely: list[dict[str, Any]], related: list[dict[str, Any]]) -> None:
    if not _package_metadata_prompt(raw_prompt):
        return
    scoped_package_prompt = bool(re.search(r"\b(workspace|crate|example|sample|packages/|crates/)\b", raw_prompt or "", re.IGNORECASE))
    ranked_manifests: list[tuple[int, str]] = []
    for path in sorted(files):
        role = classify_path_role(path)
        if _is_benchmark_prompt_file(path) and not _prompt_mentions_benchmark_prompts(raw_prompt):
            continue
        if Path(path).name.lower() in PACKAGE_METADATA_FILENAMES and not role.is_example:
            if role.package_rootness != "repo_root" and not scoped_package_prompt:
                continue
            ranked_manifests.append((_manifest_candidate_rank(path, raw_prompt), path))
    ranked_manifests.sort(key=lambda item: (-item[0], _path_depth(item[1]), item[1].lower()))
    manifest_limit = 2 if scoped_package_prompt else 1
    for _score, path in ranked_manifests[:manifest_limit]:
        likely.append({
            'path': path,
            'kind': 'package_metadata',
            'source': 'package_metadata_adjacency',
            'reason': 'package_metadata_prompt_selects_manifest',
            'manifest_candidate_rank_reason': _manifest_candidate_rank_reason(path, raw_prompt),
        })
    for path in sorted(files):
        lower = path.lower()
        if lower.startswith(("tests/", "test/")) and ("package_layout" in lower or "metadata_root" in lower):
            related.append({
                'path': path,
                'source': 'package_metadata_adjacency',
                'reason': 'package_metadata_prompt_routes_package_layout_test',
                'related_test_resolution_reason': 'config_to_package_layout_test',
            })
            return
    for path in sorted(files):
        lower = path.lower()
        if lower in {"tests/__init__.py", "test/__init__.py"}:
            related.append({
                'path': path,
                'source': 'package_metadata_adjacency',
                'reason': 'package_metadata_prompt_routes_root_test_anchor',
                'related_test_resolution_reason': 'config_to_root_test_anchor',
            })
            return


def _workflow_prompt(raw_prompt: str) -> bool:
    text = (raw_prompt or "").lower()
    return bool(re.search(r"\b(local\s+)?smoke\s+(?:validation|test|workflow)|\bci-style\b|\bci\s+checks?\b|\bworkflow\b|\blocal\s+validation\b|\bregression guard\b", text))


def _workflow_script_prompt(raw_prompt: str) -> bool:
    text = (raw_prompt or "").lower()
    return bool(re.search(r"\b(local\s+)?smoke\s+(?:validation|test|workflow)|\bci-style\b|\bci\s+checks?\b|\bworkflow\b|\bvalidation\s+script\b|\bregression guard\b", text))


def _add_workflow_hints(raw_prompt: str, files: dict[str, dict[str, Any]], likely: list[dict[str, Any]], related: list[dict[str, Any]]) -> None:
    if not _workflow_prompt(raw_prompt):
        return
    workflow_paths = [
        "scripts/smoke_test.sh",
        ".github/workflows/",
        "Makefile",
        "noxfile.py",
        "tox.ini",
        "justfile",
    ]
    if _workflow_script_prompt(raw_prompt):
        workflow_candidates: list[tuple[int, str]] = []
        for path in sorted(files):
            lower = path.lower()
            script_workflow = (
                lower.startswith("scripts/")
                and re.search(r"(smoke|test|check|validate|validation|ci)", Path(lower).name)
            )
            if _is_benchmark_prompt_file(path) and not _prompt_mentions_benchmark_prompts(raw_prompt):
                continue
            if lower == "scripts/smoke_test.sh" or script_workflow or any(lower == item.lower() for item in workflow_paths if not item.endswith("/")) or lower.startswith(".github/workflows/"):
                workflow_candidates.append((_workflow_candidate_rank(path, raw_prompt), path))
        workflow_candidates.sort(key=lambda item: (-item[0], _path_depth(item[1]), item[1].lower()))
        for _score, path in workflow_candidates[:3]:
            likely.append({
                'path': path,
                'kind': 'workflow_validation',
                'source': 'workflow_adjacency',
                'reason': 'smoke_or_local_validation_workflow_prompt',
                'workflow_candidate_rank_reason': _workflow_candidate_rank_reason(path, raw_prompt),
            })
    for path in sorted(files):
        lower = path.lower()
        if lower.startswith(("tests/", "test/")) and ("local_validation" in lower or "v266" in lower or "smoke" in lower):
            related.append({
                'path': path,
                'source': 'workflow_adjacency',
                'reason': 'workflow_prompt_routes_local_validation_test',
                'related_test_resolution_reason': 'workflow_validation_test',
                'related_test_anchor_confidence': 'high',
            })


def _test_only_prompt(raw_prompt: str) -> bool:
    text = (raw_prompt or "").lower()
    return bool(
        re.search(r"\b(add|write|create)\b[^\n.;]{0,80}\b(?:(?:regression\s+)?tests?|coverage)\b", text)
        and re.search(r"\bwithout\s+(?:changing|touching|editing|modifying)\s+(?:(?:production|runtime)\s+)?(?:code|source)\b", text)
    )


def _generic_candidate_rank(path: str, raw_prompt: str) -> int:
    role = classify_path_role(path)
    score = path_role_rank(path, infer_prompt_intent(raw_prompt))
    prompt_words = {_normalize_task_token(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", raw_prompt or "")}
    path_norm = _normalize_task_token(path)
    score += min(240, 60 * sum(1 for word in prompt_words if word and word in path_norm))
    if role.entrypoint_likelihood == "high":
        score += 260
    if role.is_example:
        score -= 260
    lower = path.lower()
    if any(part in lower for part in ("/fixtures/", "/fixture/", "/profiling/", "/bench/", "/benchmark/", "/scripts/release")):
        score -= 220
    return score


def _test_candidate_rank(path: str, raw_prompt: str) -> int:
    lower = path.lower()
    score = _related_test_prompt_score(path, raw_prompt)
    if lower in {"tests/__init__.py", "test/__init__.py"}:
        score += 380
    if re.search(r"(^|/)(test_[^/]+|[^/]+_test|[^/]+\.(test|spec))\.", lower):
        score += 220
    if _is_docs_fixture_test_path(path):
        score -= 900
    score -= 25 * _path_depth(path)
    return score


def _apply_precision_caps(
    raw_prompt: str,
    likely_edit_files: list[dict[str, Any]],
    files: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    intent = infer_prompt_intent(raw_prompt)
    if not likely_edit_files:
        return likely_edit_files, [], {"precision_cap_applied": False}
    if any(str(item.get("source") or "") == "prompt" or str(item.get("reason") or "").startswith("prompt_mentioned") for item in likely_edit_files):
        return likely_edit_files, [], {
            "precision_cap_applied": False,
            "precision_cap_skipped": "explicit_prompt_path",
        }
    if _prompt_mentions_swift_context(raw_prompt):
        return likely_edit_files, [], {
            "precision_cap_applied": False,
            "precision_cap_skipped": "swift_source_recovery",
        }

    kept: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []

    def demote(item: dict[str, Any], reason: str) -> None:
        moved = dict(item)
        moved["reason"] = reason
        moved["support_projection_reason"] = reason
        moved["demotion_reason"] = reason
        demoted.append(moved)

    if intent.intent == "config":
        scoped = bool(re.search(r"\b(workspace|crate|example|sample|packages/|crates/)\b", raw_prompt or "", re.IGNORECASE))
        manifest_items: list[tuple[int, dict[str, Any]]] = []
        for item in likely_edit_files:
            path = str(item.get("path") or "")
            role = classify_path_role(path)
            if _is_benchmark_prompt_file(path) and not _prompt_mentions_benchmark_prompts(raw_prompt):
                demote({**item, "manifest_candidate_rank_reason": "benchmark_prompts_excluded_from_package_metadata"}, "manifest_precision_demoted_benchmark_prompts")
            elif Path(path).name.lower() in PACKAGE_METADATA_FILENAMES and (role.package_rootness == "repo_root" or scoped):
                manifest_items.append((_manifest_candidate_rank(path, raw_prompt), {**item, "manifest_candidate_rank_reason": _manifest_candidate_rank_reason(path, raw_prompt)}))
            else:
                demote({**item, "manifest_candidate_rank_reason": "support_not_package_manifest"}, "manifest_precision_demoted_non_manifest")
        manifest_items.sort(key=lambda pair: (-pair[0], _path_depth(str(pair[1].get("path") or "")), str(pair[1].get("path") or "").lower()))
        keep_limit = 2 if scoped else 1
        kept = [item for _score, item in manifest_items[:keep_limit]]
        for _score, item in manifest_items[keep_limit:]:
            demote(item, "manifest_precision_cap_demoted_nested_manifest")
    elif intent.intent == "workflow":
        workflow_items: list[tuple[int, dict[str, Any]]] = []
        for item in likely_edit_files:
            path = str(item.get("path") or "")
            role = classify_path_role(path)
            if _is_benchmark_prompt_file(path) and not _prompt_mentions_benchmark_prompts(raw_prompt):
                demote({**item, "workflow_candidate_rank_reason": "benchmark_prompts_excluded_from_workflow"}, "workflow_precision_demoted_benchmark_prompts")
            elif role.is_workflow:
                workflow_items.append((_workflow_candidate_rank(path, raw_prompt), {**item, "workflow_candidate_rank_reason": _workflow_candidate_rank_reason(path, raw_prompt)}))
            else:
                demote({**item, "workflow_candidate_rank_reason": "support_not_workflow"}, "workflow_precision_demoted_non_workflow")
        workflow_items.sort(key=lambda pair: (-pair[0], _path_depth(str(pair[1].get("path") or "")), str(pair[1].get("path") or "").lower()))
        high_confidence_workflows = [pair for pair in workflow_items if pair[0] >= 700]
        selected_workflows = (high_confidence_workflows or workflow_items)[:3]
        selected_ids = {id(item) for _score, item in selected_workflows}
        kept = [item for _score, item in selected_workflows]
        for _score, item in workflow_items:
            if id(item) in selected_ids:
                continue
            demote(item, "workflow_precision_cap_demoted_lower_ranked_workflow")
    elif intent.intent == "test_edit":
        test_items: list[tuple[int, dict[str, Any]]] = []
        for item in likely_edit_files:
            path = str(item.get("path") or "")
            if _is_test_file(path, files.get(path) or {}):
                test_items.append((_test_candidate_rank(path, raw_prompt), item))
            else:
                demote(item, "test_only_precision_demoted_source_support")
        test_items.sort(key=lambda pair: (-pair[0], _path_depth(str(pair[1].get("path") or "")), str(pair[1].get("path") or "").lower()))
        kept = [item for _score, item in test_items[:2]]
        for _score, item in test_items[2:]:
            demote(item, "test_only_precision_cap_demoted_lower_ranked_test")
    elif intent.intent == "docs":
        # Compiler-level docs scoring performs the final README/usage selection.
        kept = likely_edit_files
    elif intent.intent == "runtime":
        if _prompt_mentions_swift_context(raw_prompt):
            kept = likely_edit_files
        else:
            source_items = [(_generic_candidate_rank(str(item.get("path") or ""), raw_prompt), item) for item in likely_edit_files]
            source_items.sort(key=lambda pair: (-pair[0], _path_depth(str(pair[1].get("path") or "")), str(pair[1].get("path") or "").lower()))
            kept = [item for _score, item in source_items[:4]]
            for _score, item in source_items[4:]:
                demote(item, "runtime_precision_cap_demoted_broad_fallback")
    else:
        kept = likely_edit_files

    diagnostics = {
        "precision_cap_applied": bool(demoted),
        "precision_cap_intent": intent.intent,
        "precision_cap_demoted_count": len(demoted),
    }
    return kept, demoted, diagnostics


def _add_test_only_hints(raw_prompt: str, files: dict[str, dict[str, Any]], likely: list[dict[str, Any]], related: list[dict[str, Any]]) -> None:
    if not _test_only_prompt(raw_prompt):
        return
    ranked: list[tuple[int, str]] = []
    for path, info in files.items():
        if not _is_test_file(path, info):
            continue
        if _is_docs_fixture_test_path(path):
            continue
        ranked.append((_test_candidate_rank(path, raw_prompt), path))
    ranked.sort(key=lambda pair: (-pair[0], _path_depth(pair[1]), pair[1].lower()))
    for _score, path in ranked[:1]:
        item = {
            'path': path,
            'kind': 'test_only_candidate',
            'source': 'test_only_adjacency',
            'reason': 'test_only_prompt_selects_regression_test',
        }
        likely.append(item)
        related.append({
            'path': path,
            'source': 'test_only_adjacency',
            'reason': 'test_candidate_mirrored_to_related_tests',
            'related_test_resolution_reason': 'test_only_direct_candidate',
        })


def _swift_source_recovery_hints(raw_prompt: str, files: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not _prompt_is_swift_source_task(raw_prompt):
        return [], {
            'source_recovery_attempted': False,
            'safe_candidate_count': 0,
            'selected_count': 0,
            'why_no_source_candidates': None,
        }
    prompt = raw_prompt.lower()
    prompt_terms = {w.lower() for w in re.findall(r'[A-Za-z][A-Za-z0-9_]{2,}', raw_prompt or '')}
    screen_action_prompt = _prompt_is_swift_screen_action_task(raw_prompt)
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    safe_candidate_count = 0
    for path, info in files.items():
        if not _is_swift_source_recovery_candidate(path, info):
            continue
        safe_candidate_count += 1
        lower = path.lower()
        score = 100
        if any(hint in f'/{lower}' for hint in SWIFT_SOURCE_PATH_HINTS):
            score += 220
        if any(term in lower for term in ('tutorial', 'overlay', 'state', 'shell', 'navigation', 'session')):
            score += 220
        if lower.endswith('view.swift') or lower.endswith('viewmodel.swift') or 'viewmodel' in lower:
            score += 140
        basename = Path(lower).stem
        normalized_basename = _normalize_task_token(basename)
        normalized_path = _normalize_task_token(path)
        if any(_normalize_task_token(term) in normalized_path for term in prompt_terms):
            score += 120
        if screen_action_prompt:
            matched_path_terms = [
                term for term in prompt_terms
                if term not in {'screen', 'screens', 'surface', 'view', 'views', 'clear', 'clearer', 'make', 'want'}
                and _normalize_task_token(term) in normalized_path
            ]
            if matched_path_terms:
                score += min(360, 90 * len(set(matched_path_terms)))
            if any(term in lower for term in ('today', 'plan', 'task', 'todo', 'priority', 'next', 'action')):
                score += 320
            if ('/views/' in lower or lower.endswith('view.swift')) and any(term in lower for term in ('today', 'plan', 'homestead', 'dashboard', 'screen')):
                score += 260
            if '/viewmodels/' in lower and any(term in lower for term in ('today', 'plan', 'next', 'action', 'task')):
                score += 300
            if any(term in lower for term in ('minigame', 'engine', 'debug', 'devtools', 'frontierrisk', 'riskresolver', 'project.pbxproj', 'assets.xcassets')):
                score -= 420
        if any(normalized_basename == f'{_normalize_task_token(term)}view' for term in prompt_terms):
            score += 360
        if 'ui' in prompt and any(term in lower for term in ('view', 'style', 'shell', 'menu', 'bar')):
            score += 120
        if 'tutorial' in prompt and any(term in lower for term in ('tutorial', 'overlay', 'guidance', 'onboarding')):
            score += 200
        if _prompt_is_swiftui_tutorial_scope_task(raw_prompt):
            scope_score = _swiftui_tutorial_scope_score(path)
            if scope_score >= 350:
                score += 600 + scope_score
            else:
                score -= 500
        if basename.endswith('tests'):
            score -= 80
        candidates.append((score, path, info))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected: list[dict[str, Any]] = []
    for score, path, info in candidates[:6]:
        selected.append({
            'path': path,
            'kind': 'swift_source_recovery',
            'source': 'swift_source_recovery',
            'reason': 'Swift/iOS source prompt matched safe Swift source path',
            'source_recovery_score': score,
            'language': info.get('language'),
        })
    diagnostic = {
        'source_recovery_attempted': True,
        'safe_candidate_count': safe_candidate_count,
        'recovered_source_candidates': [item['path'] for item in selected],
        'selected_count': len(selected),
        'why_no_source_candidates': None if selected else (
            'no safe Swift source files survived planning/art/assets/build/dependency filters'
            if safe_candidate_count == 0
            else 'safe Swift source candidates were present but below selection threshold'
        ),
    }
    return selected, diagnostic

def task_impact_hints(raw_prompt: str, repo_map: dict[str, Any], *, prompt_forbidden_paths: set[str] | None = None) -> dict[str, Any]:
    prompt = raw_prompt.lower()
    entrypoints = repo_map.get('entrypoints') or []
    files = repo_map.get('files') or {}
    likely: list[dict[str, Any]] = []
    prompt_sources, prompt_tests = _prompt_mentioned_repo_paths(raw_prompt, files)
    repo_root_value = repo_map.get('repo_root')
    repo_root = Path(str(repo_root_value)) if repo_root_value else None
    prompt_existing_paths = _prompt_mentioned_existing_paths(raw_prompt, repo_root, files)
    explicit_paths = set(prompt_sources) | set(prompt_tests)
    explicit_paths.update(prompt_existing_paths)
    forbidden_paths = {str(p).strip("/") for p in (prompt_forbidden_paths or set()) if p}
    forbidden_paths.update(_prompt_forbidden_repo_paths(raw_prompt, files, repo_root))
    related_hints: list[dict[str, Any]] = []

    for path in prompt_sources:
        info = files.get(path) or {}
        suffix = Path(path).suffix.lower()
        likely.append({
            'path': path,
            'kind': 'prompt_mentioned_source_file' if suffix in SOURCE_EXTENSIONS else 'prompt_mentioned_file',
            'source': 'prompt',
            'reason': 'prompt_mentioned_source_file' if suffix in SOURCE_EXTENSIONS else 'prompt_mentioned_file',
        })
    for path in prompt_existing_paths:
        suffix = Path(path).suffix.lower()
        likely.append({
            'path': path,
            'kind': 'prompt_mentioned_source_file' if suffix in SOURCE_EXTENSIONS else 'prompt_mentioned_file',
            'source': 'prompt',
            'reason': 'prompt_mentioned_existing_file',
        })

    prompt_is_cli = _cli_edit_prompt(raw_prompt)
    if prompt_is_cli:
        for ep in entrypoints:
            source = str(ep.get('source', '')).lower()
            kind = str(ep.get('kind', '')).lower()
            if kind in {'binary', 'cli_binary', 'workspace_binary_candidate', 'console_script'} or 'bin' in source or 'script' in kind:
                likely.append({**ep, 'reason': 'prompt mentions CLI/argument handling and manifest identifies this entrypoint'})
                if kind == 'console_script':
                    likely.extend(_resolve_console_script_implementation(ep, repo_map))
        _go_command_folder_hints(raw_prompt, files, likely)

    _domain_keyword_hints(raw_prompt, files, likely)
    _add_package_metadata_hints(raw_prompt, files, likely, related_hints)
    _add_workflow_hints(raw_prompt, files, likely, related_hints)
    _add_test_only_hints(raw_prompt, files, likely, related_hints)
    source_recovery_hints, source_recovery_diagnostics = _swift_source_recovery_hints(raw_prompt, files)
    likely.extend(source_recovery_hints)
    pre_role_likely_count = len(likely)
    role_likely, role_related, role_diagnostics = _role_model_hints(raw_prompt, files)
    role_intent = (role_diagnostics.get('prompt_intent') or {}).get('intent')
    pre_role_source_like = any(
        classify_path_role(str(item.get('path') or '')).role == 'source'
        for item in likely
        if item.get('path')
    )
    suppress_role_likely = pre_role_likely_count and role_intent in {'config', 'workflow', 'test_edit'}
    suppress_role_likely = suppress_role_likely or (
        pre_role_likely_count and role_intent == 'runtime' and pre_role_source_like
    )
    if suppress_role_likely:
        role_diagnostics['role_model_suppressed_by_specific_hints'] = len(role_likely)
    else:
        likely.extend(role_likely)
    related_hints.extend(role_related)

    # Universal native-engine fallback: SCons/CMake repos often have sparse
    # import graphs, so route platform/option prompts to the engine platform
    # detector or nearby C/C++ source instead of passing detection-only.
    native_markers = any(Path(path).name in {"SConstruct", "SCsub", "CMakeLists.txt", "meson.build"} for path in files)
    if native_markers and any(term in prompt for term in ["platform", "option", "options", "engine", "scons", "build option"]):
        for candidate in ("platform/detect.py", "platform/detect.cpp", "platform/os.cpp", "main/main.cpp", "core/object.cpp"):
            if candidate in files:
                likely.append({"path": candidate, "kind": "native_engine_hint", "source": "native_engine_layout", "reason": "prompt mentions native engine/platform option handling"})
                break

    _expand_likely_with_edges(likely, repo_map, raw_prompt)

    # If prompt names a symbol that appears in the repo map, add the containing file
    # as a weak impact hint. This remains a hint only; compile still requires stronger
    # evidence before full-text inclusion.
    words = {w for w in re.findall(r'[A-Za-z_][A-Za-z0-9_]{2,}', raw_prompt)}
    for path, info in files.items():
        symbols = set((info.get('functions') or []) + (info.get('classes') or []) + (info.get('methods') or []))
        if words & symbols:
            likely.append({'path': path, 'kind': 'symbol_match', 'source': 'repo_map symbols', 'reason': 'prompt mentions symbol present in repo map'})

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in likely:
        path = item.get('path')
        if path and (path in files or path in explicit_paths) and path not in seen:
            info = files.get(path) or {}
            out.append({
                **item,
                'language': info.get('language'),
                'related_tests_count': len(info.get('related_tests') or []),
                'direct_dependency_count': sum(1 for e in repo_map.get('edges') or [] if e.get('from') == path),
                'direct_dependent_count': len(info.get('referenced_by') or []),
            })
            seen.add(path)
    filtered_likely: list[dict[str, Any]]
    filtered_related: list[dict[str, Any]]
    filtered_likely, removed_likely = _filter_routing_paths(raw_prompt, out, explicit_paths, prompt_forbidden_paths=forbidden_paths)
    asset_manifest_filtered_count = 0
    if _prompt_excludes_in_repo_planning_art(raw_prompt) or _prompt_is_swift_source_task(raw_prompt):
        kept_likely: list[dict[str, Any]] = []
        removed_planning_art: list[dict[str, Any]] = []
        docs_downranked_count = 0
        for item in filtered_likely:
            path = str(item.get('path') or '')
            if path and (_is_in_repo_planning_art_path(path) or _is_prompt_excluded_docs_path(path, raw_prompt)) and path not in explicit_paths:
                if _is_art_source_manifest_path(path):
                    asset_manifest_filtered_count += 1
                if _is_prompt_excluded_docs_path(path, raw_prompt):
                    docs_downranked_count += 1
                removed_planning_art.append({
                    'path': path,
                    'reason': 'asset_manifest_boundary' if _is_art_source_manifest_path(path) else ('prompt_excluded_docs_boundary' if _is_prompt_excluded_docs_path(path, raw_prompt) else 'in_repo_planning_art_boundary'),
                    'strict_negative_prompt': _prompt_excludes_in_repo_planning_art(raw_prompt),
                })
            else:
                kept_likely.append(item)
        filtered_likely = kept_likely
        removed_likely.extend(removed_planning_art)
    else:
        docs_downranked_count = 0
    prompt_forbidden_files: list[dict[str, Any]] = []
    read_only_support_files: list[dict[str, Any]] = []
    likely_edit_files: list[dict[str, Any]] = []
    swiftui_scope_downranked_count = 0
    test_only_prompt = _test_only_prompt(raw_prompt)
    for item in filtered_likely:
        path = str(item.get('path') or '')
        suffix = Path(path).suffix.lower()
        safety = classify_path_for_routing(path, raw_prompt, explicit_paths=explicit_paths, prompt_forbidden_paths=forbidden_paths)
        if path and _path_matches_any(path, forbidden_paths):
            prompt_forbidden_files.append({**item, 'reason': 'prompt_forbidden_read_only'})
        elif safety.get('category') == 'read_only_manifest':
            read_only_support_files.append({**item, 'reason': safety.get('reason') or 'read_only_manifest_boundary'})
        elif safety.get('category') != 'editable_source_or_support' and not safety.get('editable'):
            prompt_forbidden_files.append({**item, 'reason': safety.get('reason') or 'restricted_routing_boundary'})
        elif (
            (item.get('kind') == 'workflow_validation' or item.get('kind') == 'role_model_workflow')
            and suffix in {'.sh', '.bash', '.zsh'}
        ):
            likely_edit_files.append(item)
        elif _is_test_file(path, files.get(path) or {}) and not (test_only_prompt or _prompt_requests_test_edit(raw_prompt)) and path not in explicit_paths:
            related_hints.append({**item, 'reason': 'test_candidate_projected_to_related_tests'})
            read_only_support_files.append({**item, 'reason': 'test_support_related_projection'})
        elif test_only_prompt and not _is_test_file(path, files.get(path) or {}) and suffix in SOURCE_EXTENSIONS:
            read_only_support_files.append({**item, 'reason': 'test_only_prompt_source_support'})
        elif suffix not in SOURCE_EXTENSIONS | CONFIG_EXTENSIONS:
            read_only_support_files.append({**item, 'reason': item.get('reason') or 'read_only_support_file'})
        elif (
            _prompt_is_swiftui_tutorial_scope_task(raw_prompt)
            and suffix == '.swift'
            and _swiftui_tutorial_scope_score(path) < 350
            and path not in explicit_paths
        ):
            swiftui_scope_downranked_count += 1
            read_only_support_files.append({**item, 'reason': 'swiftui_tutorial_scope_downranked'})
        else:
            likely_edit_files.append(item)
    precision_kept, precision_demotions, precision_cap_diagnostics = _apply_precision_caps(raw_prompt, likely_edit_files, files)
    if precision_demotions:
        likely_edit_files = precision_kept
        read_only_support_files.extend(precision_demotions)
    filtered_likely_paths = [str(item.get('path')) for item in likely_edit_files if item.get('path')]
    direct_dependencies, direct_dependents = _dependency_slices(repo_map, filtered_likely_paths)
    related_tests = _related_tests_for_paths(repo_map, filtered_likely_paths, explicit_tests=prompt_tests)
    related_seen = {str(item.get('path') or '') for item in related_tests}
    for item in related_hints:
        path = str(item.get('path') or '')
        if (
            related_tests
            and item.get('source') == 'cross_ecosystem_role_model'
            and item.get('reason') == f"prompt intent `{infer_prompt_intent(raw_prompt).intent}` requested verification role"
        ):
            continue
        if path and path in files and path not in related_seen:
            related_tests.append(item)
            related_seen.add(path)
    filtered_related, removed_related = _filter_routing_paths(
        raw_prompt,
        related_tests,
        explicit_paths,
        prompt_forbidden_paths=forbidden_paths,
        include_read_only_manifests=True,
    )
    if _prompt_excludes_in_repo_planning_art(raw_prompt) or _prompt_is_swift_source_task(raw_prompt):
        kept_related: list[dict[str, Any]] = []
        removed_planning_related: list[dict[str, Any]] = []
        for item in filtered_related:
            path = str(item.get('path') or '')
            if path and (_is_in_repo_planning_art_path(path) or _is_prompt_excluded_docs_path(path, raw_prompt)) and path not in explicit_paths:
                if _is_art_source_manifest_path(path):
                    asset_manifest_filtered_count += 1
                if _is_prompt_excluded_docs_path(path, raw_prompt):
                    docs_downranked_count += 1
                removed_planning_related.append({
                    'path': path,
                    'reason': 'asset_manifest_boundary' if _is_art_source_manifest_path(path) else ('prompt_excluded_docs_boundary' if _is_prompt_excluded_docs_path(path, raw_prompt) else 'in_repo_planning_art_boundary'),
                    'strict_negative_prompt': _prompt_excludes_in_repo_planning_art(raw_prompt),
                })
            else:
                kept_related.append(item)
        filtered_related = kept_related
        removed_related.extend(removed_planning_related)
    kept_related: list[dict[str, Any]] = []
    seen_forbidden = {str(item.get('path') or '') for item in prompt_forbidden_files}
    for item in filtered_related:
        path = str(item.get('path') or '')
        if path and _path_matches_any(path, forbidden_paths):
            if path not in seen_forbidden:
                prompt_forbidden_files.append({**item, 'reason': 'prompt_forbidden_read_only'})
                seen_forbidden.add(path)
        else:
            kept_related.append(item)
    filtered_related = kept_related
    filtered_related = _rank_related_tests(repo_map, raw_prompt, filtered_likely_paths, filtered_related)
    direct_dependencies, removed_deps = _filter_dependency_edges(direct_dependencies, explicit_paths, raw_prompt, forbidden_paths)
    direct_dependents, removed_dependents = _filter_dependency_edges(direct_dependents, explicit_paths, raw_prompt, forbidden_paths)
    filtered_reasons: dict[str, int] = {}
    for item in removed_likely + removed_related:
        reason = str(item.get('reason') or 'unknown')
        filtered_reasons[reason] = filtered_reasons.get(reason, 0) + 1
    generated_filtered_count = sum(
        1
        for item in removed_likely + removed_related
        if str(item.get('safety_category') or '') == 'generated_or_build_output'
    )
    read_only_manifest_filtered_count = sum(
        1
        for item in removed_likely + removed_related
        if str(item.get('safety_category') or '') == 'read_only_manifest'
    )
    diagnostics = {
        'ignored_boundary_filter_active': bool(removed_likely or removed_related or removed_deps or removed_dependents or _prompt_has_negative_boundary(raw_prompt)),
        'negative_boundary_prompt': _prompt_has_negative_boundary(raw_prompt),
        'prompt_forbidden_count': len(prompt_forbidden_files),
        'read_only_support_count': len(read_only_support_files),
        'filtered_count': len(removed_likely) + len(removed_related) + removed_deps + removed_dependents,
        'filtered_reasons': filtered_reasons,
        'docs_downranked_count': docs_downranked_count,
        'asset_manifest_filtered_count': asset_manifest_filtered_count,
        'generated_filtered_count': generated_filtered_count,
        'read_only_manifest_filtered_count': read_only_manifest_filtered_count,
        'swiftui_scope_tightened': bool(swiftui_scope_downranked_count),
        'swiftui_scope_downranked_count': swiftui_scope_downranked_count,
        'removed_likely_count': len(removed_likely),
        'removed_related_test_count': len(removed_related),
        'removed_dependency_edge_count': removed_deps,
        'removed_dependent_edge_count': removed_dependents,
        'removed_sample': (removed_likely + removed_related)[:5],
        'policy': 'Ignored/reference/generated paths are excluded from routing unless explicitly prompt-mentioned.',
    }
    diagnostics.update(precision_cap_diagnostics)
    diagnostics['role_model'] = role_diagnostics
    diagnostics.update(source_recovery_diagnostics)
    if source_recovery_diagnostics.get('source_recovery_attempted') and not likely_edit_files:
        diagnostics['why_no_source_candidates'] = diagnostics.get('why_no_source_candidates') or 'no editable source candidates remained after filtering'
    return {
        'likely_edit_files': likely_edit_files[:24],
        'read_only_support_files': read_only_support_files[:24],
        'prompt_forbidden_files': prompt_forbidden_files[:24],
        'likely_files': likely_edit_files[:24],
        'direct_dependencies': direct_dependencies,
        'direct_dependents': direct_dependents,
        'related_tests': filtered_related,
        'verification_order': _verification_order(repo_map, filtered_likely_paths, filtered_related),
        'entrypoint_count': len(entrypoints),
        'mapped_file_count': repo_map.get('file_count'),
        'edge_count': repo_map.get('edge_count'),
        'hint_source': 'deterministic_repo_map',
        'full_text_guardrail': 'repo-map relevance alone does not promote files to full text',
        'omitted_impact_detail_count': max(0, len(likely) - len(likely_edit_files[:24])),
        'routing_filter_diagnostics': diagnostics,
    }


def build_repo_map(repo_root: Path, entries: list[dict[str, Any]] | None = None, profile_name: str | None = None, *, write: bool = False, out_path: Path | None = None) -> dict[str, Any]:
    caps = resolve_profile(profile_name, None)
    if entries is None:
        idx = load_index(repo_root) or index_project(repo_root, profile_name)
        entries = list(idx.get('entries', []))
    ignore = IgnoreMatcher.from_repo(repo_root)
    all_paths = {str(e.get('path')) for e in entries if e.get('path')}
    files: dict[str, dict[str, Any]] = {}

    for entry in sorted(entries, key=lambda e: str(e.get('path', ''))):
        rel = str(entry.get('path') or '')
        if not rel:
            continue
        abs_path = repo_root / rel
        if not abs_path.exists() or not abs_path.is_file():
            continue
        suffix = Path(rel).suffix.lower()
        language = _language_for_path(rel)
        info: dict[str, Any] = {
            'language': language,
            'kind': entry.get('kind'),
            'bytes': int(entry.get('bytes', 0) or abs_path.stat().st_size),
            'role_model': classify_path_role(rel).to_dict(),
            'sha256': _file_sha256(abs_path),
            'imports': [],
            'import_details': [],
            'classes': [],
            'functions': [],
            'methods': [],
            'test_functions': [],
            'related_tests': [],
            'referenced_by': [],
            'risk_notes': [],
        }
        should_read = suffix in SOURCE_EXTENSIONS | CONFIG_EXTENSIONS or language == 'markdown'
        if should_read:
            result = safe_read(repo_root, rel, caps, ignore, max_bytes=min(300000, max(65536, caps.max_file_bytes)), purpose='repo_map')
            if result.allowed:
                symbols = _symbols_for(rel, result.content)
                for key, value in symbols.items():
                    info[key] = value
            else:
                info['risk_notes'].append(f'summary_read_skipped: {result.reason}')
        info['related_tests'] = _related_tests_for(rel, all_paths)
        files[rel] = info

    module_index: dict[str, str] = {}
    for path in files:
        if Path(path).suffix.lower() in {'.py', '.rs', '.ts', '.tsx', '.js', '.jsx', '.swift', '.go'}:
            for mod in _module_names_for_path(path):
                module_index.setdefault(mod, path)

    edges: list[dict[str, str]] = []
    for path, info in files.items():
        language = str(info.get('language') or '')
        import_details = info.get('import_details') or []
        if import_details:
            for detail in import_details:
                target = _resolve_import_detail_to_path(path, detail, module_index)
                if target and target != path:
                    edges.append({'from': path, 'to': target, 'kind': 'import'})
                    files[target].setdefault('referenced_by', []).append(path)
        for imp in info.get('imports') or []:
            target = None
            if language in {'typescript', 'javascript'}:
                target = _resolve_relative_js_import(path, str(imp), files)
                kind = 'js_relative_import'
            else:
                target = _match_import_to_path(str(imp), module_index)
                kind = 'import'
            if target and target != path:
                edges.append({'from': path, 'to': target, 'kind': kind})
                files[target].setdefault('referenced_by', []).append(path)
        if language == 'rust':
            for module in info.get('modules') or []:
                target = _resolve_rust_module_path(path, str(module), files)
                if target and target != path:
                    edges.append({'from': path, 'to': target, 'kind': 'rust_mod'})
                    files[target].setdefault('referenced_by', []).append(path)
    edge_seen: set[tuple[str, str, str]] = set()
    deduped_edges: list[dict[str, str]] = []
    for edge in edges:
        key = (str(edge.get('from') or ''), str(edge.get('to') or ''), str(edge.get('kind') or ''))
        if key in edge_seen:
            continue
        deduped_edges.append(edge)
        edge_seen.add(key)
    edges = deduped_edges
    for info in files.values():
        info['referenced_by'] = sorted(set(info.get('referenced_by') or []))[:80]

    entrypoints = discover_entrypoints(repo_root, all_paths)
    package_manager = detect_package_manager(repo_root, all_paths)
    stable = {
        'schema_version': 1,
        'root': '.',
        'files': files,
        'edges': sorted(edges, key=lambda e: (e['from'], e['to'], e['kind']))[:5000],
        'entrypoints': entrypoints,
        'package_manager': package_manager,
    }
    repo_map_sha256 = _sha256_text(_safe_json(stable))
    result = {
        'schema_version': 1,
        'root': '.',
        'repo_root': str(repo_root.resolve()),
        'generated_at': timestamp_iso(),
        'repo_map_sha256': repo_map_sha256,
        'file_count': len(files),
        'edge_count': len(stable['edges']),
        'entrypoint_count': len(entrypoints),
        'files': files,
        'edges': stable['edges'],
        'entrypoints': entrypoints,
        'package_manager': package_manager,
        'content_policy': 'no file contents are stored in repo_map output',
    }
    if write or out_path:
        dest = out_path or premode_dir(repo_root) / 'out' / 'repo_map.json'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        result['output_path'] = str(dest)
    return result


def _notable_repo_map_files(repo_map: dict[str, Any]) -> list[dict[str, Any]]:
    files = repo_map.get('files') or {}
    notable: list[dict[str, Any]] = []
    for path, info in sorted(files.items()):
        if info.get('functions') or info.get('classes') or info.get('test_functions') or info.get('related_tests'):
            notable.append({
                'path': path,
                'language': info.get('language'),
                'classes': (info.get('classes') or [])[:8],
                'functions': (info.get('functions') or [])[:12],
                'test_functions': (info.get('test_functions') or [])[:8],
                'related_tests': (info.get('related_tests') or [])[:8],
                'referenced_by_count': len(info.get('referenced_by') or []),
            })
    return notable


def compact_repo_map_summary(
    repo_map: dict[str, Any],
    *,
    profile_name: str = 'standard',
    impact_map: dict[str, Any] | None = None,
    max_files: int | None = None,
) -> dict[str, Any]:
    """Return a packet-safe repo-map summary.

    The full repo map is useful as an artifact, but compiled packets must keep
    metadata overhead bounded. Lite mode intentionally omits broad symbol lists
    and includes only prompt-relevant impact hints.
    """
    impact_map = impact_map or {}
    likely_paths = [str(item.get('path')) for item in impact_map.get('likely_files') or [] if item.get('path')]
    likely_set = set(likely_paths)
    entrypoints = repo_map.get('entrypoints') or []
    if likely_set:
        relevant_entrypoints = [ep for ep in entrypoints if ep.get('path') in likely_set]
    else:
        relevant_entrypoints = list(entrypoints)

    related_tests = list(impact_map.get('related_tests') or [])
    notable = _notable_repo_map_files(repo_map)
    base: dict[str, Any] = {
        'schema_version': repo_map.get('schema_version'),
        'repo_map_sha256': repo_map.get('repo_map_sha256'),
        'mapped_file_count': repo_map.get('file_count'),
        'edge_count': repo_map.get('edge_count'),
        'entrypoint_count': repo_map.get('entrypoint_count'),
        'package_manager': repo_map.get('package_manager'),
        'entrypoints': relevant_entrypoints[:6 if profile_name == 'lite' else 12 if profile_name == 'standard' else 24],
        'likely_files': (impact_map.get('likely_files') or [])[:8 if profile_name == 'lite' else 16 if profile_name == 'standard' else 24],
        'related_tests': related_tests[:8 if profile_name == 'lite' else 16 if profile_name == 'standard' else 32],
        'content_policy': repo_map.get('content_policy'),
        'summary_profile': profile_name,
    }

    if profile_name == 'lite':
        base.update({
            'omitted_repo_map_detail_count': len(notable),
            'detail_policy': 'lite omits broad notable_files and symbol arrays by default; use premode map --json for full repo-map artifact',
        })
        return base

    cap = max_files if max_files is not None else (8 if profile_name == 'standard' else 18)
    prioritized = sorted(notable, key=lambda item: (0 if item.get('path') in likely_set else 1, str(item.get('path'))))
    base['notable_files'] = prioritized[:cap]
    base['omitted_repo_map_detail_count'] = max(0, len(notable) - len(base['notable_files']))
    return base

def repo_map_language_counts(repo_map: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for info in (repo_map.get('files') or {}).values():
        language = str((info or {}).get('language') or 'unknown')
        counts[language] = counts.get(language, 0) + 1
    return dict(sorted(counts.items()))


def summarize_repo_map(repo_map: dict[str, Any]) -> dict[str, Any]:
    """Return a compact machine-readable repo-map receipt.

    This is intentionally safe for stdout on large repositories and never
    includes per-file symbol arrays or file contents.
    """
    return {
        'schema_version': repo_map.get('schema_version'),
        'root': repo_map.get('root', '.'),
        'repo_map_sha256': repo_map.get('repo_map_sha256'),
        'file_count': repo_map.get('file_count'),
        'edge_count': repo_map.get('edge_count'),
        'entrypoint_count': repo_map.get('entrypoint_count'),
        'package_manager': repo_map.get('package_manager'),
        'languages': repo_map_language_counts(repo_map),
        'entrypoints': (repo_map.get('entrypoints') or [])[:12],
        'content_policy': repo_map.get('content_policy'),
        'output_path': repo_map.get('output_path'),
        'summary_mode': 'summary_json',
    }


def limit_repo_map_files(repo_map: dict[str, Any], max_files: int | None) -> dict[str, Any]:
    """Return a full-ish repo map with the files map capped for stdout safety."""
    if not max_files or max_files <= 0:
        return repo_map
    files = repo_map.get('files') or {}
    sorted_paths = sorted(files)[:max_files]
    kept = set(sorted_paths)
    limited = dict(repo_map)
    limited['files'] = {path: files[path] for path in sorted_paths}
    limited['edges'] = [e for e in (repo_map.get('edges') or []) if e.get('from') in kept and e.get('to') in kept]
    limited['included_file_count'] = len(sorted_paths)
    limited['omitted_file_count'] = max(0, len(files) - len(sorted_paths))
    limited['edge_count'] = len(limited['edges'])
    limited['detail_policy'] = f'files capped to max_files={max_files}; use --out for full repo-map artifact'
    return limited


def estimate_repo_map_json_bytes(repo_map: dict[str, Any]) -> int:
    return len(json.dumps(repo_map, sort_keys=True, ensure_ascii=False).encode('utf-8', errors='replace'))
