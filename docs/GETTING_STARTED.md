# Getting Started

This is the canonical invited-beta journey for pCodex `0.3.0b1`. It targets a useful local dry run in under five minutes. No public package or marketplace publication is implied.

## Requirements

- macOS or Linux
- Python 3.11, 3.12, or 3.13
- the controlled `premode_router-0.3.0b1-py3-none-any.whl` artifact or a source checkout
- Codex CLI `0.143.x` for plugin discovery and real runs; dry-run works without Codex

## Install the invited-beta artifact

Use the artifact and SHA-256 supplied by the beta administrator:

```console
python3 -c 'import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); print(hashlib.sha256(p.read_bytes()).hexdigest())' /path/to/premode_router-0.3.0b1-py3-none-any.whl
python3 -m venv "$HOME/.pcodex-beta"
"$HOME/.pcodex-beta/bin/python" -m pip install --no-index --no-deps /path/to/premode_router-0.3.0b1-py3-none-any.whl
export PATH="$HOME/.pcodex-beta/bin:$PATH"
pcodex --help
```

Compare the printed digest byte-for-byte with `artifacts/SHA256SUMS` from the
controlled tester bundle before installing. Stop on any mismatch. Do not
substitute a similarly named public package.

The release matrix also qualifies this exact network-independent local-artifact form when pipx is
preferred:

```console
pipx install /path/to/premode_router-0.3.0b1-py3-none-any.whl --pip-args="--no-index --no-deps"
pcodex --help
```

The distribution is `premode-router`; the installed command is `pcodex`.
This is not a `pipx install premode-router` registry-availability claim.

## Reach the first useful dry run

From the repository you want to inspect:

```console
pcodex doctor --advisory --json
pcodex status --advisory --json
pcodex run --dry-run "Fix the failing test"
```

All three commands are literal no-write surfaces. `run --dry-run` returns the local preflight without launching Codex.

## Create the supported local setup

Preview first, then apply:

```console
pcodex install
pcodex install --apply
pcodex setup
pcodex status
```

`install` without `--apply` is a preview. Setup and install apply may create only the product-owned repository state described in `premode.product.json`.

## Install the canonical Codex plugin

```console
pcodex integrate codex --dry-run
pcodex integrate codex --write
pcodex integrate codex --status
```

MCP remains absent unless `--with-mcp` is explicitly supplied. See `docs/CODEX_INTEGRATION.md` before enabling it.

## Run and review

```console
pcodex run "Fix the failing test"
pcodex review --since-compile
```

A non-dry-run `pcodex run` launches Codex. Inspect the repository diff and validation results before accepting any patch.

## Source/developer install

When no controlled wheel was supplied, a source checkout can install into the isolated alpha-compatible root:

```console
scripts/install_pcodex_from_source.sh
export PATH="$HOME/.pcodex-alpha/bin:$PATH"
pcodex --help
```

This is a developer fallback, not a public package installation claim.

## Upgrade from the supported beta

Verify and install the qualified replacement artifact with the same Python environment first. pCodex never downloads or replaces its own package. Then preview the frozen predecessor boundary and apply only separately proven receipt-owned or supported legacy-plugin state. The actual `0.2.6.24` `.pcodex` user configuration is preserved:

```console
pcodex upgrade --check --json
pcodex upgrade --apply --json
pcodex status --advisory --json
```

`--check` is literal no-write. A modified, partial, future, unknown, or interrupted receipt reports `BLOCKED` and is preserved.

## Remove it

Preview and remove integration state before removing the Python environment:

```console
pcodex integrate codex --uninstall --dry-run
pcodex integrate codex --uninstall
pcodex uninstall --dry-run
pcodex uninstall --yes
```

Then remove the package with the same Python environment that installed it. See `docs/UNINSTALL.md` for preservation and conflict behavior.
