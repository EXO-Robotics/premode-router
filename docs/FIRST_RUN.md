# pCodex First Run

This is the canonical Private-Beta first-run path for pCodex from a current source checkout. For a tester-facing checklist, see `docs/PRIVATE_BETA_TESTER_PACKET.md`.

pCodex is a local context compiler wrapper. It does not replace Codex, does not publish packages, does not require MCP for first value, and does not require tuning for first value.

## Prerequisites

- macOS or Linux shell
- Python 3.11 or newer
- A checked-out `premode-router` source tree
- A target repository where repo-local generated state under `.premode/` is acceptable

Codex CLI is needed for real runs. It is not needed to view the receipt or run local dry-run preflight.

For a Private-Beta checkout, SSH clone requires GitHub SSH access to the private repository. HTTPS clone is an approved fallback when SSH reports `Permission denied (publickey)`. Do not print tokens or change SSH keys during dogfood; record the SSH failure and proceed with HTTPS.

## Install From Current Source

From the `premode-router` checkout:

```bash
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
```

The installer builds from the current checkout into `~/.pcodex-alpha` by default and writes:

```text
~/.pcodex-alpha/install_manifest.json
```

The manifest records version, install channel, source branch/head/dirty status, install root, Python version, console scripts, plugin packages, installer version, and warnings. It does not claim PyPI, pipx, or public package availability.

## Blessed First-Run Path

In the target repo:

```bash
pcodex doctor
pcodex setup --skip-tune --no-mcp
pcodex on
pcodex status
pcodex first-run
pcodex first-run --json
pcodex run --dry-run "Hypothetical setup verification task. Do not modify files."
```

This path keeps the first value local and auditable:

- `doctor` checks local readiness.
- `setup --skip-tune --no-mcp` avoids tuning and MCP registration.
- `on` enables the safe default `literal_symbol` path.
- `status` shows readiness and one next action.
- `first-run` emits a support-safe receipt.
- `run --dry-run` compiles/preflights locally and does not launch Codex.

The exact user prompt remains the canonical task text at compile time.

## Read-Only Advisory Receipts

Use advisory mode when a reviewer, support contact, or AI company needs a paste-safe status surface without mutating local state:

```bash
pcodex status --advisory --json
pcodex doctor --advisory --json
pcodex first-run --advisory --json
```

Advisory mode may inspect existing repo state and run bounded read-only checks. It does not create `.premode/`, refresh inventory/topology, write lockfiles, write cache manifests, record telemetry, write temp packets, register MCP, alter Codex config/home, launch Codex, or repair state. It reports missing or stale state with `writes_performed=false`, `would_write`, and `would_refresh` fields.

Advisory mode is a no-write/no-mutation claim, not a no-read claim. Run the normal first-run path above to create or repair local state.

## Receipt Shape

`pcodex first-run --json` emits a content-free non-advisory receipt with this shape:

```json
{
  "schema_version": "pcodex.first_run.v1",
  "status": "ok",
  "repo_root": "/path/to/repo",
  "public_mode": "source-visible private beta",
  "plugin_alias": "literal_symbol",
  "plugin_alias_available": true,
  "configured_mode": "on",
  "effective_mode": "on",
  "state_status": "configured",
  "advisory": false,
  "writes_performed": false,
  "codex_launch": "not_executed",
  "global_codex_config_mutation": false,
  "install_provenance_available": true,
  "install_provenance": {},
  "next_action": "pcodex setup --skip-tune --no-mcp --json",
  "cleanup_commands": [
    "pcodex cleanup --local-state --dry-run",
    "pcodex cleanup --local-state --yes"
  ]
}
```

The receipt does not include raw prompts, source bodies, source snippets, secrets, environment values, full packet text, inventory path lists, or topology path lists.

`pcodex first-run --advisory --json` is a separate read-only advisory receipt. It may report missing or stale state and a repair next action, but it must keep `writes_performed=false` and must not repair state or launch Codex.

## Dry-Run And Compile-Only Checks

Use pCodex dry-run before any real Codex launch:

```bash
pcodex run --dry-run "Hypothetical setup verification task. Do not modify files."
```

Dry-run compiles/preflights the local packet and reports out-of-band metadata. It does not launch Codex, and it should not be described as raw-prompt passthrough when LCC is on.

Use a manual no-record compile when you need a compile-only check without writing compile artifacts:

```bash
premode compile --plugin literal_symbol --no-record "Hypothetical setup verification task. Do not modify files."
```

## Generated State

Normal first-run and dry-run commands may create repo-local generated state:

- `.premode/pcodex_state.json`
- `.premode/lcc.lock.json`
- `.premode/out/cache_manifest.json`
- `.premode/inventory/files.json`
- `.premode/topology/repo_topology.json`
- `.premode/pcodex_codex_home/` when isolated MCP registration is used

These files are generated/runtime state. They should stay ignored unless explicitly reviewed and intentionally versioned.

## Cleanup

Preview cleanup:

```bash
pcodex cleanup --local-state --dry-run
pcodex cleanup --local-state --dry-run --json
```

Apply cleanup:

```bash
pcodex cleanup --local-state --yes
```

Cleanup is limited to known repo-local generated state under `.premode/`. It preserves `.pcodex/`, source files, `.gitignore`, `.premodeignore`, and user source/config files.

## Repair

Use this repair path before real runs:

```bash
pcodex doctor
pcodex cleanup --local-state --dry-run
pcodex cleanup --local-state --yes
pcodex setup --skip-tune --no-mcp
pcodex on
pcodex first-run --json
pcodex run --dry-run "Hypothetical repair verification task. Do not modify files."
```

Full install-root uninstall remains the source installer responsibility:

```bash
scripts/install_pcodex_from_source.sh --uninstall
```

This removes the isolated install root created by that installer. It does not edit real Codex config unless real Codex registration was explicitly used separately.

## Troubleshooting

- If `pcodex` is not found, add the install root `bin` directory to `PATH` or call `~/.pcodex-alpha/bin/pcodex`.
- If `pcodex cleanup --dry-run --json` fails, rerun the scoped supported form: `pcodex cleanup --local-state --dry-run --json`.
- If `doctor` reports missing Codex CLI, first-run receipt and dry-run still work, but real Codex runs need Codex CLI repaired.
- If inventory or topology is missing/stale, `pcodex run --dry-run` refreshes local generated state before spending tokens.
- If support only needs a paste-safe receipt, use `pcodex status --advisory --json`; it reports missing/stale state without repairing it.
- If a real run fails, inspect the repo diff before debugging pCodex.

## Not Active Yet

These are future or unproven and must not be claimed as active:

- `pipx install premode-router`
- PyPI or public package availability
- native `/pcodex` slash commands
- automatic hosted/internal Codex subagent interception
- automatic MCP invocation by installed Codex
- native installed-Codex schema discovery
- guaranteed prompt-cache hits or guaranteed savings

## Not Claimed

This first-run path does not claim open-source rights, public release readiness, PyPI distribution, live Codex auto-interception, universal token savings, or guaranteed provider cache behavior.
