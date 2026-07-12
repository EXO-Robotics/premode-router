# Public Surface Classification

This inventory classifies active implementation at the Private-Beta release boundary. Historical docs do not promote a surface.

| Classification | Active surfaces |
| --- | --- |
| `core` | `premode` package; compile, detect, index, inspect, locate, map, review-patch; router/compiler/locator/index/packet and safety modules |
| `codex_product` | Public: `pcodex setup`, `status`, `run`, `doctor`, `review`, `off`, `cleanup`, plus lower-level `premode review-patch`; Codex executor. `integrate codex` is an advanced repo-local UX command. The intended headline `pcodex uninstall` is not implemented. |
| `openclaw_product` | Implemented `openclaw_control_plane` repository profile and adapter policy only; no OpenClaw execution runtime or standalone integration |
| `advanced` | pCodex first-run, on/tuned/tune/ui/compile, `integrate codex`, local MCP server, plugin init; Pre-mode benchmark/stress/stats; tuning and review tooling |
| `research` | `premode lab`, hook interception, live-token and observer harnesses, `lab73*` modules/tests, OpenClaw discovery/templates/fixtures, experimental selector variants |
| `deprecated` | private-alpha naming/instructions retained for compatibility; old V2-V4 packet and historical prompt documents; future registry install examples |

The production package is `premode-router` (`src/premode`) and includes the default `literal_symbol` strategy. Third-party strategy entry points remain compatible optional extensions; plugin install/discovery machinery is advanced. `premode.mcp-server` and `pcodex mcp-server` are advanced, opt-in stdio surfaces. Templates under `templates/` and repo assets under `.agents/`/`plugins/` are integration material, not hosted publication.

Generated and persisted state is classified in `premode.product.json` and `docs/PRODUCT_CONTRACT.md`. Observer terminology, benchmarks, tuning internals, selector IDs, lab commands, and compatibility internals must not be presented as the normal public workflow.
