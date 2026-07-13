"""Canonical Codex plugin packaging and receipt-bound lifecycle.

The checked-in ``plugins/pcodex`` directory is the only plugin content source.
This module locates that tree from either a source checkout or installed wheel
data and owns only the files and registration values recorded in its receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from . import __version__


PLUGIN_NAME = "pcodex"
PLUGIN_SCHEMA_VERSION = "pcodex.plugin.v1"
STATE_SCHEMA_VERSION = "pcodex.codex-plugin-state.v1"
OPERATION_SCHEMA_VERSION = "pcodex.codex-plugin-operation.v1"
MIGRATION_SCHEMA_VERSION = "pcodex.codex-plugin-migration.v1"
PLUGIN_SOURCE_RELATIVE = Path("plugins/pcodex")
PLUGIN_INSTALL_RELATIVE = Path("plugins/pcodex")
MARKETPLACE_RELATIVE = Path(".agents/plugins/marketplace.json")
STATE_RELATIVE = Path(".pcodex/codex-plugin-state.json")
JOURNAL_RELATIVE = Path(".pcodex/codex-plugin-operation.json")
LEGACY_ROOTS = (
    Path(".agents/plugins/plugins/premode-router"),
    Path(".agents/skills/pcodex"),
    Path(".agents/skills/pcodex-status"),
    Path(".agents/skills/pcodex-dry-run"),
    Path(".agents/skills/pcodex-tune"),
)
LEGACY_PLUGIN_FINGERPRINT = {
    ".codex-plugin/plugin.json": "1998b7f42048cd2022e38a85de64f4556a560b973e541c9d04e4b64867adf769",
    ".mcp.json": "aeba6c72e04f8012578142d110d6d1fab5f7023998cc0b3f4b85cb52a4d1adb5",
    "hooks/hooks.json": "0f7be500811a316ce9ec23e237e561494085c496930e75f18ebe584919c5c827",
    "hooks/premode_hook.py": "94a299e4633c0272d9b52aae0a5fafe4ff4a9c45ae0a99f890bc00f08daec489",
    "skills/branch-review/SKILL.md": "70ff85d440cc3585690ef888f6244e75aa60aedaf6446b796917b2af5e46d3c4",
    "skills/compile-repair/SKILL.md": "45c9dee79e97932dec23a350db7272fea75209f612990f720f06918f30161d6f",
    "skills/controlled-patch/SKILL.md": "57afae79c25449697d02c5f3067eee19c2932bb1ee4bdff8b13632fde946dbe0",
    "skills/log-triage/SKILL.md": "ed8b065fc6b6bd5fae3e9e24880351e99cfed6fbaee604253d347ad4bd87b4f1",
    "skills/premode-router/SKILL.md": "04ce241a26ff00d8f995d0ee99553f49ddb30562fac14c611641ab58da98ca0e",
}
LEGACY_SKILL_FINGERPRINT = {
    "pcodex/SKILL.md": "c813d935eab4273bfe6c2e79c304ed080b4014eeeadf7ff4b7ea7a4f7c191a18",
    "pcodex/bin/resolve-pcodex.sh": "5aa2b671f50b295f3e03fcdfe12b49a57f382f2dd4997075ad5cba9c3e2b2751",
    "pcodex-dry-run/SKILL.md": "e2eb4ea6197070ee3fcdbe2340b0b4516d148f324dd0d0cf0c937cfd7a44eaec",
    "pcodex-status/SKILL.md": "f6a36ee7a08f8e480dc528e14bebe0ae7d813d51461dc8d57d11d1ff2c71d2f6",
    "pcodex-tune/SKILL.md": "3365707b3e53ebd66b8d8082e1136121af961dbca58153a6a089da1e26d43d32",
}
SUPPORTED_CODEX_VERSIONS = ">=0.143.0,<0.144.0"


class CodexPluginError(RuntimeError):
    """Fail-closed plugin lifecycle error."""


def codex_compatibility() -> dict[str, Any]:
    executable = shutil.which("codex")
    if executable is None:
        return {"installed": False, "version": None, "supported": False, "reason": "codex_missing"}
    # Test-only seam. Production compatibility is always derived from the
    # installed Codex package metadata and cannot be overridden by a public env.
    version = os.environ.get("PCODEX_TEST_CODEX_VERSION")
    if version is None:
        resolved = Path(executable).resolve()
        for parent in (resolved.parent, *resolved.parents[:4]):
            package = parent / "package.json"
            if not package.is_file():
                continue
            try:
                payload = json.loads(package.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            candidate = payload.get("version") if isinstance(payload, dict) else None
            if isinstance(candidate, str):
                version = candidate
                break
    if version is None:
        return {"installed": True, "version": None, "supported": False, "reason": "codex_version_unknown"}
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    supported = bool(match and (int(match.group(1)), int(match.group(2))) == (0, 143))
    return {"installed": True, "version": version, "supported": supported, "reason": "supported" if supported else "unsupported_codex_version"}


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _product_semver() -> str:
    """Convert the authoritative PEP 440 product version to strict semver."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:b(\d+))?", __version__)
    if match is None:
        raise CodexPluginError(f"unsupported product version for plugin manifest: {__version__}")
    major, minor, patch, beta = match.groups()
    return f"{major}.{minor}.{patch}" + (f"-beta.{beta}" if beta else "")


def canonical_manifest(*, with_mcp: bool = False) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "name": PLUGIN_NAME,
        "version": _product_semver(),
        "description": "Local-first pCodex context preflight skills for explicit terminal workflows.",
        "author": {
            "name": "EXO Robotics",
            "url": "https://github.com/EXO-Robotics",
        },
        "homepage": "https://github.com/EXO-Robotics/premode-router",
        "repository": "https://github.com/EXO-Robotics/premode-router",
        "license": "Proprietary",
        "keywords": ["codex", "context", "local-first", "privacy"],
        "skills": "./skills/",
        "interface": {
            "displayName": "pCodex",
            "shortDescription": "Local context preflight for Codex tasks.",
            "longDescription": "Run explicit, no-write pCodex status and task preflight commands before Codex work.",
            "developerName": "EXO Robotics",
            "category": "Developer Tools",
            "capabilities": ["Read", "Advisory"],
            "websiteURL": "https://github.com/EXO-Robotics/premode-router",
            "privacyPolicyURL": "https://github.com/EXO-Robotics/premode-router/blob/product/codex-beta-v1/docs/PRIVACY.md",
            "termsOfServiceURL": "https://github.com/EXO-Robotics/premode-router/blob/product/codex-beta-v1/docs/TERMS.md",
            "defaultPrompt": [
                "Run a no-write pCodex preflight for my task.",
                "Show pCodex advisory status for this repository.",
                "Explain the pCodex context plan without writing files.",
            ],
        },
    }
    if with_mcp:
        manifest["mcpServers"] = "./.mcp.json"
    return manifest


def validate_manifest(manifest: Mapping[str, Any], *, with_mcp: bool) -> None:
    expected = canonical_manifest(with_mcp=with_mcp)
    if dict(manifest) != expected:
        raise CodexPluginError("plugin manifest differs from the canonical supported contract")
    allowed = {"name", "version", "description", "author", "homepage", "repository", "license", "keywords", "skills", "interface"}
    if with_mcp:
        allowed.add("mcpServers")
    if set(manifest) != allowed or "hooks" in manifest:
        raise CodexPluginError("plugin manifest declares unsupported fields")
    if manifest.get("skills") != "./skills/" or (with_mcp and manifest.get("mcpServers") != "./.mcp.json"):
        raise CodexPluginError("plugin manifest paths are invalid")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        raise CodexPluginError("plugin interface metadata is missing")
    for key in ("privacyPolicyURL", "termsOfServiceURL", "websiteURL"):
        if not isinstance(interface.get(key), str) or not interface[key].startswith("https://"):
            raise CodexPluginError(f"plugin interface {key} must be an HTTPS URL")
    prompts = interface.get("defaultPrompt")
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3 or any(not isinstance(item, str) or len(item) > 128 for item in prompts):
        raise CodexPluginError("plugin starter prompts are invalid")


def marketplace_entry(*, enabled: bool = True) -> dict[str, Any]:
    return {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": "./plugins/pcodex"},
        "policy": {"installation": "AVAILABLE"},
        "category": "Developer Tools",
        "description": "Local-first pCodex advisory skills; terminal commands remain the control plane.",
        "enabled": enabled,
    }


def _distribution_source() -> Path | None:
    try:
        distribution = metadata.distribution("premode-router")
    except metadata.PackageNotFoundError:
        return None
    suffix = "share/premode-router/plugins/pcodex/.codex-plugin/plugin.json"
    for member in distribution.files or ():
        normalized = str(member).replace("\\", "/")
        if normalized.endswith(suffix):
            manifest = Path(distribution.locate_file(member)).resolve()
            candidate = manifest.parents[1]
            return candidate if candidate.is_dir() else None
    return None


def canonical_source_root() -> Path:
    source = Path(__file__).resolve().parents[2] / PLUGIN_SOURCE_RELATIVE
    if source.is_dir():
        return source
    installed = _distribution_source()
    if installed is not None:
        return installed
    raise CodexPluginError("canonical pCodex plugin source is unavailable")


def _mcp_payload(workspace: Path) -> dict[str, Any]:
    return {
        "mcpServers": {
            "pcodex": {
                "command": sys.executable,
                "args": ["-m", "premode.pcodex_bootstrap", "mcp-server"],
                "env": {"PCODEX_WORKSPACE": str(workspace.resolve())},
                "enabled": True,
            }
        }
    }


def canonical_files(workspace: Path, *, with_mcp: bool = False) -> dict[str, bytes]:
    root = canonical_source_root()
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise CodexPluginError(f"canonical source contains a symlink: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {".mcp.json", ".codex-plugin/plugin.json"}:
            continue
        files[relative] = path.read_bytes()
    manifest = canonical_manifest(with_mcp=with_mcp)
    validate_manifest(manifest, with_mcp=with_mcp)
    files[".codex-plugin/plugin.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if with_mcp:
        files[".mcp.json"] = (json.dumps(_mcp_payload(workspace), indent=2, sort_keys=True) + "\n").encode("utf-8")
    return files


def _lstat_regular(path: Path) -> os.stat_result | None:
    try:
        result = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(result.st_mode) or result.st_nlink != 1:
        raise CodexPluginError(f"unsafe non-regular or multiply-linked file: {path}")
    return result


def _ensure_safe_parents(root: Path, path: Path) -> None:
    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise CodexPluginError(f"path escapes integration root: {path}") from exc
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise CodexPluginError(f"symlinked parent is not allowed: {current}")
        if current.exists() and not current.is_dir():
            raise CodexPluginError(f"non-directory parent is not allowed: {current}")


def _safe_unlink(root: Path, path: Path, expected_hash: str) -> None:
    """Unlink an exact regular file relative to an opened no-follow parent."""
    root = root.resolve()
    relative = path.relative_to(root)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = os.open(root, flags)
    try:
        for component in relative.parent.parts:
            next_fd = os.open(component, flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise CodexPluginError(f"unsafe removal target: {path}")
        leaf_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        leaf_fd = os.open(path.name, leaf_flags, dir_fd=parent_fd)
        try:
            opened = os.fstat(leaf_fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise CodexPluginError(f"removal target changed before verification: {path}")
            content = bytearray()
            while True:
                chunk = os.read(leaf_fd, 1024 * 1024)
                if not chunk:
                    break
                content.extend(chunk)
            if _sha256_bytes(bytes(content)) != expected_hash:
                raise CodexPluginError(f"removal target content changed: {path}")
        finally:
            os.close(leaf_fd)
        current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise CodexPluginError(f"removal target changed before unlink: {path}")
        os.unlink(path.name, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def _atomic_write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    ancestor = path.parent
    while not ancestor.exists() and not ancestor.is_symlink() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.is_symlink():
        raise CodexPluginError(f"symlinked parent is not allowed: {ancestor}")
    _ensure_safe_parents(ancestor, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_safe_parents(path.parent.parent if path.parent.parent != path.parent else path.parent, path)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: Mapping[str, Any], *, sort_keys: bool = True) -> None:
    _atomic_write(path, (json.dumps(payload, indent=2, sort_keys=sort_keys) + "\n").encode("utf-8"))


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    _lstat_regular(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexPluginError(f"malformed {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise CodexPluginError(f"{label} must contain a JSON object: {path}")
    return payload


def _load_marketplace(root: Path) -> tuple[dict[str, Any], str | None]:
    path = root / MARKETPLACE_RELATIVE
    if not path.exists() and not path.is_symlink():
        return {"name": "local-premode-marketplace", "interface": {"displayName": "Local pCodex"}, "plugins": []}, None
    _lstat_regular(path)
    try:
        before = path.read_bytes()
        payload = json.loads(before.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexPluginError(f"malformed marketplace: {path}") from exc
    if not isinstance(payload, dict):
        raise CodexPluginError(f"marketplace must contain a JSON object: {path}")
    plugins = payload.get("plugins")
    if not isinstance(plugins, list) or not all(isinstance(item, dict) for item in plugins):
        raise CodexPluginError("marketplace plugins must be an array of objects")
    schema = payload.get("schema_version")
    if schema is not None and schema != "codex.marketplace.v1":
        raise CodexPluginError(f"unsupported marketplace schema: {schema}")
    if sum(1 for item in plugins if item.get("name") == PLUGIN_NAME) > 1:
        raise CodexPluginError("duplicate pcodex marketplace registrations")
    return payload, _sha256_bytes(before)


def _scan_json_string(text: str, start: int) -> int:
    if start >= len(text) or text[start] != '"':
        raise CodexPluginError("marketplace structural edit expected a JSON string")
    index = start + 1
    escaped = False
    while index < len(text):
        character = text[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            return index + 1
        index += 1
    raise CodexPluginError("unterminated JSON string in marketplace")


def _scan_json_value(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text):
        raise CodexPluginError("missing JSON value in marketplace")
    if text[index] == '"':
        return _scan_json_string(text, index)
    if text[index] in "[{":
        opening = text[index]
        closing = "]" if opening == "[" else "}"
        depth = 1
        index += 1
        while index < len(text):
            if text[index] == '"':
                index = _scan_json_string(text, index)
                continue
            if text[index] == opening:
                depth += 1
            elif text[index] == closing:
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        raise CodexPluginError("unterminated JSON container in marketplace")
    while index < len(text) and text[index] not in ",]}\r\n\t ":
        index += 1
    return index


def _plugins_array_span(text: str) -> tuple[int, int]:
    index = 0
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "{":
        raise CodexPluginError("marketplace root must be a JSON object")
    index += 1
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == "}":
            break
        key_start = index
        key_end = _scan_json_string(text, key_start)
        key = json.loads(text[key_start:key_end])
        index = key_end
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != ":":
            raise CodexPluginError("marketplace object is not structurally patchable")
        index += 1
        while index < len(text) and text[index].isspace():
            index += 1
        value_start = index
        value_end = _scan_json_value(text, value_start)
        if key == "plugins":
            if text[value_start:value_start + 1] != "[":
                raise CodexPluginError("marketplace plugins is not an array")
            return value_start, value_end
        index = value_end
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == ",":
            index += 1
            continue
        if index < len(text) and text[index] == "}":
            break
        raise CodexPluginError("marketplace object is not structurally patchable")
    raise CodexPluginError("marketplace plugins array is missing")


def _array_item_spans(text: str, array_start: int, array_end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = array_start + 1
    limit = array_end - 1
    while True:
        while index < limit and text[index].isspace():
            index += 1
        if index >= limit:
            return spans
        start = index
        end = _scan_json_value(text, start)
        spans.append((start, end))
        index = end
        while index < limit and text[index].isspace():
            index += 1
        if index < limit and text[index] == ",":
            index += 1
            continue
        if index == limit:
            return spans
        raise CodexPluginError("marketplace plugins array is not structurally patchable")


def _patch_marketplace_entry(
    root: Path,
    desired: dict[str, Any] | None,
    *,
    plugin_name: str = PLUGIN_NAME,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    """Patch only one array element; preserve all unrelated bytes verbatim."""
    path = root / MARKETPLACE_RELATIVE
    if not path.exists() and not path.is_symlink():
        if desired is None:
            return None, None, False
        payload = {"name": "local-premode-marketplace", "interface": {"displayName": "Local pCodex"}, "plugins": [desired]}
        _atomic_json(path, payload, sort_keys=False)
        return None, None, True
    payload, before_hash = _load_marketplace(root)
    original = path.read_text(encoding="utf-8")
    array_start, array_end = _plugins_array_span(original)
    spans = _array_item_spans(original, array_start, array_end)
    matches = [index for index, item in enumerate(payload["plugins"]) if item.get("name") == plugin_name]
    if len(matches) > 1:
        raise CodexPluginError("duplicate pcodex marketplace registrations")
    existing = payload["plugins"][matches[0]] if matches else None
    replacement = json.dumps(desired, separators=(",", ":"), ensure_ascii=False) if desired is not None else None
    if not matches:
        if desired is None:
            return None, before_hash, False
        insertion = replacement if not spans else "," + replacement
        updated = original[: array_end - 1] + insertion + original[array_end - 1 :]
    else:
        item_index = matches[0]
        start, end = spans[item_index]
        if desired is not None:
            updated = original[:start] + replacement + original[end:]
        elif len(spans) == 1:
            updated = original[:start] + original[end:]
        elif item_index < len(spans) - 1:
            comma = original.find(",", end, spans[item_index + 1][0])
            if comma < 0:
                raise CodexPluginError("marketplace item delimiter is missing")
            updated = original[:start] + original[comma + 1 :]
        else:
            previous_end = spans[item_index - 1][1]
            comma = original.find(",", previous_end, start)
            if comma < 0:
                raise CodexPluginError("marketplace item delimiter is missing")
            updated = original[:comma] + original[end:]
    try:
        parsed = json.loads(updated)
    except json.JSONDecodeError as exc:
        raise CodexPluginError("marketplace structural edit produced invalid JSON") from exc
    if _sha256_bytes(path.read_bytes()) != before_hash:
        raise CodexPluginError("marketplace changed concurrently before commit")
    _atomic_write(path, updated.encode("utf-8"))
    current = next((item for item in parsed.get("plugins", []) if item.get("name") == plugin_name), None)
    if desired is None and current is not None:
        raise CodexPluginError("marketplace structural removal failed")
    if desired is not None and _sha256_json(current) != _sha256_json(desired):
        raise CodexPluginError("marketplace structural update failed")
    return existing, before_hash, False


def _registration_receipt(
    *,
    registration_type: str,
    registration_key: str,
    ownership_id: str,
    preexisting: Any,
    installed: Any,
    managed_fields: list[str],
    preserved_fields: list[str],
) -> dict[str, Any]:
    return {
        "registration_type": registration_type,
        "registration_scope": "integration_root",
        "registration_key": registration_key,
        "preexisting_value_hash": _sha256_json(preexisting) if preexisting is not None else None,
        "installed_value_hash": _sha256_json(installed),
        "current_value_hash": _sha256_json(installed),
        "ownership_id": ownership_id,
        "source_plugin_version": __version__,
        "target_plugin_version": __version__,
        "managed_fields": managed_fields,
        "preserved_fields": preserved_fields,
        "user_modified": False,
        "conflict_state": None,
        "cleanup_policy": "remove_exact_receipt_bound_value_only",
        "repair_policy": "restore_missing_exact_receipt_bound_value_only",
    }


def _matches_fingerprint(base: Path, fingerprint: Mapping[str, str]) -> bool:
    try:
        actual = _target_entries(base)
    except CodexPluginError:
        return False
    if actual != set(fingerprint):
        return False
    for relative, expected_hash in fingerprint.items():
        path = base / relative
        try:
            file_stat = _lstat_regular(path)
        except CodexPluginError:
            return False
        if file_stat is None or _sha256_bytes(path.read_bytes()) != expected_hash:
            return False
    return True


def _legacy_inventory(root: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    known_roots: set[Path] = set()
    legacy_plugin_root = root / ".agents/plugins/plugins/premode-router"
    if _matches_fingerprint(legacy_plugin_root, LEGACY_PLUGIN_FINGERPRINT):
        found.append({"path": ".agents/plugins/plugins/premode-router", "classification": "legacy_migratable", "ownership": "exact_historical_fingerprint", "will_remove": True, "requires_manual_action": False})
        known_roots.add(Path(".agents/plugins/plugins/premode-router"))
    legacy_skills_root = root / ".agents/skills"
    if _matches_fingerprint(legacy_skills_root, LEGACY_SKILL_FINGERPRINT):
        found.append({"path": ".agents/skills/pcodex*", "classification": "legacy_migratable", "ownership": "exact_historical_fingerprint", "will_remove": True, "requires_manual_action": False})
        known_roots.update(LEGACY_ROOTS[1:])
    for relative in LEGACY_ROOTS:
        if relative in known_roots:
            continue
        path = root / relative
        meaningful = path.is_symlink() or path.is_file()
        if path.is_dir() and not path.is_symlink():
            meaningful = any(candidate.is_file() or candidate.is_symlink() for candidate in path.rglob("*"))
        if meaningful:
            found.append({"path": relative.as_posix(), "classification": "legacy_preserve", "ownership": "unknown", "will_remove": False, "requires_manual_action": True})
    try:
        marketplace, _ = _load_marketplace(root)
    except CodexPluginError:
        return found
    for item in marketplace.get("plugins", []):
        if item.get("name") == "premode-router":
            exact_entry = {
                "name": "premode-router",
                "source": {"source": "local", "path": "./.agents/plugins/plugins/premode-router"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Developer Tools",
            }
            exact_files = any(item["path"] == ".agents/plugins/plugins/premode-router" and item["classification"] == "legacy_migratable" for item in found)
            migratable = exact_files and _sha256_json(item) == _sha256_json(exact_entry)
            found.append({"path": f"{MARKETPLACE_RELATIVE.as_posix()}#plugins[name=premode-router]", "classification": "legacy_migratable" if migratable else "legacy_preserve", "ownership": "exact_historical_fingerprint" if migratable else "unknown", "will_remove": migratable, "requires_manual_action": not migratable})
    return found


def _load_state(root: Path) -> dict[str, Any] | None:
    path = root / STATE_RELATIVE
    if not path.exists() and not path.is_symlink():
        return None
    payload = _read_json_object(path, label="plugin state receipt")
    schema = payload.get("schema_version")
    if schema != STATE_SCHEMA_VERSION:
        raise CodexPluginError(f"unsupported plugin state schema: {schema}")
    required = {
        "schema_version", "plugin_schema_version", "ownership_id", "plugin_name",
        "plugin_version", "plugin_semver", "source_root_hash", "installed_root",
        "files", "directories", "registrations", "marketplace_preexisting_file_hash",
        "enabled", "with_mcp", "migration",
    }
    if set(payload) != required:
        raise CodexPluginError("plugin state receipt is incomplete")
    if payload["plugin_schema_version"] != PLUGIN_SCHEMA_VERSION or payload["plugin_name"] != PLUGIN_NAME:
        raise CodexPluginError("plugin state identity is invalid")
    if not isinstance(payload["ownership_id"], str) or not payload["ownership_id"]:
        raise CodexPluginError("plugin state ownership_id is invalid")
    if not isinstance(payload["enabled"], bool) or not isinstance(payload["with_mcp"], bool):
        raise CodexPluginError("plugin state lifecycle flags are invalid")
    if (
        payload["plugin_version"] != __version__
        or payload["plugin_semver"] != _product_semver()
        or payload["installed_root"] != PLUGIN_INSTALL_RELATIVE.as_posix()
    ):
        raise CodexPluginError("plugin state version or installed root is invalid")
    files = payload["files"]
    if not isinstance(files, dict) or not files or ".codex-plugin/plugin.json" not in files:
        raise CodexPluginError("plugin state file authority is invalid")
    for relative, authority in files.items():
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
            raise CodexPluginError("plugin state contains an unsafe file path")
        if not isinstance(authority, dict) or authority.get("relative_path") != relative:
            raise CodexPluginError("plugin state file authority is malformed")
        installed_hash = authority.get("installed_hash")
        if not isinstance(installed_hash, str) or re.fullmatch(r"[0-9a-f]{64}", installed_hash) is None:
            raise CodexPluginError("plugin state installed hash is malformed")
    expected_files = canonical_files(root, with_mcp=payload["with_mcp"])
    expected_hashes = {relative: _sha256_bytes(content) for relative, content in expected_files.items()}
    if set(files) != set(expected_files):
        raise CodexPluginError("plugin state file set does not match canonical source")
    if any(files[relative].get("installed_hash") != expected_hashes[relative] for relative in expected_files):
        raise CodexPluginError("plugin state file hashes do not match canonical source")
    if payload["source_root_hash"] != _sha256_json(expected_hashes):
        raise CodexPluginError("plugin state source hash is invalid")
    expected_directories = sorted({str(Path(name).parent) for name in expected_files})
    if payload["directories"] != expected_directories:
        raise CodexPluginError("plugin state directory authority is invalid")
    registrations = payload["registrations"]
    if not isinstance(registrations, dict) or not isinstance(registrations.get("marketplace"), dict):
        raise CodexPluginError("plugin state marketplace authority is missing")
    if any(not isinstance(registration, dict) for registration in registrations.values()):
        raise CodexPluginError("plugin registration authority is malformed")
    marketplace = registrations["marketplace"]
    registration_required = {
        "registration_type", "registration_scope", "registration_key",
        "preexisting_value_hash", "installed_value_hash", "current_value_hash",
        "ownership_id", "source_plugin_version", "target_plugin_version",
        "managed_fields", "preserved_fields", "user_modified", "conflict_state",
        "cleanup_policy", "repair_policy",
    }
    registration_allowed = registration_required | {"disabled_value_hash"}
    if (
        not registration_required.issubset(marketplace)
        or not set(marketplace) <= registration_allowed
        or marketplace.get("ownership_id") != payload["ownership_id"]
    ):
        raise CodexPluginError("plugin state marketplace authority is malformed")
    expected_registration_keys = {"marketplace", "mcp"} if payload["with_mcp"] else {"marketplace"}
    if set(registrations) != expected_registration_keys:
        raise CodexPluginError("plugin state registration set is invalid")
    if (
        marketplace.get("registration_type") not in {"marketplace_entry", "marketplace_file_and_entry"}
        or marketplace.get("registration_key") != PLUGIN_NAME
        or marketplace.get("installed_value_hash") != _sha256_json(marketplace_entry(enabled=True))
    ):
        raise CodexPluginError("plugin state marketplace value authority is invalid")
    for registration in registrations.values():
        disabled_hash = registration.get("disabled_value_hash")
        if disabled_hash is not None and (
            not isinstance(disabled_hash, str) or re.fullmatch(r"[0-9a-f]{64}", disabled_hash) is None
        ):
            raise CodexPluginError("plugin disabled registration hash is invalid")
    if payload["with_mcp"]:
        mcp = registrations["mcp"]
        if (
            not isinstance(mcp, dict)
            or not registration_required.issubset(mcp)
            or not set(mcp) <= registration_allowed
            or mcp.get("ownership_id") != payload["ownership_id"]
        ):
            raise CodexPluginError("plugin MCP authority is malformed")
        expected_mcp = _mcp_payload(root)["mcpServers"]["pcodex"]
        if mcp.get("installed_value_hash") != _sha256_json(expected_mcp):
            raise CodexPluginError("plugin MCP value authority is invalid")
    if not isinstance(payload["migration"], dict) or payload["migration"].get("schema_version") != MIGRATION_SCHEMA_VERSION:
        raise CodexPluginError("plugin migration authority is malformed")
    return payload


def _current_entry(marketplace: Mapping[str, Any]) -> dict[str, Any] | None:
    for item in marketplace.get("plugins", []):
        if isinstance(item, dict) and item.get("name") == PLUGIN_NAME:
            return item
    return None


def _target_entries(target: Path) -> set[str]:
    if not target.exists() and not target.is_symlink():
        return set()
    if target.is_symlink() or not target.is_dir():
        raise CodexPluginError(f"plugin root is not a regular directory: {target}")
    entries: set[str] = set()
    for directory, directory_names, file_names in os.walk(target, followlinks=False):
        current = Path(directory)
        for name in list(directory_names):
            candidate = current / name
            if candidate.is_symlink():
                entries.add(candidate.relative_to(target).as_posix())
                directory_names.remove(name)
        for name in file_names:
            entries.add((current / name).relative_to(target).as_posix())
    return entries


def _is_canonical_source_checkout(root: Path) -> bool:
    try:
        if (root / PLUGIN_SOURCE_RELATIVE).resolve() != canonical_source_root().resolve():
            return False
        expected = canonical_files(root, with_mcp=False)
        for relative, content in expected.items():
            path = root / PLUGIN_SOURCE_RELATIVE / relative
            if not path.is_file() or path.is_symlink() or _sha256_bytes(path.read_bytes()) != _sha256_bytes(content):
                return False
        if _target_entries(root / PLUGIN_SOURCE_RELATIVE) != set(expected):
            return False
        marketplace, _ = _load_marketplace(root)
        entry = _current_entry(marketplace)
        return entry is not None and _sha256_json(entry) == _sha256_json(marketplace_entry(enabled=True))
    except (CodexPluginError, OSError):
        return False


def plugin_status(root: Path, *, native: bool = False) -> dict[str, Any]:
    root = root.resolve()
    legacy = _legacy_inventory(root)
    compatibility = codex_compatibility()
    journal_path = root / JOURNAL_RELATIVE
    try:
        state = _load_state(root)
    except CodexPluginError as exc:
        return {
            "schema_version": "pcodex.codex-plugin-status.v1",
            "readiness": "BLOCKED",
            "reason": "corrupt_or_future_authority",
            "error": str(exc),
            "legacy_sources_found": legacy,
            "codex_compatibility": compatibility,
            "writes_performed": False,
            "next_recommended_action": "restore a supported receipt or use manual recovery",
        }
    if journal_path.exists():
        return {
            "schema_version": "pcodex.codex-plugin-status.v1",
            "readiness": "BLOCKED",
            "reason": "interrupted_operation",
            "legacy_sources_found": legacy,
            "codex_compatibility": compatibility,
            "writes_performed": False,
            "next_recommended_action": "pcodex integrate codex --repair",
        }
    if state is None:
        if _is_canonical_source_checkout(root):
            source_readiness = "READY" if compatibility["supported"] else ("NEEDS_ACTION" if not compatibility["installed"] else "BLOCKED")
            result = {
                "schema_version": "pcodex.codex-plugin-status.v1",
                "readiness": source_readiness,
                "reason": "canonical_source_checkout" if source_readiness == "READY" else compatibility["reason"],
                "enabled": True,
                "optional_mcp": "disabled",
                "legacy_sources_found": legacy,
                "codex_compatibility": compatibility,
                "writes_performed": False,
                "next_recommended_action": "none",
            }
            if native:
                from .codex_native import status as native_status

                result["native_registration"] = native_status(root)
                result["optional_mcp"] = result["native_registration"].get("optional_mcp", result["optional_mcp"])
                if result["native_registration"]["readiness"] != "READY":
                    result["readiness"] = result["native_registration"]["readiness"]
                    result["reason"] = result["native_registration"]["reason"]
                    result["next_recommended_action"] = "pcodex integrate codex --write"
            return result
        target_exists = (root / PLUGIN_INSTALL_RELATIVE).exists()
        return {
            "schema_version": "pcodex.codex-plugin-status.v1",
            "readiness": "NEEDS_ACTION" if not target_exists else "BLOCKED",
            "reason": "plugin_absent" if not target_exists else "canonical_unknown_owner",
            "legacy_sources_found": legacy,
            "codex_compatibility": compatibility,
            "writes_performed": False,
            "next_recommended_action": "pcodex integrate codex --dry-run",
        }
    conflicts: list[dict[str, Any]] = []
    for relative, authority in state["files"].items():
        path = root / PLUGIN_INSTALL_RELATIVE / relative
        try:
            _ensure_safe_parents(root, path)
            file_stat = _lstat_regular(path)
        except CodexPluginError as exc:
            conflicts.append({"path": relative, "reason": str(exc)})
            continue
        if file_stat is None:
            conflicts.append({"path": relative, "reason": "missing"})
        else:
            try:
                current_hash = _sha256_bytes(path.read_bytes())
            except OSError as exc:
                conflicts.append({"path": relative, "reason": f"unreadable:{exc.__class__.__name__}"})
            else:
                if current_hash != authority["installed_hash"]:
                    conflicts.append({"path": relative, "reason": "user_modified"})
    try:
        extra_entries = sorted(_target_entries(root / PLUGIN_INSTALL_RELATIVE) - set(state["files"]))
    except CodexPluginError as exc:
        conflicts.append({"path": PLUGIN_INSTALL_RELATIVE.as_posix(), "reason": str(exc)})
    else:
        conflicts.extend({"path": entry, "reason": "untracked_plugin_entry"} for entry in extra_entries)
    try:
        marketplace, _ = _load_marketplace(root)
    except CodexPluginError as exc:
        conflicts.append({"registration": "marketplace", "reason": str(exc)})
    else:
        entry = _current_entry(marketplace)
        receipt = state["registrations"].get("marketplace")
        if entry is None:
            conflicts.append({"registration": "marketplace", "reason": "missing"})
        elif receipt is None or _sha256_json(entry) not in {
            receipt["installed_value_hash"],
            receipt.get("disabled_value_hash"),
        }:
            conflicts.append({"registration": "marketplace", "reason": "user_modified"})
    manifest_path = root / PLUGIN_INSTALL_RELATIVE / ".codex-plugin/plugin.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("version") != _product_semver() or manifest.get("name") != PLUGIN_NAME:
                conflicts.append({"path": ".codex-plugin/plugin.json", "reason": "invalid_manifest"})
        except (OSError, json.JSONDecodeError, AttributeError):
            conflicts.append({"path": ".codex-plugin/plugin.json", "reason": "invalid_manifest"})
    readiness = "READY" if not conflicts and state.get("enabled") and not legacy else "NEEDS_ACTION"
    if any(item.get("reason") not in {"missing"} for item in conflicts):
        readiness = "BLOCKED"
    if not compatibility["supported"]:
        readiness = "NEEDS_ACTION" if not compatibility["installed"] else "BLOCKED"
    reason = "healthy" if readiness == "READY" else (
        compatibility["reason"] if not compatibility["supported"]
        else ("legacy_preserved_manual_action" if legacy and not conflicts and state.get("enabled")
              else ("disabled" if not state.get("enabled") and not conflicts else "conflict"))
    )
    result = {
        "schema_version": "pcodex.codex-plugin-status.v1",
        "readiness": readiness,
        "reason": reason,
        "plugin_version": state.get("plugin_version"),
        "enabled": bool(state.get("enabled")),
        "optional_mcp": "healthy" if state.get("with_mcp") and not conflicts else ("disabled" if not state.get("with_mcp") else "conflict"),
        "conflicts": conflicts,
        "legacy_sources_found": legacy,
        "codex_compatibility": compatibility,
        "writes_performed": False,
        "next_recommended_action": "none" if readiness == "READY" else (
            "install a supported Codex CLI 0.143.x" if not compatibility["supported"]
            else ("review preserved legacy plugin state manually" if legacy and not conflicts
                  else "pcodex integrate codex --repair")
        ),
    }
    if native:
        from .codex_native import status as native_status

        result["native_registration"] = native_status(root)
        result["optional_mcp"] = result["native_registration"].get("optional_mcp", result["optional_mcp"])
        native_readiness = result["native_registration"]["readiness"]
        if native_readiness == "BLOCKED" or (native_readiness == "NEEDS_ACTION" and result["readiness"] == "READY"):
            result["readiness"] = native_readiness
            result["reason"] = result["native_registration"]["reason"]
            result["next_recommended_action"] = (
                "resolve native Codex registration conflict"
                if native_readiness == "BLOCKED" else "pcodex integrate codex --write"
            )
    return result


def integration_preview(
    root: Path, *, with_mcp: bool = False, migration: bool = False,
    native: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    if _is_canonical_source_checkout(root):
        result = {
            "schema_version": "pcodex.codex-plugin-plan.v1",
            "status": "dry_run",
            "dry_run": True,
            "writes_performed": False,
            "plugin_name": PLUGIN_NAME,
            "plugin_version": __version__,
            "plugin_semver": _product_semver(),
            "plugin_source_root": str(canonical_source_root()),
            "installed_plugin_root": str(root / PLUGIN_INSTALL_RELATIVE),
            "supported_codex_versions": SUPPORTED_CODEX_VERSIONS,
            "codex_compatibility": codex_compatibility(),
            "planned_changes": [],
            "conflicts": [],
            "preserved_unrelated_state": True,
            "optional_mcp": {"authorized": with_mcp, "would_register": with_mcp},
            "legacy_sources_found": _legacy_inventory(root),
            "migration": {"requested": migration, "canonical_target": str(root / PLUGIN_INSTALL_RELATIVE), "will_copy": False, "will_replace_owned": False, "will_register": False, "will_remove_legacy": False, "will_preserve_modified": True, "will_preserve_unrelated": True, "conflict": False, "unknown_owner": False, "requires_manual_action": False},
            "next_recommended_action": "none",
        }
        if native:
            from .codex_native import preview as native_preview

            result["native_registration"] = native_preview(marketplace_root=root, with_mcp=with_mcp)
            result["native_registration"]["codex_compatibility"] = result["codex_compatibility"]
            result["next_recommended_action"] = "pcodex integrate codex --write"
            if result["native_registration"]["conflicts"]:
                result["conflicts"] = list(result["native_registration"]["conflicts"])
            if result["codex_compatibility"]["installed"] and not result["codex_compatibility"]["supported"]:
                result["conflicts"].append({"reason": result["codex_compatibility"]["reason"]})
        return result
    files = canonical_files(root, with_mcp=with_mcp)
    legacy = _legacy_inventory(root)
    conflicts: list[dict[str, Any]] = []
    target = root / PLUGIN_INSTALL_RELATIVE
    state = None
    try:
        state = _load_state(root)
        marketplace, _ = _load_marketplace(root)
    except CodexPluginError as exc:
        conflicts.append({"reason": str(exc)})
        marketplace = {}
    if (root / JOURNAL_RELATIVE).exists():
        conflicts.append({"reason": "interrupted_operation"})
    planned: list[dict[str, Any]] = []
    for relative, content in files.items():
        path = target / relative
        if path.exists() and state is None:
            conflicts.append({"path": str(PLUGIN_INSTALL_RELATIVE / relative), "reason": "unknown_owner"})
        elif not path.exists():
            planned.append({"action": "create", "path": str(PLUGIN_INSTALL_RELATIVE / relative), "sha256": _sha256_bytes(content)})
    if state is None:
        try:
            existing_entries = _target_entries(target)
        except CodexPluginError as exc:
            conflicts.append({"path": PLUGIN_INSTALL_RELATIVE.as_posix(), "reason": str(exc)})
        else:
            if existing_entries and not any(item.get("reason") == "unknown_owner" for item in conflicts):
                conflicts.append({"path": PLUGIN_INSTALL_RELATIVE.as_posix(), "reason": "unknown_owner"})
    else:
        current = plugin_status(root)
        for item in current.get("conflicts", []):
            if item not in conflicts:
                conflicts.append(item)
    entry = _current_entry(marketplace) if marketplace else None
    if entry is not None and state is None:
        conflicts.append({"registration": "marketplace", "reason": "unknown_owner"})
    elif entry is None:
        planned.append({"action": "register", "registration": "marketplace", "key": PLUGIN_NAME})
    result = {
        "schema_version": "pcodex.codex-plugin-plan.v1",
        "status": "dry_run",
        "dry_run": True,
        "writes_performed": False,
        "plugin_name": PLUGIN_NAME,
        "plugin_version": __version__,
        "plugin_semver": _product_semver(),
        "plugin_source_root": str(canonical_source_root()),
        "installed_plugin_root": str(target),
        "supported_codex_versions": SUPPORTED_CODEX_VERSIONS,
        "codex_compatibility": codex_compatibility(),
        "planned_changes": planned,
        "conflicts": conflicts,
        "preserved_unrelated_state": True,
        "optional_mcp": {"authorized": with_mcp, "would_register": with_mcp},
        "legacy_sources_found": legacy,
        "migration": {
            "requested": migration,
            "canonical_target": str(target),
            "will_copy": bool(planned),
            "will_replace_owned": state is not None,
            "will_register": entry is None,
            "will_remove_legacy": migration and any(item.get("will_remove") for item in legacy),
            "will_preserve_modified": True,
            "will_preserve_unrelated": True,
            "conflict": bool(conflicts),
            "unknown_owner": any(item.get("ownership") == "unknown" for item in legacy),
            "requires_manual_action": any(item.get("requires_manual_action") for item in legacy),
        },
        "next_recommended_action": "resolve reported conflicts" if conflicts else "pcodex integrate codex --write",
    }
    if native:
        from .codex_native import preview as native_preview

        result["native_registration"] = native_preview(marketplace_root=root, with_mcp=with_mcp)
        result["native_registration"]["codex_compatibility"] = result["codex_compatibility"]
        result["conflicts"].extend(result["native_registration"]["conflicts"])
        if result["codex_compatibility"]["installed"] and not result["codex_compatibility"]["supported"]:
            result["conflicts"].append({"reason": result["codex_compatibility"]["reason"]})
        result["migration"]["conflict"] = bool(result["conflicts"])
    return result


def _write_journal(root: Path, payload: Mapping[str, Any]) -> None:
    _atomic_json(root / JOURNAL_RELATIVE, payload)


def _state_payload(
    root: Path,
    files: Mapping[str, bytes],
    *,
    ownership_id: str,
    existing_entry: Mapping[str, Any] | None,
    before_file_hash: str | None,
    with_mcp: bool,
    migration: bool,
    legacy_removed: list[str] | None = None,
) -> dict[str, Any]:
    desired_entry = marketplace_entry(enabled=True)
    registrations: dict[str, Any] = {
        "marketplace": _registration_receipt(
            registration_type="marketplace_file_and_entry" if before_file_hash is None else "marketplace_entry",
            registration_key=PLUGIN_NAME,
            ownership_id=ownership_id,
            preexisting=existing_entry,
            installed=desired_entry,
            managed_fields=(
                ["name", "interface", "plugins[name=pcodex]"]
                if before_file_hash is None else ["plugins[name=pcodex]"]
            ),
            preserved_fields=([] if before_file_hash is None else ["marketplace_top_level_fields", "plugins[name!=pcodex]"]),
        )
    }
    if with_mcp:
        registrations["mcp"] = _registration_receipt(
            registration_type="plugin_mcp_descriptor",
            registration_key="pcodex",
            ownership_id=ownership_id,
            preexisting=None,
            installed=_mcp_payload(root)["mcpServers"]["pcodex"],
            managed_fields=["mcpServers.pcodex"],
            preserved_fields=[],
        )
    legacy = _legacy_inventory(root)
    removed = list(legacy_removed or [])
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "plugin_schema_version": PLUGIN_SCHEMA_VERSION,
        "ownership_id": ownership_id,
        "plugin_name": PLUGIN_NAME,
        "plugin_version": __version__,
        "plugin_semver": _product_semver(),
        "source_root_hash": _sha256_json({name: _sha256_bytes(content) for name, content in files.items()}),
        "installed_root": PLUGIN_INSTALL_RELATIVE.as_posix(),
        "files": {
            relative: {
                "relative_path": relative,
                "installed_hash": _sha256_bytes(content),
                "current_hash": _sha256_bytes(content),
                "preexisting_hash": None,
                "file_type": "regular",
                "nlink_policy": 1,
                "cleanup_policy": "remove_only_if_installed_hash_matches",
                "repair_policy": "restore_only_if_missing",
            }
            for relative, content in sorted(files.items())
        },
        "directories": sorted({str(Path(name).parent) for name in files}),
        "registrations": registrations,
        "marketplace_preexisting_file_hash": before_file_hash,
        "enabled": True,
        "with_mcp": with_mcp,
        "migration": {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "requested": migration,
            "legacy_sources": legacy,
            "legacy_removed": removed,
            "legacy_preserved": [item["path"] for item in legacy],
            "complete": not legacy,
            "manual_recovery": "review preserved legacy sources" if legacy else None,
        },
    }


def _remove_exact_legacy(root: Path) -> list[str]:
    inventory = _legacy_inventory(root)
    migratable = {item["path"] for item in inventory if item["classification"] == "legacy_migratable"}
    removed: list[str] = []
    plugin_root = root / ".agents/plugins/plugins/premode-router"
    if ".agents/plugins/plugins/premode-router" in migratable:
        for relative, expected_hash in sorted(LEGACY_PLUGIN_FINGERPRINT.items(), key=lambda item: item[0].count("/"), reverse=True):
            _safe_unlink(root, plugin_root / relative, expected_hash)
            removed.append(f".agents/plugins/plugins/premode-router/{relative}")
        for directory in sorted(plugin_root.rglob("*"), key=lambda path: len(path.parts), reverse=True):
            if directory.is_dir() and not directory.is_symlink():
                directory.rmdir()
        plugin_root.rmdir()
    if ".agents/skills/pcodex*" in migratable:
        skills_root = root / ".agents/skills"
        for relative, expected_hash in sorted(LEGACY_SKILL_FINGERPRINT.items(), key=lambda item: item[0].count("/"), reverse=True):
            _safe_unlink(root, skills_root / relative, expected_hash)
            removed.append(f".agents/skills/{relative}")
        for relative in sorted({str(Path(name).parent) for name in LEGACY_SKILL_FINGERPRINT}, key=lambda value: value.count("/"), reverse=True):
            directory = skills_root / relative
            try:
                directory.rmdir()
            except OSError:
                pass
        for name in ("pcodex", "pcodex-dry-run", "pcodex-status", "pcodex-tune"):
            try:
                (skills_root / name).rmdir()
            except OSError:
                pass
    legacy_registration = f"{MARKETPLACE_RELATIVE.as_posix()}#plugins[name=premode-router]"
    if legacy_registration in migratable:
        _patch_marketplace_entry(root, None, plugin_name="premode-router")
        removed.append(legacy_registration)
    return removed


def apply_integration(
    root: Path,
    *,
    with_mcp: bool = False,
    migration: bool = False,
    native: bool = False,
    inject: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    preview = integration_preview(root, with_mcp=with_mcp, migration=migration, native=native)
    if preview["conflicts"]:
        return {**preview, "status": "blocked", "dry_run": False}
    if _is_canonical_source_checkout(root):
        result = {
            "schema_version": "pcodex.codex-plugin-result.v1",
            "status": "unchanged_source_checkout",
            "writes_performed": False,
            "registration_receipts": [],
            "legacy_preserved": [],
            "next_recommended_action": "none",
        }
        if native:
            compatibility = codex_compatibility()
            if not compatibility["installed"]:
                native_result = {"status": "deferred", "reason": "codex_missing", "writes_performed": False}
            else:
                from .codex_native import apply as native_apply

                native_result = native_apply(
                    root, marketplace_root=root, ownership_id=str(uuid4()),
                    with_mcp=with_mcp, inject=inject,
                )
            result["native_registration"] = native_result
            result["writes_performed"] = bool(native_result.get("writes_performed"))
            result["status"] = (
                "registered_source_checkout" if native_result.get("status") in {"registered", "unchanged"}
                else "needs_codex" if native_result.get("status") == "deferred" else "blocked"
            )
            result["next_recommended_action"] = "pcodex integrate codex --status"
        return result
    prior = _load_state(root)
    if prior is not None and bool(prior.get("with_mcp")) != with_mcp:
        return {**preview, "status": "blocked", "dry_run": False, "conflicts": [{"reason": "mcp_mode_change_requires_uninstall"}]}
    current_status = plugin_status(root, native=native) if prior is not None else {}
    migratable_now = migration and any(
        item.get("classification") == "legacy_migratable" for item in preview.get("legacy_sources_found", [])
    )
    if prior is not None and (
        current_status.get("readiness") == "READY"
        or current_status.get("reason") == "legacy_preserved_manual_action"
    ) and not migratable_now:
        result = {
            "schema_version": "pcodex.codex-plugin-result.v1",
            "status": "unchanged",
            "writes_performed": False,
            "ownership_id": prior["ownership_id"],
            "receipt": STATE_RELATIVE.as_posix(),
            "registration_receipts": sorted(prior["registrations"]),
            "legacy_preserved": prior.get("migration", {}).get("legacy_preserved", []),
            "next_recommended_action": "pcodex integrate codex --status",
        }
        return result
    ownership_id = prior["ownership_id"] if prior else str(uuid4())
    files = canonical_files(root, with_mcp=with_mcp)
    target = root / PLUGIN_INSTALL_RELATIVE
    journal = {
        "schema_version": OPERATION_SCHEMA_VERSION,
        "operation": "migration" if migration else "install",
        "ownership_id": ownership_id,
        "plugin_version": __version__,
        "phase": "started",
        "planned_files": sorted(files),
        "planned_hashes": {relative: _sha256_bytes(content) for relative, content in sorted(files.items())},
        "with_mcp": with_mcp,
        "legacy_removed": [],
        "marketplace_preexisting_entry": None if prior is not None else _current_entry(_load_marketplace(root)[0]),
        "marketplace_preexisting_file_hash": (
            prior["marketplace_preexisting_file_hash"] if prior is not None else _load_marketplace(root)[1]
        ),
    }
    _write_journal(root, journal)
    created: list[str] = []
    try:
        if inject:
            inject("plugin_file_staging")
        for relative, content in sorted(files.items()):
            path = target / relative
            _ensure_safe_parents(root, path)
            existing = _lstat_regular(path)
            if existing is not None:
                if _sha256_bytes(path.read_bytes()) != _sha256_bytes(content):
                    raise CodexPluginError(f"owned plugin file changed during apply: {relative}")
                continue
            mode = 0o755 if relative.endswith("/resolve-pcodex.sh") else 0o644
            _atomic_write(path, content, mode=mode)
            created.append(relative)
        journal["phase"] = "plugin_committed"
        _write_journal(root, journal)
        if inject:
            inject("plugin_directory_commit")
        marketplace, _ = _load_marketplace(root)
        existing_entry = _current_entry(marketplace)
        desired_entry = marketplace_entry(enabled=True)
        if existing_entry is not None and _sha256_json(existing_entry) != _sha256_json(desired_entry):
            raise CodexPluginError("marketplace registration changed during apply")
        if inject:
            inject("marketplace_entry_update")
        existing_entry, before_file_hash, _ = _patch_marketplace_entry(root, desired_entry)
        journal["phase"] = "marketplace_committed"
        _write_journal(root, journal)
        legacy_removed: list[str] = []
        if migration:
            if inject:
                inject("legacy_removal")
            legacy_removed = _remove_exact_legacy(root)
            journal["phase"] = "legacy_committed"
            journal["legacy_removed"] = legacy_removed
            _write_journal(root, journal)
        state = _state_payload(
            root,
            files,
            ownership_id=ownership_id,
            existing_entry=existing_entry,
            before_file_hash=before_file_hash,
            with_mcp=with_mcp,
            migration=migration,
            legacy_removed=legacy_removed,
        )
        if inject:
            inject("receipt_update")
        _atomic_json(root / STATE_RELATIVE, state)
        (root / JOURNAL_RELATIVE).unlink(missing_ok=True)
        result = {
            "schema_version": "pcodex.codex-plugin-result.v1",
            "status": "installed" if prior is None else "unchanged",
            "writes_performed": bool(created or existing_entry is None or legacy_removed),
            "created_files": created,
            "ownership_id": ownership_id,
            "receipt": STATE_RELATIVE.as_posix(),
            "registration_receipts": sorted(state["registrations"]),
            "legacy_preserved": state["migration"]["legacy_preserved"],
            "next_recommended_action": "pcodex integrate codex --status",
        }
        if native:
            compatibility = codex_compatibility()
            if not compatibility["installed"]:
                native_result = {"status": "deferred", "reason": "codex_missing", "writes_performed": False}
            else:
                from .codex_native import apply as native_apply

                native_result = native_apply(
                    root, marketplace_root=root, ownership_id=ownership_id,
                    with_mcp=with_mcp, inject=inject,
                )
            result["native_registration"] = native_result
            result["writes_performed"] = bool(result["writes_performed"] or native_result.get("writes_performed"))
            if native_result.get("status") == "blocked":
                result["status"] = "blocked"
                result["reason"] = native_result.get("reason")
            elif native_result.get("status") == "deferred":
                result["status"] = "installed_needs_codex"
                result["reason"] = native_result.get("reason")
        return result
    except Exception:
        # The journal deliberately remains. Status can never report READY until
        # the exact partial operation is inspected by repair/manual recovery.
        raise


def _replace_marketplace_entry(root: Path, state: dict[str, Any], desired: dict[str, Any]) -> None:
    marketplace, _ = _load_marketplace(root)
    entry = _current_entry(marketplace)
    receipt = state["registrations"]["marketplace"]
    allowed = {receipt["installed_value_hash"], receipt.get("disabled_value_hash")}
    if entry is None or _sha256_json(entry) not in allowed:
        raise CodexPluginError("marketplace entry is missing or user-modified")
    _patch_marketplace_entry(root, desired)


def _load_mutation_journal(root: Path, ownership_id: str) -> dict[str, Any]:
    payload = _read_json_object(root / JOURNAL_RELATIVE, label="plugin operation journal")
    required = {"schema_version", "operation", "ownership_id", "phase"}
    if not required.issubset(payload) or payload.get("schema_version") != OPERATION_SCHEMA_VERSION:
        raise CodexPluginError("plugin operation journal is malformed or future-versioned")
    if payload.get("ownership_id") != ownership_id:
        raise CodexPluginError("plugin operation journal ownership does not match")
    return payload


def disable_integration(
    root: Path, *, native: bool = False,
    inject: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    native_result: dict[str, Any] | None = None
    source_checkout = _is_canonical_source_checkout(root)
    if native:
        from .codex_native import disable as native_disable

        native_result = native_disable(root, inject=inject)
        if native_result.get("status") == "blocked":
            return {"status": "blocked", "reason": native_result.get("reason"), "native_registration": native_result, "writes_performed": False}
        if source_checkout:
            return {"status": "disabled", "native_registration": native_result, "writes_performed": bool(native_result.get("writes_performed")), "next_recommended_action": "pcodex integrate codex --repair"}
    state = _load_state(root)
    if state is None:
        return {"status": "blocked", "reason": "plugin_absent", "writes_performed": False}
    if (root / JOURNAL_RELATIVE).exists():
        return {"status": "blocked", "reason": "active_operation_journal", "writes_performed": False}
    if not state.get("enabled"):
        return {"status": "disabled", "writes_performed": False, "idempotent": True}
    desired = marketplace_entry(enabled=False)
    journal = {"schema_version": OPERATION_SCHEMA_VERSION, "operation": "disable", "ownership_id": state["ownership_id"], "phase": "started"}
    _write_journal(root, journal)
    if inject:
        inject("disable_started")
    _replace_marketplace_entry(root, state, desired)
    journal["phase"] = "marketplace_committed"
    _write_journal(root, journal)
    if inject:
        inject("disable_marketplace_update")
    receipt = state["registrations"]["marketplace"]
    receipt["disabled_value_hash"] = _sha256_json(desired)
    receipt["current_value_hash"] = receipt["disabled_value_hash"]
    state["enabled"] = False
    _atomic_json(root / STATE_RELATIVE, state)
    (root / JOURNAL_RELATIVE).unlink(missing_ok=True)
    result = {"status": "disabled", "writes_performed": True, "next_recommended_action": "pcodex integrate codex --repair"}
    if native_result is not None:
        result["native_registration"] = native_result
    return result


def _recover_interrupted_install(root: Path) -> dict[str, Any]:
    journal_path = root / JOURNAL_RELATIVE
    journal = _read_json_object(journal_path, label="plugin operation journal")
    required = {
        "schema_version", "operation", "ownership_id", "plugin_version",
        "phase", "planned_files", "planned_hashes", "with_mcp", "legacy_removed",
        "marketplace_preexisting_entry", "marketplace_preexisting_file_hash",
    }
    if set(journal) != required or journal.get("schema_version") != OPERATION_SCHEMA_VERSION:
        raise CodexPluginError("interrupted plugin journal is malformed or future-versioned")
    if journal.get("operation") not in {"install", "migration"} or journal.get("plugin_version") != __version__:
        raise CodexPluginError("interrupted operation is not recoverable by this product version")
    if not isinstance(journal.get("with_mcp"), bool) or not isinstance(journal.get("ownership_id"), str):
        raise CodexPluginError("interrupted operation identity is invalid")
    files = canonical_files(root, with_mcp=journal["with_mcp"])
    expected_hashes = {relative: _sha256_bytes(content) for relative, content in sorted(files.items())}
    if journal.get("planned_files") != sorted(files) or journal.get("planned_hashes") != expected_hashes:
        raise CodexPluginError("interrupted operation no longer matches canonical source")
    repaired: list[str] = []
    for relative, content in sorted(files.items()):
        path = root / PLUGIN_INSTALL_RELATIVE / relative
        existing = _lstat_regular(path)
        if existing is None:
            _atomic_write(path, content, mode=0o755 if relative.endswith("/resolve-pcodex.sh") else 0o644)
            repaired.append(relative)
        elif _sha256_bytes(path.read_bytes()) != expected_hashes[relative]:
            raise CodexPluginError(f"interrupted plugin file was modified: {relative}")
    marketplace, _ = _load_marketplace(root)
    entry = _current_entry(marketplace)
    desired = marketplace_entry(enabled=True)
    if entry is None:
        _patch_marketplace_entry(root, desired)
    elif _sha256_json(entry) != _sha256_json(desired):
        raise CodexPluginError("interrupted marketplace entry was modified")
    state = _state_payload(
        root,
        files,
        ownership_id=journal["ownership_id"],
        existing_entry=journal["marketplace_preexisting_entry"],
        before_file_hash=journal["marketplace_preexisting_file_hash"],
        with_mcp=journal["with_mcp"],
        migration=journal["operation"] == "migration",
        legacy_removed=journal["legacy_removed"],
    )
    _atomic_json(root / STATE_RELATIVE, state)
    journal_path.unlink()
    return {
        "status": "recovered",
        "writes_performed": True,
        "repaired_files": repaired,
        "ownership_id": state["ownership_id"],
        "next_recommended_action": "pcodex integrate codex --status",
    }


def repair_integration(root: Path, *, native: bool = False) -> dict[str, Any]:
    root = root.resolve()
    state = _load_state(root)
    if state is None:
        if native and _is_canonical_source_checkout(root):
            from .codex_native import repair as native_repair

            native_result = native_repair(root)
            return {
                "status": native_result.get("status"), "native_registration": native_result,
                "writes_performed": bool(native_result.get("writes_performed")),
                "next_recommended_action": "pcodex integrate codex --status",
            }
        if (root / JOURNAL_RELATIVE).exists():
            try:
                return _recover_interrupted_install(root)
            except CodexPluginError as exc:
                return {"status": "blocked", "reason": "interrupted_manual_recovery", "error": str(exc), "writes_performed": False}
        return {"status": "blocked", "reason": "missing_authority", "writes_performed": False}
    active_operation: str | None = None
    if (root / JOURNAL_RELATIVE).exists():
        try:
            journal = _load_mutation_journal(root, state["ownership_id"])
        except CodexPluginError as exc:
            return {"status": "blocked", "reason": "active_journal_manual_recovery", "error": str(exc), "writes_performed": False}
        active_operation = str(journal.get("operation"))
        if active_operation not in {"disable", "uninstall"}:
            return {"status": "blocked", "reason": "active_journal_manual_recovery", "writes_performed": False}
    files = canonical_files(root, with_mcp=bool(state["with_mcp"]))
    repaired: list[str] = []
    for relative, authority in state["files"].items():
        path = root / PLUGIN_INSTALL_RELATIVE / relative
        try:
            _ensure_safe_parents(root, path)
            file_stat = _lstat_regular(path)
        except CodexPluginError as exc:
            return {"status": "blocked", "reason": "alternate_filesystem_object", "path": relative, "error": str(exc), "writes_performed": False}
        if file_stat is not None:
            try:
                current_hash = _sha256_bytes(path.read_bytes())
            except OSError as exc:
                return {"status": "blocked", "reason": "unreadable", "path": relative, "error": exc.__class__.__name__, "writes_performed": False}
            if current_hash != authority["installed_hash"]:
                return {"status": "blocked", "reason": "user_modified", "path": relative, "writes_performed": False}
            continue
        content = files.get(relative)
        if content is None or _sha256_bytes(content) != authority["installed_hash"]:
            return {"status": "blocked", "reason": "source_version_mismatch", "path": relative, "writes_performed": False}
        _atomic_write(path, content, mode=0o755 if relative.endswith("/resolve-pcodex.sh") else 0o644)
        repaired.append(relative)
    marketplace, _ = _load_marketplace(root)
    entry = _current_entry(marketplace)
    desired = marketplace_entry(enabled=True)
    receipt = state["registrations"]["marketplace"]
    disabled_hash = _sha256_json(marketplace_entry(enabled=False))
    if active_operation == "disable" and entry is not None and _sha256_json(entry) == disabled_hash:
        receipt["disabled_value_hash"] = disabled_hash
        state["enabled"] = False
    if entry is None:
        _patch_marketplace_entry(root, desired)
    elif _sha256_json(entry) not in {receipt["installed_value_hash"], receipt.get("disabled_value_hash")}:
        return {"status": "blocked", "reason": "user_modified_registration", "writes_performed": bool(repaired)}
    elif not state.get("enabled"):
        _replace_marketplace_entry(root, state, desired)
    was_disabled = not state.get("enabled")
    state["enabled"] = True
    receipt["current_value_hash"] = receipt["installed_value_hash"]
    marketplace_repaired = entry is None
    changed = bool(repaired or was_disabled or marketplace_repaired or active_operation)
    if changed:
        _atomic_json(root / STATE_RELATIVE, state)
    (root / JOURNAL_RELATIVE).unlink(missing_ok=True)
    result: dict[str, Any] = {
        "status": "repaired" if changed else "healthy", "writes_performed": changed,
        "repaired_files": repaired, "next_recommended_action": "pcodex integrate codex --status",
    }
    if native:
        from .codex_native import repair as native_repair

        native_result = native_repair(root)
        result["native_registration"] = native_result
        result["writes_performed"] = bool(result["writes_performed"] or native_result.get("writes_performed"))
        if native_result.get("status") == "blocked":
            result["status"] = "blocked"
            result["reason"] = native_result.get("reason")
    return result


def uninstall_integration(
    root: Path, *, native: bool = False,
    inject: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    state = _load_state(root)
    if state is None:
        if native and _is_canonical_source_checkout(root):
            from .codex_native import uninstall as native_uninstall

            native_result = native_uninstall(root, inject=inject)
            return {
                "status": "unregistered_source_checkout" if native_result.get("status") == "uninstalled" else native_result.get("status"),
                "native_registration": native_result,
                "writes_performed": bool(native_result.get("writes_performed")),
                "next_recommended_action": "pcodex integrate codex --dry-run",
            }
        return {"status": "absent", "writes_performed": False}
    if (root / JOURNAL_RELATIVE).exists():
        return {"status": "blocked", "reason": "active_operation_journal", "writes_performed": False}
    conflicts: list[dict[str, Any]] = []
    for relative, authority in state["files"].items():
        path = root / PLUGIN_INSTALL_RELATIVE / relative
        try:
            _ensure_safe_parents(root, path)
            file_stat = _lstat_regular(path)
        except CodexPluginError as exc:
            conflicts.append({"path": relative, "reason": str(exc)})
            continue
        if file_stat is not None:
            try:
                current_hash = _sha256_bytes(path.read_bytes())
            except OSError as exc:
                conflicts.append({"path": relative, "reason": f"unreadable:{exc.__class__.__name__}"})
            else:
                if current_hash != authority["installed_hash"]:
                    conflicts.append({"path": relative, "reason": "user_modified"})
    marketplace, _ = _load_marketplace(root)
    entry = _current_entry(marketplace)
    receipt = state["registrations"]["marketplace"]
    allowed = {receipt["installed_value_hash"], receipt.get("disabled_value_hash")}
    if entry is not None and _sha256_json(entry) not in allowed:
        conflicts.append({"registration": "marketplace", "reason": "user_modified"})
    if receipt.get("registration_type") == "marketplace_file_and_entry":
        expected_container = {
            "name": "local-premode-marketplace",
            "interface": {"displayName": "Local pCodex"},
            "plugins": [entry] if entry is not None else [],
        }
        if marketplace != expected_container:
            conflicts.append({"registration": "marketplace", "reason": "created_container_modified"})
    if conflicts:
        return {"status": "blocked", "writes_performed": False, "conflicts": conflicts, "preserved": True}
    native_result: dict[str, Any] | None = None
    if native:
        from .codex_native import status as native_status

        native_preflight = native_status(root)
        if native_preflight.get("readiness") == "BLOCKED":
            return {"status": "blocked", "reason": native_preflight.get("reason"), "native_registration": native_preflight, "writes_performed": False}
    journal = {"schema_version": OPERATION_SCHEMA_VERSION, "operation": "uninstall", "ownership_id": state["ownership_id"], "phase": "started"}
    _write_journal(root, journal)
    if inject:
        inject("uninstall_started")
    if entry is not None:
        _patch_marketplace_entry(root, None)
    if receipt.get("registration_type") == "marketplace_file_and_entry":
        marketplace_path = root / MARKETPLACE_RELATIVE
        remaining = _read_json_object(marketplace_path, label="marketplace")
        expected_empty = {"name": "local-premode-marketplace", "interface": {"displayName": "Local pCodex"}, "plugins": []}
        if remaining != expected_empty:
            return {
                "status": "blocked",
                "writes_performed": True,
                "conflicts": [{"registration": "marketplace", "reason": "created_container_modified"}],
                "preserved": True,
            }
        _safe_unlink(root, marketplace_path, _sha256_bytes(marketplace_path.read_bytes()))
        for directory in (marketplace_path.parent, marketplace_path.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                break
    journal["phase"] = "marketplace_committed"
    _write_journal(root, journal)
    if inject:
        inject("uninstall_marketplace_update")
    removed: list[str] = []
    for relative in sorted(state["files"], key=lambda value: (value.count("/"), value), reverse=True):
        path = root / PLUGIN_INSTALL_RELATIVE / relative
        if path.exists():
            _safe_unlink(root, path, state["files"][relative]["installed_hash"])
            removed.append(relative)
            if inject:
                inject("uninstall_file_removal")
    for directory in sorted((root / PLUGIN_INSTALL_RELATIVE).rglob("*"), key=lambda path: len(path.parts), reverse=True) if (root / PLUGIN_INSTALL_RELATIVE).exists() else []:
        if directory.is_dir() and not directory.is_symlink():
            try:
                directory.rmdir()
            except OSError:
                pass
    try:
        (root / PLUGIN_INSTALL_RELATIVE).rmdir()
    except OSError:
        pass
    journal["phase"] = "plugin_files_committed"
    _write_journal(root, journal)
    if native:
        from .codex_native import uninstall as native_uninstall

        native_result = native_uninstall(root, inject=inject)
        if native_result.get("status") == "blocked":
            return {
                "status": "blocked", "reason": native_result.get("reason"),
                "native_registration": native_result, "writes_performed": True,
                "next_recommended_action": "pcodex integrate codex --repair",
            }
    (root / STATE_RELATIVE).unlink(missing_ok=True)
    (root / JOURNAL_RELATIVE).unlink(missing_ok=True)
    result = {
        "status": "uninstalled",
        "writes_performed": True,
        "removed_files": removed,
        "legacy_preserved": [item["path"] for item in _legacy_inventory(root)],
        "next_recommended_action": "pcodex integrate codex --dry-run",
    }
    if native_result is not None:
        result["native_registration"] = native_result
    return result


def format_result(payload: Mapping[str, Any]) -> str:
    lines = [
        "pCodex canonical Codex plugin",
        f"Status: {payload.get('status') or payload.get('readiness')}",
        f"Writes performed: {'yes' if payload.get('writes_performed') else 'no'}",
    ]
    if payload.get("plugin_version"):
        lines.append(f"Plugin version: {payload['plugin_version']}")
    conflicts = payload.get("conflicts")
    if isinstance(conflicts, list):
        lines.append(f"Conflicts: {len(conflicts)}")
    lines.append(f"Next action: {payload.get('next_recommended_action') or 'none'}")
    return "\n".join(lines)
