# Public Surface Classification

This inventory classifies active implementation at the Private-Beta release boundary. Historical docs do not promote a surface.

| Classification | Active surfaces |
| --- | --- |
| `core` | `premode` package; compile, detect, index, inspect, locate, map, review-patch; router/compiler/locator/index/packet and safety modules |
| `codex_product` | Public: `pcodex setup`, `status`, `run`; supported advanced/support: `doctor`, `integrate codex`, Codex executor and repo-local Codex UX assets |
| `openclaw_product` | Implemented `openclaw_control_plane` repository profile and adapter policy only; no OpenClaw execution runtime or standalone integration |
| `advanced` | pCodex first-run, cleanup, on/off/tuned/tune/ui/compile, local MCP server, plugin init; Pre-mode benchmark/stress/stats; tuning and review tooling |
| `research` | `premode lab`, hook interception, live-token and observer harnesses, `lab73*` modules/tests, OpenClaw discovery/templates/fixtures, experimental selector variants |
| `deprecated` | private-alpha naming/instructions retained for compatibility; old V2-V4 packet and historical prompt documents; future registry install examples |

Packages are `premode-router` (`src/premode`) and the separately versioned `premode-plugin-literal-symbol`. Plugin entry points include the production `literal_symbol` plugin; plugin install/discovery machinery is advanced. `premode.mcp-server` and `pcodex mcp-server` are advanced, opt-in stdio surfaces. Templates under `templates/` and repo assets under `.agents/`/`plugins/` are integration material, not hosted publication.

Generated and persisted state is classified in `premode.product.json` and `docs/PRODUCT_CONTRACT.md`. Observer terminology, benchmarks, tuning internals, selector IDs, lab commands, and compatibility internals must not be presented as the normal public workflow.
