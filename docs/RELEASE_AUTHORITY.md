# Release and Version Authority

- Product branch authority: the reviewed head of the explicitly selected product release branch; promotion to `Private-Beta` is a separate authorized operation.
- Product version authority: `src/premode/__init__.py::__version__`.
- Packaging derives its dynamic version from that module through root `pyproject.toml`; no second static package-version field exists.
- MCP surfaces ship inside the core package but currently report component/protocol strings (`0.1.0` and `0.1.0-alpha`); these are not core product versions or independent release authority.
- The canonical Codex plugin manifest SemVer is deterministically derived from the product version. Plugin and receipt schema versions are compatibility identifiers and do not redefine the package version.

A release candidate starts from the explicitly authorized product branch and
passes the complete release-foundation workflow from a clean exact commit.
Promotion to `Private-Beta` is a later, separately authorized operation; the
release workflow does not merge or rewrite that branch. The workflow is one
gate; branch ancestry, clean inputs, review, and merge policy are separately
verified release responsibilities. Tags, publishing, package uploads, and
promotion to production require separate explicit authority. Dirty worktrees
and generated state are never release inputs.

The non-published candidate uses in-toto/SLSA-shaped provenance whose wheel,
sdist, and algorithm-authority subjects are checked against the actual bytes.
The outer release-candidate receipt and exact SHA-256 manifests separately bind
the SBOM, provenance, six qualification receipts, supported-version matrix,
and every public bundle file. This is locally verifiable commit-and-digest
provenance; it is not a cryptographic signature. A signed or keyless public
attestation needs separate signing/publication authority and must not be
inferred from this private candidate evidence.

The non-published candidate is an install-and-verification evidence bundle, not
a source checkout. Schema and golden authorities referenced by the bundled
product manifest are included. Commands under `scripts/` in bundled documents
are explicitly source-checkout-only coordinator tooling and are not claimed to
run from the candidate archive. The live campaign gate ledger remains external
evidence so updating a post-qualification decision cannot mutate the candidate
it describes.

Historical branch names, alpha labels, and versioned design documents describe their own snapshots only. Current operating documents should link to `docs/PRODUCT_CONTRACT.md`; they must not use `Observer-Development`, UX/lab branches, or an old commit as release authority.
