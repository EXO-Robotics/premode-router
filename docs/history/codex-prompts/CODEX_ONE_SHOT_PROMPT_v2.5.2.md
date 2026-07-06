# Pre-mode Router v2.5.2 — Impact Accuracy + Governance Compression

This patch has been folded into the bundle.

Validation:

```bash
python -m pip install --no-build-isolation --no-deps -e .
python -m pytest -q
bash scripts/smoke_test.sh
```

Implemented focus:

- prompt-mentioned source files in `impact_map.likely_files`
- recursive Python AST import walking
- Python console-script re-export resolution
- narrowed related-test selection
- read-only treatment for mentioned generated/state/authority files
- compact packet-only OpenClaw/control-plane governance output
