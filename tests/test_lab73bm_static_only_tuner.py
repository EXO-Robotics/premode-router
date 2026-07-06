from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import cli
from premode import pcodex_bootstrap
from premode import tuning


REQUIRED_FILES = {
    "repo_profile.json",
    "path_taxonomy.json",
    "repo_vocabulary.json",
    "source_test_map.json",
    "prompt_phrase_routes.json",
    "hotspots_and_suppressions.json",
    "literal_symbol_weights.json",
    "evaluation_prompts.jsonl",
    "TUNING_REPORT.md",
    "VALIDATION.md",
    "VALIDATION.json",
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _synthetic_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "synthetic_repo"
    repo.mkdir()
    _write(
        repo / "src" / "auth" / "login.py",
        """
def login_user(name):
    return name.strip()
""",
    )
    _write(
        repo / "src" / "auth" / "session.py",
        """
class SessionStore:
    def create_session(self, user):
        return user
""",
    )
    _write(
        repo / "src" / "ui" / "settings_view.py",
        """
def render_settings_view():
    return "settings"
""",
    )
    _write(
        repo / "tests" / "auth" / "test_login.py",
        """
from src.auth.login import login_user

def test_login_user_trims_name():
    assert login_user(" ada ") == "ada"
""",
    )
    _write(
        repo / "tests" / "ui" / "test_settings_view.py",
        """
from src.ui.settings_view import render_settings_view

def test_settings_view_renders():
    assert render_settings_view() == "settings"
""",
    )
    _write(repo / "docs" / "auth.md", "# Auth Guide\n\nShort safe docs.")
    _write(repo / "package.json", '{"scripts": {"test": "pytest"}}')
    _write(repo / "generated" / "client.py", "def generated_client():\n    return 'generated'\n")
    _write(repo / "vendor" / "lib.py", "def vendored():\n    return 'vendor'\n")
    return repo


def _generate(repo: Path) -> Path:
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"
    return repo / ".premode" / "tuning"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_static_only_tuning_creates_required_files_under_tuning_dir(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)

    assert {path.name for path in out.iterdir() if path.is_file()} == REQUIRED_FILES
    for path in out.iterdir():
        assert path.resolve().is_relative_to((repo / ".premode" / "tuning").resolve())


def test_repo_profile_pins_schema_algorithm_boundary_and_out_of_band_diagnostics(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    profile = _load(out / "repo_profile.json")

    assert profile["schema_version"] == "pcodex.repo_profile.v1"
    assert profile["base_algorithm"] == "literal_symbol"
    assert profile["model_facing_packet_boundary"] == [
        "TASK",
        "PRIMARY_FILES",
        "RELATED_TESTS",
        "END_PREMODE_CONTEXT_PACKET_V5",
    ]
    assert profile["diagnostics_out_of_band"] is True
    assert all(str(path).startswith(".premode/tuning/") for path in profile["artifacts"].values())


def test_path_taxonomy_classifies_core_roles_and_suppressible_paths(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    taxonomy = _load(out / "path_taxonomy.json")
    roles = {entry["path"]: entry["role"] for entry in taxonomy["paths"]}

    assert roles["src/auth/login.py"] == "source"
    assert roles["tests/auth/test_login.py"] == "test"
    assert roles["docs/auth.md"] == "docs"
    assert roles["package.json"] == "config"
    assert roles["generated/client.py"] == "generated"
    assert roles["vendor/lib.py"] == "vendor"


def test_repo_vocabulary_stores_terms_and_symbols_without_large_snippets(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    vocab = _load(out / "repo_vocabulary.json")
    terms = {item["term"] for item in vocab["terms"]}
    symbols = {item["term"] for item in vocab["symbols"]}

    assert "auth" in terms
    assert "login user" in symbols
    assert "sessionstore" in symbols
    serialized = json.dumps(vocab)
    assert "return name.strip()" not in serialized
    assert all("\n" not in value for value in _all_strings(vocab))
    assert all(len(value) <= 240 for value in _all_strings(vocab))


def _all_strings(obj):
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _all_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _all_strings(value)
    elif isinstance(obj, str):
        yield obj


def test_source_test_map_includes_confidence_without_overconfident_weak_mappings(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    source_map = _load(out / "source_test_map.json")

    login_mapping = next(item for item in source_map["mappings"] if item["source_path"] == "src/auth/login.py")
    assert login_mapping["tests"][0]["test_path"] == "tests/auth/test_login.py"
    assert 0.0 <= login_mapping["tests"][0]["confidence"] <= 1.0
    weak = [test for item in source_map["mappings"] for test in item["tests"] if test["relation_type"] != "basename_exact"]
    assert all(test["confidence"] < 0.9 for test in weak)


def test_prompt_phrase_routes_mark_ambiguity_instead_of_guessing(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    routes = _load(out / "prompt_phrase_routes.json")

    ambiguous = routes["ambiguous_phrases"]
    assert any(item["phrase"] == "auth" for item in ambiguous)
    route = next(item for item in routes["routes"] if item["phrase"] == "auth")
    assert route["ambiguity"] == "ambiguous"


def test_hotspots_and_suppressions_include_generated_vendor_noise_suppressions(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    _write(repo / "build" / "artifact.txt", "compiled output")
    out = _generate(repo)
    suppressions = _load(out / "hotspots_and_suppressions.json")["suppressions"]
    suppressed = {item["path"]: item for item in suppressions}

    assert suppressed["generated/client.py"]["reason"] == "generated_path"
    assert suppressed["vendor/lib.py"]["reason"] == "vendor_path"
    assert suppressed["build/artifact.txt"]["reason"] == "noise_path"


def test_literal_symbol_weights_exist_and_are_bounded(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    weights = _load(out / "literal_symbol_weights.json")

    assert weights["weights"]
    assert all(-5.0 <= float(value) <= 5.0 for value in weights["weights"].values())
    assert weights["safety_caps"]["cannot_disable_suppressions"] is True


def test_tuning_report_contains_required_safety_summary(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    report = (out / "TUNING_REPORT.md").read_text(encoding="utf-8")

    assert "local-only scan" in report
    assert "source edits: none" in report
    assert "model-facing packet expansion: none" in report
    assert "secret values stored: none" in report


def test_validate_succeeds_on_generated_artifacts(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    _generate(repo)

    validation = tuning.validate_tuning_artifacts(repo)

    assert validation["status"] == "pass"
    assert validation["failures"] == []


def test_validate_fails_on_invalid_schema_version(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    profile = _load(out / "repo_profile.json")
    profile["schema_version"] = "wrong"
    (out / "repo_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    validation = tuning.validate_tuning_artifacts(repo)

    assert validation["status"] == "fail"
    assert "profile_schema_version_invalid" in validation["failures"]


def test_validate_fails_on_missing_required_artifact(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    (out / "source_test_map.json").unlink()

    validation = tuning.validate_tuning_artifacts(repo)

    assert validation["status"] == "fail"
    assert "missing_artifact:source_test_map" in validation["failures"]


def test_validate_fails_if_obvious_secret_value_appears_in_artifact(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    vocab = _load(out / "repo_vocabulary.json")
    vocab["terms"].append({"term": "api_key = sk_test_1234567890", "paths": ["src/auth/login.py"], "count": 1, "sources": ["test"]})
    (out / "repo_vocabulary.json").write_text(json.dumps(vocab), encoding="utf-8")

    validation = tuning.validate_tuning_artifacts(repo)

    assert validation["status"] == "fail"
    assert any(failure.startswith("secret_like_value:repo_vocabulary") for failure in validation["failures"])


def test_validate_fails_if_large_source_snippet_appears_in_artifact(tmp_path: Path) -> None:
    repo = _synthetic_repo(tmp_path)
    out = _generate(repo)
    vocab = _load(out / "repo_vocabulary.json")
    vocab["terms"].append(
        {
            "term": "def leaked_source_snippet(): return 'this is a long snippet shaped value that should never be stored inside a tuning artifact because it is source body text'",
            "paths": ["src/auth/login.py"],
            "count": 1,
            "sources": ["test"],
        }
    )
    (out / "repo_vocabulary.json").write_text(json.dumps(vocab), encoding="utf-8")

    validation = tuning.validate_tuning_artifacts(repo)

    assert validation["status"] == "fail"
    assert any(failure.startswith("large_or_snippet_like_string:repo_vocabulary") for failure in validation["failures"])


def test_pcodex_tune_static_only_routes_correctly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _synthetic_repo(tmp_path)

    assert pcodex_bootstrap.main(["tune", "--repo-root", str(repo), "--static-only"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "generated"
    assert payload["validation_status"] == "pass"
    assert Path(payload["artifacts"]["repo_profile"]).exists()
    assert payload["next"] == "pcodex tune --validate"


def test_pcodex_tune_validate_routes_correctly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _synthetic_repo(tmp_path)
    tuning.write_tuning_artifacts(repo)

    assert pcodex_bootstrap.main(["tune", "--repo-root", str(repo), "--validate"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "pass"
    assert payload["failures"] == []


def test_pcodex_main_tune_routes_to_bootstrap_without_codex_exec_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("pcodex tune must not launch the Codex wrapper"))

    assert cli.pcodex_main(["tune", "--static-only"]) == 0
    assert calls == [["tune", "--static-only"]]
    assert "--execute" not in calls[0]
    assert "--output-last-message" not in calls[0]


def test_generalized_compile_default_remains_unchanged() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")

    assert 'comp.add_argument("--plugin"' in source
    assert "--tuning" not in source


def test_model_facing_packet_rendering_constants_remain_internal_only() -> None:
    assert tuning.MODEL_FACING_PACKET_BOUNDARY == [
        "TASK",
        "PRIMARY_FILES",
        "RELATED_TESTS",
        "END_PREMODE_CONTEXT_PACKET_V5",
    ]
