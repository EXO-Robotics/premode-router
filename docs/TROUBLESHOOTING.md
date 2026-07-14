# Troubleshooting

Start with literal no-write evidence:

```console
pcodex doctor --advisory --json
pcodex status --advisory --json
pcodex integrate codex --status --json
```

After setup, automation can require a usable installation with:

```console
pcodex doctor --strict --json
```

Strict doctor returns nonzero when required executables, the production plugin,
Git repository state, supported Codex version, product configuration, or the
managed lifecycle is not ready.

## Command not found

For the invited-beta environment, add its bin directory to `PATH`:

```console
export PATH="$HOME/.pcodex-beta/bin:$PATH"
pcodex --help
```

For a source install, use `$HOME/.pcodex-alpha/bin` instead. Do not install a similarly named package from a public registry.

## Unsupported Python or Codex

pCodex supports Python 3.11-3.13 on macOS and Linux. The canonical plugin supports Codex `0.143.x` only. Dry-run can work without Codex; discovery and real runs cannot.

```console
python3 --version
codex --version
```

## Dry-run or advisory reports no state

That is expected on a clean repository. Literal no-write operations report missing or stale state without creating, refreshing, repairing, or migrating it. Preview the supported install and apply it explicitly:

```console
pcodex install
pcodex install --apply
pcodex setup
pcodex status
```

## Plugin lifecycle state

`READY` means the receipt-proven canonical plugin and exact registrations are healthy. `NEEDS_ACTION` includes absent, disabled, or safely repairable state. `BLOCKED` means ownership cannot be proven—for example malformed/future receipts, duplicate authority, modified owned files, or an interrupted journal.

Preview repair before applying it:

```console
pcodex integrate codex --repair --dry-run --json
pcodex integrate codex --repair --json
```

Repair does not overwrite modified files or unrelated Codex, marketplace, plugin, or MCP state.

Managed repository state uses a separate receipt-bound repair path. Preview it
before applying any change:

```console
pcodex repair --dry-run
pcodex repair --yes
```

## Legacy migration

Migration is always explicit:

```console
pcodex integrate codex --dry-run --migrate --json
pcodex integrate codex --write --migrate --json
pcodex integrate codex --status --json
```

Only exact accepted historical fingerprints may be removed. Modified, unknown, or uncertain legacy assets are preserved for manual review.

## MCP

MCP remains disabled unless `--with-mcp` is explicitly supplied. MCP preview does not write configuration or launch a server. Registration lifecycle proof does not imply complete protocol, containment, cancellation, or production-server qualification.

## OpenClaw adapter

OpenClaw integration supports exactly `2026.4.14`. Begin with no-write status and preview:

```console
openclaw --version
pcodex integrate openclaw --status --json
pcodex integrate openclaw --dry-run --json
```

`NEEDS_ACTION` covers an absent, disabled, or receipt-proven missing registration. `BLOCKED` covers an unsupported version, malformed/future receipt, changed workspace identity, changed configuration authority, modified registration, or unknown existing `pcodex` entry. Do not edit `.pcodex/openclaw-integration-state.json` or delete the JSON5 entry manually. Use repair only after its preview:

```console
pcodex integrate openclaw --repair --dry-run --json
pcodex integrate openclaw --repair --json
```

Unrelated MCP registrations and JSON5 formatting are preserved. OpenClaw config validation remains available independently:

Before an OpenClaw state-changing lifecycle command, stop OpenClaw and any
other process writing the selected JSON5 configuration. Concurrent pathname
or observed content changes fail closed with recovery staging; writes made
after the final observation through an independently retained descriptor are
outside the beta's portable crash-consistency guarantee.

```console
openclaw config validate --json
openclaw mcp show pcodex --json
```

## Installed-artifact no-write evidence

Qualification fails closed when filesystem or process observation is unavailable. On macOS, `process_observation=unavailable` usually means the environment denied bounded process-table observation. Rerun the same builder in a controlled environment that permits process monitoring; do not disable monitoring or remove governed roots.

Failure evidence is preserved under `receipts/probe-execution/` and `private-receipts/probe-execution/` in the qualification output. Public receipts are sanitized; private receipts may contain controlled absolute paths and must not be published.

## Interrupted operations

Run status and follow its single recommended action:

```console
pcodex status --advisory --json
pcodex integrate codex --status --json
```

Do not delete `.premode`, `.pcodex`, plugin, marketplace, Codex configuration, or quarantine paths by hand. See `docs/ROLLBACK.md`.

## Unsupported expectations

Automatic agent interception, public marketplace publication, OpenClaw versions other than `2026.4.14`, universal savings, Windows, and arbitrary power-loss recovery are not supported claims.
