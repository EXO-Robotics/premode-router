from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

DEFAULT_PREMODEIGNORE = """DerivedData/
build/
.env
.env.*
*.p12
*.mobileprovision
*.xcarchive
*.pem
*.key
node_modules/
.venv/
dist/
.cache/
"""


def _clean(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # Negation is intentionally unsupported in the MVP. Safer to keep ignores
    # monotonic and predictable.
    if line.startswith("!"):
        return None
    return line.replace("\\", "/")


@dataclass
class IgnoreMatcher:
    patterns: list[str]

    @classmethod
    def from_repo(cls, repo_root: Path) -> "IgnoreMatcher":
        patterns: list[str] = []
        for name in (".gitignore", ".premodeignore"):
            p = repo_root / name
            if p.exists():
                try:
                    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                        cleaned = _clean(line)
                        if cleaned:
                            patterns.append(cleaned)
                except OSError:
                    continue
        return cls(patterns)

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        rel = rel_path.replace("\\", "/").strip("/")
        if not rel:
            return False
        parts = rel.split("/")
        base = parts[-1]
        for pattern in self.patterns:
            p = pattern.strip("/") if pattern.startswith("/") else pattern
            dir_only = p.endswith("/")
            p = p.rstrip("/")
            if not p:
                continue
            if dir_only:
                if rel == p or rel.startswith(p + "/") or any(fnmatch(part, p) for part in parts):
                    return True
                continue
            if "/" not in p:
                if any(fnmatch(part, p) for part in parts) or fnmatch(base, p):
                    return True
            else:
                if fnmatch(rel, p) or rel.startswith(p + "/"):
                    return True
        return False
