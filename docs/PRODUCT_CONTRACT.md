# pCodex Product Contract

Status: source-visible proprietary Private-Beta. This document is the authority for the supported release product at the `Private-Beta` branch head. Implementation and tests remain authoritative when this document is wrong.

## Product promise

pCodex is the Codex CLI product surface for Pre-mode Router. It preserves the user's task, selects likely repository paths reproducibly for identical eligible inputs, configuration, and version, formats a compact V5 packet, and can launch Codex with that packet. The production package is `premode-router`; the production ranking and packet path is the separately packaged `literal_symbol` plugin mapped to packet version `v5`, variant `tool_assisted_anchors_internal`, and strategy `literal_symbol`.

The first supported runtime is Python 3.11 or newer on a local source installation, driving Codex CLI through explicit terminal commands. Source installation is documented in `docs/FIRST_RUN.md`. No package-registry release is asserted.

## Deliberate non-goals

pCodex is not a reasoning engine, planner, autonomous agent, hosted service, or replacement for Codex. It does not promise correct patches, universal token savings, native `/pcodex` slash commands, hosted Codex UI integration, automatic MCP invocation, internal Codex subagent interception, or automatic global Codex configuration.

OpenClaw detection and the `openclaw_control_plane` repository profile are implemented advanced adapter behavior, but OpenClaw is not a supported execution runtime or standalone product integration. Templates, fixtures, and control-plane research do not automate OpenClaw, Unreal, Blender, or bridge writes.

## Supported workflow and commands

The public workflow is dry-run first:

```text
pcodex doctor
pcodex setup --skip-tune --no-mcp
pcodex status
pcodex run --dry-run "<task>"
pcodex run "<task>"
```

Supported public pCodex commands are exactly `setup`, `status`, and `run`. `doctor`, `integrate codex`, and `premode review-patch` are supported advanced/support steps. The implemented `pcodex cleanup --local-state` command owns bounded local cleanup; there is no public `pcodex uninstall` command. `first-run`, `on`, `off`, `tuned`, `tune`, `ui`, and `compile` are advanced compatibility or operator surfaces. MCP, plugin scaffolding, benchmarks, stress tools, labs, hooks, selector identifiers, and tuning internals are not normal public help promises.

## Read and write boundaries

Compilation may read repository metadata and eligible files subject to ignore, sensitivity, and task-root boundaries. Running pCodex may also read its repo-local configuration and state plus the installed Codex executable's help/capabilities. It must not treat ignored secrets as model-facing context.

Owned generated state is repo-local unless an explicitly approved installation or integration command says otherwise:

| Path | Owner | Purpose | Cleanup responsibility |
| --- | --- | --- | --- |
| `.premode/out/` | Pre-mode | packets and compile outputs | `pcodex cleanup --local-state --yes` or user deletion |
| `.premode/audit/`, `.premode/metrics/` | Pre-mode | content-free review/measurement records | same |
| `.premode/pcodex_state.json` | pCodex | mode state | same |
| `.premode/lcc.lock.json` | Pre-mode | deterministic compile authority | same |
| `.premode/inventory/`, `.premode/topology/` | Pre-mode | local indexes | same |
| `.premode/tuning/` | pCodex tuning | repo-specific advanced state | same; review before versioning |
| `.pcodex/` | legacy pCodex material | compatibility path, not in the active cleanup allowlist | manual, after inspection |
| `PCODEX_SETUP_REPORT.md` | user/bootstrap workflow | optional pasted-bootstrap report; not emitted by the active CLI | manual |
| `.agents/skills/pcodex*`, `.agents/plugins/`, `plugins/pcodex/` | Codex integration command/repo | repo-local integration assets | remove only with explicit user approval |
| `$HOME/.pcodex-alpha/` | source installer | isolated installation | installer manifest-guided user removal |

Normal commands must not mutate global Codex config. Integration writes require `pcodex integrate codex --write`; optional MCP setup remains separate and user-approved. Uninstall is currently manual: remove the manifest-recorded install root and intentionally created repo-local assets/state. pCodex must not delete user-authored files merely because they share a parent directory.

## Integration status

Codex CLI terminal operation is the supported product integration. Repo-local skills and plugin scaffolds are discoverability/UX assets, not marketplace publication. The local stdio MCP transformer is advanced and opt-in, not automatically registered or invoked. The OpenClaw repository profile is advanced; OpenClaw execution integration is unsupported.

## Claims that remain unproven

The project has not proven universal end-to-end token or cost savings, improved patch quality across repositories, production readiness, public package availability, hosted-agent interception, automatic MCP behavior, or production-grade OpenClaw support. Benchmark and packet-size results are bounded measurements, not general product guarantees.

## Authority map

- Product and claim boundary: this document and `premode.product.json`.
- First run: `docs/FIRST_RUN.md`.
- Codex status and limitations: `docs/PCODEX_MCP_STATUS.md` and `docs/CLAIMS_AND_LIMITATIONS.md`.
- Troubleshooting: `docs/PRIVATE_BETA_TESTER_PACKET.md`.
- Historical material: `docs/history/`; it is never current operating authority.
- Version: root `pyproject.toml` `[project].version`, mirrored by `src/premode/__init__.py` and checked by CI.
- Release branch: remote `Private-Beta`; feature branches are reviewed before merge and tags/releases require separate authority.
