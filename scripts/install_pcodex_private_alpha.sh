#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_ROOT="/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact"
INSTALL_ROOT="/private/tmp/premode_alpha_install"
CODEX_MODE="isolated"
UNINSTALL=0
SAFE_DUMMY_PROMPT="Hypothetical dummy task: inspect a file named hello.txt and report whether it contains the text hello from pcodex. Do not modify files."
PYTHON_BIN=""

usage() {
  cat <<'USAGE'
Usage: install_pcodex_private_alpha.sh [options]

Options:
  --artifact-root PATH              Local artifact root containing dist_core and dist_plugin.
  --install-root PATH               Local install root. Default: /private/tmp/premode_alpha_install
  --skip-codex-registration         Do not run codex mcp registration smoke.
  --isolated-codex-registration     Register/remove pcodex under install-root/codex_home only. Default.
  --real-codex-registration         Mutate real local Codex MCP config. Requires explicit flag.
  --uninstall                       Remove install-root venv and isolated codex_home only.
  --help                            Show this help.

Default behavior installs from local artifacts only, runs command smoke, and uses isolated CODEX_HOME if codex is available.
No live Codex task is run.
USAGE
}

log() { printf '[pcodex-alpha] %s\n' "$*"; }
fail() { printf '[pcodex-alpha] ERROR: %s\n' "$*" >&2; exit 1; }

select_python() {
  local candidate
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PYVERSION' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PYVERSION
      then
        PYTHON_BIN="$candidate"
        return 0
      fi
    fi
  done
  fail "Python >=3.11 is required; install python3.11 or python3.12 and rerun"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-root) ARTIFACT_ROOT="${2:?missing artifact root}"; shift 2 ;;
    --install-root) INSTALL_ROOT="${2:?missing install root}"; shift 2 ;;
    --skip-codex-registration) CODEX_MODE="skip"; shift ;;
    --isolated-codex-registration) CODEX_MODE="isolated"; shift ;;
    --real-codex-registration) CODEX_MODE="real"; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --help) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

VENV="$INSTALL_ROOT/venv"
ISOLATED_CODEX_HOME="$INSTALL_ROOT/codex_home"
BENCHMARK_OUT="$INSTALL_ROOT/benchmark_literal_symbol.json"
REPORT_OUT="$INSTALL_ROOT/install_report.txt"

if [[ "$UNINSTALL" -eq 1 ]]; then
  log "uninstall mode: removing isolated install artifacts under $INSTALL_ROOT"
  rm -rf "$VENV" "$ISOLATED_CODEX_HOME"
  log "removed: $VENV"
  log "removed: $ISOLATED_CODEX_HOME"
  log "real Codex config was not modified by uninstall mode"
  exit 0
fi

[[ -d "$ARTIFACT_ROOT/dist_core" ]] || fail "missing dist_core under $ARTIFACT_ROOT"
[[ -d "$ARTIFACT_ROOT/dist_plugin" ]] || fail "missing dist_plugin under $ARTIFACT_ROOT"
[[ -f "$ARTIFACT_ROOT/dist_core/premode_router-0.2.6.24-py3-none-any.whl" ]] || fail "missing core wheel"
[[ -f "$ARTIFACT_ROOT/dist_plugin/premode_plugin_literal_symbol-0.1.0-py3-none-any.whl" ]] || fail "missing plugin wheel"

mkdir -p "$INSTALL_ROOT"
: > "$REPORT_OUT"
log "install root: $INSTALL_ROOT" | tee -a "$REPORT_OUT"
log "artifact root: $ARTIFACT_ROOT" | tee -a "$REPORT_OUT"
select_python
log "using Python: $PYTHON_BIN" | tee -a "$REPORT_OUT"
log "creating venv" | tee -a "$REPORT_OUT"
"$PYTHON_BIN" -m venv "$VENV"
# shellcheck disable=SC1091
. "$VENV/bin/activate"

log "installing from local artifacts only" | tee -a "$REPORT_OUT"
python -m pip install --no-index \
  --find-links "$ARTIFACT_ROOT/dist_core" \
  --find-links "$ARTIFACT_ROOT/dist_plugin" \
  premode-router premode-plugin-literal-symbol | tee -a "$REPORT_OUT"

run_cmd() {
  log "running: $*" | tee -a "$REPORT_OUT"
  "$@" 2>&1 | tee -a "$REPORT_OUT"
}

run_cmd which premode
run_cmd which pcodex
run_cmd premode --help
run_cmd premode compile --help
run_cmd premode benchmark --help
run_cmd pcodex --help
run_cmd pcodex doctor
run_cmd pcodex status
run_cmd pcodex compile --help
run_cmd pcodex run --dry-run "$SAFE_DUMMY_PROMPT"
run_cmd pcodex mcp-server --help
run_cmd premode compile --plugin literal_symbol --help
run_cmd premode benchmark --profile lite --json --plugin literal_symbol --out "$BENCHMARK_OUT"

if [[ "$CODEX_MODE" == "skip" ]]; then
  log "codex MCP registration smoke skipped" | tee -a "$REPORT_OUT"
elif ! command -v codex >/dev/null 2>&1; then
  log "codex command not found; MCP registration smoke skipped" | tee -a "$REPORT_OUT"
elif [[ "$CODEX_MODE" == "isolated" ]]; then
  log "running isolated Codex MCP registration smoke" | tee -a "$REPORT_OUT"
  mkdir -p "$ISOLATED_CODEX_HOME"
  export CODEX_HOME="$ISOLATED_CODEX_HOME"
  run_cmd codex mcp add pcodex -- pcodex mcp-server
  codex mcp list --json 2>&1 | tee -a "$REPORT_OUT" || true
  codex mcp get pcodex 2>&1 | tee -a "$REPORT_OUT" || true
  codex mcp remove pcodex 2>&1 | tee -a "$REPORT_OUT" || true
  codex mcp list --json 2>&1 | tee -a "$REPORT_OUT" || true
elif [[ "$CODEX_MODE" == "real" ]]; then
  log "This mutates your real local Codex MCP config. Continuing only because --real-codex-registration was explicitly provided." | tee -a "$REPORT_OUT"
  run_cmd codex mcp add pcodex -- pcodex mcp-server
  log "rollback real config with: codex mcp remove pcodex" | tee -a "$REPORT_OUT"
else
  fail "unknown CODEX_MODE: $CODEX_MODE"
fi

log "install smoke complete" | tee -a "$REPORT_OUT"
log "rollback isolated install with: $0 --install-root '$INSTALL_ROOT' --uninstall" | tee -a "$REPORT_OUT"
