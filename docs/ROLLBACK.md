# Rollback

pCodex lifecycle operations use versioned ownership receipts and bounded journals. If an install, repair, migration, or uninstall is interrupted, rerun status before taking another action:

```console
pcodex status --advisory --json --repo-root /path/to/repository
pcodex integrate codex --status --json --repo-root /path/to/repository
```

Use the single recommended action returned by status. Do not delete `.premode`, `.pcodex`, plugin, marketplace, Codex configuration, or quarantine paths by hand. User-modified, unrelated, malformed, and future-schema state is preserved rather than normalized.

Rollback means restoring the last receipt-proven state during the same operation. It does not claim arbitrary power-loss recovery or support package downgrade from `0.3.0b1`.
