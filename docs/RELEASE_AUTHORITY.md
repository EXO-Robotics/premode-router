# Release and Version Authority

- Product branch authority: the reviewed head of remote `Private-Beta`.
- Core version authority: root `pyproject.toml` `[project].version`.
- Runtime mirror: `src/premode/__init__.py::__version__`; CI requires exact equality.
- Literal-symbol plugin version: its own package `pyproject.toml`. It is independently versioned and must not be inferred from the core version.
- MCP surfaces ship inside the core package but currently report component/protocol strings (`0.1.0` and `0.1.0-alpha`); these are not core product versions or independent release authority.
- Repo-local Codex plugin metadata may carry its own schema/cache-busting version and does not redefine the Python package version.

A release candidate starts as a feature branch from current `origin/Private-Beta`, passes the release-foundation workflow's network-free checks after dependency/bootstrap setup, receives review, and is merged without rewriting `Private-Beta` history. The workflow is one gate; branch ancestry, clean inputs, review, and merge policy are separately verified release responsibilities. Tags, publishing, package uploads, and promotion to production require separate explicit authority. Dirty worktrees and generated state are never release inputs.

Historical branch names, alpha labels, and versioned design documents describe their own snapshots only. Current operating documents should link to `docs/PRODUCT_CONTRACT.md`; they must not use `Observer-Development`, UX/lab branches, or an old commit as release authority.
