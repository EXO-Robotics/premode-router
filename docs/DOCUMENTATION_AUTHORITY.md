# Documentation Authority

The canonical user documentation set is deliberately small:

| Need | Authority |
| --- | --- |
| Product promise, non-goals, commands, and state | `docs/PRODUCT_CONTRACT.md`, `premode.product.json` |
| Installation and first useful dry run | `docs/GETTING_STARTED.md` |
| Codex lifecycle | `docs/CODEX_INTEGRATION.md` |
| OpenClaw status | `docs/OPENCLAW_INTEGRATION.md` |
| Troubleshooting | `docs/TROUBLESHOOTING.md` |
| Privacy, no-write, containment, and receipts | `docs/PRIVACY_AND_SAFETY.md` |
| Current unsupported claims | `docs/KNOWN_LIMITATIONS.md` |
| Migration | `docs/MIGRATION.md` |
| Upgrade and rollback | `docs/ROLLBACK.md` |
| Uninstall | `docs/UNINSTALL.md` |
| Literal 90/100 program and status | `docs/ROADMAP_TO_90.md`, `docs/PRODUCT_READINESS_GATE_LEDGER.md` |

`README.md`, `AI_START_HERE.md`, `premode.ai.json`, and `AGENTS.md` are entrypoints, not competing contracts.

`docs/FIRST_RUN.md`, `docs/PRIVATE_BETA_TESTER_PACKET.md`, `docs/PCODEX_BOOTSTRAP.md`, pasteable bootstrap prompts, tuning guides, private-alpha instructions, version plans, and lab reports are compatibility, developer, research, or historical material. They must not override the canonical set or create a second plugin/onboarding authority. Documents under `docs/history/` are explicitly historical.

Executable examples in the canonical set are statically validated by `scripts/validate_documentation.py`; validation parses commands and schemas but never executes stateful examples.
