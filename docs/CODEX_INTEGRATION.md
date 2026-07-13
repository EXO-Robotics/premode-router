# Canonical Codex Plugin

`plugins/pcodex` is the only supported source tree. Wheel and sdist artifacts
install the same files under `share/premode-router/plugins/pcodex`; lifecycle
code locates installed data without assuming a checkout or current directory.

Use `pcodex integrate codex --dry-run` first. `--write` installs canonical
files and one repo marketplace entry, registers the marketplace and plugin
through the supported Codex CLI, then writes independent repo and native
authority receipts at `.pcodex/codex-plugin-state.json` and
`.pcodex/codex-native-state.json`. `--status` is read-only. `--repair` restores
only missing receipt-proven bytes and re-enables exact disabled entries.
`--disable` is reversible. `--uninstall` removes only exact owned files and the
exact owned entry. Modified, linked, malformed, future-schema, duplicate, and
unknown-owner state is preserved or blocked.

`--dry-run --migrate` previews and `--write --migrate` applies migration.
Migration never infers legacy ownership from a name or path. Exact historical
fingerprints may be removed; unknown or modified legacy files are preserved for
manual recovery. Interrupted operations retain ownership-bound journals and
never report `READY`.

MCP is absent by default. `--with-mcp` explicitly creates a plugin-local,
workspace-bound descriptor and an exact Codex MCP registration resolved through
the installed Python artifact. Disable removes the owned active MCP entry and
repair restores it. Full server-containment qualification remains deferred.
Hooks, slash commands, automatic subagent interception, automatic
MCP invocation, public marketplace publication, production approval, and
OpenClaw production integration are unsupported.
