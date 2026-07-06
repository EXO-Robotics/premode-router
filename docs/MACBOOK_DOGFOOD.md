# MacBook Dogfood Notes

Date: 2026-07-06

## v0.3.1 Real-Prompt Smoke

- Public branch: `Private-Beta`
- Public install method: `scripts/install_pcodex_from_source.sh`
- Install root used: `/tmp/pcodex-alpha-source-v031`
- Direct Codex smoke: passed after updating Codex CLI
- pCodex dry-run: passed
- pCodex real run: passed
- Changed files: `PCODEX_REAL_PROMPT_SMOKE.md` only
- Runtime state observed: `.premode/pcodex_state.json`
- Known non-blocking warning: `.codex/skills/pcodex-subagent-routing/SKILL.md` was missing YAML frontmatter before the v0.3.2 hardening patch

## Codex CLI Finding

The initial MacBook Codex CLI version was `0.121.0` and failed real-run smoke with service-tier/config incompatibility symptoms. Updating Codex CLI to `0.142.5` allowed both direct Codex and pCodex real-prompt smoke to complete.

If direct `codex exec` fails, update or fix Codex CLI and local Codex config before debugging pCodex.

## Result

The v0.3.1 source install path supported a fresh public clone, isolated install, dry-run transform, and one deliberately scoped real Codex launch. The real prompt edited only the disposable target file and the final file contained:

```text
- pCodex real prompt smoke passed.
```

This is private-alpha dogfood evidence for the public source install path. It is not a production-readiness claim, not a universal savings claim, not native slash-command support, not native installed-Codex schema discovery, and not automatic or internal Codex subagent interception.
