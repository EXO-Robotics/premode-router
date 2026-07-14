# Contract Compatibility

The machine-readable product authority is `premode.product.json`. Cross-process payloads use one strict v1 schema each, a typed Python authority, and a checked golden fixture.

## Contract map

| Product name | Python authority | Schema | Sensitivity |
| --- | --- | --- | --- |
| `ContextRequestV1` | `ProductionRankingRequestV1` | `production-ranking-request-v1.schema.json` | sensitive/private |
| `ContextSelectionV1` | `ProductionRankingResultV1` | `production-ranking-provider-v1.schema.json` | private metadata; receipt content-free |
| `ContextPacketV1` | `ContextPacketV1` | `context-packet-v1.schema.json` | sensitive/private |
| `ContextReceiptV1` | `ContextReceiptV1` | `context-receipt-v1.schema.json` | private metadata |
| `PacketStrategyPluginV1` | `PacketStrategyPluginV1` | `packet-strategy-plugin-v1.schema.json` | public-safe descriptor |
| `AgentAdapterV1` | `AgentAdapterV1` | `agent-adapter-v1.schema.json` | public-safe descriptor |

`ContextRequestV1` and `ContextSelectionV1` are product vocabulary for the existing production-ranking request and result contracts. They are not duplicate wire formats.

## Compatibility policy

- Consumers accept the exact declared v1 schema and reject missing, additional, malformed, or unknown-version fields.
- Legacy Python `premode.plugins` entry points without descriptor-version fields are adapted to `PacketStrategyPluginV1` only after their original required packet fields validate. Explicitly declared unknown versions or sensitivities fail closed.
- Unknown major, minor, or future schema identifiers fail closed. There is no implicit downgrade or best-effort coercion.
- Because the schemas use `additionalProperties: false`, an additive wire change requires a new schema version and an explicit compatibility adapter.
- Golden fixtures are contract examples, not evaluation data. Packaging permits exactly the six named fixtures and rejects additional files in that directory.
- The exact task exists once in `ContextPacketV1`, inside the canonical rendered packet. Its length and SHA-256 bind the TASK field without copying the raw task into metadata.
- Public-safe descriptors may be included in release evidence. Context requests and packets must never enter public receipts, logs, SBOMs, provenance, or case-study bundles without explicit sanitization.

The installed wheel and sdist validate every golden against its installed schema outside the source checkout.
