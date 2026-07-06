# Private Alpha Install

This is a local/private install flow for the current pCodex alpha. It is not a publishing guide and does not describe PyPI or external registry distribution.

## Local Setup

For a source-only public clone, use the source-build installer from the repository root:

```bash
scripts/install_pcodex_from_source.sh
~/.pcodex-alpha/bin/pcodex setup --no-mcp
~/.pcodex-alpha/bin/pcodex status
~/.pcodex-alpha/bin/pcodex run --dry-run "Hypothetical dummy task: inspect this repo. Do not modify files."
```

The source-build installer builds and installs `premode-router` and `premode-plugin-literal-symbol` from the checked-out source tree into `~/.pcodex-alpha` by default. It does not publish packages, does not install from PyPI for the pCodex packages, does not run live Codex tasks, and does not mutate real Codex config unless `--real-codex-registration` is passed explicitly.

For manual source setup, clone or copy the repository through an approved path, then create a virtual environment:

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

## Private Bundle Install

The private-alpha bundle installer is for a prepared local artifact bundle, not a source-only public clone:

```bash
scripts/install_pcodex_private_alpha.sh --artifact-root /path/to/pcodex-private-alpha-v0.3.0
```

The artifact root must contain:

```text
README_INSTALL_FIRST.md
ARTIFACT_MANIFEST.json
SHA256SUMS.txt
dist_core/
dist_plugin/
```

`scripts/install_pcodex_private_alpha.sh` requires `dist_core/` and `dist_plugin/` wheel artifacts and is not expected to work from a source-only public clone.

## Smoke Checks

```bash
.venv/bin/premode compile --plugin literal_symbol --help
.venv/bin/premode compile --plugin literal_symbol "Inspect hello.txt" --profile lite --json
.venv/bin/pcodex doctor
.venv/bin/pcodex setup --no-mcp
.venv/bin/pcodex status
.venv/bin/pcodex status --json
.venv/bin/pcodex tune
.venv/bin/pcodex tune --help
.venv/bin/pcodex mcp-server --help
```

## pCodex Modes

```bash
.venv/bin/pcodex install
.venv/bin/pcodex setup
.venv/bin/pcodex on
.venv/bin/pcodex status
.venv/bin/pcodex off
```

`pcodex install` defaults to a dry run. Use `pcodex install --apply` only when you intentionally want to write repo-local pCodex config.

`pcodex setup` is the recommended default path after local install. It runs local checks, optional isolated MCP registration, one-step tuning, safe mode selection, and dashboard output. Use `pcodex setup --no-mcp` to skip MCP registration and `pcodex setup --json` for automation. Real Codex config mutation is never the default.

Modes:

- `off`: raw prompt, no pCodex transform
- `on`: best safe available pCodex behavior
- `tuned`: force tuned behavior or fail clearly

Missing mode state reports the safe default `on`. Smart `on` uses tuned behavior only when a valid profile exists and `.premode/tuning/VERIFY_RESULTS.json` has verdict `PASS`; otherwise it falls back to generalized `literal_symbol`.

## Tuning Flow

```bash
.venv/bin/pcodex tune
.venv/bin/pcodex tuned
.venv/bin/pcodex status --json
```

`pcodex tune` runs static generation, validation, and offline verification. The advanced `--static-only`, `--validate`, and `--verify` flags remain available for focused maintenance.

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

`pcodex run` and `pcodex run --dry-run` respect effective mode and report configured/effective mode out of band. Invalid strict tuned state fails before any Codex launch.

## Status And Telemetry

`pcodex status` shows configured mode, effective mode, tuning, MCP status, fallback state, local telemetry counters, and savings-estimate availability. Fallback telemetry is local-only and stores counters/reasons only. It must not store prompts, source snippets, secrets, or file contents. Savings availability is a local estimate status, not a guaranteed or monetary savings claim.

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
