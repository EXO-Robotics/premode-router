from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import cli
from premode.compiler import compile_prompt
from premode import tuning


LITERAL_SYMBOL_KWARGS = {
    "packet_version": "v5",
    "packet_variant": "tool_assisted_anchors_internal",
    "packet_strategy": "literal_symbol",
    "record_artifacts": False,
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "synthetic_repo"
    repo.mkdir()
    _write(repo / "docs" / "client.md", "# Client\n\nSafe synthetic docs.")
    _write(repo / "generated" / "client.py", "def generated_client():\n    return 'generated'\n")
    _write(repo / "vendor" / "client.py", "def vendor_client():\n    return 'vendor'\n")
    _write(repo / "src" / "alpha" / "client.py", "def alpha_client():\n    return 'alpha'\n")
    _write(repo / "src" / "client.py", "def client_entrypoint():\n    return 'client'\n")
    _write(repo / "src" / "auth" / "login.py", "def login_user(name):\n    return name.strip()\n")
    _write(repo / "src" / "auth" / "session.py", "class SessionStore:\n    pass\n")
    _write(repo / "tests" / "a" / "test_login.py", "def test_a_login():\n    assert True\n")
    _write(repo / "tests" / "b" / "test_login.py", "def test_b_login():\n    assert True\n")
    _write(repo / "tests" / "c" / "test_login.py", "def test_c_login():\n    assert True\n")
    _write(repo / "tests" / "z_auth" / "test_login.py", "def test_login_user():\n    assert True\n")
    return repo


def _generate_tuning(repo: Path) -> Path:
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"
    out = repo / ".premode" / "tuning"
    routes = _json(out / "prompt_phrase_routes.json")
    routes["routes"].insert(
        0,
        {
            "phrase": "client",
            "targets": [{"path": "src/client.py", "role": "source"}],
            "confidence": 0.95,
            "ambiguity": "none",
            "evidence": {"source": "synthetic_test"},
        },
    )
    _write_json(out / "prompt_phrase_routes.json", routes)
    source_map = _json(out / "source_test_map.json")
    for mapping in source_map["mappings"]:
        if mapping["source_path"] == "src/auth/login.py":
            mapping["tests"] = [
                {"test_path": "tests/z_auth/test_login.py", "confidence": 0.98, "relation_type": "synthetic_exact", "evidence": ["login"]}
            ]
    _write_json(out / "source_test_map.json", source_map)
    validation = tuning.validate_tuning_artifacts(repo)
    assert validation["status"] == "pass"
    return out / "repo_profile.json"


def _paths(items: list[dict] | list[str] | None) -> list[str]:
    out = []
    for item in items or []:
        out.append(str(item.get("path") if isinstance(item, dict) else item))
    return out


def test_compile_help_hides_developer_tuning(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["compile", "--help"])

    assert exc.value.code == 0
    assert "--tuning" not in capsys.readouterr().out


def test_literal_symbol_default_output_unchanged_without_tuning(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = compile_prompt(repo, "Update client behavior.", "lite", **LITERAL_SYMBOL_KWARGS)
    _generate_tuning(repo)
    after = compile_prompt(repo, "Update client behavior.", "lite", **LITERAL_SYMBOL_KWARGS)

    assert after["packet"] == before["packet"]
    assert after["candidate_edit_files"] == before["candidate_edit_files"]
    assert after["tool_assisted_anchors_internal"]["primary_files_after"] == before["tool_assisted_anchors_internal"]["primary_files_after"]


def test_explicit_missing_tuning_file_fails_clearly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)

    code = cli.main(
        [
            "compile",
            "Update client behavior.",
            "--repo",
            str(repo),
            "--plugin",
            "literal_symbol",
            "--tuning",
            ".premode/tuning/repo_profile.json",
            "--no-record",
        ]
    )

    assert code == 2
    assert "Tuning profile not found: .premode/tuning/repo_profile.json" in capsys.readouterr().err


def test_explicit_invalid_tuning_file_fails_clearly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    profile_path = _generate_tuning(repo)
    profile = _json(profile_path)
    profile["schema_version"] = "wrong"
    _write_json(profile_path, profile)

    code = cli.main(
        [
            "compile",
            "Update client behavior.",
            "--repo",
            str(repo),
            "--plugin",
            "literal_symbol",
            "--tuning",
            ".premode/tuning/repo_profile.json",
            "--no-record",
        ]
    )

    assert code == 2
    assert "Invalid tuning profile:" in capsys.readouterr().err


def test_tuning_with_non_literal_strategy_fails_clearly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _generate_tuning(repo)

    code = cli.main(
        [
            "compile",
            "Update client behavior.",
            "--repo",
            str(repo),
            "--packet-version",
            "v5",
            "--packet-variant",
            "ranked_paths",
            "--tuning",
            ".premode/tuning/repo_profile.json",
            "--no-record",
        ]
    )

    assert code == 2
    assert "--tuning currently supports only --plugin literal_symbol / packet_strategy literal_symbol" in capsys.readouterr().err


def test_valid_tuning_affects_internal_primary_ranking_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile_path = _generate_tuning(repo)

    general = compile_prompt(repo, "Update client behavior.", "lite", **LITERAL_SYMBOL_KWARGS)
    tuned = compile_prompt(repo, "Update client behavior.", "lite", tuning_profile=profile_path, **LITERAL_SYMBOL_KWARGS)

    general_primary = _paths(general["candidate_edit_files"])
    assert not general_primary or general_primary[0] != "src/client.py"
    assert _paths(tuned["candidate_edit_files"])[0] == "src/client.py"
    assert tuned["tool_assisted_anchors_internal"]["primary_files_after"][0] == "src/client.py"
    assert "tuning_profile_diagnostics" not in tuned["packet"]
    assert "<TASK_CLASS>" not in tuned["packet"]
    assert "<SUPPORT_RELATIONS>" not in tuned["packet"]


def test_tuning_can_improve_related_test_ranking(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile_path = _generate_tuning(repo)

    general = compile_prompt(repo, "Update login behavior and related tests.", "lite", **LITERAL_SYMBOL_KWARGS)
    tuned = compile_prompt(repo, "Update login behavior and related tests.", "lite", tuning_profile=profile_path, **LITERAL_SYMBOL_KWARGS)

    assert _paths(general["related_tests"])[0] != "tests/z_auth/test_login.py"
    assert _paths(tuned["related_tests"])[0] == "tests/z_auth/test_login.py"
    assert tuned["tool_assisted_anchors_internal"]["related_tests_after"][0] == "tests/z_auth/test_login.py"


def test_generated_vendor_suppressions_reduce_false_positives(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile_path = _generate_tuning(repo)

    tuned = compile_prompt(repo, "Update client behavior.", "lite", tuning_profile=profile_path, **LITERAL_SYMBOL_KWARGS)
    primary = _paths(tuned["candidate_edit_files"])[:4]

    assert "src/client.py" in primary
    assert "generated/client.py" not in primary[:2]
    assert "vendor/client.py" not in primary[:2]


def test_ambiguous_phrase_routes_do_not_overboost(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile_path = _generate_tuning(repo)
    out = profile_path.parent
    routes = _json(out / "prompt_phrase_routes.json")
    routes["routes"] = [route for route in routes["routes"] if route.get("phrase") != "client"]
    _write_json(out / "prompt_phrase_routes.json", routes)
    baseline = compile_prompt(repo, "Update client behavior.", "lite", tuning_profile=profile_path, **LITERAL_SYMBOL_KWARGS)
    routes = _json(out / "prompt_phrase_routes.json")
    routes["routes"].insert(
        0,
        {
            "phrase": "client",
            "targets": [{"path": "src/client.py", "role": "source"}],
            "confidence": 1.0,
            "ambiguity": "ambiguous",
            "evidence": {"source": "synthetic_test"},
        },
    )
    _write_json(out / "prompt_phrase_routes.json", routes)

    tuned = compile_prompt(repo, "Update client behavior.", "lite", tuning_profile=profile_path, **LITERAL_SYMBOL_KWARGS)

    assert _paths(tuned["candidate_edit_files"])[0] == _paths(baseline["candidate_edit_files"])[0]


def test_weights_are_bounded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile_path = _generate_tuning(repo)
    weights = _json(profile_path.parent / "literal_symbol_weights.json")["weights"]

    assert all(-5.0 <= float(value) <= 5.0 for value in weights.values())


def test_model_facing_packet_boundary_and_forbidden_sections_remain_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile_path = _generate_tuning(repo)

    tuned = compile_prompt(repo, "Update client behavior.", "lite", tuning_profile=profile_path, **LITERAL_SYMBOL_KWARGS)
    packet = tuned["packet"]
    tag_order = [tag for tag in ("<TASK>", "<PRIMARY_FILES>", "<RELATED_TESTS>", "<END_PREMODE_CONTEXT_PACKET_V5>") if tag in packet]

    assert tag_order == ["<TASK>", "<PRIMARY_FILES>", "<RELATED_TESTS>", "<END_PREMODE_CONTEXT_PACKET_V5>"]
    forbidden = [
        "<TASK_CLASS>",
        "<SUPPORT_RELATIONS>",
        "<FILE",
        "<SNIPPET",
        "confidence",
        "validation",
        "run this",
        "TASK_CLASS",
        "SUPPORT_RELATIONS",
        "tuning_profile",
    ]
    assert all(term not in packet for term in forbidden)


def test_tuning_diagnostics_stay_out_of_band(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile_path = _generate_tuning(repo)

    tuned = compile_prompt(repo, "Update client behavior.", "lite", tuning_profile=profile_path, **LITERAL_SYMBOL_KWARGS)

    assert tuned["tuning_profile_diagnostics"]["applied"] is True
    assert tuned["tuning_profile_diagnostics"]["model_facing_allowed"] is False
    assert "tuning_profile_diagnostics" not in tuned["packet"]


def test_pcodex_tune_verify_still_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _generate_tuning(repo)

    result = tuning.verify_tuning_profile(repo)

    assert result["verdict"] in {"PASS", "NEEDS_ADJUSTMENT"}
