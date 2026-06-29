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

run() {
  echo "+ $*"
  "$PYTHON_BIN" scripts/run_with_timeout.py --timeout 120 -- "$@" >/tmp/premode-smoke-last.json 2>&1 || { cat /tmp/premode-smoke-last.json >&2; return 1; }
}
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
run premode plugin install-local --scope repo
run premode stats --savings
run premode lab compare "Fix the build" --provider mock
run premode benchmark --profile lite --json --out .premode/out/benchmark_report.json
echo "smoke test passed"
