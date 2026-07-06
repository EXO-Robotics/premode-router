# Private Alpha Install

This is a local/private install flow for the current pCodex alpha. It is not a publishing guide and does not describe PyPI or external registry distribution.

## Local Setup

Clone or copy the private repository through an approved private path, then create a virtual environment:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
```

Install the core package editable:

```bash
.venv/bin/python -m pip install -e .
```

Install the private literal-symbol plugin locally:

```bash
.venv/bin/python -m pip install -e packages/premode-plugin-literal-symbol
```

## Smoke Checks

```bash
.venv/bin/premode compile --plugin literal_symbol --help
.venv/bin/premode compile --plugin literal_symbol "Inspect hello.txt" --profile lite --json
.venv/bin/pcodex doctor
.venv/bin/pcodex status
.venv/bin/pcodex status --json
.venv/bin/pcodex tune --help
.venv/bin/pcodex mcp-server --help
```

## pCodex Modes

```bash
.venv/bin/pcodex install
.venv/bin/pcodex on
.venv/bin/pcodex status
.venv/bin/pcodex off
```

`pcodex install` defaults to a dry run. Use `pcodex install --apply` only when you intentionally want to write repo-local pCodex config.

Modes:

- `off`: raw prompt, no pCodex transform
- `on`: generalized `literal_symbol` transform
- `tuned`: `literal_symbol` transform with a validated tuning profile

Missing mode state reports the safe default `on`.

## Tuning Flow

```bash
.venv/bin/pcodex tune --static-only
.venv/bin/pcodex tune --validate
.venv/bin/pcodex tune --verify
.venv/bin/pcodex tuned
.venv/bin/pcodex status --json
```

The default profile is `.premode/tuning/repo_profile.json`. `pcodex tuned` validates the profile before writing tuned mode state. Use `pcodex tuned --profile .premode/tuning/repo_profile.json` to be explicit.

Compile-time tuning can also be invoked directly:

```bash
.venv/bin/premode compile --plugin literal_symbol --tuning .premode/tuning/repo_profile.json "Inspect hello.txt" --profile lite --json
```

Tuned improvements are repo-specific and must be verified locally. `pcodex tune --verify` is compile-only local selection, not a live Codex task.

## Dry Run

```bash
.venv/bin/pcodex run --dry-run "Inspect hello.txt"
```

Dry run reports the planned wrapper behavior without executing Codex.

`pcodex run` and `pcodex run --dry-run` respect off/on/tuned mode state. Invalid tuned state fails before any Codex launch.

## Optional Isolated Codex MCP Registration

Use an isolated Codex home for lab registration:

```bash
export CODEX_HOME=/private/tmp/premode_labs/<lab>/codex_home
codex mcp add pcodex -- pcodex mcp-server
codex mcp list
codex mcp get pcodex
codex mcp remove pcodex
```

If `pcodex` is not on `PATH`, register the venv command instead:

```bash
codex mcp add pcodex -- .venv/bin/pcodex mcp-server
```

## Cleanup

Remove isolated Codex registration:

```bash
codex mcp remove pcodex
```

Turn off repo-local pCodex config when the wrapper should be disabled:

```bash
.venv/bin/pcodex off
```

Do not publish, push tags, push commits, or package this alpha for public distribution from this flow.
