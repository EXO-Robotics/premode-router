from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _subprocess_diagnostics(repo: Path, result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join([
        f"cwd={repo}",
        f"returncode={result.returncode}",
        f"stdout_tail={result.stdout[-2000:]}",
        f"stderr_tail={result.stderr[-2000:]}",
        f"premode_out_exists={(repo / '.premode' / 'out').exists()}",
        f"last_packet_exists={(repo / '.premode' / 'out' / 'last_packet.json').exists()}",
    ])


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def test_smoke_script_uses_portable_timeout_helper():
    script = (ROOT / "scripts" / "smoke_test.sh").read_text(encoding="utf-8")
    helper = ROOT / "scripts" / "run_with_timeout.py"
    assert helper.exists()
    assert "scripts/run_with_timeout.py" in script
    assert 'timeout 120 "$@"' not in script

    completed = subprocess.run(
        [sys.executable, str(helper), "--timeout", "5", "--", sys.executable, "-c", "print('ok')"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0


def test_no_install_pythonpath_module_detect_works():
    completed = subprocess.run(
        [sys.executable, "-m", "premode.cli", "detect", "--json"],
        cwd=ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == 3
    assert payload["active_project_kind"] == "python"


def test_review_patch_since_compile_end_to_end_cli_temp_git_repo(tmp_path: Path):
    repo = tmp_path / "review-e2e"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname='review-e2e'\nversion='0.1.0'\n[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")

    compile_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "premode.cli",
            "compile",
            "Fix src/app.py without expanding scope",
            "--profile",
            "lite",
            "--use-repo-map",
            "--cache-optimized",
            "--save",
            "--json",
        ],
        cwd=repo,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert compile_result.returncode == 0, _subprocess_diagnostics(repo, compile_result)
    assert (repo / ".premode" / "out" / "last_packet.json").exists()

    (repo / "src" / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    review_result = subprocess.run(
        [sys.executable, "-m", "premode.cli", "review-patch", "--since-compile", "--json"],
        cwd=repo,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert review_result.returncode == 0, _subprocess_diagnostics(repo, review_result)
    payload = json.loads(review_result.stdout)
    assert "src/app.py" in payload["changed_files"]
    assert payload["merge_readiness"] == "warning"
    assert payload["verification"]["verification_status"] == "missing_evidence"


def test_docs_v266_python_and_cache_kpi_clarity():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    benchmark = (ROOT / "docs" / "BENCHMARK.md").read_text(encoding="utf-8")
    assert "Python >=3.11 is required" in readme
    assert "tomllib requires Python 3.11+" in readme
    assert "PYTHONPATH=src python -m premode.cli detect --json" in readme
    assert "console scripts like `premode` and `pcodex` require editable install" in readme
    assert "Estimated savings compares the compiled packet to the eligible repo surface" in readme
    assert "Cacheable-prefix percent measures how much of the remaining packet is positioned for provider prefix caching" in readme
    assert "total repo-token savings" in benchmark
    assert "cacheable-prefix percent" in benchmark
    assert "dynamic-suffix percent" in benchmark
