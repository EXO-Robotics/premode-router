# Migration

The supported release migration is from `0.2.6.24` at commit `b9aede455c8d49217ef0a67e8dec0c8cf2c565a6` to `0.3.0b1`. Install the new package, preview the canonical Codex integration, then apply only after the preview reports a supported legacy form.

```console
pcodex integrate codex --dry-run --repo-root /path/to/repository
pcodex integrate codex --write --repo-root /path/to/repository
pcodex integrate codex --status --repo-root /path/to/repository
```

pCodex migrates only state whose exact ownership is proven. Modified or unknown legacy files are preserved and reported for manual action. A canonical install may coexist on disk with preserved legacy material, but status does not report `READY` while two active authorities conflict.

Package downgrade is unsupported. Future or unknown receipt schemas fail closed and are not rewritten by an older release.
