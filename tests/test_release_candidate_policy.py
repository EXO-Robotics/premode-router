from __future__ import annotations

from pathlib import Path

import pytest

from premode.candidate_policy import CandidateClassification, evaluate_candidate
from premode.locator import locate_files, locate_media_files


def _write(repo: Path, relative: str, content: str = "def runtime_config():\n    return True\n") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        (".pcodex/config.toml", CandidateClassification.DENY_RUNTIME),
        (".premode/out/packet.json", CandidateClassification.DENY_SECRET),
        (".git/config", CandidateClassification.DENY_SECRET),
        ("nested/.pcodex/config.toml", CandidateClassification.DENY_RUNTIME),
        ("foo/bar/.premode/index.json", CandidateClassification.DENY_SECRET),
        ("package/.git/HEAD", CandidateClassification.DENY_SECRET),
    ],
)
def test_known_product_runtime_roots_are_hard_denied(tmp_path: Path, relative: str, expected: CandidateClassification) -> None:
    result = evaluate_candidate(
        tmp_path,
        relative,
        "explicit_prompt_path",
        {"explicit_paths": [relative], "generated_intent": True},
    )

    assert result.classification == expected
    assert result.final_disposition == "REJECT"
    assert "explicit_prompt_path" in result.provenance_chain


def test_repo_agent_instructions_are_not_misclassified_as_runtime(tmp_path: Path) -> None:
    result = evaluate_candidate(tmp_path, ".agents/skills/foo/SKILL.md", "inventory")

    assert result.classification != CandidateClassification.DENY_RUNTIME
    assert result.admitted is True


def test_hard_boundaries_precede_explicit_and_generated_exceptions(tmp_path: Path) -> None:
    outside = evaluate_candidate(tmp_path, "../outside.py", "explicit_prompt_path", {"explicit_paths": ["../outside.py"]})
    secret = evaluate_candidate(tmp_path, ".env", "explicit_prompt_path", {"explicit_paths": [".env"]})

    assert outside.classification == CandidateClassification.DENY_OUTSIDE_ROOT
    assert secret.classification == CandidateClassification.DENY_SECRET


def test_symlink_escape_is_hard_denied(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("outside = True\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    link.symlink_to(outside)

    result = evaluate_candidate(tmp_path, "linked.py", "inventory")

    assert result.classification == CandidateClassification.DENY_SYMLINK_ESCAPE


def test_ignored_path_requires_an_explicit_prompt_path(tmp_path: Path) -> None:
    _write(tmp_path, ".gitignore", "ignored/\n")
    _write(tmp_path, "ignored/feature.py")

    implicit = evaluate_candidate(tmp_path, "ignored/feature.py", "inventory")
    explicit = evaluate_candidate(
        tmp_path,
        "ignored/feature.py",
        ("inventory", "explicit_prompt_path"),
        {"explicit_paths": ["ignored/feature.py"]},
    )

    assert implicit.classification == CandidateClassification.DENY_IGNORED
    assert explicit.classification == CandidateClassification.ALLOW_IF_EXPLICIT
    assert explicit.admitted is True


def test_generated_exception_requires_generated_intent(tmp_path: Path) -> None:
    _write(tmp_path, "generated/client.py")

    ordinary = evaluate_candidate(tmp_path, "generated/client.py", "inventory")
    intended = evaluate_candidate(
        tmp_path,
        "generated/client.py",
        ("inventory", "generated_intent_exception"),
        {"generated_intent": True},
    )

    assert ordinary.classification == CandidateClassification.DENY_IGNORED
    assert intended.classification == CandidateClassification.GENERATED_EXCEPTION
    assert intended.admitted is True
    assert "generated_intent_exception" in intended.provenance_chain


def test_generated_intent_exception_reaches_scoring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "generated/client.py", "def generated_client():\n    return 'client'\n")
    import premode.locator as locator

    scored_paths: list[str] = []
    original_score = locator._score_file

    def recording_score(file, evidence):
        scored_paths.append(file.path)
        return original_score(file, evidence)

    monkeypatch.setattr(locator, "_score_file", recording_score)
    locate_files(tmp_path, "Update generated/client.py generated client behavior.", inventory_paths=["generated/client.py"])

    assert scored_paths == ["generated/client.py"]


def test_support_relation_is_admitted_only_as_support(tmp_path: Path) -> None:
    result = evaluate_candidate(tmp_path, "pyproject.toml", ("inventory", "support_relation"))

    assert result.classification == CandidateClassification.SUPPORT_ONLY
    assert result.final_disposition == "ADMIT_SUPPORT"
    assert "support_relation" in result.provenance_chain


def test_inventory_runtime_state_is_filtered_before_scoring_and_return(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write(tmp_path, "src/runtime_config.py")
    _write(tmp_path, ".pcodex/config.toml", "runtime_config = true\n")
    _write(tmp_path, ".premode/out/runtime_config.py")
    _write(tmp_path, ".git/runtime_config.py")
    import premode.locator as locator

    scored_paths: list[str] = []
    original_score = locator._score_file

    def recording_score(file, evidence):
        scored_paths.append(file.path)
        return original_score(file, evidence)

    monkeypatch.setattr(locator, "_score_file", recording_score)
    result = locate_files(
        tmp_path,
        "Fix runtime_config behavior in src/runtime_config.py and .pcodex/config.toml.",
        inventory_paths=[
            ".pcodex/config.toml",
            ".premode/out/runtime_config.py",
            ".git/runtime_config.py",
            "src/runtime_config.py",
            "missing/stale.py",
        ],
    )

    returned = [file.path for file in result.primary_files + result.support_files + result.verification_files]
    assert scored_paths == ["src/runtime_config.py"]
    assert returned == ["src/runtime_config.py"]
    policy = result.metadata["candidate_policy"]
    assert policy["source_counts"]["inventory"] == {"evaluated": 5, "admitted": 2, "rejected": 3}
    assert policy["source_counts"]["explicit_prompt_path"]["rejected"] == 1
    assert policy["classification_counts"]["DENY_RUNTIME"] == 2
    assert policy["classification_counts"]["DENY_SECRET"] == 2


def test_explicit_path_missing_from_stale_inventory_uses_same_policy(tmp_path: Path) -> None:
    _write(tmp_path, "src/explicit_feature.py", "def explicit_feature():\n    return True\n")

    result = locate_files(
        tmp_path,
        "Fix src/explicit_feature.py.",
        inventory_paths=["missing/stale.py"],
    )

    returned = [file.path for file in result.primary_files + result.support_files + result.verification_files]
    assert "src/explicit_feature.py" in returned
    record = next(
        record
        for record in result.metadata["candidate_provenance"]
        if record["normalized_path"] == "src/explicit_feature.py"
    )
    assert record["provenance_source"] == "explicit_prompt_path"
    assert record["final_disposition"] == "ADMIT_PRIMARY"


def test_fallback_walk_and_media_ingress_share_candidate_policy(tmp_path: Path) -> None:
    _write(tmp_path, "assets/palm.png", "not really binary")
    _write(tmp_path, ".pcodex/palm.png", "runtime")

    normal = locate_files(tmp_path, "Locate assets/palm.png")
    media = locate_media_files(
        tmp_path,
        "Locate the palm png asset. Do not modify files.",
        inventory_paths=["assets/palm.png", ".pcodex/palm.png"],
    )

    assert normal.metadata["candidate_policy"]["source_counts"]["fallback_walk"]["evaluated"] >= 2
    assert [file.path for file in media.primary_files] == ["assets/palm.png"]
    assert media.metadata["candidate_policy"]["classification_counts"]["DENY_RUNTIME"] == 1
