# One-Paste Codex Bootstrap Prompt - pCodex Private Alpha

You are installing and verifying pCodex from local private alpha artifacts only.

Treat pCodex as private/proprietary and local-only. Do not publish, push, upload, paste secrets, print environment dumps, run private live Codex tasks, or dispatch real subagents. Do not claim universal token savings, native installed-Codex schema discovery, automatic Codex MCP invocation, hosted Codex UI integration, or real internal Codex subagent interception.

Use these local artifact paths exactly unless the user provides replacements:

```text
ARTIFACT_ROOT=/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact
CORE_WHEEL=/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact/dist_core/premode_router-0.2.6.24-py3-none-any.whl
CORE_SDIST=/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact/dist_core/premode-router-0.2.6.24.tar.gz
PLUGIN_WHEEL=/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact/dist_plugin/premode_plugin_literal_symbol-0.1.0-py3-none-any.whl
PLUGIN_SDIST=/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact/dist_plugin/premode-plugin-literal-symbol-0.1.0.tar.gz
SOURCE_TAR=/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact/premode-router-private-alpha.tar
SOURCE_ZIP=/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact/premode-router-private-alpha.zip
```

Prefer isolated verification mode first. Use:

```bash
PCODEX_ALPHA_ROOT="/private/tmp/premode_alpha_install"
PCODEX_ARTIFACT_ROOT="/private/tmp/premode_labs/lab_7_3be_clean_private_alpha_artifact"
PCODEX_VENV="$PCODEX_ALPHA_ROOT/venv"
CODEX_HOME="$PCODEX_ALPHA_ROOT/codex_home"
mkdir -p "$PCODEX_ALPHA_ROOT"
python3.11 -m venv "$PCODEX_VENV"  # or another Python >=3.11
. "$PCODEX_VENV/bin/activate"
python -m pip install --no-index   --find-links "$PCODEX_ARTIFACT_ROOT/dist_core"   --find-links "$PCODEX_ARTIFACT_ROOT/dist_plugin"   premode-router premode-plugin-literal-symbol
```

Verify commands without running live tasks:

```bash
which premode
which pcodex
premode --help
premode compile --help
premode compile --plugin literal_symbol --help || true
premode benchmark --profile lite --json --plugin literal_symbol --out "$PCODEX_ALPHA_ROOT/benchmark_literal_symbol.json"
pcodex --help
pcodex doctor
pcodex status
pcodex compile --help
pcodex run --dry-run "Hypothetical dummy task: inspect a file named hello.txt and report whether it contains the text hello from pcodex. Do not modify files." || true
pcodex mcp-server --help || true
```

If `codex` exists, verify MCP registration only under isolated config:

```bash
export CODEX_HOME="$PCODEX_ALPHA_ROOT/codex_home"
codex mcp add pcodex -- pcodex mcp-server
codex mcp list --json || true
codex mcp get pcodex || true
codex mcp remove pcodex || true
codex mcp list --json || true
```

Do not mutate real Codex config unless the user explicitly approves real config registration. If explicitly approved, run only:

```bash
codex mcp add pcodex -- pcodex mcp-server
```

Rollback real config registration with:

```bash
codex mcp remove pcodex
```

Rollback isolated install with:

```bash
rm -rf /private/tmp/premode_alpha_install/venv /private/tmp/premode_alpha_install/codex_home
```

Expected pass/fail interpretation:

- PASS: local wheel install succeeds, `premode` and `pcodex` are on PATH, `literal_symbol` plugin alias resolves, pCodex dry-run does not execute Codex, and isolated MCP add/list/get/remove works when `codex` is available.
- NON-BLOCKING: `premode compile --plugin literal_symbol --help` may be accepted as help output rather than a compile execution; use the benchmark plugin smoke as the plugin-resolution proof.
- BLOCKING: install requires network, local wheels are missing, `literal_symbol` alias cannot resolve, pCodex command is missing, `pcodex mcp-server` fails to start/help, or real Codex config is changed without explicit approval.

Produce a local install report containing commands, exit codes, artifact paths used, whether isolated `CODEX_HOME` was used, whether real Codex config was touched, and rollback status.
