---
name: compile-repair
description: Use for fixing build, compile, test, Xcode, pytest, or CI failures with minimal scoped edits.
---

# Compile Repair

1. Read the Pre-mode task classification, repo state, selected files, and relevant log errors.
2. Reproduce or reason from the first meaningful error before editing.
3. Change the smallest set of files needed to restore the build/test gate.
4. Run the relevant verification command and report exact pass/fail results.
5. Do not add unrelated features or refactors while the build is red.
