# CODEX ONE-SHOT PROMPT — v2.6.2 Review Baseline Hardening

You are implementing Pre-mode Router v2.6.2.

Goal: harden `premode review-patch` for real local workflows where repos may already contain dirty or untracked files before a coding agent starts.

Do not implement benchmark mode, auto-running tests, auto-reverting, cloud features, embeddings, or agent config linting in this patch.

Required changes:

1. Save compile-time worktree baseline
   - Add `pre_agent_worktree_state` to compile output and saved `.premode/out/last_packet.json`.
   - Include git HEAD SHA, branch, dirty files, untracked files, status records, and file hashes.
   - Include the same object in `review_contract`.

2. Add review mode
   - Add `premode review-patch --since-compile`.
   - When available, compare against `pre_agent_worktree_state.git_head_sha`.
   - Keep `--against` behavior as fallback.

3. Split changes
   - Report `all_current_changed_files`.
   - Report `preexisting_changes` for unchanged files already dirty/untracked at compile time.
   - Report `post_compile_changes` and `agent_candidate_changes` for files changed after compile.
   - Only agent-candidate changes should drive merge readiness.
   - If a pre-existing dirty file changes again, review it normally.

4. Improve report metadata
   - Add `base_ref_requested`, `base_ref_used`, and `base_ref_fallback_reason`.
   - Split findings into `blocking_findings`, `warning_findings`, and `info_findings`.
   - Keep `risk_findings` for compatibility.

5. Tests
   - compile saves `pre_agent_worktree_state`.
   - `--since-compile` uses saved HEAD.
   - pre-existing untracked `.premode/` setup files do not warn if unchanged.
   - a pre-existing dirty file changed after compile is reviewed as an agent candidate.
   - missing base ref reports fallback metadata.
   - findings are split.

Validation:

```bash
python -m pip install --no-index --no-build-isolation --no-deps -e .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
bash scripts/smoke_test.sh
premode stress --profile lite
```

Return a concise implementation report with files changed, commands run, tests passed, risks, and next recommended patch.
