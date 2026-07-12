# ExampleGame Valley Pre-mode Setup Template

This is an example project-local setup for using Pre-mode as a Qwen/Codex/Opus context governor on ExampleGame Valley.

This file is a template. Do not hardcode these rules into Pre-mode itself.

## `.premode/commands.json`

Adjust simulator destination if your local simulator name differs.

```json
{
  "schema_version": 2,
  "commands": {
    "build_debug_sim": {
      "command": "xcodebuild -project ExampleGame.xcodeproj -scheme ExampleGame -destination 'platform=iOS Simulator,name=iPhone 17' build CODE_SIGNING_ALLOWED=NO",
      "description": "ExampleGame debug simulator build",
      "safe_to_suggest": true,
      "auto_run": false
    },
    "build_release_sim": {
      "command": "xcodebuild -project ExampleGame.xcodeproj -scheme ExampleGame -destination 'platform=iOS Simulator,name=iPhone 17' -configuration Release build CODE_SIGNING_ALLOWED=NO",
      "description": "ExampleGame release simulator build without code signing",
      "safe_to_suggest": true,
      "auto_run": false
    }
  }
}
```

## `.premode/rules.md`

```markdown
# ExampleGame Valley Rules

- ExampleGame Valley is a cozy frontier survival narrative game.
- Do not expand MVP scope unless explicitly asked.
- Do not add new systems unless they replace or clarify an existing one.
- Do not touch Assets.xcassets unless the active task is asset import.
- Do not touch minigames unless the task names a minigame.
- Preserve Day 1–7 canon order unless explicitly authorized.
- Hidden values must not leak into the HUD.
- SwiftUI views should not directly mutate core campaign state when a ViewModel method exists.
- End Day blockers must remain deterministic.
- Save/load changes require snapshot compatibility.
- If build fails, fix the first meaningful compiler error before chasing cascades.
- If the failure appears outside the requested patch, stop and report.
```

## `.premode/memory/project_memory.md`

```markdown
# Project Memory

## Current Active Work

Frontier Risk system patches:
- Patch 1 committed: foundation compile integration.
- Patch 2/3 were attempted by Qwen but paused.
- Opus should verify/rework before committing.

Risk direction:
- campaign-wide upkeep
- character scars
- delayed costs
- risky job resolver
- Day Report risk receipts

## Last Good State

5a71ebd GPV_FRONTIER_RISK_01_Foundation_Compile_Integration

## Known Fragile Areas

- GameSessionViewModel.swift is oversized.
- EventCatalog.swift is oversized.
- ExtendedMinigameTaskViews.swift is oversized.
- Day advancement and End Day blockers are fragile.
- Save/load compatibility must be preserved.

## Do Not Touch Unless Asked

- Assets.xcassets
- project.pbxproj unless adding/removing files
- minigame engines unless named
- future regions
- monetization
- procedural systems
```

## Recommended workflow

Before Qwen/Codex work:

```bash
premode compile "Implement Frontier Risk Patch 2 campaign upkeep in GameState.swift DayReport.swift GameSessionSnapshot.swift. Do not touch minigames or assets. Keep patch minimal." \
  --profile standard \
  --out .premode/out/qwen_patch_packet.md \
  --json-out .premode/out/qwen_patch_packet.json
```

After Qwen edits, save the build log:

```bash
xcodebuild -project ExampleGame.xcodeproj \
  -scheme ExampleGame \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  build CODE_SIGNING_ALLOWED=NO 2>&1 | tee xcodebuild.log
```

Then produce an Opus verification packet:

```bash
premode compile "Review Qwen's dirty changes against the requested Frontier Risk patch. Use xcodebuild.log. Fix only the first meaningful build error if it is inside scope. Do not expand systems, minigames, assets, or story." \
  --profile standard \
  --out .premode/out/opus_verify_packet.md \
  --json-out .premode/out/opus_verify_packet.json
```
