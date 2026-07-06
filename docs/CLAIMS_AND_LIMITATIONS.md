# Claims And Limitations

This document defines the public wording boundary for the current private pCodex alpha.

## Supported Claims

- On the six-prompt public same-run matrix, `literal_symbol` reduced derived cache-adjusted input by 17.02% versus standard and 11.68% versus `ranked_paths_plus_anchors`, with zero scope issues and zero leakage.
- `premode compile --plugin literal_symbol` is the lead local plugin path.
- Explicit compile-time tuning is available with `premode compile --plugin literal_symbol --tuning PATH`.
- pCodex can generate static repo tuning artifacts locally with `pcodex tune --static-only`.
- pCodex can validate tuning artifacts locally with `pcodex tune --validate`.
- pCodex can run an offline mini verifier with `pcodex tune --verify`.
- pCodex supports three repo-local modes: `off`, `on`, and `tuned`.
- `pcodex run` and the pCodex MCP transform respect off/on/tuned mode state.
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

## Required Wording Discipline

Use:

- measured public same-run matrix
- private local alpha
- command-backed MCP harness
- not yet proven

Avoid:

- always
- guaranteed
- automatic interception
- production-ready
- universal

## Current Claim Boundary

The supported efficiency claim is limited to the measured public same-run matrix. It does not establish performance on every repository, every task, or every Codex workflow.

Tuned-mode improvements are repo-specific and must be verified locally. `pcodex tune --verify` is a compile-only local-selection verifier; it is not a live Codex success guarantee.

The supported MCP claim is command-backed local MCP compatibility for the pCodex server command and tool. It does not prove that installed Codex natively exposes schema inspection, calls the tool automatically, or intercepts internal subagent dispatch.
