# pCodex Integration Commands Plan

This is a future CLI plan. It is not implemented in this patch.

## Proposed Commands

```bash
pcodex integrate codex --dry-run
pcodex integrate codex --write
pcodex integrate opencode --dry-run
pcodex integrate opencode --write
pcodex integrate generic --dry-run
pcodex integrate generic --write
```

## Defaults

- `--dry-run` should be the recommended default.
- `--write` must be explicit.
- Generated files should be project-local by default.
- Real `~/.codex/config.toml` mutation must require a separate explicit flag.
- MCP registration must require separate explicit approval.
- The command should list every generated or patched file before writing.
- The command should write `PCODEX_SETUP_REPORT.md`.
- Skill templates must be validated for YAML frontmatter before write.
- Claim boundaries must be enforced before write.

## Codex Integration

`pcodex integrate codex --dry-run` should plan:

- `.codex/skills/pcodex/SKILL.md`
- `.codex/skills/pcodex-status/SKILL.md`
- `.codex/skills/pcodex-dry-run/SKILL.md`
- `.codex/skills/pcodex-tune/SKILL.md`
- `AGENTS.md` pCodex section
- `PCODEX_SETUP_REPORT.md`

It should not create custom prompt files as the primary Codex target. Codex skills are the Codex-facing reusable instruction surface.

## OpenCode Integration

`pcodex integrate opencode --dry-run` should plan:

- `.opencode/commands/pcodex.md`
- `.opencode/commands/pcodex-status.md`
- `.opencode/commands/pcodex-dry-run.md`
- `.opencode/commands/pcodex-tune.md`
- optional `.opencode/agents/pcodex-router.md`
- `AGENTS.md` pCodex section
- `PCODEX_SETUP_REPORT.md`

OpenCode command files are OpenCode-specific and must not imply Codex command support.

## Generic Integration

`pcodex integrate generic --dry-run` should plan:

- `AGENTS.md` pCodex section
- install/locate verification
- `pcodex doctor || true`
- `pcodex status`
- `pcodex setup`
- `pcodex run --dry-run`
- `PCODEX_SETUP_REPORT.md`

## Explicit Approval Gates

The integration command must require separate approval for:

- writing files
- registering MCP
- mutating real Codex config
- running non-dry-run `pcodex run`

The command must not claim built-in `/pcodex` command support, automatic MCP invocation, internal subagent interception, production readiness, or guaranteed savings.
