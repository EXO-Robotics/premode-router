# Canonical Codex Plugin

`plugins/pcodex` is the only supported source tree. Wheel and sdist artifacts
install the same files under `share/premode-router/plugins/pcodex`; lifecycle
code locates installed data without assuming a checkout or current directory.
The qualified and supported Codex line is `0.143.x`; live qualification used
Codex `0.143.0`.

The complete supported lifecycle is:

```console
pcodex integrate codex --dry-run
pcodex integrate codex --write
pcodex integrate codex --status
pcodex integrate codex --repair --dry-run
pcodex integrate codex --repair
pcodex integrate codex --disable
pcodex integrate codex --write
pcodex integrate codex --uninstall --dry-run
pcodex integrate codex --uninstall
pcodex integrate codex --write
pcodex integrate codex --status
```

Use `pcodex integrate codex --dry-run` first. `--write` installs canonical
files and one repo marketplace entry, registers the marketplace and plugin
through the supported Codex CLI, then writes independent repo and native
authority receipts at `.pcodex/codex-plugin-state.json` and
`.pcodex/codex-native-state.json`. `--status` is read-only. `--repair` restores
only missing receipt-proven bytes and re-enables exact disabled entries;
`--repair --dry-run` previews those actions literally without writing.
`--disable` is reversible. `--uninstall --dry-run` previews and `--uninstall`
applies removal of only exact owned files and the
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
repair restores it. The server binds once to the exact resolved
`PCODEX_WORKSPACE` recorded by the registration and never derives authority
from its launch directory or model-callable input. The installed wheel and
sdist probes exercise initialization, tool discovery, a real no-write call,
strict input rejection, bounded errors, and shutdown from a different launch
directory.

MCP requests are bounded to a 32,768-character and 65,536-byte exact task.
Undeclared fields, malformed types, control characters, and oversized task or
metadata inputs fail closed. Cancellation is bounded: an in-flight worker is
terminated, its result is discarded, and the request returns as cancelled. No
raw prompt, packet, or diagnostic receipt is persisted by the MCP server.

For the assigned optional-MCP first-run fixture, use this exact lifecycle:

```console
pcodex integrate codex --dry-run --with-mcp
pcodex integrate codex --write --with-mcp
pcodex integrate codex --status
pcodex integrate codex --disable
pcodex integrate codex --repair --dry-run
pcodex integrate codex --repair
pcodex integrate codex --uninstall --dry-run
pcodex integrate codex --uninstall
```

The status, disable, repair, and uninstall operations derive optional-MCP
authority from the exact installation receipt; they do not accept
`--with-mcp` as an ignored modifier.
Hooks, slash commands, automatic subagent interception, automatic Codex MCP
invocation, public marketplace publication, production approval, and OpenClaw
production integration are unsupported. Protocol qualification proves the
local registered server boundary; it does not claim that Codex automatically
chooses the tool for every task.
