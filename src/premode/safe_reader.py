from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable

from .ignore import IgnoreMatcher
from .paths import normalize_for_manifest, safe_repo_path
from .profiles import ResourceCaps

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz", ".xz", ".7z",
    ".mp3", ".mp4", ".m4a", ".mov", ".wav", ".aiff", ".dmg", ".xcarchive", ".p12",
    ".mobileprovision", ".sqlite", ".db", ".otf", ".ttf", ".woff", ".woff2",
}
SECRET_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.mobileprovision",
    "id_rsa", "id_ed25519", "*.ppk", "*.cer", "*.crt", "*.keystore",
    "*.jks", "*.secret", "secrets.*", "credentials.*", "aws_credentials",
]
LOG_SUFFIXES = {".log", ".trace", ".txt"}


@dataclass
class SafeReadResult:
    path: str
    allowed: bool
    content: str = ""
    bytes_read: int = 0
    truncated: bool = False
    reason: str | None = None
    max_bytes: int | None = None

    def to_manifest(self) -> dict:
        return {
            "path": self.path,
            "allowed": self.allowed,
            "bytes_read": self.bytes_read,
            "truncated": self.truncated,
            "reason": self.reason,
            "max_bytes": self.max_bytes,
        }


def is_secret_name(rel_path: str) -> bool:
    base = rel_path.replace("\\", "/").split("/")[-1]
    for pat in SECRET_PATTERNS:
        if fnmatch(base, pat) or fnmatch(rel_path, pat):
            return True
    return False


def is_probably_binary_path(path: Path) -> bool:
    return path.suffix.lower() in BINARY_EXTENSIONS


def _looks_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    if not data:
        return False
    # Treat very high control-byte ratio as binary.
    ctrl = sum(1 for b in data[:4096] if b < 9 or (13 < b < 32))
    return ctrl / max(1, min(len(data), 4096)) > 0.20


def _cap_text_to_bytes(text: str, max_bytes: int) -> str:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= max_bytes:
        return text
    return data[:max_bytes].decode("utf-8", errors="ignore")


def _read_head_tail(path: Path, max_bytes: int) -> tuple[bytes, bool]:
    size = path.stat().st_size
    if size <= max_bytes:
        return path.read_bytes(), False
    half = max(1, max_bytes // 2)
    with path.open("rb") as f:
        head = f.read(half)
        f.seek(max(0, size - half))
        tail = f.read(half)
    marker = b"\n\n[... PREMODE LOG TRUNCATED: middle omitted ...]\n\n"
    combined = head + marker + tail
    return combined[:max_bytes], True


def safe_read(
    repo_root: Path,
    rel_path: str | Path,
    caps: ResourceCaps,
    ignore: IgnoreMatcher | None = None,
    *,
    max_bytes: int | None = None,
    purpose: str = "context",
) -> SafeReadResult:
    ignore = ignore or IgnoreMatcher.from_repo(repo_root)
    norm = normalize_for_manifest(rel_path, repo_root)
    display_path = norm.rel_path or str(rel_path).replace("\\", "/")
    if not norm.ok or not norm.rel_path:
        return SafeReadResult(display_path, False, reason=norm.reason, max_bytes=max_bytes)
    if ignore.is_ignored(norm.rel_path):
        return SafeReadResult(norm.rel_path, False, reason="ignored by .premodeignore/.gitignore", max_bytes=max_bytes)
    if is_secret_name(norm.rel_path):
        return SafeReadResult(norm.rel_path, False, reason="secret-like path blocked", max_bytes=max_bytes)

    path, reason = safe_repo_path(repo_root, norm.rel_path)
    if path is None:
        return SafeReadResult(norm.rel_path, False, reason=reason, max_bytes=max_bytes)
    if not path.exists() or not path.is_file():
        return SafeReadResult(norm.rel_path, False, reason="not a regular file", max_bytes=max_bytes)
    if is_probably_binary_path(path):
        return SafeReadResult(norm.rel_path, False, reason="binary/asset extension blocked", max_bytes=max_bytes)

    cap = max_bytes or (caps.max_log_bytes if path.suffix.lower() in LOG_SUFFIXES and "log" in path.name.lower() else caps.max_file_bytes)
    cap = int(cap)
    try:
        if path.suffix.lower() in LOG_SUFFIXES and "log" in path.name.lower():
            data, truncated = _read_head_tail(path, cap)
        else:
            with path.open("rb") as f:
                data = f.read(cap + 1)
            truncated = len(data) > cap
            data = data[:cap]
        if _looks_binary(data[:4096]):
            return SafeReadResult(norm.rel_path, False, reason="binary content blocked", max_bytes=cap)
        text = data.decode("utf-8", errors="replace")
        text = _cap_text_to_bytes(text, cap)
        return SafeReadResult(
            norm.rel_path,
            True,
            content=text,
            bytes_read=len(text.encode("utf-8", errors="replace")),
            truncated=truncated,
            max_bytes=cap,
        )
    except OSError as exc:
        return SafeReadResult(norm.rel_path, False, reason=f"read failed: {exc}", max_bytes=cap)
