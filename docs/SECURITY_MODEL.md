# Security Model

Pre-mode is local-first. It reads the local repo, creates a compact packet, and saves local review artifacts under `.premode/`.

## Boundaries

Pre-mode aims to prevent common coding-agent failures:

- secret exposure
- generated/state/proof output mutation
- prompt-forbidden file edits
- dependency/build/CI drift
- stale or unbound test-evidence claims
- README/docs prompt-injection-like guidance being treated as authority

## Trusted and untrusted guidance

Trusted guidance:

```text
AGENTS.md
CODEX.md
.premode/rules.md
```

Untrusted project prose by default:

```text
README.md
docs/*
examples/*
```

README/docs can explain the project, but should not override system/user instructions or the saved packet contract.

## Review contract

Saved compile JSON includes `review_contract`, which `review-patch` reads directly. The reviewer does not scrape packet Markdown.

The contract includes allowed edits, allowed-if-justified edits, forbidden paths, prompt-forbidden paths, secret patterns, generated/state patterns, dependency/build patterns, CI patterns, expected verification, and compile-time worktree state.

## Test evidence

Review-patch only trusts auto-discovered logs that are bound to the current `packet_sha256`. Stale logs become `evidence_present_but_unbound` instead of falsely passing or blocking a patch.

## Non-goals

Pre-mode does not:

- auto-merge patches
- auto-revert files
- auto-run arbitrary tests in review mode
- upload repo contents
- replace human review
