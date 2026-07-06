# One-Paste Codex Bootstrap Prompt - pCodex Private Alpha

You are installing and verifying pCodex from local private alpha artifacts only.

Treat pCodex as private/proprietary and local-only. Do not publish, push, upload, paste secrets, print environment dumps, run private live Codex tasks, or dispatch real subagents. Do not claim universal token savings, native installed-Codex schema discovery, automatic Codex MCP invocation, hosted Codex UI integration, or real internal Codex subagent interception.

Preferred local bundle shape:

```text
pcodex-private-alpha-v0.1.0/
  README_INSTALL_FIRST.md
  ARTIFACT_MANIFEST.json
  SHA256SUMS.txt
  dist_core/
  dist_plugin/
  docs/
  scripts/install_pcodex_private_alpha.sh
```

Install from the bundle root:

```bash
cd /path/to/pcodex-private-alpha-v0.1.0
scripts/install_pcodex_private_alpha.sh --artifact-root .
```

The installer uses this layout by default:

```text
~/.pcodex-alpha/
  venv/
  bin/
    premode
    pcodex
  codex_home/
  pcodex-alpha.env
```

Add the shims to PATH only if you want shell-wide convenience:

```bash
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
```

The installer detects Python >=3.11, venv support, pip, the local artifact bundle, and the optional Codex CLI. Python, venv, or pip repair is explained when missing. System dependency installation is opt-in only:

```bash
scripts/install_pcodex_private_alpha.sh --artifact-root . --allow-system-deps
```

Use `--assume-yes-system-deps` only when noninteractive system dependency repair is acceptable. The installer does not use sudo itself; Linux package-manager guidance may include sudo commands for the human operator to run deliberately.

Hash verification is automatic when `SHA256SUMS.txt` is present:

```bash
scripts/install_pcodex_private_alpha.sh --artifact-root .
```

If a hash mismatch is reported, stop and replace the local bundle from the trusted private source. Do not use `--skip-hash-check` unless you are deliberately testing a lab-owned artifact copy.

Verify commands without running live tasks:

```bash
~/.pcodex-alpha/bin/premode --help
~/.pcodex-alpha/bin/premode compile --help
~/.pcodex-alpha/bin/premode compile --plugin literal_symbol --no-record "Hypothetical dummy task: inspect a file named hello.txt and report whether it contains the text hello from pcodex. Do not modify files."
~/.pcodex-alpha/bin/pcodex --help
~/.pcodex-alpha/bin/pcodex doctor
~/.pcodex-alpha/bin/pcodex status
~/.pcodex-alpha/bin/pcodex compile --help
~/.pcodex-alpha/bin/pcodex run --dry-run "Hypothetical dummy task: inspect a file named hello.txt and report whether it contains the text hello from pcodex. Do not modify files."
~/.pcodex-alpha/bin/pcodex mcp-server --help
```

If `codex` exists, the installer verifies MCP registration only under isolated config by default:

```bash
CODEX_HOME="$HOME/.pcodex-alpha/codex_home" codex mcp list --json || true
```

The installer registers with an absolute shim path:

```bash
CODEX_HOME="$HOME/.pcodex-alpha/codex_home" codex mcp add pcodex -- "$HOME/.pcodex-alpha/bin/pcodex" mcp-server
CODEX_HOME="$HOME/.pcodex-alpha/codex_home" codex mcp remove pcodex
```

Do not mutate real Codex config unless the user explicitly approves real config registration. If explicitly approved, use only:

```bash
scripts/install_pcodex_private_alpha.sh --artifact-root . --real-codex-registration
```

Rollback real config registration with:

```bash
codex mcp remove pcodex
```

Rollback the isolated install with:

```bash
scripts/install_pcodex_private_alpha.sh --uninstall
```

Expected pass/fail interpretation:

- PASS: local wheel install succeeds with `--no-index --find-links`, `premode` and `pcodex` absolute shims work without manual venv activation, `literal_symbol` plugin alias resolves, pCodex dry-run does not execute Codex, hash verification passes when checksum files are present, and isolated MCP add/list/get/remove works when `codex` is available.
- NON-BLOCKING: Codex CLI is not installed when MCP registration was not requested.
- BLOCKING: install requires network, local wheels are missing, hash verification fails, `literal_symbol` alias cannot resolve, pCodex command is missing, `pcodex mcp-server` fails to start/help, or real Codex config is changed without explicit approval.

Produce a local install report containing commands, exit codes, artifact paths used, whether isolated `CODEX_HOME` was used, whether real Codex config was touched, hash-verification status, shim paths, and rollback status.
