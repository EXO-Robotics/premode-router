# Codex One-Shot Prompt — Pre-mode Router v2.4.1

You are making a focused v2.4.1 hardening patch for `premode-router`.

## Goal

Fold trust-hardening fixes into the v2.4 deterministic Evidence Packet compiler.

Do **not** add repo-map intelligence, Ollama, embeddings, local assist, MCP expansion, patch-review commands, or auto-running build/test commands in this patch.

The product should remain simple:

```bash
premode setup
pcodex "Fix the build"
```

The goal is to make the v2.4 evidence packet more trustworthy:

```text
fix false evidence
fix fake prompt path mentions
fix patch-boundary contradictions
fix generated command override reporting
make hard packet budgets actually hard
```

## Required fixes

### 1. Fix log scanner false positives

Current issue:

`src/premode/log_scanner.py` can be scanned as a log file because its path contains `log`. If the source contains regex text such as `error:`, the compiler can treat that source line as a real first meaningful error.

Fix in:

```text
src/premode/log_scanner.py
```

Only scan actual log-like files:

- `*.log`
- `*.trace`
- `build.log`
- `test.log`
- `xcodebuild.log`
- `pytest.log`
- `*.txt` only when filename contains `build`, `test`, `error`, `crash`, `compile`, `xcode`, or `pytest`

Do **not** scan source files merely because their path contains `log`:

- `.py`
- `.swift`
- `.ts`
- `.tsx`
- `.js`
- `.jsx`
- `.go`
- `.rs`
- `.java`
- `.kt`
- `.c`
- `.cpp`
- `.h`
- `.hpp`

Regression test:

```text
A repo containing src/premode/log_scanner.py with ERROR_RE/error text but no real logs should produce first_meaningful_error = null.
```

### 2. Fix prompt-mentioned path extraction

Current issue:

A sentence ending with:

```text
make sure the app builds.
```

can create:

```json
{
  "prompt_mentioned_files": ["builds"]
}
```

Fix in:

```text
src/premode/compiler.py
```

Rules:

- Strip punctuation before path detection.
- Resolve prompt path mentions against the indexed repo.
- Only mark prompt-mentioned paths when:
  - token exactly matches an indexed repo-relative path, or
  - token contains `/`, has a known file extension, and matches an indexed path suffix, or
  - token has a known file extension and matches an indexed basename.
- Do not treat ordinary sentence punctuation as a file extension.

Known useful extensions include:

```text
.py .swift .md .json .toml .yaml .yml .log .trace .txt .ts .tsx .js .jsx .go .rs .java .kt .c .cpp .h .hpp .plist
```

Regression test:

```text
Prompt "make sure the app builds." should not create prompt_mentioned_files ["builds"].
```

### 3. Fix patch-boundary contradictions

Current issue:

A file can appear in contradictory categories, for example:

```json
{
  "allowed_edit_files": ["README.md", "pyproject.toml"],
  "discouraged_files": ["README.md"],
  "allowed_if_justified": ["pyproject.toml"]
}
```

Fix in:

```text
src/premode/compiler.py
```

Add this category:

```json
{
  "read_only_context_files": []
}
```

Patch boundary should use mutually exclusive categories:

```json
{
  "read_only_context_files": [],
  "allowed_edit_files": [],
  "allowed_if_justified": [],
  "discouraged_files": [],
  "forbidden_without_user_confirmation": []
}
```

Guidance files should default to read-only context unless the primary intent is documentation-focused:

- `README.md`
- `AGENTS.md`
- `CODEX.md`
- `.premode/rules.md`
- docs/ guidance files

Ensure no file appears in more than one patch-boundary category.

Regression test:

```text
No file may appear in contradictory patch-boundary categories.
```

### 4. Fix command override honesty

Current issue:

`premode init` writes discovered commands to:

```text
.premode/commands.json
```

Then compile reports them as:

```json
{
  "user_overrides_applied": ["test"]
}
```

That is wrong because the user did not override anything.

Fix in:

```text
src/premode/command_discovery.py
src/premode/config.py
src/premode/adapters.py
```

Use this split:

```text
.premode/out/discovered_commands.json   generated, overwritten safely
.premode/commands.json                  user overrides only
```

Initial `.premode/commands.json` should be:

```json
{
  "schema_version": 2,
  "commands": {},
  "note": "User overrides only. Discovered commands are written to .premode/out/discovered_commands.json."
}
```

Compile should merge:

```text
fresh deterministic discovery + user .premode/commands.json overrides
```

Only report `user_overrides_applied` when `.premode/commands.json` contains actual non-empty user commands.

Backward compatibility:

- Detect v2.4-style generated `.premode/commands.json` using markers such as `discovery: deterministic`, `generated_by: premode`, `sources`, or `project_root`.
- Do not treat those generated commands as user overrides.
- Report `legacy_generated_commands_ignored: true` when this compatibility path is used.

Regression tests:

```text
premode init creates empty user override commands.json and discovered_commands.json.
load_commands reports user_overrides_applied = [] when only generated discovery exists.
v2.4-style generated commands.json is not treated as a user override.
```

### 5. Make hard packet budgets truly hard

Current issue:

Manifest entries can bypass the available context budget because of logic like:

```python
if full_tokens + summary_tokens + manifest_tokens + estimated <= available_context_tokens or score > 0:
```

Fix in:

```text
src/premode/compiler.py
```

Remove the `score > 0` bypass.

If a file cannot fit in the remaining budget, exclude it with a clear reason:

```json
{
  "path": "src/example.py",
  "reason": "hard packet budget reached"
}
```

Also reserve enough metadata overhead before adding context so the final packet remains under the hard profile budget.

A 5% effective-budget margin is acceptable:

```python
effective_budget = int(hard_packet_token_budget * 0.95)
```

Regression test:

```text
Create many positive-score files with a constrained hard_packet_token_budget. Assert packet_total_tokens <= hard_packet_token_budget and overflow files are excluded with hard packet budget reached.
```

## Tests required

Add or update tests for:

- log scanner source-file false positive
- prompt path extraction false positive from `builds.`
- patch-boundary category exclusivity
- command override honesty
- legacy generated commands.json compatibility
- hard packet budget overflow
- existing V2 packet sections
- existing context tiers
- existing command discovery
- existing root marker detection
- existing privacy/Codex stdin contract
- existing safety/redaction behavior

## Validation required

Run:

```bash
python -m pip install -e ".[dev]"
pytest -q
bash scripts/smoke_test.sh
```

Expected:

```text
54 passed
smoke test passed
```

Run this package self-check:

```bash
premode detect --json
premode compile "Fix the campaign upkeep patch, don't expand scope, check what Qwen did, and make sure the app builds." --profile lite --json
```

Expected:

- active Python project root is `.`
- packet marker is `PREMODE_COMPILED_PACKET_V2`
- packet remains under the lite 12k hard budget
- no fake first meaningful error from `src/premode/log_scanner.py`
- no prompt-mentioned file `builds`
- no contradictory patch-boundary entries
- no fake `user_overrides_applied` from generated command discovery

## Non-goals

Do not add:

- Ollama provider
- OpenAI-compatible local provider
- embeddings
- local reranker
- repo map
- impact map
- patch review command
- automatic test/build execution
- MCP expansion

Keep the patch focused.

## Final product framing

Update README and implementation report to say:

```text
v2.4.1 is a trust-hardening patch for the deterministic Evidence Packet compiler.
It makes Pre-mode a more reliable local AI-coding preflight and patch-governor layer before Codex receives the task.
```

Recommended roadmap after this patch:

```text
v2.5 = repo map + impact map
v2.6 = patch review governor
v3.0 = optional local assist through schema-validated JSON
```
