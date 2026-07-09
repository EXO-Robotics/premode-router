from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .config import premode_dir

SECRET_LIKE_PATTERNS = [
    ".env", ".env.*", "*.env", "env.local", "env.*.bak", "*.env.bak", "env.local.*.bak",
    "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa", "id_ed25519",
    "secret.*", "secrets.*", "credential.*", "credentials.*", "token.*",
    "**/.env", "**/.env.*", "**/*.env", "**/env.local", "**/env.*.bak", "**/*.env.bak",
    "**/env.local.*.bak", "**/*.pem", "**/*.key", "**/id_rsa", "**/id_ed25519",
    "**/secret.*", "**/secrets.*", "**/credential.*", "**/credentials.*", "**/token.*",
    "._backup_codex/**", "**/._backup_codex/**", ".agents/**", "**/.agents/**",
    ".premode/**", "**/.premode/**",
]

DEPENDENCY_OR_BUILD_PATTERNS = [
    "pyproject.toml", "requirements*.txt", "package.json", "pnpm-lock.yaml", "yarn.lock",
    "package-lock.json", "bun.lock", "bun.lockb", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
    "Package.swift", "*.xcodeproj/*", "*.xcworkspace/*", "build.gradle", "settings.gradle",
    "pom.xml", "composer.json", "composer.lock", "Gemfile", "Gemfile.lock", "Rakefile",
    "*.sln", "*.csproj", "Directory.Build.props", "Directory.Build.targets", "packages.lock.json",
    "build.zig", "build.zig.zon", "stack.yaml", "*.cabal", "cabal.project",
    ".terraform.lock.hcl", "Makefile", "SConstruct", "CMakeLists.txt", "justfile", ".premode/commands.json",
]

CI_PATTERNS = [
    ".github/workflows/*", ".gitlab-ci.yml", ".circleci/*", "azure-pipelines.yml", "Jenkinsfile",
]

GENERATED_OR_STATE_PATTERNS = [
    "_output/*", "generated/*", "gen/*", "bazel-*", "build/*", "dist/*", "target/*", "out/*",
    ".dart_tool/*", ".terraform/*", "tmp/*", "cache/*", ".cache/*", "coverage/*", "_claw_output/*",
    "PROJECT/state/*", "PROJECT/artifacts/generated/*", "*.generated.*", "*.gen.*", "*_generated.*",
    "*.pb.go", "*.g.dart", "*.tfstate", "*.tfstate.backup", "*.ckpt", "*.pt", "*.pth", "*.onnx",
]

TEST_PATH_PATTERNS = [
    "tests/*", "test/*", "__tests__/*", "*.test.*", "*.spec.*", "*_test.py", "test_*.py",
]

DOC_PATH_PATTERNS = [
    "README.md", "CHANGELOG.md", "docs/*", "*.md", "*.rst", "*.txt",
]

TEST_CLAIM_RE = re.compile(
    r"(?i)(python(?:3)?\s+-m\s+pytest\b|python(?:3)?\s+tests?/[^\n.;]+|python(?:3)?\s+-m\s+py_compile\b|git\s+diff\s+--check\b|\bpytest\b|\bnpm\s+test\b|\bpnpm\s+test\b|\byarn\s+test\b|\bbun\s+test\b|\bcargo\s+test\b|\bgo\s+test\b|\bxcodebuild(?:\s+test)?\b|\bswift\s+test\b|\bswiftc\s+-parse\b|tests? passed|test suite passed|xcodebuild succeeded|\bpassed\b)"
)
COMMAND_LIKE_CLAIM_RE = re.compile(
    r"(?im)^\s*(?P<command>(?:python3?|pytest|npm|pnpm|yarn|bun|cargo|go|swift|swiftc|xcodebuild|git)\b[^\n]*?)(?:\s+with\s+(?P<result>[^\n]+))?\s*$"
)
SPECIFIC_RESULT_RE = re.compile(
    r"(?i)(\bpass\b|\b[1-9][0-9]*\s+passed\b|\b[0-9]+/[0-9]+\b.*\bpassed\b|\b0\s+failed\b|\bsucceeded\b|\bsuccess\b|exit code\s*[:=]?\s*0|no changes|clean)"
)
VAGUE_VALIDATION_CLAIM_RE = re.compile(r"(?i)^\s*(tests? passed|validated everything|looks good|all good|checks passed)\s*\.?\s*$")
# Evidence parsing is deliberately numeric where possible. Many real test
# runners print phrases like "10 passed, 0 failed"; a broad "failed" regex
# would incorrectly block a passing patch.
FAIL_COUNT_RE = re.compile(r"(?i)\b([0-9]+)\s+failed\b")
ERROR_COUNT_RE = re.compile(r"(?i)\b([0-9]+)\s+errors?\b")
PASS_COUNT_RE = re.compile(r"(?i)\b([0-9]+)\s+passed\b")
FAILED_WORD_RE = re.compile(r"(?i)(^|\n)(FAILED|ERROR|Traceback \(most recent call last\)|exit code\s*[:=]?\s*[1-9][0-9]*)")
PASSED_WORD_RE = re.compile(r"(?i)(success|succeeded|passed in [0-9.]+s|exit code\s*[:=]?\s*0)")
PACKET_SHA_RE = re.compile(r"(?i)(?:packet_sha256|PREMODE_PACKET_SHA256)\s*[:=]\s*([a-f0-9]{64})")


@dataclass(frozen=True)
class ChangedFile:
    status: str
    path: str
    old_path: str | None = None


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True, check=False)


def _is_git_repo(repo_root: Path) -> bool:
    result = _run_git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _norm(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def _matches(path: str, patterns: list[str] | tuple[str, ...] | set[str]) -> bool:
    lower = _norm(path).lower()
    for pattern in patterns or []:
        pat = _norm(str(pattern)).lower()
        if not pat:
            continue
        if fnmatch(lower, pat) or fnmatch(lower, pat.replace("**/", "*/")):
            return True
        if pat.endswith("/*"):
            base = pat[:-2].rstrip("/")
            if lower == base or lower.startswith(base + "/"):
                return True
        if lower == pat or lower.startswith(pat.rstrip("/") + "/") or lower.endswith("/" + pat):
            return True
    return False


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _norm(str(item))
        key = text.lower()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def _path_list(items: Any) -> list[str]:
    paths: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            path = item.get("path")
        elif isinstance(item, str) and item.lstrip().startswith("{"):
            try:
                parsed = ast.literal_eval(item)
            except (SyntaxError, ValueError):
                parsed = None
            path = parsed.get("path") if isinstance(parsed, dict) else item
        else:
            path = item
        if path:
            paths.append(str(path))
    return _dedupe(paths)


def _parse_name_status(text: str) -> list[ChangedFile]:
    changed: list[ChangedFile] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0].strip()
        if status.startswith("R") or status.startswith("C"):
            if len(parts) >= 3:
                changed.append(ChangedFile(status=status, old_path=_norm(parts[1]), path=_norm(parts[2])))
        elif len(parts) >= 2:
            changed.append(ChangedFile(status=status, path=_norm(parts[1])))
    return changed


def _parse_status_porcelain(text: str) -> list[ChangedFile]:
    changed: list[ChangedFile] = []
    for line in (text or "").splitlines():
        if len(line) < 4:
            continue
        status = line[:2].strip() or "?"
        path = line[3:]
        if " -> " in path:
            old, new = path.split(" -> ", 1)
            changed.append(ChangedFile(status=status, old_path=_norm(old), path=_norm(new)))
        else:
            changed.append(ChangedFile(status=status, path=_norm(path)))
    return changed


def _changed_files(repo_root: Path, base_ref: str) -> tuple[list[ChangedFile], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    candidates = [base_ref]
    if base_ref != "HEAD":
        candidates.append("HEAD")
    for candidate_ref in candidates:
        args = ["diff", "--name-status", candidate_ref, "--"]
        result = _run_git(repo_root, args)
        attempts.append({"command": "git " + " ".join(args), "returncode": result.returncode, "stderr": result.stderr.strip()[:300]})
        if result.returncode == 0:
            changed = _parse_name_status(result.stdout)
            status = _run_git(repo_root, ["status", "--porcelain"])
            # Include untracked files that are not visible in git diff.
            status_changed = _parse_status_porcelain(status.stdout) if status.returncode == 0 else []
            expanded_status: list[ChangedFile] = []
            for item in status_changed:
                candidate = repo_root / item.path
                if item.status.startswith("?") and candidate.is_dir():
                    for child in sorted(candidate.rglob("*")):
                        if child.is_file():
                            expanded_status.append(ChangedFile(status=item.status, path=child.relative_to(repo_root).as_posix()))
                else:
                    expanded_status.append(item)
            combined: dict[tuple[str | None, str], ChangedFile] = {}
            for item in changed:
                combined[(item.old_path, item.path)] = item
            for item in expanded_status:
                combined.setdefault((item.old_path, item.path), item)
            fallback_reason = None if candidate_ref == base_ref else f"{base_ref} not found or not comparable"
            return list(combined.values()), {
                "diff_source": "git_diff",
                "base_ref_requested": base_ref,
                "base_ref_used": candidate_ref,
                "base_ref_fallback_reason": fallback_reason,
                "attempts": attempts,
            }
    status = _run_git(repo_root, ["status", "--porcelain"])
    attempts.append({"command": "git status --porcelain", "returncode": status.returncode, "stderr": status.stderr.strip()[:300]})
    if status.returncode == 0:
        parsed = _parse_status_porcelain(status.stdout)
        expanded: list[ChangedFile] = []
        for item in parsed:
            candidate = repo_root / item.path
            if item.status.startswith("?") and candidate.is_dir():
                for child in sorted(candidate.rglob("*")):
                    if child.is_file():
                        expanded.append(ChangedFile(status=item.status, path=child.relative_to(repo_root).as_posix()))
            else:
                expanded.append(item)
        return expanded, {
            "diff_source": "git_status",
            "base_ref_requested": base_ref,
            "base_ref_used": "WORKTREE_STATUS",
            "base_ref_fallback_reason": f"{base_ref} and HEAD diff were unavailable; used git status --porcelain",
            "attempts": attempts,
        }
    return [], {
        "diff_source": "unavailable",
        "base_ref_requested": base_ref,
        "base_ref_used": None,
        "base_ref_fallback_reason": "git diff and git status were unavailable",
        "attempts": attempts,
    }


def default_packet_path(repo_root: Path) -> Path:
    return premode_dir(repo_root) / "out" / "last_packet.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _extract_review_contract(packet: dict[str, Any]) -> dict[str, Any]:
    contract = packet.get("review_contract")
    if isinstance(contract, dict) and contract:
        out = dict(contract)
        out["candidate_edit_files"] = _path_list(out.get("candidate_edit_files") or out.get("allowed_edit_files") or [])
        out["allowed_edit_files"] = _path_list(out.get("allowed_edit_files") or out.get("candidate_edit_files") or [])
        out["support_files"] = _path_list(out.get("support_files") or out.get("read_only_support_files") or [])
        out["read_only_support_files"] = _path_list(out.get("read_only_support_files") or out.get("support_files") or [])
        out["promoted_support_candidate_files"] = _path_list(out.get("promoted_support_candidate_files") or [])
        if out["promoted_support_candidate_files"]:
            out["candidate_edit_files"] = _dedupe(list(out.get("candidate_edit_files") or []) + out["promoted_support_candidate_files"])
            out["allowed_edit_files"] = _dedupe(list(out.get("allowed_edit_files") or []) + out["promoted_support_candidate_files"])
        out["verification_files"] = _path_list(out.get("verification_files") or out.get("suggested_tests") or [])
        out["verification_edit_files"] = _path_list(out.get("verification_edit_files") or [])
        packet_files = _path_list(out.get("packet_files") or [])
        out["packet_files"] = packet_files or _dedupe(
            list(out.get("candidate_edit_files") or [])
            + list(out.get("support_files") or [])
            + list(out.get("verification_files") or [])
        )
        return out
    boundary = packet.get("patch_boundary") if isinstance(packet.get("patch_boundary"), dict) else {}
    control = boundary.get("control_plane_boundary") if isinstance(boundary.get("control_plane_boundary"), dict) else {}
    metrics = packet.get("metrics") if isinstance(packet.get("metrics"), dict) else {}
    candidate_files = _path_list(packet.get("candidate_edit_files") or boundary.get("candidate_edit_files") or boundary.get("allowed_edit_files") or control.get("allowed_source_edits") or [])
    promoted_support = _path_list(packet.get("promoted_support_candidate_files") or [])
    candidate_files = _dedupe(candidate_files + promoted_support)
    support_files = _path_list(packet.get("support_files") or packet.get("read_only_support_files") or boundary.get("support_files") or boundary.get("read_only_support_files") or boundary.get("read_only_context_files") or [])
    verification_files = _path_list(packet.get("verification_files") or packet.get("suggested_tests") or packet.get("related_tests") or [])
    verification_edit_files = _path_list(packet.get("verification_edit_files") or [])
    safety_blocked = (
        packet.get("safety_blocked_files")
        or boundary.get("safety_blocked_files")
        or (boundary.get("forbidden_without_user_confirmation") or []) + (control.get("forbidden_runtime_mutation") or []) + (control.get("authority_read_only") or [])
    )
    return {
        "packet_sha256": packet.get("packet_sha256") or packet.get("compiled_packet_sha256") or metrics.get("packet_sha256"),
        "raw_prompt_sha256": packet.get("raw_prompt_sha256"),
        "candidate_edit_files": candidate_files,
        "allowed_edit_files": candidate_files,
        "support_files": support_files,
        "read_only_support_files": support_files,
        "promoted_support_candidate_files": promoted_support,
        "promotion_reasons": packet.get("promotion_reasons") or {},
        "verification_files": verification_files,
        "verification_edit_files": verification_edit_files,
        "packet_files": _dedupe(list(candidate_files or []) + list(support_files or []) + list(verification_files or [])),
        "allowed_if_justified": (boundary.get("allowed_if_justified") or []) + (control.get("allowed_config_if_justified") or []),
        "safety_blocked_files": safety_blocked,
        "forbidden_without_user_confirmation": safety_blocked,
        "prompt_forbidden_files": packet.get("prompt_forbidden_paths") or (packet.get("evidence_summary") or {}).get("prompt_forbidden_files") or [],
        "secret_like_patterns": SECRET_LIKE_PATTERNS,
        "generated_or_state_patterns": GENERATED_OR_STATE_PATTERNS + (control.get("state_mutation_requires_explicit_authorization") or []) + (control.get("evidence_only_generated_outputs") or []),
        "dependency_or_build_patterns": DEPENDENCY_OR_BUILD_PATTERNS,
        "ci_patterns": CI_PATTERNS,
        "expected_verification": _expected_verification_from_packet(packet),
        "negative_prompt_intent": packet.get("prompt_forbidden_paths") or (packet.get("evidence_summary") or {}).get("prompt_forbidden_files") or [],
    }


def _expected_verification_from_packet(packet: dict[str, Any]) -> list[str]:
    out: list[str] = []
    impact = packet.get("impact_map") if isinstance(packet.get("impact_map"), dict) else {}
    for item in impact.get("verification_order") or []:
        if isinstance(item, dict) and item.get("command"):
            out.append(str(item["command"]))
        elif isinstance(item, str):
            out.append(item)
    commands = packet.get("commands") if isinstance(packet.get("commands"), dict) else {}
    for key in ("test", "build", "lint", "typecheck"):
        item = commands.get(key)
        if isinstance(item, dict) and item.get("command"):
            out.append(str(item["command"]))
        elif isinstance(item, str):
            out.append(item)
    acceptance = packet.get("acceptance_checks") or []
    for item in acceptance:
        if isinstance(item, dict) and item.get("command"):
            out.append(str(item["command"]))
        elif isinstance(item, str) and any(term in item.lower() for term in ["pytest", "test", "build", "cargo", "go test", "xcodebuild"]):
            out.append(item)
    return _dedupe(out)[:20]


def _read_text_maybe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _claim_commands_from_text(text: str) -> list[str]:
    claims: list[str] = []
    for match in TEST_CLAIM_RE.finditer(text or ""):
        token = match.group(1).strip()
        if token:
            claims.append(token)
    return _dedupe(claims)


def _parse_validation_claims(text: str, *, source: str = "claims_file") -> tuple[list[dict[str, Any]], list[str]]:
    structured = _parse_structured_validation_claims(text, source=source)
    if structured is not None:
        return structured
    evidence: list[dict[str, Any]] = []
    vague: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip().strip("-* ")
        if not line:
            continue
        if VAGUE_VALIDATION_CLAIM_RE.match(line):
            vague.append(line)
            continue
        match = COMMAND_LIKE_CLAIM_RE.match(line)
        if not match:
            continue
        command = (match.group("command") or "").strip()
        claimed_result = (match.group("result") or "").strip()
        if " with " in command and not claimed_result:
            command, claimed_result = command.split(" with ", 1)
            command = command.strip()
            claimed_result = claimed_result.strip()
        command = command.rstrip(".")
        claimed_result = claimed_result.rstrip(".")
        if not command:
            continue
        evidence.append({
            "source": source,
            "command": command,
            "claimed_result": claimed_result or None,
            "trusted_as_execution_proof": False,
        })
    return evidence, _dedupe(vague)


def _parse_structured_validation_claims(text: str, *, source: str = "claims_file") -> tuple[list[dict[str, Any]], list[str]] | None:
    try:
        payload = json.loads(text or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    raw_claims = payload.get("claims")
    if not isinstance(raw_claims, list):
        return None
    default_source = str(payload.get("source") or source)
    evidence: list[dict[str, Any]] = []
    vague: list[str] = []
    for item in raw_claims:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip().rstrip(".")
        claimed_result = str(item.get("claimed_result") or "").strip().rstrip(".")
        if not command:
            text_claim = claimed_result or str(item.get("claim") or "").strip()
            if text_claim and VAGUE_VALIDATION_CLAIM_RE.match(text_claim):
                vague.append(text_claim)
            continue
        if VAGUE_VALIDATION_CLAIM_RE.match(command) and not COMMAND_LIKE_CLAIM_RE.match(command):
            vague.append(command)
            continue
        if not COMMAND_LIKE_CLAIM_RE.match(command):
            continue
        evidence.append({
            "source": str(item.get("source") or default_source),
            "command": command,
            "claimed_result": claimed_result or None,
            "trusted_as_execution_proof": bool(item.get("trusted_as_execution_proof") is True),
        })
    return evidence, _dedupe(vague)


def _evidence_result(text: str) -> str:
    """Return failed|passed|none for a test/log body without false-failing on `0 failed`."""
    body = text or ""
    fail_counts = [int(x) for x in FAIL_COUNT_RE.findall(body)]
    error_counts = [int(x) for x in ERROR_COUNT_RE.findall(body)]
    pass_counts = [int(x) for x in PASS_COUNT_RE.findall(body)]
    if any(n > 0 for n in fail_counts) or any(n > 0 for n in error_counts):
        return "failed"
    if FAILED_WORD_RE.search(body):
        return "failed"
    if any(n > 0 for n in pass_counts):
        return "passed"
    if PASSED_WORD_RE.search(body):
        return "passed"
    if "0 passed" in body.lower():
        return "failed"
    return "none"


def _packet_sha_bound(text: str, packet_sha: str | None) -> bool:
    if not packet_sha:
        return False
    body = text or ""
    sha = str(packet_sha).strip().lower()
    if sha and sha in body.lower():
        return True
    for match in PACKET_SHA_RE.finditer(body):
        if match.group(1).lower() == sha:
            return True
    return False


def _verification(repo_root: Path, contract: dict[str, Any], claims_path: Path | None, changed_paths: list[str], docs_only: bool) -> dict[str, Any]:
    expected = _dedupe([str(x) for x in (contract.get("expected_verification") or []) if x])
    packet_sha = str(contract.get("packet_sha256") or "").strip() or None
    claims: list[str] = []
    validation_evidence: list[dict[str, Any]] = []
    vague_validation_claims: list[str] = []
    evidence_sources: list[str] = []
    failed_sources: list[str] = []
    unbound_sources: list[str] = []

    if claims_path:
        claims_abs = claims_path if claims_path.is_absolute() else repo_root / claims_path
        text = _read_text_maybe(claims_abs)
        parsed_evidence, parsed_vague = _parse_validation_claims(text)
        validation_evidence.extend(parsed_evidence)
        vague_validation_claims.extend(parsed_vague)
        claims.extend([item["command"] for item in parsed_evidence if item.get("command")])
        claims.extend(_claim_commands_from_text(text))
        result = _evidence_result(text)
        if result == "none" and any(_is_specific_validation_evidence_claim(item) for item in parsed_evidence):
            result = "passed"
        # A user-supplied claims file is explicit review input, so it can act as
        # evidence even without packet binding. Automatic log discovery below is
        # stricter and requires packet_sha256 binding.
        if result == "failed":
            failed_sources.append(str(claims_path))
        elif result == "passed":
            evidence_sources.append(str(claims_path))

    out_dir = premode_dir(repo_root) / "out"
    if out_dir.exists():
        for path in sorted(out_dir.glob("*.log"))[:30]:
            text = _read_text_maybe(path)
            claims.extend(_claim_commands_from_text(text))
            result = _evidence_result(text)
            if result == "none":
                continue
            if _packet_sha_bound(text, packet_sha):
                if result == "failed":
                    failed_sources.append(str(path))
                elif result == "passed":
                    evidence_sources.append(str(path))
            else:
                unbound_sources.append(str(path))

    claims = _dedupe(claims)
    evidence_sources = _dedupe(evidence_sources)
    failed_sources = _dedupe(failed_sources)
    unbound_sources = _dedupe(unbound_sources)
    code_changed = any(not _matches(path, DOC_PATH_PATTERNS) for path in changed_paths)
    tests_changed = any(_matches(path, TEST_PATH_PATTERNS) for path in changed_paths)

    if failed_sources:
        status = "failed_evidence_found"
    elif evidence_sources:
        status = "evidence_found"
    elif unbound_sources:
        status = "evidence_present_but_unbound"
    elif claims:
        status = "claimed_without_evidence"
    elif not changed_paths or docs_only or (not code_changed and not expected):
        status = "not_applicable"
    elif expected or code_changed or tests_changed:
        status = "missing_evidence"
    else:
        status = "not_applicable"
    return {
        "expected_commands": expected,
        "tests_claimed": claims,
        "validation_evidence": validation_evidence,
        "vague_validation_claims": vague_validation_claims,
        "test_evidence_found": bool(evidence_sources) and not failed_sources,
        "test_evidence_sources": evidence_sources,
        "failed_test_evidence_sources": failed_sources,
        "unbound_test_evidence_sources": unbound_sources,
        "evidence_binding": "packet_sha256" if packet_sha else "unavailable",
        "verification_status": status,
    }


def _is_specific_validation_evidence_claim(item: dict[str, Any]) -> bool:
    command = str(item.get("command") or "")
    claimed_result = str(item.get("claimed_result") or "")
    if not claimed_result or not SPECIFIC_RESULT_RE.search(claimed_result):
        return False
    return bool(TEST_CLAIM_RE.search(command))


def _file_sha256(repo_root: Path, rel_path: str) -> str | None:
    try:
        path = repo_root / rel_path
        if not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _pre_agent_state_from_packet(packet: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    state = contract.get("pre_agent_worktree_state")
    if isinstance(state, dict) and state:
        return state
    state = packet.get("pre_agent_worktree_state")
    if isinstance(state, dict):
        return state
    return {}


def _paths_for_item(item: ChangedFile) -> list[str]:
    paths: list[str] = []
    if item.old_path:
        paths.append(_norm(item.old_path))
    if item.path:
        paths.append(_norm(item.path))
    return _dedupe(paths)


def _compile_snapshot_paths(pre_state: dict[str, Any]) -> set[str]:
    paths = set()
    for key in ("dirty_files_at_compile", "untracked_files_at_compile"):
        for item in pre_state.get(key) or []:
            norm = _norm(str(item))
            if norm:
                paths.add(norm.lower())
    file_hashes = pre_state.get("file_hashes_at_compile") if isinstance(pre_state.get("file_hashes_at_compile"), dict) else {}
    for item in file_hashes:
        norm = _norm(str(item))
        if norm:
            paths.add(norm.lower())
    return paths


def _item_preexisted_unchanged(repo_root: Path, item: ChangedFile, pre_state: dict[str, Any]) -> bool:
    if not pre_state:
        return False
    snapshot_paths = _compile_snapshot_paths(pre_state)
    file_hashes = pre_state.get("file_hashes_at_compile") if isinstance(pre_state.get("file_hashes_at_compile"), dict) else {}
    paths = _paths_for_item(item)
    if not paths:
        return False
    # Rename/copy/delete records are treated as post-compile agent candidates.
    # A rename from a preexisting .env still needs review of the old path.
    if item.old_path or item.status.startswith(("R", "C", "D")):
        return False
    path = _norm(item.path)
    if path.lower() not in snapshot_paths:
        return False
    before = file_hashes.get(path) or file_hashes.get(path.lower())
    after = _file_sha256(repo_root, path)
    # If we have a compile-time hash, ignore only when the current content is identical.
    if before:
        return after == before
    # If no hash was available at compile time but the path was recorded as dirty/untracked,
    # conservatively treat it as preexisting only when it still exists and has no old_path.
    return after is not None


def _split_preexisting_changes(repo_root: Path, changed: list[ChangedFile], pre_state: dict[str, Any]) -> tuple[list[ChangedFile], list[ChangedFile]]:
    preexisting: list[ChangedFile] = []
    post_compile: list[ChangedFile] = []
    for item in changed:
        if _item_preexisted_unchanged(repo_root, item, pre_state):
            preexisting.append(item)
        else:
            post_compile.append(item)
    return preexisting, post_compile


def _items_to_paths(items: list[ChangedFile], *, include_old: bool = False) -> list[str]:
    paths: list[str] = []
    for item in items:
        if include_old and item.old_path:
            paths.append(item.old_path)
        if item.path:
            paths.append(item.path)
    return _dedupe(paths)


def _items_to_status(items: list[ChangedFile]) -> list[dict[str, Any]]:
    return [{"status": item.status, "path": item.path, **({"old_path": item.old_path} if item.old_path else {})} for item in items]

def classify_changed_files(changed_paths: list[str], contract: dict[str, Any]) -> dict[str, list[str]]:
    candidate_patterns = _path_list(contract.get("candidate_edit_files") or contract.get("allowed_edit_files") or [])
    promoted_patterns = _path_list(contract.get("promoted_support_candidate_files") or [])
    candidate_patterns = _dedupe(candidate_patterns + promoted_patterns)
    allowed_patterns = candidate_patterns
    support_patterns = _path_list(contract.get("support_files") or contract.get("read_only_support_files") or [])
    verification_patterns = _path_list(contract.get("verification_files") or contract.get("suggested_tests") or [])
    verification_edit_patterns = _path_list(contract.get("verification_edit_files") or [])
    packet_patterns = _path_list(contract.get("packet_files") or [])
    if not packet_patterns:
        packet_patterns = _dedupe(candidate_patterns + support_patterns + verification_patterns)
    allowed_if_patterns = list(contract.get("allowed_if_justified") or [])
    forbidden_patterns = list(contract.get("forbidden_without_user_confirmation") or [])
    prompt_forbidden_patterns = list(contract.get("prompt_forbidden_files") or [])
    secret_patterns = list(contract.get("secret_like_patterns") or []) or SECRET_LIKE_PATTERNS
    generated_patterns = list(contract.get("generated_or_state_patterns") or []) or GENERATED_OR_STATE_PATTERNS
    dependency_patterns = list(contract.get("dependency_or_build_patterns") or []) or DEPENDENCY_OR_BUILD_PATTERNS
    ci_patterns = list(contract.get("ci_patterns") or []) or CI_PATTERNS

    out: dict[str, list[str]] = {
        "allowed_files_changed": [],
        "candidate_edit_files_changed": [],
        "promoted_support_candidate_files_changed": [],
        "verification_edit_files_changed": [],
        "support_files_changed": [],
        "packet_non_edit_files_changed": [],
        "outside_packet_files_changed": [],
        "allowed_if_justified_changed": [],
        "unexpected_files_changed": [],
        "forbidden_files_touched": [],
        "prompt_forbidden_files_touched": [],
        "secret_like_paths_touched": [],
        "generated_or_state_mutation": [],
        "dependency_or_build_files_changed": [],
        "ci_files_changed": [],
        "docs_only_changed": [],
        "tests_changed": [],
    }
    for path in changed_paths:
        if _matches(path, prompt_forbidden_patterns):
            out["prompt_forbidden_files_touched"].append(path)
        if _matches(path, forbidden_patterns):
            out["forbidden_files_touched"].append(path)
        if _matches(path, secret_patterns):
            out["secret_like_paths_touched"].append(path)
        if _matches(path, generated_patterns):
            out["generated_or_state_mutation"].append(path)
        if _matches(path, dependency_patterns):
            out["dependency_or_build_files_changed"].append(path)
        if _matches(path, ci_patterns):
            out["ci_files_changed"].append(path)
        if _matches(path, DOC_PATH_PATTERNS):
            out["docs_only_changed"].append(path)
        if _matches(path, TEST_PATH_PATTERNS):
            out["tests_changed"].append(path)

        in_candidate = _matches(path, candidate_patterns)
        in_promoted = _matches(path, promoted_patterns)
        in_verification_edit = _matches(path, verification_edit_patterns)
        in_support = _matches(path, support_patterns)
        in_packet = _matches(path, packet_patterns)

        if in_candidate:
            out["allowed_files_changed"].append(path)
            out["candidate_edit_files_changed"].append(path)
        if in_promoted:
            out["promoted_support_candidate_files_changed"].append(path)
        if in_verification_edit:
            out["verification_edit_files_changed"].append(path)
        if in_candidate or in_verification_edit:
            continue
        if in_support:
            out["support_files_changed"].append(path)
            out["unexpected_files_changed"].append(path)
        elif in_packet:
            out["packet_non_edit_files_changed"].append(path)
            out["unexpected_files_changed"].append(path)
        elif _matches(path, allowed_if_patterns):
            out["allowed_if_justified_changed"].append(path)
        elif not any(path in out[key] for key in ["forbidden_files_touched", "prompt_forbidden_files_touched", "secret_like_paths_touched", "generated_or_state_mutation"]):
            out["outside_packet_files_changed"].append(path)
            out["unexpected_files_changed"].append(path)

    classified = {k: _dedupe(v) for k, v in out.items()}
    classified["changed_candidate_files"] = list(classified.get("allowed_files_changed") or [])
    classified["changed_promoted_support_candidate_files"] = list(classified.get("promoted_support_candidate_files_changed") or [])
    classified["changed_verification_edit_files"] = list(classified.get("verification_edit_files_changed") or [])
    classified["changed_support_files"] = list(classified.get("support_files_changed") or [])
    classified["changed_packet_non_edit_files"] = list(classified.get("packet_non_edit_files_changed") or [])
    classified["changed_outside_packet_files"] = list(classified.get("outside_packet_files_changed") or [])
    classified["changed_unlisted_files"] = list(classified.get("unexpected_files_changed") or [])
    classified["changed_safety_blocked_files"] = _dedupe(
        list(classified.get("forbidden_files_touched") or [])
        + list(classified.get("secret_like_paths_touched") or [])
        + list(classified.get("generated_or_state_mutation") or [])
    )
    classified["changed_prompt_forbidden_files"] = list(classified.get("prompt_forbidden_files_touched") or [])
    return classified


def _split_findings(classified: dict[str, list[str]], verification: dict[str, Any], preexisting_paths: list[str] | None = None) -> dict[str, list[str]]:
    blocking: list[str] = []
    warning: list[str] = []
    info: list[str] = []
    for path in classified.get("prompt_forbidden_files_touched", []):
        blocking.append(f"{path} was changed but the saved context contract marked it as prompt-forbidden.")
    for path in classified.get("forbidden_files_touched", []):
        blocking.append(f"{path} was changed but the saved context contract marked it as safety-blocked without confirmation.")
    for path in classified.get("secret_like_paths_touched", []):
        blocking.append(f"{path} appears secret-like and must not be changed by an agent patch.")
    for path in classified.get("generated_or_state_mutation", []):
        blocking.append(f"{path} touched safety-blocked generated/state/proof output and requires explicit authorization.")
    for path in classified.get("dependency_or_build_files_changed", []):
        warning.append(f"{path} changed; dependency/build changes require review.")
    for path in classified.get("ci_files_changed", []):
        warning.append(f"{path} changed; CI workflow changes require review.")
    for path in classified.get("promoted_support_candidate_files_changed", []):
        info.append(f"{path} changed as a promoted support candidate within the saved context contract.")
    for path in classified.get("verification_edit_files_changed", []):
        info.append(f"{path} changed as verification evidence coverage within the saved context contract.")
    for path in classified.get("support_files_changed", []):
        warning.append(f"{path} changed in support/reference context rather than candidate edit files.")
    for path in classified.get("packet_non_edit_files_changed", []):
        warning.append(f"{path} changed inside the packet context but outside candidate or verification edit files.")
    for path in classified.get("outside_packet_files_changed", []):
        warning.append(f"{path} changed outside the saved packet context and outside the saved context contract.")
    legacy_unexpected = set(
        classified.get("support_files_changed", [])
        + classified.get("packet_non_edit_files_changed", [])
        + classified.get("outside_packet_files_changed", [])
    )
    for path in classified.get("unexpected_files_changed", []):
        if path not in legacy_unexpected:
            warning.append(f"{path} changed outside the saved context contract.")
    status = verification.get("verification_status")
    if status == "claimed_without_evidence":
        warning.append("Tests were claimed but no supporting evidence was found.")
    elif status == "missing_evidence":
        warning.append("No test evidence found for a code patch.")
    elif status == "evidence_present_but_unbound":
        warning.append("Test evidence was found, but it was not bound to the current packet_sha256/run identity.")
    elif status == "failed_evidence_found":
        blocking.append("Failed test evidence was found.")
    for path in preexisting_paths or []:
        info.append(f"{path} was already dirty or untracked at compile time and is ignored for working-tree readiness because it is unchanged.")
    return {
        "blocking_findings": _dedupe(blocking),
        "warning_findings": _dedupe(warning),
        "info_findings": _dedupe(info),
    }


def _risk_findings(classified: dict[str, list[str]], verification: dict[str, Any], preexisting_paths: list[str] | None = None) -> list[str]:
    split = _split_findings(classified, verification, preexisting_paths=preexisting_paths)
    return split["blocking_findings"] + split["warning_findings"] + split["info_findings"]


def _merge_readiness(classified: dict[str, list[str]], verification: dict[str, Any], changed_paths: list[str]) -> str:
    if not changed_paths:
        return "pass"
    blocking_keys = [
        "secret_like_paths_touched", "prompt_forbidden_files_touched", "forbidden_files_touched", "generated_or_state_mutation",
    ]
    if any(classified.get(key) for key in blocking_keys):
        return "blocked"
    if verification.get("verification_status") == "failed_evidence_found":
        return "blocked"
    warning_keys = [
        "unexpected_files_changed", "dependency_or_build_files_changed", "ci_files_changed", "allowed_if_justified_changed",
    ]
    if any(classified.get(key) for key in warning_keys):
        return "warning"
    if verification.get("verification_status") in {"missing_evidence", "claimed_without_evidence", "evidence_present_but_unbound"}:
        return "warning"
    return "pass"


def _recommended_next_step(readiness: str, classified: dict[str, list[str]], verification: dict[str, Any], changed_paths: list[str]) -> str:
    if not changed_paths:
        return "No patch changes detected."
    if classified.get("prompt_forbidden_files_touched"):
        return "Revert prompt-forbidden files or rerun compile with explicit authorization."
    if classified.get("secret_like_paths_touched"):
        return "Revert secret-like file changes before review."
    if classified.get("forbidden_files_touched"):
        return "Revert safety-blocked files or get explicit user confirmation before review."
    if classified.get("generated_or_state_mutation"):
        return "Revert generated/state/proof mutations unless the user explicitly authorized them."
    if verification.get("verification_status") == "failed_evidence_found":
        return "Fix failing tests or revert the patch before review."
    if verification.get("verification_status") == "evidence_present_but_unbound":
        return "Attach test evidence bound to the current packet_sha256/run identity before review."
    if verification.get("verification_status") in {"missing_evidence", "claimed_without_evidence"}:
        return "Verify tests and attach evidence before review."
    if readiness == "warning":
        return "Review changes outside the saved context contract or build/CI/dependency changes."
    return "Patch stayed inside the saved context contract; continue normal code review."


def _is_ignored_runtime_metadata(item: ChangedFile) -> bool:
    paths = [_norm(item.path)]
    if item.old_path:
        paths.append(_norm(item.old_path))
    ignored_prefixes = (
        "premode/out/", "premode/audit/", "premode/metrics/", "premode/index/",
        ".premode/out/", ".premode/audit/", ".premode/metrics/", ".premode/index/",
    )
    ignored_files = {"premode/out/discovered_commands.json", ".premode/out/discovered_commands.json"}
    # Ignore only records where every path belongs to Pre-mode runtime metadata.
    return all(any(path.startswith(prefix) for prefix in ignored_prefixes) or path in ignored_files for path in paths if path)


def review_patch(
    repo_root: Path,
    *,
    base_ref: str = "main",
    packet_path: Path | None = None,
    claims_path: Path | None = None,
    out_path: Path | None = None,
    since_compile: bool = False,
) -> dict[str, Any]:
    repo_root = Path(repo_root)
    if not _is_git_repo(repo_root):
        return {
            "schema_version": 1,
            "review_kind": "patch_review",
            "error": "review-patch requires a git repository.",
            "merge_readiness": "blocked",
            "recommended_next_step": "Run this command from inside a git repository.",
        }

    packet_path = packet_path or default_packet_path(repo_root)
    packet_abs = packet_path if packet_path.is_absolute() else repo_root / packet_path
    if not packet_abs.exists():
        return {
            "schema_version": 1,
            "review_kind": "patch_review",
            "base_ref": base_ref,
            "packet_path": str(packet_path),
            "error": "No saved Pre-mode packet found. Run premode compile --save or pcodex first.",
            "merge_readiness": "blocked",
            "recommended_next_step": "Run premode compile --save or pcodex first.",
        }

    packet = _load_json(packet_abs)
    contract = _extract_review_contract(packet)
    pre_state = _pre_agent_state_from_packet(packet, contract)
    effective_base_ref = base_ref
    since_compile_error: str | None = None
    if since_compile:
        saved_head = str(pre_state.get("git_head_sha") or "").strip()
        if saved_head:
            effective_base_ref = saved_head
        else:
            since_compile_error = "Saved packet does not include pre_agent_worktree_state.git_head_sha; falling back to --against."
    changed, diff_meta = _changed_files(repo_root, effective_base_ref)
    if since_compile:
        diff_meta["review_mode"] = "since_compile"
        diff_meta["saved_git_head_sha"] = pre_state.get("git_head_sha")
        if since_compile_error:
            diff_meta["since_compile_warning"] = since_compile_error
    else:
        diff_meta["review_mode"] = "against_ref"
    changed = [item for item in changed if not _is_ignored_runtime_metadata(item)]
    preexisting_items, agent_items = _split_preexisting_changes(repo_root, changed, pre_state)
    all_changed_paths = _items_to_paths(changed)
    preexisting_paths = _items_to_paths(preexisting_items)
    agent_paths = _items_to_paths(agent_items)
    classification_paths = _items_to_paths(agent_items, include_old=True)
    classified = classify_changed_files(classification_paths, contract)
    docs_only = bool(agent_paths) and len(classified.get("docs_only_changed", [])) == len(agent_paths)
    verification = _verification(repo_root, contract, claims_path, agent_paths, docs_only)
    readiness = _merge_readiness(classified, verification, agent_paths)
    finding_groups = _split_findings(classified, verification, preexisting_paths=preexisting_paths)
    findings = finding_groups["blocking_findings"] + finding_groups["warning_findings"] + finding_groups["info_findings"]
    report: dict[str, Any] = {
        "schema_version": 1,
        "review_kind": "patch_review",
        "base_ref": base_ref,
        "base_ref_requested": diff_meta.get("base_ref_requested", base_ref),
        "base_ref_used": diff_meta.get("base_ref_used"),
        "base_ref_fallback_reason": diff_meta.get("base_ref_fallback_reason"),
        "since_compile": bool(since_compile),
        "packet_path": str(packet_path),
        "packet_sha256": contract.get("packet_sha256"),
        "raw_prompt_sha256": contract.get("raw_prompt_sha256"),
        "all_current_changed_files": all_changed_paths,
        "preexisting_changes": preexisting_paths,
        "post_compile_changes": agent_paths,
        "agent_candidate_changes": agent_paths,
        "changed_files": agent_paths,
        "changed_file_status": _items_to_status(agent_items),
        "all_changed_file_status": _items_to_status(changed),
        "preexisting_change_status": _items_to_status(preexisting_items),
        "pre_agent_worktree_state": {k: v for k, v in pre_state.items() if k != "file_hashes_at_compile"},
        **classified,
        "scope_compliance": "pass",
        "verification": verification,
        "validation_evidence": verification.get("validation_evidence") or [],
        "vague_validation_claims": verification.get("vague_validation_claims") or [],
        "blocking_findings": finding_groups["blocking_findings"],
        "warning_findings": finding_groups["warning_findings"],
        "info_findings": finding_groups["info_findings"],
        "risk_findings": findings,
        "merge_readiness": readiness,
        "working_tree_readiness": readiness,
        "staged_patch_readiness": "not_evaluated",
        "staged_patch_readiness_note": "Staged-only review is deferred; this report evaluates the working tree diff.",
        "recommended_next_step": _recommended_next_step(readiness, classified, verification, agent_paths),
        "diff_metadata": diff_meta,
    }
    if classified.get("unexpected_files_changed") or classified.get("dependency_or_build_files_changed") or classified.get("ci_files_changed") or classified.get("allowed_if_justified_changed"):
        report["scope_compliance"] = "warning"
    if readiness == "blocked":
        report["scope_compliance"] = "blocked"
    if out_path:
        out_abs = out_path if out_path.is_absolute() else repo_root / out_path
        out_abs.parent.mkdir(parents=True, exist_ok=True)
        out_abs.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def format_review_report(report: dict[str, Any]) -> str:
    if report.get("error"):
        return f"Patch review: BLOCKED\n{report['error']}\nRecommended next step:\n{report.get('recommended_next_step', '')}".rstrip()
    readiness = str(report.get("merge_readiness") or "warning").upper()
    lines = [
        f"Patch review: {readiness}",
        f"Working tree readiness: {str(report.get('working_tree_readiness') or report.get('merge_readiness') or 'warning')}",
        f"Staged patch readiness: {str(report.get('staged_patch_readiness') or 'not_evaluated')}",
        f"Changed files: {len(report.get('changed_files') or [])}",
        f"Preexisting ignored: {len(report.get('preexisting_changes') or [])}",
        f"Changed candidate files: {len(report.get('changed_candidate_files') or [])}",
        f"Changed promoted support candidate files: {len(report.get('changed_promoted_support_candidate_files') or [])}",
        f"Changed verification edit files: {len(report.get('changed_verification_edit_files') or [])}",
        f"Changed support files: {len(report.get('changed_support_files') or [])}",
        f"Changed packet non-edit files: {len(report.get('changed_packet_non_edit_files') or [])}",
        f"Changed outside-packet files: {len(report.get('changed_outside_packet_files') or [])}",
        f"Changed unlisted files: {len(report.get('changed_unlisted_files') or [])}",
        f"Changed safety-blocked files: {len(report.get('changed_safety_blocked_files') or [])}",
        f"Changed prompt-forbidden files: {len(report.get('changed_prompt_forbidden_files') or [])}",
        f"Secret-like: {len(report.get('secret_like_paths_touched') or [])}",
        f"Generated/state/proof: {len(report.get('generated_or_state_mutation') or [])}",
    ]
    verification = report.get("verification") or {}
    if verification:
        lines.append(f"Verification: {verification.get('verification_status', 'unknown')}")
    for label, key in (("Blocking findings", "blocking_findings"), ("Warning findings", "warning_findings"), ("Info findings", "info_findings")):
        findings = report.get(key) or []
        if findings:
            lines.append(f"{label}:")
            lines.extend(f"- {item}" for item in findings)
    lines.append("Recommended next step:")
    lines.append(str(report.get("recommended_next_step") or "Review the patch manually."))
    return "\n".join(lines)
