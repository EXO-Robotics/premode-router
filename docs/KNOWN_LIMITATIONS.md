# Known Limitations

The production ranking path is deliberately frozen to the incumbent provider for `0.3.0b1`. The sanitized handoff records `no_candidate_promoted`; this does not establish broad token savings, cross-model qualification, or final held-out release proof.

The `0.3.0b1` foundation has CI-backed qualification on macOS and Linux with Python 3.11-3.13. The supported Codex line is `0.143.x`, with canonical live discovery qualified on `0.143.0`. The supported OpenClaw version is exactly `2026.4.14`. Other Codex minor versions and OpenClaw versions are unsupported unless separately declared and tested.

The following are not current release claims:

- public package or marketplace availability;
- automatic hosted-agent interception;
- universal token savings or quality improvement;
- automatic OpenClaw interception, arbitrary workspace selection, or OpenClaw versions other than `2026.4.14`;
- Windows support;
- arbitrary power-loss recovery;
- preservation of writes made through an uncooperative, already-open file
  descriptor after the corresponding configuration or receipt pathname has
  been removed;
- a completed five-tester first-run study;
- a frozen 10-repository, 100-task held-out release proof.

Optional MCP remains disabled by default. The canonical Codex plugin does not require MCP for its supported lifecycle.
The registered local MCP server is workspace-bound and protocol-qualified, but
automatic Codex tool selection or subagent interception is not claimed.
The production OpenClaw adapter uses its own explicit workspace-bound MCP registration. Its selection tool does not execute validation commands or grant arbitrary command execution.
Its frozen 20-task/10-fixture suite qualifies adapter policy and conformance,
not end-to-end agent task success, patch quality, or complete-task economics.
Those outcome claims remain gated on the frozen held-out evaluation.

OpenClaw state-changing lifecycle commands require OpenClaw and other writers
of the selected JSON5 configuration to be quiescent. The lifecycle detects
pathname replacement, parent swaps, and content changes observed before and
after publication/removal, preserves detected competing bytes in recovery
staging, and fails closed. POSIX does not provide a portable conditional
unlink that can preserve a future write made through an independently held
descriptor after the last observable read; that stronger arbitrary-writer
guarantee is not claimed. Preview and status remain safe while OpenClaw is
running.
