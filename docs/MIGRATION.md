# Migration

The supported release migration is from `0.2.6.24` at commit `b9aede455c8d49217ef0a67e8dec0c8cf2c565a6` to `0.3.0b1`. Verify and install the qualified new package with the existing environment first. Then run the product-state preview and apply:

```bash
pcodex upgrade --check
pcodex upgrade --apply
```

The command never downloads or replaces the Python package. The released `0.2.6.24` installer created `.pcodex` user configuration rather than the newer `.premode/install-state.json` authority; that actual predecessor state is preserved unchanged and normally makes the product-state apply a no-op. If an exact compatible predecessor receipt or a supported historical Codex fingerprint is present, the command changes only that proven state. Unknown legacy state is preserved and blocks automatic migration. Receipt-compatibility fixtures are qualification evidence for fail-closed handling and are not represented as output from the historical wheel.

```console
pcodex integrate codex --dry-run --migrate --repo-root /path/to/repository
pcodex integrate codex --write --migrate --repo-root /path/to/repository
pcodex integrate codex --status --repo-root /path/to/repository
```

pCodex migrates only state whose exact ownership is proven. Modified or unknown legacy files are preserved and reported for manual action. A canonical install may coexist on disk with preserved legacy material, but status does not report `READY` while two active authorities conflict.

Running preview or write without `--migrate` performs the ordinary canonical plugin lifecycle; it is not a migration operation.

Package downgrade is unsupported. Future or unknown receipt schemas fail closed and are not rewritten by an older release.
