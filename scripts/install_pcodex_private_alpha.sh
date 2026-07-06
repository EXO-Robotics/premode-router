#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_ROOT="/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact"
INSTALL_ROOT="${HOME}/.pcodex-alpha"
CODEX_MODE="isolated"
UNINSTALL=0
SKIP_HASH_CHECK=0
SYSTEM_DEPS_MODE="no"
SAFE_DUMMY_PROMPT="Hypothetical dummy task: inspect a file named hello.txt and report whether it contains the text hello from pcodex. Do not modify files."
PYTHON_BIN=""

usage() {
  cat <<'USAGE'
Usage: install_pcodex_private_alpha.sh [options]

Options:
  --artifact-root PATH              Local artifact root containing dist_core and dist_plugin.
  --install-root PATH               Local install root. Default: $HOME/.pcodex-alpha
  --skip-codex-registration         Do not run codex mcp registration smoke.
  --isolated-codex-registration     Register/remove pcodex under install-root/codex_home only. Default.
  --real-codex-registration         Mutate real local Codex MCP config. Requires explicit flag.
  --skip-hash-check                 Skip SHA256SUMS.txt verification when checksum files are present.
  --allow-system-deps               Allow non-sudo package-manager repair for missing Python dependencies.
  --no-system-deps                  Do not install system dependencies. Default.
  --assume-yes-system-deps          Use noninteractive yes flags with --allow-system-deps where supported.
  --uninstall                       Remove install-root venv, shims, env file, and isolated codex_home only.
  --help                            Show this help.

Default behavior installs from local artifacts only, verifies hashes when checksum files exist,
creates absolute shims under install-root/bin, runs command smoke through those shims, and uses
isolated CODEX_HOME if codex is available. No live Codex task is run.
USAGE
}

log() { printf '[pcodex-alpha] %s\n' "$*"; }
fail() { printf '[pcodex-alpha] ERROR: %s\n' "$*" >&2; exit 1; }

repair_command_for_platform() {
  if command -v brew >/dev/null 2>&1; then
    printf 'brew install python@3.11\n'
  elif command -v apt >/dev/null 2>&1; then
    printf 'sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip\n'
  elif command -v dnf >/dev/null 2>&1; then
    printf 'sudo dnf install -y python3.11 python3.11-pip\n'
  elif command -v yum >/dev/null 2>&1; then
    printf 'sudo yum install -y python3.11 python3-pip\n'
  elif command -v pacman >/dev/null 2>&1; then
    printf 'sudo pacman -S --needed python python-pip\n'
  elif command -v zypper >/dev/null 2>&1; then
    printf 'sudo zypper install python311 python311-pip\n'
  else
    printf 'Install Python >=3.11 with venv and pip using your system package manager.\n'
  fi
}

attempt_system_deps_repair() {
  [[ "$SYSTEM_DEPS_MODE" == "allow" || "$SYSTEM_DEPS_MODE" == "assume_yes" ]] || return 1
  if command -v brew >/dev/null 2>&1; then
    log "attempting non-sudo Python repair with Homebrew"
    if [[ "$SYSTEM_DEPS_MODE" == "assume_yes" ]]; then
      brew install python@3.11
    else
      brew install python@3.11
    fi
    return 0
  fi
  return 1
}

select_python() {
  local candidate repair
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
        repair="$(repair_command_for_platform)"
        fail "Python >=3.11 was found at $(command -v "$candidate"), but venv support is missing. Repair suggestion: $repair"
      fi
    fi
  done

  if attempt_system_deps_repair; then
    for candidate in python3.12 python3.11 python3; do
      if command -v "$candidate" >/dev/null 2>&1 && "$candidate" - <<'PYVERSION' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PYVERSION
      then
        PYTHON_BIN="$(command -v "$candidate")"
        return 0
      fi
    done
  fi

  repair="$(repair_command_for_platform)"
  fail "Python >=3.11 with venv support is required. Repair suggestion: $repair. System dependency installation is opt-in via --allow-system-deps."
}

verify_artifact_layout() {
  [[ -d "$ARTIFACT_ROOT/dist_core" ]] || fail "missing dist_core under $ARTIFACT_ROOT"
  [[ -d "$ARTIFACT_ROOT/dist_plugin" ]] || fail "missing dist_plugin under $ARTIFACT_ROOT"
  [[ -f "$ARTIFACT_ROOT/dist_core/premode_router-0.2.6.24-py3-none-any.whl" ]] || fail "missing core wheel"
  [[ -f "$ARTIFACT_ROOT/dist_plugin/premode_plugin_literal_symbol-0.1.0-py3-none-any.whl" ]] || fail "missing plugin wheel"
}

hash_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    fail "cannot verify SHA256SUMS.txt because neither shasum nor sha256sum is available"
  fi
}

verify_hashes_if_present() {
  local sums="$ARTIFACT_ROOT/SHA256SUMS.txt"
  local rel expected actual file mismatch=0
  [[ "$SKIP_HASH_CHECK" -eq 0 ]] || {
    log "hash verification skipped by --skip-hash-check"
    return 0
  }
  [[ -f "$sums" ]] || {
    log "no SHA256SUMS.txt found under artifact root; hash verification not available"
    return 0
  }

  log "verifying artifact hashes from $sums" | tee -a "$REPORT_OUT"
  while read -r expected rel; do
    [[ -n "${expected:-}" ]] || continue
    [[ "${expected:0:1}" == "#" ]] && continue
    rel="${rel#\\*}"
    rel="${rel#./}"
    file="$ARTIFACT_ROOT/$rel"
    if [[ ! -f "$file" ]]; then
      printf '[pcodex-alpha] HASH MISSING: %s\n' "$rel" >&2
      mismatch=1
      continue
    fi
    actual="$(hash_file "$file")"
    if [[ "$actual" != "$expected" ]]; then
      printf '[pcodex-alpha] HASH MISMATCH: %s expected=%s actual=%s\n' "$rel" "$expected" "$actual" >&2
      mismatch=1
    fi
  done < "$sums"
  [[ "$mismatch" -eq 0 ]] || fail "hash verification failed; install stopped before creating venv"
  log "hash verification passed" | tee -a "$REPORT_OUT"
}

write_shim() {
  local shim_path="$1"
  local target_path="$2"
  cat > "$shim_path" <<SHIM
#!/usr/bin/env bash
set -euo pipefail
exec "$target_path" "\$@"
SHIM
  chmod +x "$shim_path"
}

run_cmd() {
  log "running: $*" | tee -a "$REPORT_OUT"
  "$@" 2>&1 | tee -a "$REPORT_OUT"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-root) ARTIFACT_ROOT="${2:?missing artifact root}"; shift 2 ;;
    --install-root) INSTALL_ROOT="${2:?missing install root}"; shift 2 ;;
    --skip-codex-registration) CODEX_MODE="skip"; shift ;;
    --isolated-codex-registration) CODEX_MODE="isolated"; shift ;;
    --real-codex-registration) CODEX_MODE="real"; shift ;;
    --skip-hash-check) SKIP_HASH_CHECK=1; shift ;;
    --allow-system-deps) SYSTEM_DEPS_MODE="allow"; shift ;;
    --no-system-deps) SYSTEM_DEPS_MODE="no"; shift ;;
    --assume-yes-system-deps) SYSTEM_DEPS_MODE="assume_yes"; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --help) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

ARTIFACT_ROOT="$(cd "$ARTIFACT_ROOT" 2>/dev/null && pwd -P)" || fail "artifact root does not exist: $ARTIFACT_ROOT"
INSTALL_ROOT="${INSTALL_ROOT%/}"
VENV="$INSTALL_ROOT/venv"
BIN_DIR="$INSTALL_ROOT/bin"
ISOLATED_CODEX_HOME="$INSTALL_ROOT/codex_home"
ENV_FILE="$INSTALL_ROOT/pcodex-alpha.env"
BENCHMARK_OUT="$INSTALL_ROOT/benchmark_literal_symbol.json"
REPORT_OUT="$INSTALL_ROOT/install_report.txt"
PREMODE_SHIM="$BIN_DIR/premode"
PCODEX_SHIM="$BIN_DIR/pcodex"

if [[ "$UNINSTALL" -eq 1 ]]; then
  log "uninstall mode: removing isolated install artifacts under $INSTALL_ROOT"
  rm -rf "$VENV" "$BIN_DIR" "$ISOLATED_CODEX_HOME" "$ENV_FILE" "$BENCHMARK_OUT" "$REPORT_OUT"
  log "removed: $VENV"
  log "removed: $BIN_DIR"
  log "removed: $ISOLATED_CODEX_HOME"
  log "removed: $ENV_FILE"
  log "real Codex config was not modified by uninstall mode"
  exit 0
fi

if [[ "$CODEX_MODE" == "real" ]]; then
  log "real Codex config registration was explicitly requested"
elif [[ "$CODEX_MODE" != "isolated" && "$CODEX_MODE" != "skip" ]]; then
  fail "unknown CODEX_MODE: $CODEX_MODE"
fi

mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
: > "$REPORT_OUT"
log "install root: $INSTALL_ROOT" | tee -a "$REPORT_OUT"
log "artifact root: $ARTIFACT_ROOT" | tee -a "$REPORT_OUT"
log "system dependency mode: $SYSTEM_DEPS_MODE" | tee -a "$REPORT_OUT"
verify_artifact_layout
verify_hashes_if_present
select_python

log "using Python: $PYTHON_BIN" | tee -a "$REPORT_OUT"
log "creating venv" | tee -a "$REPORT_OUT"
"$PYTHON_BIN" -m venv "$VENV"

if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  log "pip missing in venv; attempting ensurepip" | tee -a "$REPORT_OUT"
  "$VENV/bin/python" -m ensurepip --upgrade 2>&1 | tee -a "$REPORT_OUT" || fail "pip is missing and ensurepip failed. Repair Python with pip support, then rerun."
fi

log "installing from local artifacts only" | tee -a "$REPORT_OUT"
"$VENV/bin/python" -m pip install --no-index \
  --find-links "$ARTIFACT_ROOT/dist_core" \
  --find-links "$ARTIFACT_ROOT/dist_plugin" \
  premode-router premode-plugin-literal-symbol 2>&1 | tee -a "$REPORT_OUT"

write_shim "$PREMODE_SHIM" "$VENV/bin/premode"
write_shim "$PCODEX_SHIM" "$VENV/bin/pcodex"
cat > "$ENV_FILE" <<ENV
export PCODEX_ALPHA_ROOT="$INSTALL_ROOT"
export PATH="$BIN_DIR:\$PATH"
ENV

log "created shims: $PREMODE_SHIM $PCODEX_SHIM" | tee -a "$REPORT_OUT"
log "optional PATH line: export PATH=\"$BIN_DIR:\$PATH\"" | tee -a "$REPORT_OUT"

run_cmd "$PREMODE_SHIM" --help
run_cmd "$PREMODE_SHIM" compile --help
run_cmd "$PREMODE_SHIM" compile --plugin literal_symbol --no-record "$SAFE_DUMMY_PROMPT"
run_cmd "$PREMODE_SHIM" benchmark --help
run_cmd "$PCODEX_SHIM" --help
run_cmd "$PCODEX_SHIM" doctor
run_cmd "$PCODEX_SHIM" status
run_cmd "$PCODEX_SHIM" status --json
run_cmd "$PCODEX_SHIM" compile --help
run_cmd "$PCODEX_SHIM" tune --help
run_cmd "$PCODEX_SHIM" run --dry-run "$SAFE_DUMMY_PROMPT"
run_cmd "$PCODEX_SHIM" mcp-server --help
run_cmd "$PREMODE_SHIM" benchmark --profile lite --json --plugin literal_symbol --out "$BENCHMARK_OUT"

if [[ "$CODEX_MODE" == "skip" ]]; then
  log "codex MCP registration smoke skipped" | tee -a "$REPORT_OUT"
elif ! command -v codex >/dev/null 2>&1; then
  log "codex command not found; MCP registration smoke skipped" | tee -a "$REPORT_OUT"
elif [[ "$CODEX_MODE" == "isolated" ]]; then
  log "running isolated Codex MCP registration smoke with absolute pcodex shim" | tee -a "$REPORT_OUT"
  mkdir -p "$ISOLATED_CODEX_HOME"
  export CODEX_HOME="$ISOLATED_CODEX_HOME"
  run_cmd codex mcp add pcodex -- "$PCODEX_SHIM" mcp-server
  codex mcp list --json 2>&1 | tee -a "$REPORT_OUT" || true
  codex mcp get pcodex 2>&1 | tee -a "$REPORT_OUT" || true
  codex mcp remove pcodex 2>&1 | tee -a "$REPORT_OUT" || true
  codex mcp list --json 2>&1 | tee -a "$REPORT_OUT" || true
elif [[ "$CODEX_MODE" == "real" ]]; then
  log "This mutates your real local Codex MCP config. Continuing only because --real-codex-registration was explicitly provided." | tee -a "$REPORT_OUT"
  run_cmd codex mcp add pcodex -- "$PCODEX_SHIM" mcp-server
  log "rollback real config with: codex mcp remove pcodex" | tee -a "$REPORT_OUT"
fi

log "install smoke complete" | tee -a "$REPORT_OUT"
log "pCodex installed. Run: pcodex setup" | tee -a "$REPORT_OUT"
log "Use: pcodex setup --json for machine-readable setup output" | tee -a "$REPORT_OUT"
log "Use: pcodex status to inspect configured/effective mode, tuning, MCP, fallback, telemetry, and savings availability" | tee -a "$REPORT_OUT"
log "Use: pcodex off / pcodex on / pcodex tuned for manual control" | tee -a "$REPORT_OUT"
log "Use: pcodex tune for one-step static generation, validation, and verification" | tee -a "$REPORT_OUT"
log "rollback isolated install with: $0 --install-root '$INSTALL_ROOT' --uninstall" | tee -a "$REPORT_OUT"
