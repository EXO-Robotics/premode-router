# CI Contract

The offline release workflow has four bounded gates:

1. Base routing contracts: closure, intent, provenance, confidence, modes, support, packet, and abstention.
2. Safety: runtime/secret denial, containment, symlinks, and ignored/explicit behavior.
3. Package/install: exact wheel equality plus setup, status, dry-run, cleanup, uninstall, and reinstall.
4. Bounded integration: deterministic fixtures with no live model or external repository.

Jobs have explicit 8-10 minute timeouts. Source-only benchmark and live-token
modules are absent from the wheel and their commands are not registered there.

The workflow may use the network during CI bootstrap to obtain the selected
Python runtime and pinned build/test tools. After bootstrap, `PIP_NO_INDEX=1`
is set for test, build, and smoke commands. The product test runtime must not
contact live models or external services.

CI does not publish packages, run live Codex/model evaluations, mutate user
configuration, or treat optional plugin installation as part of the core wheel
contract.
