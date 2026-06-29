# Pre-mode Router v2.5.5 — Native Repo Shapes + Negative Intent Hardening

Goal: harden v2.5.4 against universal stress-test gaps without adding patch review, local assist, embeddings, Tree-sitter, ctags, or cloud features.

Required changes:

1. Parse negative prompt intent: phrases like `do not touch X`, `do not edit X`, `without touching X`, `avoid X`, and `must not mutate X` must make matched repo paths read-only/forbidden rather than edit targets.
2. Suppress secret-like paths from all context tiers and impact maps. Report only counts/examples in `redaction_summary`.
3. Add native C/C++/SCons/CMake engine detection. `SConstruct`, `SCsub`, `CMakeLists.txt`, and engine dirs such as `core/`, `scene/`, `modules/`, `platform/`, `servers/`, and `drivers/` should beat nested helper Python scripts.
4. Improve Go CLI impact routing by matching prompt flag/command terms to command folders, `cmd/root.go`, Go flag declarations, and adjacent `_test.go` files.
5. Add domain keyword hints for repo-map/context-receipt/packet-output tasks without making these hints model-dependent.
6. Keep OpenClaw as one high-risk fixture, not the benchmark center.

Validation:

```bash
python -m pip install --no-build-isolation --no-deps -e .
python -m pytest -q
bash scripts/smoke_test.sh
premode detect --json
premode map --summary-json
premode compile "Find the right files for a safe Python CLI patch that changes command-line argument handling without touching packaging or release scripts." --profile lite --use-repo-map --json
```
