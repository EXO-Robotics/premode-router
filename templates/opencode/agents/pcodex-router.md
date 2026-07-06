---
description: Guidance for using pCodex from OpenCode without claiming automatic routing.
---
# pCodex Router Guidance

Use pCodex as an explicit terminal control plane before OpenCode work when the user asks for it.

Recommended checks:

```bash
pcodex status
pcodex run --dry-run "<task>"
```

This is guidance only. It does not prove automatic routing, built-in Codex commands, automatic MCP invocation, or internal subagent interception.
