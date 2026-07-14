# Uninstall

Preview is literal no-write:

```console
pcodex uninstall --dry-run --json --repo-root /path/to/repository
pcodex integrate codex --uninstall --dry-run --json --repo-root /path/to/repository
```

Apply only after reviewing the plan:

```console
pcodex integrate codex --uninstall --json --repo-root /path/to/repository
pcodex uninstall --yes --json --repo-root /path/to/repository
```

Uninstall removes only exact, receipt-proven, unmodified pCodex files and registrations. It preserves unrelated configuration, modified files, unknown legacy state, and unproven MCP entries. Remove the Python package with the same environment's package manager only after integration cleanup.

For the canonical invited-beta virtual environment:

```console
"$HOME/.pcodex-beta/bin/python" -m pip uninstall premode-router
```

For a source installation, use the source installer's manifest-validated removal:

```console
scripts/install_pcodex_from_source.sh --uninstall
```

Do not delete plugin, marketplace, Codex, `.premode`, `.pcodex`, or quarantine paths by hand when status reports a conflict or interrupted operation.
