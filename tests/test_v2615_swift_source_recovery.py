from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


PROMPT = (
    "Find likely files for a small SwiftUI tutorial guidance issue. Focus only on "
    "tutorial overlay/state code and current UI shell Swift files. Do not edit files. "
    "Avoid Docs, Planning_Bundles, ArtSource, animal folders, Assets.xcassets, generated files, "
    "build outputs, DerivedData, .premode, .agents, signing settings, dependency files, and CI."
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_examplegame_like_repo(repo: Path) -> None:
    (repo / "ExampleGame.xcodeproj").mkdir()
    _write(repo / "ExampleGame" / "Views" / "MainMenuView.swift", "struct MainMenuView { var tutorialOverlayVisible = false }\n")
    _write(repo / "ExampleGame" / "Views" / "BottomBarView.swift", "struct BottomBarView { var body: String { \"bar\" } }\n")
    _write(repo / "ExampleGame" / "Views" / "HomesteadView.swift", "struct HomesteadView { var mapGuidance = \"Tap a place\" }\n")
    _write(repo / "ExampleGame" / "Views" / "HomesteadLocationSceneView.swift", "struct HomesteadLocationSceneView { var backToMapHint = \"Map\" }\n")
    _write(repo / "ExampleGame" / "Views" / "PannableHomesteadMapView.swift", "struct PannableHomesteadMapView { var zoom = 1 }\n")
    _write(repo / "ExampleGame" / "Views" / "SharedViewStyles.swift", "struct SharedViewStyles {}\n")
    _write(repo / "ExampleGame" / "Views" / "FounderSelectView.swift", "struct FounderSelectView { var body: String { \"founder\" } }\n")
    _write(repo / "ExampleGame" / "Views" / "EventCardView.swift", "struct EventCardView { var body: String { \"event\" } }\n")
    _write(repo / "ExampleGame" / "ViewModels" / "NewGameViewModel.swift", "final class NewGameViewModel { var selectedFounder = \"\" }\n")
    _write(repo / "ExampleGame" / "ViewModels" / "GameSessionViewModel+HomesteadNavigation.swift", "final class GameSessionViewModel { var tutorialState = 0 }\n")
    _write(repo / "ExampleGame" / "Models" / "TutorialState.swift", "struct TutorialState { var step: Int }\n")
    _write(repo / "ExampleGame" / "Models" / "FrontierRisk" / "FrontierRiskModels.swift", "struct FrontierRiskModels { var risk = 0 }\n")
    _write(repo / "ExampleGame" / "Systems" / "RiskResolver.swift", "struct RiskResolver { func resolve() {} }\n")
    _write(repo / "ExampleGame" / "DevTools" / "DevCheckpointID.swift", "enum DevCheckpointID { case start }\n")
    _write(repo / "ExampleGame" / "Assets.xcassets" / "AppIcon.appiconset" / "Contents.json", "{}\n")
    animal_manifest = "[\n" + ",\n".join(
        f'  {{"animal": "fox", "sprite": "pose_{i}", "source": "ArtSource/NPC_Models/fox_{i}.png", "crop": [{i}, {i + 1}, 64, 64]}}'
        for i in range(160)
    ) + "\n]\n"
    _write(repo / "animal_sprite_pose_screenshot_manifest.json", animal_manifest)
    _write(repo / "animal_sprite_crop_manifest.json", animal_manifest)
    noisy = "# Planning note\n" + ("Historical planning/art guidance only.\n" * 260)
    _write(repo / "Docs" / "Planning_Bundles" / "Week_04" / "AGENTS.md", noisy)
    _write(repo / "Docs" / "Planning_Bundles" / "Week_04" / "PATCH_NOTES.md", noisy)
    _write(repo / "Docs" / "Planning_Bundles" / "Week_04" / "System_Bibles" / "06_UI_State_Contract_v1.md", noisy)
    _write(repo / "ArtSource" / "NPC_Models" / "README.md", noisy)
    _write(repo / "Docs" / "app_reality_alignment.md", noisy)
    _write(repo / "Docs" / "ExampleGame_Campaign_Bible_Weeks2-8_v1.md", noisy)


def test_v2615_dirty_planning_art_does_not_dominate_swiftui_source_prompt(tmp_path: Path) -> None:
    repo = tmp_path
    _make_examplegame_like_repo(repo)
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
        "Docs/ExampleGame_Campaign_Bible_Weeks2-8_v1.md",
        "animal_sprite_pose_screenshot_manifest.json",
        "animal_sprite_crop_manifest.json",
    ):
        path = repo / rel
        path.write_text(path.read_text(encoding="utf-8") + noisy_update, encoding="utf-8")

    init_project(repo)
    index_project(repo, "lite")
    result = compile_prompt(repo, PROMPT, "lite", use_repo_map=True, cache_optimized=True)

    assert result["metrics"]["packet_total_tokens"] <= result["caps"]["hard_packet_token_budget"]
    impact = result["impact_map"]
    likely_edit = {item["path"] for item in impact["likely_edit_files"]}
    likely_files = {item["path"] for item in impact["likely_files"]}
    top_level_likely_edit = {item["path"] for item in result["likely_edit_files"]}
    top_level_likely_files = {item["path"] for item in result["likely_files"]}
    required_swift = {
        "ExampleGame/Views/MainMenuView.swift",
        "ExampleGame/Views/BottomBarView.swift",
        "ExampleGame/Views/HomesteadView.swift",
        "ExampleGame/Views/HomesteadLocationSceneView.swift",
        "ExampleGame/ViewModels/GameSessionViewModel+HomesteadNavigation.swift",
    }
    expected_swift = {
        "ExampleGame/Views/MainMenuView.swift",
        "ExampleGame/Views/BottomBarView.swift",
        "ExampleGame/Views/HomesteadView.swift",
        "ExampleGame/Views/HomesteadLocationSceneView.swift",
        "ExampleGame/Views/SharedViewStyles.swift",
        "ExampleGame/ViewModels/GameSessionViewModel+HomesteadNavigation.swift",
        "ExampleGame/Models/TutorialState.swift",
    }
    assert required_swift <= likely_edit
    assert required_swift <= likely_files
    assert required_swift <= top_level_likely_edit
    assert required_swift <= top_level_likely_files
    assert likely_edit & expected_swift
    broad_swift = {
        "ExampleGame/ViewModels/NewGameViewModel.swift",
        "ExampleGame/DevTools/DevCheckpointID.swift",
        "ExampleGame/Models/FrontierRisk/FrontierRiskModels.swift",
        "ExampleGame/Systems/RiskResolver.swift",
        "ExampleGame/Views/FounderSelectView.swift",
        "ExampleGame/Views/EventCardView.swift",
    }
    assert not broad_swift & likely_edit
    assert not broad_swift & top_level_likely_edit
    allowed = set(result["patch_boundary"]["allowed_edit_files"])
    assert required_swift <= allowed
    assert not broad_swift & allowed
    forbidden_fragments = (
        "Docs/Planning_Bundles",
        "ArtSource",
        "Assets.xcassets",
        "DerivedData",
        ".premode",
        ".agents",
        "animal_sprite",
    )
    assert not any(any(fragment in path for fragment in forbidden_fragments) for path in likely_edit)

    full_paths = [item["path"] for item in result["context_tiers"]["full_text_files"]]
    assert any(path.startswith("ExampleGame/") and path.endswith(".swift") for path in full_paths)
    assert required_swift & set(full_paths)
    assert not any(path.startswith("Docs/Planning_Bundles/") for path in full_paths)
    assert not any(path.startswith("ArtSource/") for path in full_paths)
    assert "Docs/ExampleGame_Campaign_Bible_Weeks2-8_v1.md" not in full_paths
    assert "animal_sprite_pose_screenshot_manifest.json" not in full_paths
    assert "animal_sprite_crop_manifest.json" not in full_paths

    summarized_or_manifest = result["context_tiers"]["summarized_files"] + result["context_tiers"]["manifest_only_files"]
    planning_compacted = [
        item["path"]
        for item in summarized_or_manifest
        if "planning_art_dirty_compacted" in item.get("evidence_flags", [])
    ]
    docs_compacted = [
        item["path"]
        for item in summarized_or_manifest
        if "docs_dirty_compacted" in item.get("evidence_flags", [])
    ]
    assert planning_compacted
    assert "Docs/ExampleGame_Campaign_Bible_Weeks2-8_v1.md" in docs_compacted
    diagnostics = impact["routing_filter_diagnostics"]
    assert diagnostics["source_recovery_attempted"] is True
    assert diagnostics["safe_candidate_count"] >= 4
    assert set(diagnostics["recovered_source_candidates"]) & expected_swift
    assert diagnostics["filtered_count"] >= 0
    assert "filtered_reasons" in diagnostics
    assert diagnostics["docs_downranked_count"] >= 0
    assert diagnostics["asset_manifest_filtered_count"] >= 2
    assert diagnostics["filtered_reasons"]["asset_manifest_boundary"] >= 2
    assert result["routing_filter_diagnostics"]
    assert result["routing_filter_diagnostics"]["swiftui_scope_tightened"] is True
