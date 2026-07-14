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
tester only the controlled wheel, its SHA-256 checksum, and the canonical
documents listed in `premode.product.json`. Do not coach the tester unless the
tester explicitly requests help; record every intervention verbatim.

## Frozen fixture assignment

The campaign coordinator materializes the immutable fixture archives and blind
payload from the qualified wheel:

```console
python scripts/build_first_run_study_kit.py --output /private/coordinator-kit --wheel /path/to/premode_router-0.3.0b1-py3-none-any.whl --qualification /path/to/qualification-summary.json --commit CANDIDATE_COMMIT_SHA
```

The generated `blind-tester-payload` contains only one wheel, its checksum, and
the canonical documents. Fixture archives, receipt templates, the receipt
schema, and protocol remain in the separate coordinator directory.

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

The tester verifies the supplied artifact hash and follows
`docs/GETTING_STARTED.md` without additional instructions. The first-use timer
starts immediately before the install command and stops when this command
returns a structurally valid dry-run result:

```console
pcodex run --dry-run "Fix the failing test"
```

The tester then performs the canonical setup, plugin lifecycle, repair preview,
uninstall, and reinstall journeys appropriate to the assigned fixture. A tester
without Codex validates the documented missing-Codex behavior rather than live
discovery.

## Required receipt fields

Store one private receipt per tester with:

- anonymous tester ID, a privately stored signed no-prior-knowledge
  attestation, and its content-free SHA-256 evidence hash;
- artifact filename, SHA-256, product version, and candidate commit;
- platform, architecture, Python version, Codex version or `absent`;
- fixture ID and fixture content hash;
- monotonic start, first-use, and completion durations, with completion not
  earlier than first useful dry run;
- exact command transcript with stdout/stderr sensitivity-reviewed; lifecycle
  success booleans are accepted only when the transcript contains the matching
  canonical dry-run, repeated install, uninstall, reinstall, and assigned
  migration or optional-MCP commands;
- first useful dry-run acceptance result;
- undocumented help requests and every intervention;
- failures, repair steps, and final disposition;
- plugin install-twice, uninstall, reinstall, and unrelated-state preservation;
- tester confirmation that the canonical documentation was sufficient or an
  exact statement of what was missing.

Raw prompts, repository contents, secrets, usernames, home paths, and Codex
credentials must stay out of the public summary.

## Decision and reporting

Preserve invalid and failed attempts. Compute activation success, median time to
first useful dry run, range, undocumented-repair count, uninstall success, and
reinstall success. The public-safe summary may contain only aggregate metrics,
fixture classes, content-free failure categories, artifact hashes, and the
frozen protocol version.

The gate remains external evidence debt until five valid receipts exist. Do not
infer human success from automated installed-artifact tests.

After all five private receipts are complete, validate them and emit the
content-free decision with:

```console
python scripts/validate_first_run_study.py /private/receipts/*.json --study-kit /private/coordinator-kit/coordinator/study-kit.json --json
```
