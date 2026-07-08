#!/usr/bin/env sh
set -eu

if [ -x "./.venv/bin/pcodex" ]; then
  printf '%s\n' "./.venv/bin/pcodex"
  exit 0
fi

if [ -n "${HOME:-}" ] && [ -x "$HOME/.pcodex-alpha/bin/pcodex" ]; then
  printf '%s\n' "$HOME/.pcodex-alpha/bin/pcodex"
  exit 0
fi

if command -v pcodex >/dev/null 2>&1; then
  command -v pcodex
  exit 0
fi

cat >&2 <<'EOF'
pCodex executable not found.

Looked for:
- ./.venv/bin/pcodex
- $HOME/.pcodex-alpha/bin/pcodex
- pcodex on PATH

Install/setup guidance:
- From the pCodex source checkout, create or refresh the local install so a pcodex executable exists.
- For a repo-local developer checkout, run the source install/bootstrap flow first, then retry this skill.
- Do not run live Codex tasks until `pcodex status --advisory --json` succeeds.
EOF
exit 127
