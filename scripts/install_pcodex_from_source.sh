#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${HOME}/.pcodex-alpha"
RUN_SMOKE=1
MCP_MODE="none"
VERBOSE=0
UNINSTALL=0
PYTHON_BIN=""
BUILD_ROOT=""

log() { printf '[pcodex-source] %s\n' "$*"; }
fail() { printf '[pcodex-source] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: install_pcodex_from_source.sh [options]

Install pCodex from a checked-out source tree into an isolated user-local venv.

Options:
  --install-root PATH          Install venv root. Default: $HOME/.pcodex-alpha
  --isolated-mcp               Register/list/get/remove pCodex using isolated CODEX_HOME under install root.
  --real-codex-registration    Register pCodex in the real Codex MCP config. Explicit opt-in only.
  --skip-smoke                 Skip premode/pcodex help and status smoke checks.
  --verbose                    Print shell trace while running install steps.
  --uninstall                  Remove only the install root created by this installer.
  --help                       Show this help.

This installer builds from the local source checkout. It does not use PyPI
packages for premode-router or premode-plugin-literal-symbol, does not publish
anything, does not run live Codex tasks, and does not mutate real Codex config
unless --real-codex-registration is passed explicitly.
USAGE
}

script_dir() {
  local source="${BASH_SOURCE[0]}"
  local dir
  while [[ -h "$source" ]]; do
    dir="$(cd -P "$(dirname "$source")" >/dev/null 2>&1 && pwd)"
    source="$(readlink "$source")"
    [[ "$source" != /* ]] && source="$dir/$source"
  done
  cd -P "$(dirname "$source")" >/dev/null 2>&1 && pwd
}

require_repo_layout() {
  [[ -f "$REPO_ROOT/pyproject.toml" ]] || fail "missing pyproject.toml at repo root: $REPO_ROOT"
  [[ -f "$REPO_ROOT/packages/premode-plugin-literal-symbol/pyproject.toml" ]] || fail "missing plugin pyproject.toml"
  [[ -d "$REPO_ROOT/src/premode" ]] || fail "missing src/premode package directory"
}

cleanup_build_root() {
  if [[ -n "${BUILD_ROOT:-}" && -d "$BUILD_ROOT" ]]; then
    rm -rf "$BUILD_ROOT"
  fi
}

select_python() {
  local candidate
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PYVERSION' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PYVERSION
      then
        if "$candidate" -m venv --help >/dev/null 2>&1; then
          PYTHON_BIN="$(command -v "$candidate")"
          return 0
        fi
        fail "Python >=3.11 was found at $(command -v "$candidate"), but venv support is missing. Install Python with venv support, then rerun."
      fi
    fi
  done
  fail "Python >=3.11 with venv support is required. Install python3.11 or newer, then rerun."
}

safe_remove_install_root() {
  [[ -n "$INSTALL_ROOT" ]] || fail "refusing to remove an empty install root"
  case "$INSTALL_ROOT" in
    "/"|"$HOME"|"$REPO_ROOT"|"$REPO_ROOT"/*)
      fail "refusing to remove unsafe install root: $INSTALL_ROOT"
      ;;
  esac
  if [[ -d "$INSTALL_ROOT" ]]; then
    rm -rf "$INSTALL_ROOT"
    log "removed install root: $INSTALL_ROOT"
  else
    log "install root does not exist: $INSTALL_ROOT"
  fi
}

run_cmd() {
  log "running: $*"
  "$@"
}

run_smoke() {
  run_cmd "$INSTALL_ROOT/bin/premode" --help
  run_cmd "$INSTALL_ROOT/bin/pcodex" --help
  run_cmd "$INSTALL_ROOT/bin/pcodex" status
}

run_isolated_mcp_smoke() {
  if ! command -v codex >/dev/null 2>&1; then
    log "codex command not found; isolated MCP registration smoke skipped"
    return 0
  fi
  local isolated_home="$INSTALL_ROOT/codex_home"
  mkdir -p "$isolated_home"
  log "running isolated MCP registration smoke with CODEX_HOME=$isolated_home"
  CODEX_HOME="$isolated_home" codex mcp add pcodex -- "$INSTALL_ROOT/bin/pcodex" mcp-server
  CODEX_HOME="$isolated_home" codex mcp list --json || true
  CODEX_HOME="$isolated_home" codex mcp get pcodex || true
  CODEX_HOME="$isolated_home" codex mcp remove pcodex || true
}

run_real_codex_registration() {
  command -v codex >/dev/null 2>&1 || fail "codex command not found; cannot register real Codex MCP config"
  log "WARNING: mutating real Codex MCP config because --real-codex-registration was explicitly passed"
  run_cmd codex mcp add pcodex -- "$INSTALL_ROOT/bin/pcodex" mcp-server
  log "rollback command: codex mcp remove pcodex"
}

prepare_build_source() {
  BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/pcodex-source-build.XXXXXX")"
  local build_repo="$BUILD_ROOT/source"
  log "copying source to temporary build directory: $build_repo"
  "$PYTHON_BIN" - "$REPO_ROOT" "$build_repo" <<'PYCOPY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

ignore_names = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
}


def ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in ignore_names or name.endswith(".egg-info"):
            ignored.add(name)
    return ignored


shutil.copytree(src, dst, ignore=ignore)
PYCOPY
  printf '%s\n' "$build_repo"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-root) INSTALL_ROOT="${2:?missing install root}"; shift 2 ;;
    --isolated-mcp) MCP_MODE="isolated"; shift ;;
    --real-codex-registration) MCP_MODE="real"; shift ;;
    --skip-smoke) RUN_SMOKE=0; shift ;;
    --verbose) VERBOSE=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --help) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

SCRIPT_DIR="$(script_dir)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P)"
INSTALL_ROOT="${INSTALL_ROOT%/}"

[[ "$VERBOSE" -eq 0 ]] || set -x
trap cleanup_build_root EXIT

require_repo_layout

if [[ "$UNINSTALL" -eq 1 ]]; then
  safe_remove_install_root
  exit 0
fi

select_python

log "repo root: $REPO_ROOT"
log "install root: $INSTALL_ROOT"
log "using Python: $PYTHON_BIN"

run_cmd "$PYTHON_BIN" -m venv "$INSTALL_ROOT"

if ! "$INSTALL_ROOT/bin/python" -m pip --version >/dev/null 2>&1; then
  log "pip missing in venv; attempting ensurepip"
  run_cmd "$INSTALL_ROOT/bin/python" -m ensurepip --upgrade
fi

run_cmd "$INSTALL_ROOT/bin/python" -m pip install --upgrade pip setuptools wheel
BUILD_REPO_ROOT="$(prepare_build_source | tail -n 1)"
run_cmd "$INSTALL_ROOT/bin/python" -m pip install "$BUILD_REPO_ROOT"
run_cmd "$INSTALL_ROOT/bin/python" -m pip install "$BUILD_REPO_ROOT/packages/premode-plugin-literal-symbol"

[[ "$RUN_SMOKE" -eq 0 ]] || run_smoke

case "$MCP_MODE" in
  none) ;;
  isolated) run_isolated_mcp_smoke ;;
  real) run_real_codex_registration ;;
  *) fail "unknown MCP mode: $MCP_MODE" ;;
esac

log "source install complete"
log "optional PATH line: export PATH=\"$INSTALL_ROOT/bin:\$PATH\""
log "next checks:"
log "  $INSTALL_ROOT/bin/pcodex status"
log "  $INSTALL_ROOT/bin/pcodex setup --no-mcp"
log "  $INSTALL_ROOT/bin/pcodex run --dry-run \"Hypothetical dummy task: inspect this repo. Do not modify files.\""
