# Local Context Compiler / premode-router Codex Instructions

Codex is working on a local context compiler and routing formatter. Do not turn Pre-mode into a planner or local reasoning engine.

## Subagent / Thread Policy

Codex is allowed and encouraged to use subagents for broad, parallel, or read-heavy Local Context Compiler work.

Use subagents by default for:

- comparing standard vs enhanced lanes,
- reviewing packet contents, routing diagnostics, changed files, and forbidden-path boundaries,
- checking benchmark methodology, token metrics, and clean-baseline evidence,
- exploring multiple ecosystem adapters or test surfaces in parallel.

Prefer flat subagent fan-out over nested delegation:

- spawn 3-6 subagents for normal broad work,
- spawn up to 10 only when the task is explicitly large or naturally separable,
- wait for all subagents and return one consolidated summary,
- keep subagents read-heavy unless implementation is explicitly requested.

Do not use subagents for tiny single-file edits, narrow commands, or parallel write-heavy work that would create conflicts.

## Canonical Agent Entry Points

For current repo operation, start with:

- `AI_START_HERE.md`
- `premode.ai.json`
- `AGENTS.md`

Historical prompt files under `docs/history/` are preserved for traceability and are not current operating instructions.

## pCodex Routing

When working in this repo, use pCodex for local Codex routing where available.

Primary commands:

- `.venv/bin/pcodex doctor`
- `.venv/bin/pcodex status`
- `.venv/bin/pcodex on`
- `.venv/bin/pcodex off`
- `.venv/bin/pcodex run --dry-run "<task>"`
- `.venv/bin/premode compile --plugin literal_symbol`

When creating a local subagent or delegated-agent prompt:

1. First write the exact raw subagent prompt Codex intends to send.
2. Route that exact Codex-created subagent prompt through pCodex before dispatch, using `transform_subagent_prompt` or the equivalent pCodex CLI/API.
3. Use `literal_symbol` unless the user explicitly configures a different supported algorithm.
4. Send the transformed prompt to the subagent.
5. If pCodex is disabled or transformation fails, send the raw prompt unchanged and report the fallback out of band.

This is an instruction-level routing contract and adapter-ready local behavior guidance. Do not claim it controls hosted/internal Codex subagents unless an official hook or local source patch is present and tested. Do not patch hosted Codex/Web UI. Do not print secrets, full environment dumps, diagnostics, TASK_CLASS, SUPPORT_RELATIONS, snippets, confidence, validation guidance, command suggestions, review metadata, or do-not-edit language into model-facing subagent prompts.

## Core Product Boundary

- Preserve the exact user prompt canonically. Do not rewrite or replace the prompt in model-facing packets.
- Keep Pre-mode focused on context selection, packet formatting, routing diagnostics, safety boundaries, and review support.
- Do not add planner-like task decomposition to compiled packets unless the user explicitly asks for planner behavior.
- Efficiency claims must be based on end-to-end behavior, not packet estimates alone.

## Source And Runtime Boundaries

- Do not modify `.premode/`, `.agents/`, `.agents/plugins/`, generated outputs, runtime caches, or plugin state unless explicitly requested.
- Do not modify `pcodex` Codex CLI argument handling unless explicitly requested.
- Use repo-local entrypoints such as `.venv/bin/python`, `.venv/bin/premode`, and `.venv/bin/pcodex` when available.
- For enhanced lanes, prove the import path before execution when the task depends on isolated Pre-mode source.

## Lab And Benchmark Work

- Use isolated `git worktree` lanes for Goldpine or cross-repo A/B labs. Do not use copied trees when a worktree is required.
- Both standard and enhanced lanes must start from the same baseline SHA.
- Keep results/logs under the requested results root, not inside the source repo unless explicitly requested.
- Preserve strict separation: standard lanes must not read enhanced packets, logs, or outputs.
- If an enhanced lane would send local repo context to an external Codex service, stop and ask for explicit approval.
- If usage limits or policy gates block execution, report the block instead of treating compile-only output as a completed live result.

## Patch Quality Gates

- A smaller packet is not a win if the resulting patch is bad, under-scoped, unrelated, unsafe, fails build, or mutates forbidden paths.
- Inspect changed files and task coverage before calling a lane successful.
- Use cheap runtime or behavior checks to validate wording and claims when possible.
- Reject strategies that improve candidate lists or packet size but fail patch fidelity.

## Commit Hygiene

- In dirty repos, stage only the explicit intended files.
- Do not stage `.premode/*`, `.agents/*`, plugins, generated outputs, or runtime artifacts by default.
- Before commit, run:
  - `git status --short`
  - `git diff --stat`
  - `git diff --check`
  - `git diff --cached --stat`
  - `git diff --cached --check`
- If the user asks for benchmark or regression numbers after a commit, rerun from the clean committed baseline before reporting final numbers.
