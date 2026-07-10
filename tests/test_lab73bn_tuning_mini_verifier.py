from __future__ import annotations

import json
from pathlib import Path

import pytest

from premode import cli
from premode import pcodex_bootstrap
from premode import tuning


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "synthetic_repo"
    repo.mkdir()
    _write(repo / "docs" / "client.md", "# Client\n\nShort safe docs.")
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


def _generate(repo: Path) -> Path:
    result = tuning.write_tuning_artifacts(repo)
    assert result["validation_status"] == "pass"
    return repo / ".premode" / "tuning"


def _set_eval_rows(out: Path) -> None:
    _append_jsonl(
        out / "evaluation_prompts.jsonl",
        [
            {
                "id": "client-route-001",
                "prompt": "Update client behavior.",
                "expected_primary_files": ["src/client.py"],
                "expected_related_tests": [],
                "tags": ["client"],
            },
            {
                "id": "login-tests-001",
                "prompt": "Update login behavior and related tests.",
                "expected_primary_files": ["src/auth/login.py"],
                "expected_related_tests": ["tests/z_auth/test_login.py"],
                "tags": ["auth"],
            },
        ],
    )


def _add_client_path_route(out: Path, *, ambiguous: bool = False) -> None:
    routes = _json(out / "prompt_phrase_routes.json")
    if ambiguous:
        routes["routes"] = [route for route in routes.get("routes", []) if route.get("phrase") != "client"]
    routes["routes"].insert(
        0,
        {
            "phrase": "client",
            "targets": [{"path": "src/client.py", "role": "source"}],
            "confidence": 0.95,
            "ambiguity": "ambiguous" if ambiguous else "none",
            "evidence": {"source": "synthetic_test"},
        },
    )
    if ambiguous:
        routes.setdefault("ambiguous_phrases", []).append(
            {"phrase": "client", "candidate_roles": ["source", "generated"], "tie_break_policy": "prefer explicit prompt paths"}
        )
    _write_json(out / "prompt_phrase_routes.json", routes)


def _pin_login_source_test_map(out: Path) -> None:
    source_map = _json(out / "source_test_map.json")
    for mapping in source_map["mappings"]:
        if mapping["source_path"] == "src/auth/login.py":
            mapping["tests"] = [
                {"test_path": "tests/z_auth/test_login.py", "confidence": 0.98, "relation_type": "synthetic_exact", "evidence": ["login"]}
            ]
    _write_json(out / "source_test_map.json", source_map)


def test_pcodex_tune_verify_routes_correctly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _set_eval_rows(out)
    _add_client_path_route(out)
    _pin_login_source_test_map(out)

    assert pcodex_bootstrap.main(["tune", "--repo-root", str(repo), "--verify"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "pcodex.tuning_verify.v1"
    assert payload["verdict"] in {"PASS", "NEEDS_ADJUSTMENT", "FAIL"}
    assert (out / "VERIFY_REPORT.md").exists()
    assert (out / "VERIFY_RESULTS.json").exists()


def test_verify_validates_profile_before_scoring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _set_eval_rows(out)
    profile = _json(out / "repo_profile.json")
    profile["schema_version"] = "wrong"
    _write_json(out / "repo_profile.json", profile)

    monkeypatch.setattr(tuning, "score_general_selection", lambda row, artifacts: pytest.fail("scoring must not run after validation failure"))
    result = tuning.verify_tuning_profile(repo)

    assert result["verdict"] == "FAIL"
    assert result["profile_validation_status"] == "FAIL"


def test_missing_evaluation_prompts_produces_fail(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    (out / "evaluation_prompts.jsonl").unlink()

    result = tuning.verify_tuning_profile(repo)

    assert result["verdict"] == "FAIL"
    assert "missing_or_empty_evaluation_prompts" in result["notes"]


def test_invalid_profile_produces_fail(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _set_eval_rows(out)
    profile = _json(out / "repo_profile.json")
    profile["base_algorithm"] = "other"
    _write_json(out / "repo_profile.json", profile)

    result = tuning.verify_tuning_profile(repo)

    assert result["verdict"] == "FAIL"
    assert "profile_base_algorithm_invalid" in result["profile_validation_failures"]


def test_safe_profile_and_prompts_write_verify_artifacts_with_metrics(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _set_eval_rows(out)
    _add_client_path_route(out)
    _pin_login_source_test_map(out)

    result = tuning.verify_tuning_profile(repo)
    written = _json(out / "VERIFY_RESULTS.json")

    assert (out / "VERIFY_REPORT.md").exists()
    assert written["schema_version"] == "pcodex.tuning_verify.v1"
    assert result["verdict"] in {"PASS", "NEEDS_ADJUSTMENT", "FAIL"}
    assert set(result["general"]) >= {"expected_primary_file_hit_rate", "expected_related_test_hit_rate"}
    assert set(result["tuned"]) >= {"expected_primary_file_hit_rate", "expected_related_test_hit_rate"}
    assert set(result["delta"]) >= {"primary_hit_rate", "related_test_hit_rate", "rank_improvement"}


def test_tuned_route_can_improve_expected_primary_hit_rate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _append_jsonl(
        out / "evaluation_prompts.jsonl",
        [
            {
                "id": "client-route-001",
                "prompt": "Update client behavior.",
                "expected_primary_files": ["src/client.py"],
                "expected_related_tests": [],
                "tags": ["client"],
            }
        ],
    )
    _add_client_path_route(out)

    result = tuning.verify_tuning_profile(repo)

    assert result["general"]["expected_primary_file_hit_rate"] == 0.0
    assert result["tuned"]["expected_primary_file_hit_rate"] == 1.0
    assert result["delta"]["primary_hit_rate"] == 1.0


def test_tuned_source_test_map_can_improve_expected_related_test_hit_rate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _append_jsonl(
        out / "evaluation_prompts.jsonl",
        [
            {
                "id": "login-tests-001",
                "prompt": "Update login behavior and related tests.",
                "expected_primary_files": ["src/auth/login.py"],
                "expected_related_tests": ["tests/z_auth/test_login.py"],
                "tags": ["auth"],
            }
        ],
    )
    _pin_login_source_test_map(out)

    result = tuning.verify_tuning_profile(repo)

    assert result["general"]["expected_related_test_hit_rate"] == 0.0
    assert result["tuned"]["expected_related_test_hit_rate"] == 1.0
    assert result["delta"]["related_test_hit_rate"] == 1.0


def test_ambiguous_phrase_route_does_not_overclaim(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _append_jsonl(
        out / "evaluation_prompts.jsonl",
        [
            {
                "id": "client-ambiguous-001",
                "prompt": "Update client behavior.",
                "expected_primary_files": ["src/client.py"],
                "expected_related_tests": [],
                "tags": ["client"],
            }
        ],
    )
    routes = _json(out / "prompt_phrase_routes.json")
    routes["routes"] = [route for route in routes.get("routes", []) if route.get("phrase") != "client"]
    _write_json(out / "prompt_phrase_routes.json", routes)
    baseline = tuning.verify_tuning_profile(repo)
    _add_client_path_route(out, ambiguous=True)

    result = tuning.verify_tuning_profile(repo)

    assert result["rows"][0]["tuned_primary_files"] == baseline["rows"][0]["tuned_primary_files"]
    assert result["tuned"]["expected_primary_file_hit_rate"] == baseline["tuned"]["expected_primary_file_hit_rate"]


def test_generated_vendor_suppression_reduces_false_positives(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _append_jsonl(
        out / "evaluation_prompts.jsonl",
        [
            {
                "id": "client-suppression-001",
                "prompt": "Update client behavior.",
                "expected_primary_files": ["src/client.py"],
                "expected_related_tests": [],
                "tags": ["client"],
            }
        ],
    )
    _add_client_path_route(out)

    result = tuning.verify_tuning_profile(repo)

    assert result["delta"]["false_positive_reduction"] > 0.0


def test_packet_boundary_safe_requires_unchanged_boundary(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _set_eval_rows(out)
    profile = _json(out / "repo_profile.json")
    profile["model_facing_packet_boundary"] = ["TASK", "BROKEN"]
    _write_json(out / "repo_profile.json", profile)

    result = tuning.verify_tuning_profile(repo)

    assert result["packet_boundary_safe"] is False
    assert result["verdict"] == "FAIL"


def test_verifier_does_not_write_outside_tuning_dir(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _generate(repo)
    _set_eval_rows(out)
    before = {path.relative_to(repo).as_posix() for path in repo.rglob("*") if path.is_file() and ".premode/tuning" not in path.as_posix()}

    tuning.verify_tuning_profile(repo)

    after = {path.relative_to(repo).as_posix() for path in repo.rglob("*") if path.is_file() and ".premode/tuning" not in path.as_posix()}
    assert after == before
    assert (out / "VERIFY_REPORT.md").exists()
    assert (out / "VERIFY_RESULTS.json").exists()


def test_verify_artifacts_do_not_store_large_source_snippets_or_secret_values(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(
        repo / "src" / "secret_holder.py",
        """
def harmless_name():
    value = "api_key = sk_test_1234567890"
    return "this source body is intentionally much longer than a path and must never appear inside verify artifacts"
""",
    )
    out = _generate(repo)
    _set_eval_rows(out)
    tuning.verify_tuning_profile(repo)

    serialized = (out / "VERIFY_RESULTS.json").read_text(encoding="utf-8") + (out / "VERIFY_REPORT.md").read_text(encoding="utf-8")
    assert "api_key = sk_test_1234567890" not in serialized
    assert "this source body is intentionally much longer" not in serialized


def test_pcodex_main_tune_verify_routes_to_bootstrap_without_codex_exec_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("pcodex tune --verify must not launch the Codex wrapper"))

    assert cli.pcodex_main(["tune", "--verify"]) == 0
    assert calls == [["tune", "--verify"]]


def test_generalized_compile_keeps_developer_tuning_and_legacy_boundary_compatible() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")

    assert 'comp.add_argument("--tuning"' in source
    assert "help=argparse.SUPPRESS" in source
    assert tuning.MODEL_FACING_PACKET_BOUNDARY == [
        "TASK",
        "PRIMARY_FILES",
        "RELATED_TESTS",
        "END_PREMODE_CONTEXT_PACKET_V5",
    ]
