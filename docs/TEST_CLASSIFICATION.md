# Test Classification

## Unit and contract tests

The default CI test phase runs the repository's deterministic pytest suite. It
may read and write temporary local files, but it must not call live models,
external repositories, package registries, or other network services. Tests
marked `external_fixtures` are outside the default release gate.

`tests/test_release_install_contract.py` is the release contract gate. It
checks version synchronization, core dependency metadata, built-in default
locator imports, console scripts, and the exact classes of files permitted in a
wheel.

## Artifact tests

Artifact validation builds one wheel from the checked-out source, inspects its
contents against an allowlist, installs it into a clean virtual environment
with `--no-index --no-deps`, and performs import and console-script smokes.

## Excluded tests

Live model, Codex execution, Ollama, network, registry publication, and private
external-repository tests are not release CI. They require a separately
authorized environment and cannot be used as evidence for this offline gate.
