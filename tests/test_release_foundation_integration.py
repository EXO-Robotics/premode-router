from __future__ import annotations

from pathlib import Path

from premode import compiler
from premode import pcodex_bootstrap as pcodex
from premode.write_policy import ADVISORY


def _write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    _write(tmp_path, "src/auth.py", "def authenticate(token):\n    return bool(token)\n")
    _write(tmp_path, "tests/test_auth.py", "from src.auth import authenticate\n\ndef test_authenticate():\n    assert authenticate('x')\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname = 'auth-package'\n")
    return tmp_path


def test_canonical_packet_paths_equal_routing_projection(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = pcodex.compile_pcodex_packet(
        repo,
        "Fix the authenticate symbol and verify its direct test.",
        write_policy=ADVISORY,
    )

    projection = result["routing_decision"]["packet_projection"]
    expected = [
        *projection["primary_paths"],
        *projection["verification_paths"],
        *projection["support_paths"],
    ]
    assert result["selected_paths"] == expected
    assert result["model_facing_selected_paths"] == expected
    assert result["packet"].count("Fix the authenticate symbol and verify its direct test.") == 1
    for path in expected:
        assert path in result["packet"]
    assert "candidate_provenance" not in result["packet"]
    assert "routing_mode" not in result["packet"]


def test_runtime_state_is_denied_from_scoring_metadata_and_model_bytes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, ".pcodex/config.toml", "default_ranker = 'poison'\n")
    _write(repo, ".premode/out/runtime_packet.json", "{}\n")
    task = "Fix authenticate in src/auth.py; do not use .pcodex/config.toml."

    result = compiler.compile_prompt(
        repo,
        task,
        "lite",
        use_repo_map=True,
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
        canonical_core_packet=True,
        record_artifacts=False,
    )

    assert ".pcodex/config.toml" not in result["model_facing_selected_paths"]
    assert ".premode/out/runtime_packet.json" not in result["model_facing_selected_paths"]
    generated = result["packet"].replace(task, "", 1)
    assert ".pcodex/config.toml" not in generated
    assert ".premode/out/runtime_packet.json" not in generated
    denied = {
        record["normalized_path"]
        for record in result["candidate_provenance"]
        if record["final_disposition"] == "REJECT"
    }
    assert ".pcodex/config.toml" in denied


def test_abstention_is_exact_standard_task_at_model_boundary(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(compiler, "_LARGE_REPO_BROAD_DEGRADE_THRESHOLD", 1)
    task = "Review the repository broadly.\nDo not infer hidden routing metadata."

    result = pcodex.compile_pcodex_packet(repo, task, write_policy=ADVISORY)
    standard_request = pcodex.compose_final_prompt(task, None)
    abstain_request = pcodex.compose_final_prompt(task, result["packet"])

    assert result["routing_mode"] == "ABSTAIN"
    assert result["selected_paths"] == []
    assert abstain_request == standard_request == task
    assert result["model_facing_sections"] == []
