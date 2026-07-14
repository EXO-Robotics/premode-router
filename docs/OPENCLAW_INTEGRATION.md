# OpenClaw Integration

pCodex `0.3.0b1` includes one production OpenClaw adapter for OpenClaw `2026.4.14` on the qualified macOS and Linux matrix. It is an explicit, receipt-bound registration lifecycle; it does not intercept arbitrary OpenClaw activity.

From a qualified OpenClaw control-plane repository, preview before applying:

```console
pcodex integrate openclaw --dry-run
pcodex integrate openclaw --write
pcodex integrate openclaw --status
```

The preview is literal no-write. It resolves configuration authority and checks the installed OpenClaw package metadata locally without launching OpenClaw, MCP, Codex, or a helper process. Apply edits only `mcp.servers.pcodex` in the resolved OpenClaw JSON5 configuration, preserves unrelated bytes and formatting, and writes versioned lifecycle authority under `.pcodex/`.

The registration launches the installed package interpreter with `premode.pcodex_bootstrap openclaw-mcp-server`. The configured workspace is bound by absolute path plus device/inode identity. The `premode_preflight` tool accepts the exact task and optional `openclaw` profile only; callers cannot select another root or supply commands, environment variables, validation commands, or arbitrary execution fields.

Use the reversible lifecycle for damage, disablement, and removal:

```console
pcodex integrate openclaw --repair --dry-run
pcodex integrate openclaw --repair
pcodex integrate openclaw --disable
pcodex integrate openclaw --write
pcodex integrate openclaw --uninstall --dry-run
pcodex integrate openclaw --uninstall
```

Repair restores only a missing receipt-proven registration. Modified or unknown registrations, changed configuration authority, changed workspace identity, malformed/future receipts, and unsupported OpenClaw versions fail closed. Disable removes the owned registration while retaining reversible authority. Uninstall removes only the exact owned registration and product receipts; unrelated MCP registrations and user modifications are preserved.

Stop OpenClaw and any other writer of the selected configuration before
`--write`, `--repair`, `--disable`, or `--uninstall`. The beta detects and
preserves observed concurrent pathname/content races, but it does not claim to
preserve a write made later through an uncooperative descriptor that another
process kept open after pathname removal. This POSIX boundary does not affect
literal no-write preview or status operations.

The three versioned application contracts are
`OpenClawPreflightRequestV1`, `OpenClawPreflightResultV1`, and
`OpenClawPreflightReceiptV1`. Their Python models, JSON Schemas, and golden
fixtures define the product-level request, result, and content-free receipt.
MCP JSON-RPC messages are a transport mapping onto those contracts; MCP method
envelopes and tool-call arguments are not a second application-contract
authority.

Qualification covers wheel/sdist installation outside the checkout, real
OpenClaw discovery and config validation, no-write preview/status, lifecycle
parity, protocol initialization, tool listing and invocation, invalid input,
bounded concurrency, cancellation, shutdown, traversal/symlink containment,
and sensitive-error review. The frozen 20-task/10-fixture set is an adapter
policy and conformance set spanning investigation, source modification, repair,
state and authority reconciliation, Unreal, Blender, generated evidence, and
nested executors. It does not establish agent task success, patch quality,
complete-task cost, or the final held-out product claims.

Only OpenClaw `2026.4.14` is supported. Public marketplace publication, automatic interception, arbitrary command execution, arbitrary workspace selection, validation execution by the selection tool, and observer/Qwen harnesses are not part of this adapter.
