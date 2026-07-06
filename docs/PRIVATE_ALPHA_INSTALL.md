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
.venv/bin/pcodex mcp-server --help
```

## pCodex Toggle

```bash
.venv/bin/pcodex install
.venv/bin/pcodex on
.venv/bin/pcodex status
.venv/bin/pcodex off
```

`pcodex install` defaults to a dry run. Use `pcodex install --apply` only when you intentionally want to write repo-local pCodex config.

## Dry Run

```bash
.venv/bin/pcodex run --dry-run "Inspect hello.txt"
```

Dry run reports the planned wrapper behavior without executing Codex.

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
