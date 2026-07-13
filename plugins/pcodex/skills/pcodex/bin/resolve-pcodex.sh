#!/usr/bin/env sh
set -eu

if [ -n "${PCODEX_BIN:-}" ] && [ -x "$PCODEX_BIN" ]; then
  printf '%s\n' "$PCODEX_BIN"
  exit 0
fi

if command -v pcodex >/dev/null 2>&1; then
  command -v pcodex
  exit 0
fi

cat >&2 <<'EOF'
pCodex executable not found.

Install the premode-router artifact in the active environment and ensure its
`pcodex` console script is on PATH. Discovery is read-only: this resolver does
not inspect a source checkout, a sibling repository, or a legacy alpha install.
Do not run live Codex tasks until `pcodex status --advisory --json` succeeds.
EOF
exit 127
