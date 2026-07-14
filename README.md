# pCodex / Local Context Compiler

pCodex is a local, deterministic repository-context router for coding agents. It preserves the exact user task, ranks likely repository paths, and renders one bounded packet for Codex. It is not a planner, autonomous agent, hosted service, or replacement for the coding agent.

Version `0.3.0b1` is source-visible proprietary beta software. Python >=3.11 is required; the qualified range is Python 3.11-3.13, and tomllib requires Python 3.11+. It has not been published to PyPI or a public Codex marketplace.

## Start here

- [Getting started](docs/GETTING_STARTED.md)
- [Codex integration](docs/CODEX_INTEGRATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Privacy and safety](docs/PRIVACY_AND_SAFETY.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Migration](docs/MIGRATION.md)
- [Rollback](docs/ROLLBACK.md)
- [Uninstall](docs/UNINSTALL.md)
- [OpenClaw integration status](docs/OPENCLAW_INTEGRATION.md)

The authoritative product contract is [docs/PRODUCT_CONTRACT.md](docs/PRODUCT_CONTRACT.md). The literal 90/100 program is [docs/ROADMAP_TO_90.md](docs/ROADMAP_TO_90.md), with current status in [docs/PRODUCT_READINESS_GATE_LEDGER.md](docs/PRODUCT_READINESS_GATE_LEDGER.md).

## Invited-beta workflow

Install from the controlled artifact supplied to the tester, or use the source installer described in Getting Started. Then, from the target repository:

```console
pcodex doctor --advisory --json
pcodex status --advisory --json
pcodex run --dry-run "Fix the failing test"
```

These advisory and dry-run operations are literal no-write surfaces. They do not create repository, user, cache, receipt, temporary, Codex, MCP, or integration state and do not launch Codex.

To create the supported repository-local setup after reviewing the preview:

```console
pcodex install
pcodex install --apply
pcodex setup
pcodex status
```

Run Codex only through an explicit non-dry-run request:

```console
pcodex run "Fix the failing test"
pcodex review --since-compile
```

The compatibility commands `pcodex first-run` and
`premode review-patch --since-compile` remain available for existing scripts;
they are not a second onboarding journey.
`pcodex cleanup --local-state --dry-run` remains the bounded cleanup preview.
The research-only `premode benchmark --profile lite` command is not part of the
product journey or release evidence.
For legacy source-checkout diagnostics,
`PYTHONPATH=src python -m premode.cli detect --json` remains available as a
developer-only compatibility command.
In that checkout-only mode, console scripts like `premode` and `pcodex` require an editable or source install.
The source installer verifies the installed `pcodex` help, first-run, cleanup, and unknown-command fail-closed surface.
Packet-size and cache-prefix fields are structural local observations only;
they do not establish downstream token savings, cost savings, or task-quality gains.

## Canonical Codex plugin

`plugins/pcodex` is the only supported Codex plugin source. Installed wheel and sdist artifacts carry the same tree. MCP is disabled by default.

```console
pcodex integrate codex --dry-run
pcodex integrate codex --write
pcodex integrate codex --status
pcodex integrate codex --repair --dry-run
pcodex integrate codex --repair
pcodex integrate codex --disable
pcodex integrate codex --uninstall --dry-run
pcodex integrate codex --uninstall
```

The supported Codex runtime is `0.143.x`. There is no automatic hosted-agent interception, custom slash command, or public marketplace publication claim.

## Production OpenClaw adapter

OpenClaw `2026.4.14` has a separate explicit integration lifecycle:

```console
pcodex integrate openclaw --dry-run
pcodex integrate openclaw --write
pcodex integrate openclaw --status
pcodex integrate openclaw --repair --dry-run
pcodex integrate openclaw --repair
pcodex integrate openclaw --disable
pcodex integrate openclaw --uninstall --dry-run
pcodex integrate openclaw --uninstall
```

It registers one immutable-workspace `premode_preflight` tool and preserves unrelated OpenClaw JSON5 configuration. It does not grant arbitrary command execution, execute validation, or intercept OpenClaw automatically.

## Supported claims

- Exact-task-preserving deterministic context routing.
- One canonical packet and one production ranking-provider seam.
- Literal no-write advisory, preview, and dry-run operations.
- Receipt-bound setup, repair, migration, disable, uninstall, and reinstall.
- Literal no-write `pcodex upgrade --check`; after explicit qualified package replacement, `pcodex upgrade --apply` preserves the actual `0.2.6.24` `.pcodex` state and changes only separately proven receipt-owned or supported legacy-plugin state.
- Qualified wheel and sdist lifecycle on macOS and Linux with Python 3.11-3.13.
- Canonical Codex plugin lifecycle with Codex `0.143.x`.
- Receipt-bound production OpenClaw adapter for OpenClaw `2026.4.14`.

## Unsupported claims

- Universal token savings or quality improvement.
- Public package or marketplace availability.
- Automatic Codex interception or internal subagent routing.
- OpenClaw versions other than `2026.4.14` or automatic OpenClaw interception.
- Complete protocol conformance for the separately optional Codex MCP surface.
- Windows support.
- A completed five-person first-run study.
- A frozen 10-repository/100-task release proof.

## Development validation

From a development checkout with the pinned test environment installed:

```console
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python scripts/check_public_hygiene.py --json
python scripts/validate_documentation.py --root . --json
```

Publishing, tagging, releasing, or promoting another branch requires separate authorization.

## License

Proprietary and all rights reserved. See [LICENSE](LICENSE).
