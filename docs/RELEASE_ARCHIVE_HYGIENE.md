# Release Archive Hygiene

This repository can produce research archives, blind invited-beta tester
bundles, and one canonical non-published release-candidate bundle. Every form
must avoid secrets, runtime ledgers, private lab outputs, and local machine
state.

## Research Archive

A research archive may include lab reports, benchmark summaries, decision matrices, and supporting JSON artifacts when they are explicitly approved for the audience.

Before sharing a research archive, remove or redact:

- private repo prompts
- secrets and tokens
- local usernames and machine-specific paths
- full packets from private repositories
- runtime ledgers
- raw Codex task transcripts unless approved

## Canonical release-candidate bundle

The release-foundation workflow selects one byte-identical wheel/sdist pair
only after all six macOS/Linux and Python 3.11-3.13 cells pass. The canonical
bundle contains public qualification receipts, checksums, SBOM, provenance,
the supported-version matrix, migration/rollback/uninstall guidance, product
contract, gate ledger, and known limitations. It excludes private probe
receipts and is uploaded only as a retained workflow artifact.

It must exclude:

- `__pycache__/`
- `.pytest_cache/`
- `.DS_Store`
- `.premode/out/`
- `.premode/audit/`
- `.premode/metrics/`
- `.premode/index/`
- `.pcodex/`
- `usage_ledger.jsonl`
- private lab artifacts
- large temporary outputs
- local env files
- secrets

## Current Repo Hygiene

`.gitignore`, `MANIFEST.in`, and package-data excludes should block common Python caches, OS files, Pre-mode runtime outputs, pCodex local config, JSONL ledgers, local env files, and secret-like files.

Do not delete existing lab artifacts during docs or package-hygiene work unless the generated artifact lives inside the active lab directory and the lab explicitly calls for cleanup.

## Local release-candidate smoke

Build from a clean exact commit, validate every output byte against the release
metadata, install outside the checkout, and verify the product, Codex, and
OpenClaw lifecycles. The workflow also installs the exact local wheel through a
controlled offline pipx environment and removes it without residue.

```bash
python scripts/validate_release_candidate.py /path/to/pcodex-0.3.0b1-rc --archive /path/to/pcodex-0.3.0b1-rc.zip
python scripts/installed_tool_install_probe.py --wheel /path/to/premode_router-0.3.0b1-py3-none-any.whl --root /new/controlled/root --output /private/receipt.json
```

Do not publish the candidate to PyPI, a package registry, a marketplace, or a
public release without separate authority.
