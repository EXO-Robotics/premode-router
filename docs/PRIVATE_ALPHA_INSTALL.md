# Private Alpha Install

This is a local/private install flow for the current pCodex alpha. It is not a publishing guide and does not describe PyPI or external registry distribution.

## Local Setup

For an authorized source checkout, use the source-build installer from the repository root:

```bash
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
~/.pcodex-alpha/bin/pcodex doctor
~/.pcodex-alpha/bin/pcodex setup --skip-tune --no-mcp
~/.pcodex-alpha/bin/pcodex on
~/.pcodex-alpha/bin/pcodex status
~/.pcodex-alpha/bin/pcodex first-run
~/.pcodex-alpha/bin/pcodex first-run --json
~/.pcodex-alpha/bin/pcodex run --dry-run "Hypothetical dummy task: inspect this repo. Do not modify files."
```

The source-build installer builds and installs `premode-router` and `premode-plugin-literal-symbol` from the checked-out source tree into `~/.pcodex-alpha` by default. It prunes generated/runtime state from the temporary build copy and writes `~/.pcodex-alpha/install_manifest.json`. It does not publish packages, does not install from PyPI for the pCodex packages, does not run live Codex tasks, and does not mutate real Codex config unless `--real-codex-registration` is passed explicitly.

## Before First Real Run

Verify the installed Codex CLI before blaming pCodex for real-run failures:

```bash
codex --version
codex exec -C "$PWD" --sandbox workspace-write --ephemeral - <<'EOF'
Edit only a disposable file. Do not modify source files.
EOF
```

If direct Codex fails, update or fix Codex CLI and local Codex config first. `pcodex doctor` and `pcodex status --json` report Codex CLI version/config warnings when they can be detected.

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
.venv/bin/pcodex setup --skip-tune --no-mcp
.venv/bin/pcodex status
.venv/bin/pcodex status --json
.venv/bin/pcodex first-run
.venv/bin/pcodex first-run --json
.venv/bin/pcodex cleanup --local-state --dry-run
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

`pcodex setup --skip-tune --no-mcp` is the recommended first-run path after local install. It runs local checks, skips tuning, skips MCP registration, writes safe `on` mode, and keeps the first value local. Use `pcodex setup` when you intentionally want the fuller setup path with one-step tuning. Real Codex config mutation is never the default.

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

## Generated Local State

Normal pCodex use may create repo-local generated state under `.premode/` and `.pcodex/`, including `.premode/pcodex_state.json`, `.premode/lcc.lock.json`, `.premode/out/`, `.premode/out/cache_manifest.json`, `.premode/audit/`, `.premode/metrics/`, and `.premode/tuning/`.

These paths should generally stay untracked. Version tuning artifacts only when deliberately reviewed and useful for the repository. The pasteable bootstrap prompts add a bounded `.gitignore` section for this state and do not blanket-ignore all `.premode/`.

## Daily-Use Boundaries

Use terminal `pcodex` commands. Do not use `/pcodex` slash commands yet, do not rely on native Codex UI integration yet, and keep real Codex MCP registration as explicit opt-in only.

Start daily use with:

```bash
pcodex status
pcodex setup --skip-tune --no-mcp
pcodex status --json
pcodex first-run --json
pcodex run --dry-run "Hypothetical dummy task: inspect this repo. Do not modify files."
```

Run the first real prompt against a disposable file or disposable repository, then inspect:

```bash
git diff --name-only
git diff -- PCODEX_DAILY_USE_TEST.md
```

For pasteable agent onboarding, see:

- [Pasteable Codex bootstrap](PASTEABLE_CODEX_BOOTSTRAP.md)
- [Pasteable OpenCode bootstrap](PASTEABLE_OPENCODE_BOOTSTRAP.md)
- [Bootstrapper design](BOOTSTRAPPER_DESIGN.md)
- [Integration commands plan](INTEGRATION_COMMANDS_PLAN.md)

The pasteable prompts configure repo-local pCodex UX files. Terminal `pcodex` commands remain the guaranteed control plane. Codex skills are the Codex-facing surface. OpenCode commands are OpenCode-specific.

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

Preview known repo-local generated state cleanup:

```bash
.venv/bin/pcodex cleanup --local-state --dry-run
```

Apply known repo-local generated state cleanup:

```bash
.venv/bin/pcodex cleanup --local-state --yes
```

This preserves source files, `.pcodex/`, `.gitignore`, `.premodeignore`, and user config.

Remove isolated Codex registration:

```bash
codex mcp remove pcodex
```

Turn off repo-local pCodex config when the wrapper should be disabled:

```bash
.venv/bin/pcodex off
```

Do not publish, push tags, push commits, or package this alpha for public distribution from this flow.
