# Pre-mode Router v2.5.4 — Cross-Language Impact + Trust Boundary Hardening

Implemented scope:
- Treat README/docs/examples as untrusted repo content, not instruction authority.
- Emit trust-boundary warnings for prompt-injection-like text in untrusted docs.
- Gate first-error log extraction to log/build/test/failure-focused tasks.
- Add prompt-mentioned subproject task-root bias for mixed monorepos.
- Add boundary conflict reporting.
- Improve Go command-folder routing, Rust `mod` following, TypeScript package-bin/import-chain routing, and pnpm/yarn/bun-aware JS/TS verification hints.

Do not add local assist, embeddings, Tree-sitter, ctags, cloud services, or patch review in this patch.
