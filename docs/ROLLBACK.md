# Rollback

pCodex lifecycle operations use versioned ownership receipts and bounded journals. If an install, repair, migration, or uninstall is interrupted, rerun status before taking another action:

```console
pcodex status --advisory --json --repo-root /path/to/repository
pcodex integrate codex --status --json --repo-root /path/to/repository
pcodex integrate openclaw --status --json --repo-root /path/to/repository
```

Use the single recommended action returned by status. Do not delete `.premode`, `.pcodex`, plugin, marketplace, Codex configuration, or quarantine paths by hand. User-modified, unrelated, malformed, and future-schema state is preserved rather than normalized.

Rollback means restoring the last receipt-proven state during the same operation. It does not claim arbitrary power-loss recovery or support package downgrade from `0.3.0b1`.

## Upgrade procedure

Before installing a replacement invited-beta artifact, capture read-only state and remove no owned integration files:

```console
pcodex status --advisory --json
pcodex integrate codex --status --json
pcodex integrate openclaw --status --json
```

Install the authorized replacement with the same environment, then inspect and repair only proven-owned state:

```console
"$HOME/.pcodex-beta/bin/python" -m pip install --no-index --no-deps /path/to/authorized-replacement.whl
pcodex integrate codex --status --json
pcodex integrate codex --repair --dry-run --json
pcodex integrate codex --repair --json
pcodex integrate openclaw --status --json
pcodex integrate openclaw --repair --dry-run --json
pcodex integrate openclaw --repair --json
```

OpenClaw rollback is registration-scoped. A caught failed write restores the
verified prior JSON5 bytes and does not issue a completion receipt. Disable is
the reversible rollback surface: it removes only the exact receipt-proven
`mcp.servers.pcodex` registration while retaining bounded authority for a later
`--write`. Modified registrations, changed workspace or configuration
authority, malformed/future receipts, and interrupted uncertain state fail
closed and require the exact action reported by status.

The release matrix covers the declared previous beta, existing canonical and legacy plugins, partial installs, modified managed files, corrupt/future receipts, interrupted upgrades, caught upgrade failure rollback, unsupported downgrade, uninstall after failure, and reinstall after rollback.

## Failure behavior

On a caught failure, pCodex restores verified prior bytes before returning and does not issue a false completion receipt. If status reports an interrupted journal or uncertain ownership, automatic recovery stops. Preserve the evidence and follow the exact manual action; do not attempt package downgrade or delete staging paths.
