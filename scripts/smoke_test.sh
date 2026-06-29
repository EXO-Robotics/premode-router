#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "No Python executable found. Set PYTHON=/path/to/python3.11 or activate a venv." >&2
    exit 127
  fi
fi

SMOKE_PHASE="${SMOKE_PHASE:-smoke_core}"

phase() {
  SMOKE_PHASE="$1"
  echo "== ${SMOKE_PHASE} =="
}

run() {
  local start end duration status
  start="$(date +%s)"
  echo "[${SMOKE_PHASE}] + $*"
  if "$PYTHON_BIN" scripts/run_with_timeout.py --timeout 120 -- "$@" >/tmp/premode-smoke-last.json 2>&1; then
    status=0
  else
    status=$?
  fi
  end="$(date +%s)"
  duration=$((end - start))
  echo "[${SMOKE_PHASE}] duration=${duration}s status=${status} command=$*"
  if [[ "${status}" -ne 0 ]]; then
    cat /tmp/premode-smoke-last.json >&2
    return "${status}"
  fi
}
phase smoke_core
run premode setup --skip-plugin
run premode doctor --recommend-profile
run premode detect --json
run premode run-fixture
run premode init
run premode index --incremental
run premode inspect "Fix the campaign upkeep patch, don't expand scope, check what Qwen did, and make sure the app builds."
run premode compile "Fix the campaign upkeep patch, don't expand scope, check what Qwen did, and make sure the app builds." --out .premode/out/example.md --json-out .premode/out/example.json
run premode compile "Fix the campaign upkeep patch, don't expand scope, check what Qwen did, and make sure the app builds." --json
run premode codex "Fix the campaign upkeep patch, don't expand scope, check what Qwen did, and make sure the app builds." --dry-run
run pcodex "Fix the campaign upkeep patch, don't expand scope, check what Qwen did, and make sure the app builds." --dry-run
phase smoke_plugin
run premode plugin install-local --scope repo
run premode stats --savings
run premode lab compare "Fix the build" --provider mock
phase smoke_benchmark
run premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
echo "smoke test passed"
