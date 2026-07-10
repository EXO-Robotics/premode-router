# One-Paste Codex Bootstrap Prompt - pCodex Private Alpha

You are installing and verifying pCodex from local private alpha artifacts only.

Treat pCodex as private/proprietary and local-only. Do not publish, push, upload, paste secrets, print environment dumps, run private live Codex tasks, or dispatch real subagents. Do not claim universal token savings, native installed-Codex schema discovery, automatic Codex MCP invocation, hosted Codex UI integration, or real internal Codex subagent interception.

Preferred local bundle shape:

```text
pcodex-private-alpha-v0.3.0-candidate/
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
cd /path/to/pcodex-private-alpha-v0.3.0-candidate
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
~/.pcodex-alpha/bin/pcodex setup
~/.pcodex-alpha/bin/pcodex status
~/.pcodex-alpha/bin/pcodex status --json
~/.pcodex-alpha/bin/pcodex compile --help
~/.pcodex-alpha/bin/pcodex tune
~/.pcodex-alpha/bin/pcodex tune --help
~/.pcodex-alpha/bin/pcodex run --dry-run "Hypothetical dummy task: inspect a file named hello.txt and report whether it contains the text hello from pcodex. Do not modify files."
~/.pcodex-alpha/bin/pcodex mcp-server --help
```

Post-install recommended flow:

```bash
~/.pcodex-alpha/bin/pcodex setup
~/.pcodex-alpha/bin/pcodex status
~/.pcodex-alpha/bin/pcodex status --json
~/.pcodex-alpha/bin/pcodex run --dry-run "Hypothetical dummy task: inspect login flow. Do not modify files."
```

`pcodex setup` is the default finishing step. It runs local checks, skips tuning and MCP registration, writes safe `on` mode, and prints a concise dashboard. Use `pcodex setup --json` for automation.

`pcodex tune` now runs static generation, validation, and verification by default. `pcodex tune --static-only`, `pcodex tune --validate`, and `pcodex tune --verify` remain available for focused maintenance.

Mode meanings:

- `off`: raw prompt, no pCodex transform
- `on`: best safe available pCodex behavior
- `tuned`: force tuned behavior or fail clearly

Smart `on` uses tuned behavior only when a valid profile exists and `.premode/tuning/VERIFY_RESULTS.json` has verdict `PASS`; otherwise it falls back to generalized `literal_symbol`. Use `pcodex tuned` only when strict tuned behavior is intentional. Use `pcodex off` when the raw prompt should pass through without a pCodex transform.

`pcodex status` shows configured mode, effective mode, tuning, MCP, fallback, local telemetry counters, and savings-estimate availability. Fallback telemetry is local-only and stores counters/reasons only, not prompts, source snippets, secrets, or file contents. Savings availability is not a guaranteed or monetary savings claim.

Slash-style `/pcodex` commands are not native Codex UI commands yet. Treat any slash-style language as instruction-level or future work only.

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
- PASS after setup/smart-on refresh: `pcodex setup`, `pcodex tune`, `pcodex status`, `pcodex status --json`, `pcodex run --dry-run`, and `premode compile --plugin literal_symbol` all work from the installed bundle.
- NON-BLOCKING: Codex CLI is not installed when MCP registration was not requested.
- BLOCKING: install requires network, local wheels are missing, hash verification fails, `literal_symbol` alias cannot resolve, pCodex command is missing, `pcodex mcp-server` fails to start/help, or real Codex config is changed without explicit approval.

Produce a local install report containing commands, exit codes, artifact paths used, whether isolated `CODEX_HOME` was used, whether real Codex config was touched, hash-verification status, shim paths, and rollback status.
