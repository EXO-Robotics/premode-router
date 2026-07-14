# Privacy and Safety

pCodex runs locally and deterministically. It reads eligible repository metadata and file content to select likely paths, subject to repository root, ignore, sensitivity, generated-file, and containment policies. The coding agent—not pCodex—decides whether a later real run sends content to an external model runtime.

## Model-facing data

The canonical packet contains the exact task once, ordered likely paths, optional path roles, and the fixed expansion instruction. It excludes observer state, Qwen/evaluation data, experiment identifiers, private receipts, raw repository inventories, and diagnostics.

Context requests and packets are sensitive/private. Public receipts contain content-free status, hashes, counts, versions, and bounded reasons. Managed receipts must not store raw prompts, packet text, source bodies, snippets, secrets, environment values, or path inventories.

## Literal no-write operations

Advisory, preview, and dry-run operations listed in `docs/NO_WRITE_CONTRACT.md` must produce:

- zero repository, user, integration, cache, receipt, metadata, and governed temporary changes;
- zero Codex, OpenClaw, or MCP launches;
- zero registration changes;
- valid public and private evidence receipts.

If filesystem or process observation is unavailable, installed-artifact qualification fails closed. It does not disable monitoring or narrow governed roots to manufacture a pass.

## State and reversibility

State-changing operations require explicit authority. Repair and uninstall act only on exact receipt-proven state and preserve modified files, unrelated configuration, unknown owners, malformed/future schemas, and uncertain legacy state. Path traversal, root escape, hard links, symlinks, and ownership mismatches fail closed.

## Codex and MCP

The canonical Codex plugin is repository-bound and MCP is disabled by default. `--with-mcp` is explicit opt-in. The registered stdio server binds to the exact resolved workspace from receipt-owned configuration, rejects caller-selected roots and oversized or malformed inputs, performs no-write selection, and returns bounded errors without absolute roots or environment values. This qualification does not claim automatic Codex invocation or hosted-agent interception.

Normal pCodex operations do not claim that network activity is globally absent; no-write evidence reports network observation as measured or not measured. Real Codex runs follow the installed Codex runtime's own network and data policies.

Technical authorities:

- `docs/NO_WRITE_CONTRACT.md`
- `premode.product.json`
- `schemas/pcodex.no-write-evidence.schema.json`
- `schemas/pcodex.no-write-evidence.private.schema.json`
- `schemas/pcodex.install-state.schema.json`
- `docs/CONTRACT_COMPATIBILITY.md`
