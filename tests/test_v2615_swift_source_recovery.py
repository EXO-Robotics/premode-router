from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


PROMPT = (
    "Find likely files for a small SwiftUI tutorial guidance issue. Focus only on "
    "tutorial overlay/state code and current UI shell Swift files. Do not edit files. "
    "Avoid Docs, Planning_Bundles, ArtSource, Assets.xcassets, generated files, "
    "DerivedData, .premode, .agents, signing settings, dependency files, and CI."
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_goldpine_like_repo(repo: Path) -> None:
    (repo / "GoldpineValley.xcodeproj").mkdir()
    _write(repo / "GoldpineValley" / "Views" / "MainMenuView.swift", "struct MainMenuView { var tutorialOverlayVisible = false }\n")
    _write(repo / "GoldpineValley" / "Views" / "BottomBarView.swift", "struct BottomBarView { var body: String { \"bar\" } }\n")
    _write(repo / "GoldpineValley" / "Views" / "SharedViewStyles.swift", "struct SharedViewStyles {}\n")
    _write(repo / "GoldpineValley" / "ViewModels" / "GameSessionViewModel+HomesteadNavigation.swift", "final class GameSessionViewModel { var tutorialState = 0 }\n")
    _write(repo / "GoldpineValley" / "Models" / "TutorialState.swift", "struct TutorialState { var step: Int }\n")
    _write(repo / "GoldpineValley" / "Assets.xcassets" / "AppIcon.appiconset" / "Contents.json", "{}\n")
    noisy = "# Planning note\n" + ("Historical planning/art guidance only.\n" * 260)
    _write(repo / "Docs" / "Planning_Bundles" / "Week_04" / "AGENTS.md", noisy)
    _write(repo / "Docs" / "Planning_Bundles" / "Week_04" / "PATCH_NOTES.md", noisy)
    _write(repo / "Docs" / "Planning_Bundles" / "Week_04" / "System_Bibles" / "06_UI_State_Contract_v1.md", noisy)
    _write(repo / "ArtSource" / "NPC_Models" / "README.md", noisy)
    _write(repo / "Docs" / "app_reality_alignment.md", noisy)


def test_v2615_dirty_planning_art_does_not_dominate_swiftui_source_prompt(tmp_path: Path) -> None:
    repo = tmp_path
    _make_goldpine_like_repo(repo)
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")

    noisy_update = "\nDirty planning update that should not dominate source context.\n"
    for rel in (
        "Docs/Planning_Bundles/Week_04/AGENTS.md",
        "Docs/Planning_Bundles/Week_04/PATCH_NOTES.md",
        "Docs/Planning_Bundles/Week_04/System_Bibles/06_UI_State_Contract_v1.md",
        "ArtSource/NPC_Models/README.md",
        "Docs/app_reality_alignment.md",
    ):
        path = repo / rel
        path.write_text(path.read_text(encoding="utf-8") + noisy_update, encoding="utf-8")

    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, PROMPT, "lite", use_repo_map=True, cache_optimized=True)

    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]
    impact = result["impact_map"]
    likely_edit = {item["path"] for item in impact["likely_edit_files"]}
    assert likely_edit & {
        "GoldpineValley/Views/MainMenuView.swift",
        "GoldpineValley/Views/BottomBarView.swift",
        "GoldpineValley/Views/SharedViewStyles.swift",
        "GoldpineValley/ViewModels/GameSessionViewModel+HomesteadNavigation.swift",
        "GoldpineValley/Models/TutorialState.swift",
    }
    forbidden_fragments = (
        "Docs/Planning_Bundles",
        "ArtSource",
        "Assets.xcassets",
        "DerivedData",
        ".premode",
        ".agents",
    )
    assert not any(any(fragment in path for fragment in forbidden_fragments) for path in likely_edit)

    full_paths = [item["path"] for item in result["context_tiers"]["full_text_files"]]
    assert any(path.startswith("GoldpineValley/") and path.endswith(".swift") for path in full_paths)
    assert not any(path.startswith("Docs/Planning_Bundles/") for path in full_paths)
    assert not any(path.startswith("ArtSource/") for path in full_paths)

    summarized_or_manifest = result["context_tiers"]["summarized_files"] + result["context_tiers"]["manifest_only_files"]
    compacted = [
        item["path"]
        for item in summarized_or_manifest
        if "planning_art_dirty_compacted" in item.get("evidence_flags", [])
    ]
    assert compacted
    diagnostics = impact["routing_filter_diagnostics"]
    assert diagnostics["source_recovery_attempted"] is True
    assert diagnostics["safe_candidate_count"] >= 4
