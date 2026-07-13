# Qwen Scouting Corpus

This branch contains content-free tooling for a private, local repository corpus.
The cloned repositories, task prompts, mutations, validator answers, run receipts,
and raw model outputs live outside this repository under the private corpus root.

The corpus workflow is intentionally separate from B0. It profiles pinned public
clones, creates controlled regression fixtures, checks each validator against the
known-good, mutated, and incomplete-repair states, and prepares disposable Git
worktrees for later STANDARD-versus-B0 execution. It does not alter ranking,
packet selection, thresholds, fallback, or abstention behavior.

Run metadata-only inventory with bounded traversal:

```bash
python3 scripts/scouting_corpus.py inventory \
  --roots /path/one /path/two \
  --max-depth 5 \
  --output /private/corpus/manifests/PRIVATE_LOCAL_REPOSITORY_INVENTORY.json
```

Build profiles and task fixtures from a private selection file:

```bash
python3 scripts/scouting_corpus.py build \
  --corpus-root /private/corpus \
  --selection /private/corpus/manifests/PRIVATE_SELECTION_INPUT.json
```

Only sanitized summaries may be copied back into `qualification/`. Never commit
local paths, remotes for private repositories, prompts, mutation patches,
validator specifications, transcripts, model outputs, or active run worktrees.
