# Testing Gates

Pre-mode release validation is split into deterministic default tests, optional external fixture tests, and private exploratory checks.

## Default Release Gate

The default gate must pass in a clean checkout without network access, private repositories, mutable external clones, or fixed `/private/tmp` external repo paths. Tests in this tier use deterministic synthetic fixtures committed under `tests/` or built in temporary pytest directories.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -m "not external_fixtures"
```

## Optional External Fixture Gate

External fixture tests may use local public repository clones when explicitly provided. They are skipped by default and require both the `external_fixtures` pytest marker and an opt-in environment variable.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -m external_fixtures
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PREMODE_ENABLE_EXTERNAL_FIXTURES=1 .venv/bin/python -m pytest -q -m external_fixtures
```

If the expected local fixture is missing or incomplete, the optional gate should skip with a clear reason. Drift failures in this tier are advisory unless a release task explicitly promotes them to blocking.

## Private Exploratory Gate

Private exploratory checks are local-only experiments. They may depend on lab artifacts under `/private/tmp`, but they are never part of default release validation and are not suitable for CI or release readiness claims.
