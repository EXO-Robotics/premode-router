from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from premode import cli
from premode import compiler
from premode import pcodex_bootstrap as pcodex
from premode.core_packet import CorePath, render_context_packet_v1, render_core_packet
from premode.role_core import classify_path_role, infer_prompt_intent, path_role_rank
from premode.role_model import (
    classify_path_role as legacy_classify_path_role,
    infer_prompt_intent as legacy_infer_prompt_intent,
    path_role_rank as legacy_path_role_rank,
)
from premode.write_policy import ADVISORY


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(repo / "pyproject.toml", "[project]\nname='core-fixture'\n")
    _write(repo / "src" / "auth.py", "def authenticate(token):\n    return bool(token)\n")
    _write(repo / "tests" / "test_auth.py", "def test_authenticate():\n    assert True\n")
    _write(repo / ".env", "TOKEN=do-not-route\n")
    return repo


def test_path_only_packet_is_exact_compact_and_deterministic() -> None:
    task = "Fix the auth flow exactly -- keep  spacing."
    items = [CorePath("src/auth.py"), CorePath("tests/test_auth.py"), CorePath("src/auth.py")]

    first = render_core_packet(task, items)
    second = render_core_packet(task, items)

    assert first == second
    assert first.count(task) == 1
    assert "PRIMARY" not in first
    assert "VERIFY" not in first
    assert "SUPPORT" not in first
    assert first.count("* src/auth.py") == 1
    assert first.endswith("Start with these files. Expand only when required by the task.\n")


def test_typed_context_packet_boundary_is_byte_equivalent_to_canonical_renderer() -> None:
    task = "Update parser.\nKeep the exact task text."
    items = [
        CorePath("src/parser.py", "primary"),
        CorePath("tests/test_parser.py", "verification"),
    ]

    typed = render_context_packet_v1(task, items)

    assert typed.rendered_packet == render_core_packet(task, items)
    assert typed.exact_task_length == len(task)


def test_typed_context_packet_boundary_accepts_canonical_empty_fallback() -> None:
    task = "Investigate the repository broadly."

    typed = render_context_packet_v1(task, [])

    assert typed.rendered_packet == render_core_packet(task, [])
    assert "No likely files met the confidence threshold." in typed.rendered_packet


def test_task_line_occurs_once_when_task_text_matches_a_selected_path() -> None:
    task = "src/auth.py"
    packet = render_core_packet(task, [CorePath("src/auth.py")])

    assert packet.count(task) == 1
    assert "* (same path as TASK)" in packet


def test_roles_empty_sections_and_anchor_cap() -> None:
    packet = render_core_packet(
        "Change authenticate and its test.",
        [
            CorePath("src/auth.py", role="primary", anchor="symbol=authenticate"),
            CorePath("tests/test_auth.py", role="verification", anchor="test_name=test_authenticate"),
        ],
    )

    assert "\nPRIMARY\n\n* src/auth.py :: symbol=authenticate" in packet
    assert "\nVERIFY\n\n* tests/test_auth.py :: test_name=test_authenticate" in packet
    assert "SUPPORT" not in packet
    assert packet.count(" :: ") == 2


def test_fallback_omits_empty_likely_files_section() -> None:
    packet = render_core_packet("Investigate the repository broadly.", [])

    assert "LIKELY FILES" not in packet
    assert "No likely files met the confidence threshold." in packet


def test_normal_pcodex_uses_canonical_renderer_and_excludes_credentials(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    task = "Change authenticate in src/auth.py and update its test."

    compiled = pcodex.compile_pcodex_packet(repo, task, write_policy=ADVISORY)
    packet = compiled["packet"]

    assert compiled["canonical_core_packet"] is True
    assert packet.startswith("TASK\n")
    assert packet.count(task) == 1
    assert "* src/auth.py" in packet
    assert ".env" not in packet
    assert "PREMODE_CONTEXT_PACKET" not in packet
    assert "audit" not in packet.casefold()
    assert "selection_lock_hash" not in packet
    assert "raw_prompt_sha256" not in packet


def test_normal_compile_does_not_invoke_experimental_selector(monkeypatch, tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    import premode.role_model as role_model

    def forbidden(*_args, **_kwargs):
        raise AssertionError("experimental selector entered normal production")

    monkeypatch.setattr(role_model, "dry_run_selector_candidate", forbidden)
    monkeypatch.setattr(role_model, "rank_intent_v2_paths", forbidden)

    compiled = pcodex.compile_pcodex_packet(
        repo,
        "Change authenticate in src/auth.py.",
        write_policy=ADVISORY,
    )
    assert compiled["packet"].startswith("TASK\n")


def test_primary_help_exposes_only_narrow_surfaces(capsys) -> None:
    try:
        pcodex._parser().parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    help_text = capsys.readouterr().out

    for command in ("setup", "status", "run", "review", "off", "cleanup", "uninstall", "doctor"):
        assert command in help_text
    for developer_surface in ("tune", "tuned", "mcp-server", "integrate", "plugin", "ui", "compile"):
        assert developer_surface not in help_text


def test_premode_compile_help_hides_packet_strategy_matrix(capsys) -> None:
    try:
        cli.build_parser().parse_args(["compile", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    help_text = capsys.readouterr().out

    assert "--packet-version" not in help_text
    assert "--packet-variant" not in help_text
    assert "--packet-strategy" not in help_text
    assert "--packet-mode" not in help_text
    assert "--tuning" not in help_text


def test_installed_entrypoint_targets_narrow_bootstrap() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'pcodex = "premode.pcodex_bootstrap:main"' in text


def test_normal_pcodex_startup_does_not_import_experiment_or_benchmark_modules() -> None:
    script = (
        "import sys; import premode.pcodex_bootstrap; "
        "print('\\n'.join(sorted(name for name in sys.modules if name.startswith('premode.'))))"
    )
    completed = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True, check=False)

    assert completed.returncode == 0
    loaded = set(completed.stdout.splitlines())
    assert "premode.benchmark" not in loaded
    assert "premode.live_token_harness" not in loaded
    assert "premode.live_ledger" not in loaded
    assert "premode.fixture" not in loaded
    assert "premode.stress" not in loaded
    assert "premode.role_model" not in loaded
    assert not any(name.startswith("premode.lab73") for name in loaded)


def test_setup_cli_uses_narrow_default(monkeypatch, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    captured = {}

    def fake_setup(root, **kwargs):
        captured.update({"root": root, **kwargs})
        return {"setup_status": "complete"}

    monkeypatch.setattr(pcodex, "setup", fake_setup)
    assert pcodex.main(["setup", "--repo-root", str(repo), "--json"]) == 0
    assert captured["skip_tune"] is True
    assert captured["no_mcp"] is True
    assert captured["real_codex_registration"] is False
    assert "complete" in capsys.readouterr().out


def test_hidden_isolated_setup_preserves_legacy_broad_workflow(monkeypatch, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    captured = {}

    def fake_setup(root, **kwargs):
        captured.update({"root": root, **kwargs})
        return {"setup_status": "complete"}

    monkeypatch.setattr(pcodex, "setup", fake_setup)
    assert pcodex.main(["setup", "--isolated", "--repo-root", str(repo), "--json"]) == 0
    assert captured["skip_tune"] is False
    assert captured["no_mcp"] is False
    assert captured["real_codex_registration"] is False
    assert "complete" in capsys.readouterr().out


def test_review_alias_uses_existing_review_engine(monkeypatch, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    captured = {}

    def fake_review(root, **kwargs):
        captured.update({"root": root, **kwargs})
        return {"status": "pass", "error": None}

    monkeypatch.setattr(pcodex, "review_patch", fake_review)
    assert pcodex.main(["review", "--repo-root", str(repo), "--since-compile", "--json"]) == 0
    assert captured["root"] == repo
    assert captured["since_compile"] is True
    assert '"status": "pass"' in capsys.readouterr().out


def test_role_core_matches_legacy_compatibility_projection() -> None:
    paths = [
        "src/main.py",
        "tests/test_main.py",
        "README.md",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        "examples/demo.ts",
        "vendor/generated.py",
    ]
    prompts = [
        "Fix the runtime behavior.",
        "Update the documentation without changing source code.",
        "Change project configuration.",
        "Add regression tests without changing production code.",
    ]
    for path in paths:
        assert classify_path_role(path).to_dict() == legacy_classify_path_role(path).to_dict()
    for prompt in prompts:
        current = infer_prompt_intent(prompt)
        legacy = legacy_infer_prompt_intent(prompt)
        assert current.to_dict() == legacy.to_dict()
        for path in paths:
            assert path_role_rank(path, current) == legacy_path_role_rank(path, legacy)


def test_normal_low_confidence_compile_can_render_path_only(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    original = compiler.locate_files

    def low_confidence(*args, **kwargs):
        result = original(*args, **kwargs)
        return replace(result, confidence="low")

    monkeypatch.setattr(compiler, "locate_files", low_confidence)
    compiled = pcodex.compile_pcodex_packet(repo, "Inspect authenticate.", write_policy=ADVISORY)
    packet = compiled["packet"]
    assert "LIKELY FILES" in packet
    assert "\nPRIMARY\n" in packet
    assert "\nVERIFY\n" in packet
    assert " :: " not in packet


def test_integrated_degraded_pcodex_uses_canonical_fallback(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    for index in range(80):
        _write(repo / "bulk" / f"file_{index:04d}.txt", f"item {index}\n")
    monkeypatch.setattr(compiler, "_LARGE_REPO_BROAD_DEGRADE_THRESHOLD", 50)
    task = "Inspect this repository and summarize the relevant surfaces."

    compiled = pcodex.compile_pcodex_packet(repo, task, write_policy=ADVISORY)

    assert compiled["compile_degraded"] is True
    assert compiled["compile_degraded_reason"] == "large_repo_budget_exceeded"
    assert compiled["packet"].splitlines().count(task) == 1
    assert "LIKELY FILES" not in compiled["packet"]
    assert compiled["packet"] == task
    assert compiled["production_ranking"]["routing_mode"] == "abstain"
    assert "No likely files met the confidence threshold." not in compiled["packet"]
    assert "large_repo_budget_exceeded" not in compiled["packet"]


def test_plugin_metadata_drift_reports_fixed_explicit_authority(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    resolved = SimpleNamespace(
        as_compile_kwargs=lambda: {
            "packet_version": "v5",
            "packet_variant": "ranked_paths",
            "packet_strategy": "ranked_paths",
        },
        as_dict=lambda: {
            "plugin_name": "literal_symbol",
            "packet_version": "v5",
            "packet_variant": "ranked_paths",
            "packet_strategy": "ranked_paths",
        },
    )
    monkeypatch.setattr(pcodex, "resolve_packet_plugin", lambda _name: resolved)

    compiled = pcodex.compile_pcodex_packet(repo, "Change authenticate.", write_policy=ADVISORY)

    assert compiled["route"] == "explicit_fixed_authority"
    assert "--plugin" not in compiled["premode_command"]
    start = compiled["premode_command"].index("--packet-version")
    assert compiled["premode_command"][start:start + 6] == [
        "--packet-version", "v5",
        "--packet-variant", "tool_assisted_anchors_internal",
        "--packet-strategy", "literal_symbol",
    ]


def test_compile_dry_run_reports_fixed_authority_on_plugin_metadata_drift(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    resolved = SimpleNamespace(
        as_compile_kwargs=lambda: {
            "packet_version": "v5",
            "packet_variant": "ranked_paths",
            "packet_strategy": "ranked_paths",
        }
    )
    monkeypatch.setattr(pcodex, "resolve_packet_plugin", lambda _name: resolved)

    assert pcodex.main(["compile", "Change authenticate.", "--dry-run", "--repo", str(repo)]) == 0
    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["route"] == "explicit_fixed_authority"
    assert "--plugin" not in payload["premode_command"]
    assert payload["fallback_reason"] == "plugin_alias_metadata_ignored_for_fixed_production_authority"
