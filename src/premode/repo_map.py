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
from .safe_reader import safe_read
from .timeutil import timestamp_iso

SOURCE_EXTENSIONS = {'.py', '.swift', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.rs', '.go', '.java', '.kt', '.c', '.cpp', '.h', '.hpp'}
CONFIG_EXTENSIONS = {'.json', '.toml', '.yaml', '.yml', '.plist'}
IGNORE_BOUNDARY_SEGMENTS = {
    '_external_references',
    'node_modules',
    'vendor',
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
    '_evidence',
    '_integration_staging',
    '_run_captures',
    'generated',
    'artifacts',
    'proof',
    'proofs',
    'state',
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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()


def _safe_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _is_ignore_boundary_path(path: str) -> bool:
    parts = [p.lower() for p in str(path).replace('\\', '/').strip('/').split('/') if p]
    return bool(set(parts) & IGNORE_BOUNDARY_SEGMENTS)


def _prompt_has_negative_boundary(raw_prompt: str) -> bool:
    prompt = raw_prompt.lower()
    return any(term in prompt for term in NEGATIVE_BOUNDARY_TERMS)


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
    )


def _source_test_name_candidates(path: str) -> set[str]:
    p = path.replace('\\', '/').strip('/')
    stem = Path(p).stem
    parent = Path(p).parent.name
    c = {
        f'test_{stem}', f'{stem}_test', f'test_{parent}', f'{parent}_test',
        f'{stem}tests', f'{parent}tests',
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
    return sorted(c for c in candidates if c in all_paths)[:40]


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
            out.append({'path': test_path, 'source': 'prompt', 'reason': 'prompt_mentioned_test_file'})
            seen.add(test_path)

    for path in paths:
        info = files.get(path) or {}
        for test_path in info.get('related_tests') or []:
            if test_path not in seen and test_path in files:
                out.append({'path': test_path, 'source': path, 'reason': 'repo_map related_tests'})
                seen.add(test_path)
        for candidate, candidate_info in files.items():
            if candidate in seen or not _is_test_file(candidate, candidate_info):
                continue
            if candidate in (info.get('referenced_by') or []):
                out.append({'path': candidate, 'source': path, 'reason': 'test imports impacted source'})
                seen.add(candidate)
                continue
            if _test_matches_source_path(candidate, path):
                out.append({'path': candidate, 'source': path, 'reason': 'test path matches impacted source name'})
                seen.add(candidate)
    return out[:40]


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
    if 'rust' in languages:
        add('cargo check', 'Rust impacted files detected')
        add('cargo test', 'Rust impacted files detected')
    if 'python' in languages:
        add('python -m pytest', 'Python impacted files detected')
    if 'swift' in languages:
        add('swift test', 'Swift impacted files detected')
    if 'go' in languages:
        add('go test ./...', 'Go impacted files detected')
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    strict = _prompt_has_negative_boundary(raw_prompt)
    kept: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for item in items:
        path = str(item.get(path_key) or '')
        if path and _is_ignore_boundary_path(path) and path not in explicit_paths:
            filtered.append({
                'path': path,
                'reason': 'ignored_reference_generated_boundary',
                'strict_negative_prompt': strict,
            })
            continue
        kept.append(item)
    return kept, filtered


def _filter_dependency_edges(edges: list[dict[str, str]], explicit_paths: set[str]) -> tuple[list[dict[str, str]], int]:
    kept: list[dict[str, str]] = []
    removed = 0
    for edge in edges:
        src = str(edge.get('from') or '')
        dst = str(edge.get('to') or '')
        if ((_is_ignore_boundary_path(src) and src not in explicit_paths) or (_is_ignore_boundary_path(dst) and dst not in explicit_paths)):
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
    'map output': ['src/premode/repo_map.py', 'src/premode/cli.py'],
    'context receipt': ['src/premode/compiler.py', 'tests/test_v253_output_hardening.py'],
    'receipt': ['src/premode/compiler.py', 'tests/test_v253_output_hardening.py'],
    'why-included': ['src/premode/compiler.py', 'tests/test_v253_output_hardening.py'],
    'why included': ['src/premode/compiler.py', 'tests/test_v253_output_hardening.py'],
    'packet': ['src/premode/compiler.py', 'src/premode/packet_schema.py'],
    'compile output': ['src/premode/compiler.py', 'src/premode/cli.py'],
}

def _domain_keyword_hints(raw_prompt: str, files: dict[str, dict[str, Any]], likely: list[dict[str, Any]]) -> None:
    prompt = raw_prompt.lower()
    for phrase, paths in DOMAIN_KEYWORD_HINTS.items():
        if phrase in prompt:
            for path in paths:
                if path in files:
                    likely.append({'path': path, 'kind': 'domain_keyword_hint', 'source': 'domain_keyword_hints', 'reason': f'prompt mentions `{phrase}`'})

def task_impact_hints(raw_prompt: str, repo_map: dict[str, Any]) -> dict[str, Any]:
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

    prompt_is_cli = any(term in prompt for term in ['cli', 'argument', 'arguments', 'arg ', 'args', 'flag', 'flags', 'command-line', 'command line', 'subcommand', 'option', 'options'])
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
    filtered_likely, removed_likely = _filter_routing_paths(raw_prompt, out, explicit_paths)
    filtered_likely_paths = [str(item.get('path')) for item in filtered_likely if item.get('path')]
    direct_dependencies, direct_dependents = _dependency_slices(repo_map, filtered_likely_paths)
    related_tests = _related_tests_for_paths(repo_map, filtered_likely_paths, explicit_tests=prompt_tests)
    filtered_related, removed_related = _filter_routing_paths(raw_prompt, related_tests, explicit_paths)
    direct_dependencies, removed_deps = _filter_dependency_edges(direct_dependencies, explicit_paths)
    direct_dependents, removed_dependents = _filter_dependency_edges(direct_dependents, explicit_paths)
    diagnostics = {
        'ignored_boundary_filter_active': bool(removed_likely or removed_related or removed_deps or removed_dependents or _prompt_has_negative_boundary(raw_prompt)),
        'negative_boundary_prompt': _prompt_has_negative_boundary(raw_prompt),
        'removed_likely_count': len(removed_likely),
        'removed_related_test_count': len(removed_related),
        'removed_dependency_edge_count': removed_deps,
        'removed_dependent_edge_count': removed_dependents,
        'removed_sample': (removed_likely + removed_related)[:5],
        'policy': 'Ignored/reference/generated paths are excluded from routing unless explicitly prompt-mentioned.',
    }
    return {
        'likely_files': filtered_likely[:24],
        'direct_dependencies': direct_dependencies,
        'direct_dependents': direct_dependents,
        'related_tests': filtered_related,
        'verification_order': _verification_order(repo_map, filtered_likely_paths, filtered_related),
        'entrypoint_count': len(entrypoints),
        'mapped_file_count': repo_map.get('file_count'),
        'edge_count': repo_map.get('edge_count'),
        'hint_source': 'deterministic_repo_map',
        'full_text_guardrail': 'repo-map relevance alone does not promote files to full text',
        'omitted_impact_detail_count': max(0, len(likely) - len(filtered_likely[:24])),
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
