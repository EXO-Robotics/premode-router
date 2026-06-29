# Swift/iOS Real-Repo Hardening — v2.4.2

## Why this patch exists

Testing against a large Swift/Xcode app exposed issues that do not show up in small Python fixtures:

- `.xcodeproj` is a directory marker and may not appear in the readable index.
- The readable source root can dominate compile-time detection and hide the true Xcode project root.
- Long Swift paths can look high-entropy and be redacted before path extraction.
- App concepts such as `Day Report` can be misclassified as documentation if `report` is treated too generically.
- Generated `.premode/` files can pollute dirty-branch review packets.

v2.4.2 fixes those issues in a universal way.

## Fixes

### 1. Filesystem-level marker merge

Compile-time project detection now merges readable indexed files with filesystem project markers:

```text
*.xcodeproj
*.xcworkspace
Package.swift
ProjectSettings/
Assets/
pyproject.toml
package.json
Cargo.toml
go.mod
```

This keeps Xcode root detection stable even when the index only contains Swift source files.

### 2. Path-safe redaction

Path-like strings ending in known source/log extensions are preserved before high-entropy redaction.

Example preserved path:

```text
GoldpineValley/Views/PlayerActivities/StarterMinigames/RepairAssistGameEngine.swift
```

### 3. Day Report intent routing

Generic `report` no longer means documentation. App/game concepts such as:

```text
Day Report
DayReport.swift
receipt
receipts
result screen
end-day report
```

should route toward feature/UI/controlled patch work, not docs-only work.

### 4. Dirty-state cleanup

Generated Pre-mode files are filtered from dirty-branch evidence:

```text
.premode/
.premodeignore
```

This prevents Qwen/Opus verification packets from being polluted by Pre-mode’s own generated files.

## Recommended local Git ignore

For local-only use:

```bash
echo ".premode/" >> .git/info/exclude
echo ".premodeignore" >> .git/info/exclude
```

For team-wide use, prefer a narrow repo-level ignore:

```gitignore
.premode/out/
.premode/audit/
.premode/metrics/
```

Do not commit generated packets, audit files, or metric logs unless your team intentionally wants them.
