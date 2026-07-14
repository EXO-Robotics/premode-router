# Canonical Codex Plugin Troubleshooting

Start with the read-only status command:

```console
pcodex integrate codex --status
```

`READY` means the receipt-proven canonical plugin and its exact registrations
are healthy. `NEEDS_ACTION` includes an absent or disabled plugin, a missing
supported Codex CLI, or preserved legacy state that requires a named next
action. `BLOCKED` means pCodex cannot prove safe ownership, such as malformed or
future-schema authority, duplicate registrations, modified owned files, or an
interrupted lifecycle journal.

Use `pcodex integrate codex --repair` only after reviewing status. Repair
restores only missing receipt-proven bytes and exact registrations; it does not
overwrite modified files or unrelated Codex, marketplace, plugin, or MCP state.
`pcodex integrate codex --disable` is reversible. Preview removal with
`pcodex integrate codex --uninstall --dry-run`, then apply it with
`pcodex integrate codex --uninstall`.

Legacy migration is always explicit. Preview with
`pcodex integrate codex --dry-run --migrate` and apply with
`pcodex integrate codex --write --migrate`. Only exact accepted historical
fingerprints are automatically removed. Modified or unknown legacy assets are
preserved and reported for manual review.

MCP remains disabled unless `--with-mcp` is explicitly supplied. MCP preview
does not write configuration or launch a server. Registration lifecycle proof
does not imply full protocol, containment, cancellation, or production-server
qualification.

Installed-artifact no-write qualification deliberately fails closed when
filesystem or process observation is unavailable. On macOS, a receipt with
`process_observation=unavailable` usually means the environment denied bounded
`ps` process-table observation. Run the same builder in a controlled environment
that permits `/bin/ps`; do not disable monitoring or remove governed roots.
Structured failure evidence is retained under `receipts/probe-execution/` and
`private-receipts/probe-execution/`.

The supported plugin requires Codex CLI `0.143.x`. The canonical source is
`plugins/pcodex`; installed artifacts carry it at
`share/premode-router/plugins/pcodex`. Source checkout paths, automatic agent
interception, public marketplace publication, production OpenClaw integration,
and universal savings claims are not supported.
