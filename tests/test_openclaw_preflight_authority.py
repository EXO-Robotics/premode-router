from __future__ import annotations

from pathlib import Path

import pytest

from premode.openclaw_adapter import (
    OpenClawAdapterError,
    classify_openclaw_path,
    qualify_openclaw_workspace,
)


def _write(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")


def _qualified_root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    for marker in (
        "AGENTS.md",
        "PROJECT/tasks.json",
        "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    ):
        _write(root, marker)
    return root


def test_workspace_requires_all_three_marker_families(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _write(root, "AGENTS.md")
    _write(root, "_claw_output/proof.json")
    _write(root, "tools/symphony/readme.md")

    qualification = qualify_openclaw_workspace(root)

    assert qualification.qualified is False
    assert "current_authority" in qualification.reason
    assert "worker_surface" in qualification.reason


def test_workspace_qualification_is_bound_to_root_not_nested_false_positive(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    for marker in (
        "AGENTS.md",
        "PROJECT/tasks.json",
        "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    ):
        _write(nested, marker)

    assert qualify_openclaw_workspace(root).qualified is False


def test_symlinked_markers_do_not_qualify_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    external = tmp_path / "external-authority.txt"
    external.write_text("not workspace authority\n", encoding="utf-8")
    for marker in (
        "AGENTS.md",
        "PROJECT/tasks.json",
        "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    ):
        path = root / marker
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(external)

    assert qualify_openclaw_workspace(root).qualified is False


def test_qualified_workspace_reports_exact_marker_families(tmp_path: Path) -> None:
    root = _qualified_root(tmp_path)

    qualification = qualify_openclaw_workspace(root)

    assert qualification.qualified is True
    assert qualification.reason == "qualified"
    assert qualification.governance_markers == ("AGENTS.md",)
    assert qualification.current_authority_markers == ("PROJECT/tasks.json",)
    assert qualification.worker_markers == (
        "PROJECT/AI/worker_start/WORKER_START_HERE.md",
    )


def test_current_authority_outranks_general_source_policy(tmp_path: Path) -> None:
    root = _qualified_root(tmp_path)

    policy = classify_openclaw_path(
        root, "reconcile the current queue", "PROJECT/tasks.json"
    )

    assert policy.authority_class == "current_authority"
    assert policy.mutation_policy == "explicit_authorization_required"
    assert policy.include is True


def test_unmentioned_history_and_generated_evidence_are_excluded(
    tmp_path: Path,
) -> None:
    root = _qualified_root(tmp_path)

    history = classify_openclaw_path(
        root, "reconcile current state", "PROJECT/state/history/old.json"
    )
    generated = classify_openclaw_path(
        root, "reconcile current state", "_claw_output/proof.json"
    )

    assert history.include is False
    assert history.authority_class == "historical_evidence"
    assert generated.include is False
    assert generated.authority_class == "generated_evidence"


def test_exact_named_history_is_read_only_but_basename_is_not_enough(
    tmp_path: Path,
) -> None:
    root = _qualified_root(tmp_path)
    path = "PROJECT/state/history/old.json"

    exact = classify_openclaw_path(root, f"compare {path} to current state", path)
    basename = classify_openclaw_path(root, "compare old.json to current state", path)

    assert exact.include is True
    assert exact.explicitly_task_named is True
    assert exact.mutation_policy == "read_only"
    assert basename.include is False
    assert basename.explicitly_task_named is False


@pytest.mark.parametrize(
    ("path", "surface"),
    (
        ("Content/Maps/World.umap", "unreal_asset"),
        ("Assets/scene.blend", "blender_asset"),
    ),
)
def test_binary_assets_require_exact_naming_and_authorization(
    tmp_path: Path, path: str, surface: str
) -> None:
    root = _qualified_root(tmp_path)

    unnamed = classify_openclaw_path(root, "repair the world", path)
    named = classify_openclaw_path(root, f"inspect {path}", path)

    assert unnamed.include is False
    assert named.include is True
    assert named.surface == surface
    assert named.mutation_policy == "explicit_authorization_required"


@pytest.mark.parametrize(
    "path",
    (
        "../outside.txt",
        "/tmp/outside.txt",
        "C:/outside.txt",
    ),
)
def test_provider_paths_must_remain_relative_and_contained(
    tmp_path: Path, path: str
) -> None:
    root = _qualified_root(tmp_path)

    with pytest.raises(OpenClawAdapterError):
        classify_openclaw_path(root, "inspect", path)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = _qualified_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OpenClawAdapterError):
        classify_openclaw_path(root, "inspect", "linked/file.py")


def test_dependency_and_secret_paths_are_forbidden(tmp_path: Path) -> None:
    root = _qualified_root(tmp_path)

    dependency = classify_openclaw_path(
        root, "inspect", "web/node_modules/pkg/index.js"
    )
    secret = classify_openclaw_path(root, "inspect .env.production", ".env.production")

    assert dependency.include is False
    assert dependency.mutation_policy == "forbidden"
    assert secret.include is False
    assert secret.mutation_policy == "forbidden"
