# Claims And Limitations

This document defines the wording boundary for the current pCodex Private-Beta.

## Supported Claims

- Normal pCodex routing preserves the exact task and emits ordered likely paths through one canonical compact renderer.
- `literal_symbol` remains the compatibility-preserved production ranking path; it is not declared strategically final.
- Explicit compile-time tuning is available with `premode compile --plugin literal_symbol --tuning PATH`.
- Plain `pcodex setup` is the narrow path and skips tuning and MCP registration. Broader setup remains developer compatibility behavior.
- pCodex can run static generation, validation, and offline verification locally with `pcodex tune`.
- Advanced tuning maintenance remains available with `pcodex tune --static-only`, `pcodex tune --validate`, and `pcodex tune --verify`.
- pCodex supports three repo-local modes: `off`, `on`, and `tuned`.
- pCodex provides `pcodex first-run` and `pcodex first-run --json` for content-free first-run receipts.
- pCodex provides `pcodex cleanup --local-state --dry-run` and `pcodex cleanup --local-state --yes` for known repo-local generated state.
- pCodex provides read-only/no-write advisory receipts with `pcodex status --advisory`, `pcodex doctor --advisory`, and `pcodex first-run --advisory`.
- `premode benchmark` is a compile-only harness. Its full-repo reduction and derived cache-adjusted fields are benchmark estimates, not live Codex token usage or cost savings.
- `on` means best safe available pCodex behavior: it uses tuned behavior only when a valid profile exists and local verifier verdict is `PASS`; otherwise it uses generalized `literal_symbol`.
- `tuned` is strict and fails clearly when a tuning profile is missing or invalid.
- `pcodex status` reports configured mode, effective mode, tuning, MCP, fallback, local telemetry, and savings-estimate availability.
- Fallback telemetry is local-only and stores counters/reasons only, not prompts, source snippets, secrets, or file contents.
- `pcodex run` and the pCodex MCP transform respect effective mode and expose configured/effective mode in out-of-band metadata.
- pCodex provides local wrapper, mode state, compile, run, and dry-run behavior around the `literal_symbol` path.
- pCodex alpha4 provides a command-backed stdio MCP server surface through `pcodex mcp-server`.
- The command-backed MCP harness discovered `pcodex_transform_subagent_prompt`, exposed schema through `tools/list`, and transformed a safe dummy prompt.

## Unsupported Claims

- Universal token savings.
- Savings on all Codex tasks.
- Guaranteed tuned savings.
- Production-ready Codex interception.
- Automatic internal Codex subagent routing.
- Native slash-command support.
- Native installed-Codex schema discovery.
- Hosted Codex UI integration.
- Public package release readiness.
- PyPI or pipx package availability unless a package has actually been published.
- Public benchmark proof or generalized public performance proof.
- No local reads in advisory mode; advisory mode is a no-write/no-mutation claim.
- Live Codex token savings or live cost savings from compile-only benchmark output.

## Required Wording Discipline

Use:

- bounded local same-run matrix
- source-visible proprietary Private-Beta
- command-backed MCP harness
- not yet proven

Avoid:

- always
- guaranteed
- automatic interception
- production-ready
- universal

## Current Claim Boundary

Packet byte counts and structural measurements are observations only. They do not establish downstream token savings, task-quality gains, or public benchmark superiority.

Tuned-mode improvements are repo-specific and must be verified locally. `pcodex tune --verify` is a compile-only local-selection verifier; it is not a live Codex success guarantee.

`pcodex tune` now includes verification in the default local pipeline. A `PASS` verifier result allows `on` mode to use tuned behavior, but it still does not guarantee live Codex task success or universal savings.

The supported MCP claim is command-backed local MCP compatibility for the pCodex server command and tool. It does not prove that installed Codex natively exposes schema inspection, calls the tool automatically, or intercepts internal subagent dispatch.
