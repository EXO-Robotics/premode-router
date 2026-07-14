# First-Run Study Protocol

This protocol is the required external evidence for the pCodex first-run gate.
It is not a substitute for completed tester receipts and must not be reported as
human evidence until five eligible people have run it.

## Acceptance policy

- Product target: first useful dry run in under five minutes.
- G1 minimum: median under ten minutes with no undocumented repair.
- Literal 90/100 aspiration: median under five minutes.
- Invited-beta activation success: at least 95%. With five testers, that means
  all five must activate successfully; every failed attempt is retained and
  explained.

## Tester eligibility

Recruit five testers with no prior internal knowledge of pCodex. Give each
tester only the controlled wheel, its SHA-256 checksum, the canonical
documents listed in `premode.product.json`, and exactly one frozen fixture task
card. The card is protocol material, not undocumented coaching. Do not coach the tester unless the
tester explicitly requests help; record every intervention verbatim.

## Frozen fixture assignment

The campaign coordinator materializes the immutable fixture archives and blind
payload from the qualified wheel:

```console
python scripts/build_first_run_study_kit.py --output /private/coordinator-kit --wheel /path/to/qualified-release/artifacts/premode_router-0.3.0b1-py3-none-any.whl --qualification-root /path/to/qualified-release --python /absolute/path/to/python --git /absolute/path/to/git --commit CANDIDATE_COMMIT_SHA
```

The generated `blind-tester-payload` contains only one wheel, its checksum, and
the canonical documents. Fixture archives, frozen task cards, the receipt
schema, and protocol remain in the separate coordinator directory. The
coordinator gives each tester exactly one assigned task card.
The coordinator kit deliberately binds the absolute, regular-file Python and
Git executables (including their hashes) from the controlled study host. Run
all five journeys on that host or rebuild and requalify a new kit; the kit is
not a portable promise for arbitrary tester machines.
The source-checkout-only `scripts/restore_first_run_fixture.py` is copied into
that coordinator directory and is not installed as a public product command.
The source-checkout-only `scripts/first_run_study_authority.py` freezes fixture,
runbook, and task-card content and is not installed as a public product command.
The source-checkout-only `scripts/record_first_run_study.py` is copied into the
private coordinator kit. Its `init`, `run-next`, `review`, and `finalize`
subcommands capture exact commands, controlled environments, checkpoint
measurements, explicit sensitivity review, signed claims, and the final private
receipt without accepting caller-supplied stdout or success results.
Preassign exactly one session file per fixture, named
`<fixture-id>.session.json`, in a dedicated private `0700` directory. Keep the
HMAC-chained `attempt-ledger.jsonl` in a different coordinator-owned private
directory and run the five journeys sequentially. A failed or interrupted
session remains the authority for that fixture; do not delete it, its ledger,
or create a replacement attempt. The aggregate validator requires all five
signed sessions, the chained initialization and transition ledger, and all five
receipts. The coordinator/HMAC-key holder remains the trust anchor and could
rewrite same-authority evidence; archive the ledger and obtain an external
digest witness before citing the human study in a release claim.

Across the five testers, cover all of these conditions. A fixture may cover
multiple conditions:

1. clean repository, no Codex, no MCP;
2. dirty repository with an existing unrelated `.agents` tree;
3. unrelated Codex configuration and supported Codex `0.143.x`;
4. path containing spaces and Unicode, with a supported legacy plugin fixture;
5. optional MCP fixture, repeated install, uninstall, and clean reinstall.

Every fixture must have a content hash and a restoration script or immutable
snapshot. Private repository content must not enter the public receipt.

## Tester journey

The tester verifies the supplied artifact hash and follows the canonical
documentation plus the assigned frozen task card, without additional
instructions. The first-use timer
starts immediately before the install command and stops when this command
returns a structurally valid dry-run result:

```console
pcodex run --dry-run "Fix the failing test" --json
```

The assigned task card renders the exact ordered operation list stored for the assigned
fixture in `study-kit.json`. This includes advisory checks, a managed install
preview and apply, plugin lifecycle, repair preview, final integration cleanup,
and managed uninstall journeys that apply to that fixture. The optional-MCP
idempotency command retains `--with-mcp`; omitting it is an intentional mode
conflict, not a successful rerun. A tester without Codex validates the documented
missing-Codex `NEEDS_ACTION` result and exit code `1` rather than claiming a live
plugin lifecycle.

## Required receipt fields

Store one private receipt per tester with:

- anonymous tester ID, a privately stored signed no-prior-knowledge
  attestation, and its content-free SHA-256 evidence hash;
- artifact filename, SHA-256, product version, and candidate commit;
- platform, architecture, Python version, Codex version or `absent`;
- fixture ID and fixture content hash;
- hashes binding the receipt to the exact study kit, release qualification,
  receipt and kit schemas, protocol, validator, fixture restorer, and canonical
  document manifest;
- monotonic command start and completion offsets. Artifact verification and
  virtual-environment creation are pre-timer; package installation starts at
  offset zero; first-use time equals the successful dry-run completion offset;
  final completion equals the last required command completion offset;
- ordered command evidence containing the exact argument vector, resolved
  executable, working directory, complete controlled-environment binding, virtual-environment
  root, exit code,
  stdout and stderr hashes, a content-addressed private evidence-file hash,
  sensitivity review, and a normalized result. Preview and advisory operations
  must report zero writes. Mutating and idempotent operations must report their
  exact expected outcome. No self-asserted lifecycle boolean is accepted;
- first useful dry-run acceptance result;
- undocumented help requests and every intervention;
- failures, repair steps, and final disposition;
- fixture-condition evidence and hashes for every named unrelated-state surface
  at every required checkpoint. The before hash must match the immutable kit and
  all later preservation checkpoints must remain byte-equivalent;
- tester confirmation that the canonical documentation was sufficient or an
  exact statement of what was missing.

Raw prompts, repository contents, secrets, usernames, home paths, and Codex
credentials must stay out of the public summary.

The recorder's before/after repository-and-sandbox digest detects persistent
first-run drift only. It does not prove absence of transient create/delete
activity or forbidden process launches. Literal no-write qualification remains
the separate installed-artifact monitor and process/filesystem evidence gate;
do not use the human-study digest as G2 or G5 no-write proof.

## Decision and reporting

Preserve invalid and failed attempts. Compute activation success, median time to
first useful dry run, range, undocumented-repair count, uninstall success, and
reinstall success. The public-safe summary may contain only aggregate metrics,
fixture classes, content-free failure categories, artifact hashes, and the
frozen protocol version.

The gate remains external evidence debt until five valid receipts exist. Do not
infer human success from automated installed-artifact tests.

Private coordinator-witnessed attestations are strict JSON stored as
`<sha256>.attestation`. The coordinator signs the canonical JSON attestation
with HMAC-SHA256 and a private key supplied only to the validator. The signature
binds the tester and fixture to ordered manifests of every command, condition,
and preservation evidence digest. It proves coordinator witnessing and evidence
integrity; it is not a claim of independent cryptographic tester identity.

Private command, condition, and preservation evidence are strict JSON stored as
`<sha256>.evidence`. Raw stdout, stderr, observations, and preservation
measurements are bounded base64 fields. The validator decodes them, recomputes
all hashes and normalized command results, verifies unique evidence per event,
and fails closed on a mismatch. Preservation evidence is bound to the immutable
fixture bytes at every required checkpoint. Keep these private files outside the
study-kit root.

The validator requires the complete release qualification root, including its
wheel, sdist, manifest, SBOM, provenance, and qualification metadata. A detached
or copied passing receipt cannot qualify arbitrary artifact bytes. It also
requires the exact clean candidate checkout and rejects custom receipt schemas.
No first-run receipt was accepted before this evidence-strengthening revision;
older string-transcript or self-asserted lifecycle drafts are invalid.

After all five private receipts are complete, validate them and emit the
content-free decision with:

```console
python scripts/validate_first_run_study.py /private/receipts/*.json --study-kit /private/coordinator-kit/coordinator/study-kit.json --qualification-root /path/to/qualified-release --wheel /path/to/qualified-release/artifacts/premode_router-0.3.0b1-py3-none-any.whl --attestation-dir /private/attestations --evidence-dir /private/evidence --attestation-key /private/coordinator-hmac.key --session-dir /private/sessions --attempt-ledger /private/authority/attempt-ledger.jsonl --json
```
