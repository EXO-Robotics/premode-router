# Literal No-Write Contract

This document refines the lifecycle meanings in `docs/PRODUCT_CONTRACT.md` and the state authority in `premode.product.json`. It does not create a competing command registry.

## Operation meanings

- `advisory`: inspect current state without mutation, repair, migration, refresh, agent launch, or diagnostic bundle creation.
- `preview`: calculate and report a bounded proposed change without preparatory mutation.
- `dry-run`: exercise the supported planning or in-memory compilation path without writes, external-agent launch, or capability-probe execution.
- `apply`: perform only the explicitly authorized state change and its required receipt writes.

`advisory`, `preview`, and `dry-run` use the typed `ADVISORY` write policy at every shared lower-level boundary. Missing, stale, corrupt, partial, and unknown-future state remains unchanged. Normal apply behavior retains the `NORMAL` policy.

## Command inventory

| Surface | Classification | Literal behavior |
| --- | --- | --- |
| `pcodex status --advisory` | `literal_no_write_required` | Read state and return paste-safe readiness; no lock refresh, Git helper, or Codex execution. |
| `pcodex doctor --advisory` | `literal_no_write_required` | Read diagnostics; executable discovery is path-only and no external agent is executed. |
| `pcodex run --dry-run` | `literal_no_write_required` | Compile in memory with `ADVISORY`; no packet, cache, lock, telemetry, receipt, or Codex capability probe. |
| `pcodex integrate codex --dry-run` | `literal_no_write_required` | Inspect canonical, legacy, marketplace, and optional-MCP state and build a plan in memory. |
| `pcodex integrate codex --status` | `literal_no_write_required` | Classify plugin and registration state without repair or capability processes. |
| `pcodex integrate codex --dry-run --with-mcp` | `literal_no_write_required` | Preview the optional descriptor and workspace binding without creating or launching it. |
| `pcodex integrate codex --repair --dry-run` | `literal_no_write_required` | Preview only missing receipt-proven plugin and registration restoration without mutation or Codex launch. |
| `pcodex integrate codex --uninstall --dry-run` | `literal_no_write_required` | Preview only exact receipt-proven removals while preserving modified or unrelated state. |
| `pcodex repair --dry-run` | `literal_no_write_required` | Read bound lifecycle authority and exact hashes; no repair, migration, operation receipt, or temporary file. |
| `pcodex uninstall --dry-run` | `literal_no_write_required` | Read receipt and targets with fail-closed ownership rules; no operation receipt or quarantine. |
| `pcodex cleanup --local-state --dry-run` | `literal_no_write_required` | List bounded generated-state targets without deletion. |
| `pcodex install` without `--apply` | `literal_no_write_required` | Preview config creation and use advisory diagnostics. |
| `pcodex first-run --advisory` | `literal_no_write_required` | Emit content-free read-only receipt to stdout. |
| `pcodex plugin init --local-marketplace --dry-run` | `literal_no_write_required` | Plan repo-local plugin files without writes. |
| `pcodex compile --dry-run` | `literal_no_write_required` | Report the compile command plan; does not compile or record. |
| `premode codex --dry-run` | `literal_no_write_required` | Compile in memory; force save and record off; do not probe or launch Codex. |
| `premode compile --no-record` without output flags | `read_only_but_not_publicly_promised` | Existing in-memory compilation surface; output/save flags are state-changing. |
| `premode review-patch` without `--out` | `read_only_but_not_publicly_promised` | Git-backed inspection; `--out` is state-changing. |
| `pcodex ui` | `read_only_but_not_publicly_promised` | State inspection only; no Codex execution. |
| `pcodex tune --validate` | `state_changing` | Validation currently writes a report; it is not advertised as no-write. |
| `pcodex tune --verify` | `state_changing` | Verification writes validation and verification reports. |
| `pcodex status` without `--advisory` | `state_changing` | May refresh the repository lock receipt. |
| install `--apply`, setup/on/off/tuned/tune apply, integration `--write`, plugin init without `--dry-run`, cleanup/repair/uninstall `--yes` | `state_changing` | Require explicit apply authority. |
| setup/off dry-run, review-patch dry-run, plugin migration preview | `unsupported` | No such current authoritative flag is advertised. |
| legacy private-alpha installer/plugin names | `deprecated` | Compatibility-only; no new guarantee is inferred. |
| OpenClaw execution integration | `experimental` | Not a production no-write surface. |

## Evidence model

`premode.no_write` snapshots bounded governed roots derived by the product-authority root factory, including controlled `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, and `XDG_DATA_HOME` pCodex roots. A receipt cannot claim complete coverage from caller-supplied category labels: the factory binding and the complete canonical root-ID/category map are required. The framework records no-follow entry type, device/inode, size, mode, uid/gid, regular-file content evidence, symlink target, directory membership, mtime, ctime, birth time where available, xattr name/value hashes where supported, and hard-link count. Missing and unreadable paths remain explicit records. FIFOs, sockets, and device files are never opened.

Files up to 4 MiB receive a full SHA-256. Larger files receive size plus SHA-256 over bounded 64 KiB samples at the start, midpoint, and end. Metadata detects size, timestamp, ownership, mode, inode, and link changes; an adversarial same-size modification outside all three samples with restored metadata is a documented limitation. `O_NOATIME` is used where the platform supports and permits it; otherwise platform access-time behavior is not part of the comparison because reading evidence can itself affect access time.

Symlinks are recorded and never followed during enumeration. Hard links are represented by device, inode, and link count. Scan, hash, xattr, and traversal errors make evidence fail closed. On macOS, recursive kqueue vnode observation detects transient create/write/delete activity that a before/after snapshot alone would miss; requested transient observation fails closed where that backend is unavailable or fails after startup. Process evidence uses `/proc` where available and bounded `ps` polling on macOS, classifies exact executable paths and interpreter/wrapper arguments, and is paired with controlled fake-executable marker roots for installed Codex, OpenClaw, and MCP checks. A strict receipt reports `pass` only when both filesystem and process observation completed; disabled or unavailable observation produces a failure receipt. Polling still has a documented sub-interval observation limit, so the process field means no classified launch was observed within that backend rather than a universal operating-system execution audit. Network attempts are currently reported as `not_measured`, not claimed absent.

The detailed `pcodex.no-write-evidence.private.v1` receipt has its own strict registered schema, contains local relative changes and governed-root paths, and remains private; task arguments remain opaque even there. The strict sanitized `pcodex.no-write-evidence.v1` receipt exposes bounded command IDs, explicitly allowlisted option names, opaque values, root IDs, hashes, classifications, coverage, and results without raw tasks, packets, repository contents, secret values, full configuration, or absolute private paths. The writer rejects output that overlaps any governed root. Installed-artifact probing validates every generated public and private receipt against the installed schemas before release persistence; only sanitized receipts belong on a public handoff surface.
