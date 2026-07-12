# Install Contract

Pre-mode Router `0.3.0b1` supports Python 3.11 and newer. The release artifact is
a pure-Python wheel containing the `premode` package and the `premode` and
`pcodex` console scripts.

The supported default ranker is the built-in locator in `premode.locator`. It
ships in the core wheel and has no optional runtime dependency. The separate
`premode-plugin-literal-symbol` distribution is an optional alias and metadata
integration; it is not required to import or use the default locator.

For a local release-candidate smoke test, install the already-built wheel into a
fresh virtual environment without dependency resolution:

```bash
python3.11 -m venv /tmp/premode-release-smoke
/tmp/premode-release-smoke/bin/python -m pip install --no-index --no-deps \
  dist/premode_router-0.3.0b1-py3-none-any.whl
/tmp/premode-release-smoke/bin/premode --version
/tmp/premode-release-smoke/bin/pcodex setup --skip-tune --no-mcp --json --repo-root /tmp/premode-fixture
/tmp/premode-release-smoke/bin/pcodex status --json
/tmp/premode-release-smoke/bin/pcodex run --dry-run --json "Change calculate_total."
/tmp/premode-release-smoke/bin/python -c \
  "from premode.locator import locate_files; assert callable(locate_files)"
```

The installed lifecycle additionally proves `.premode/index/` cleanup and an
offline uninstall/reinstall of the identical wheel. Benchmark, lab, and
live-token commands are source-checkout development surfaces, not wheel APIs.

This contract describes local artifact validation only. It does not claim that
the package has been published to a registry.
