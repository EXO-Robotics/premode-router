from __future__ import annotations

import json
from pathlib import Path
import subprocess
import zipfile

from scripts.check_public_hygiene import scan
from scripts.build_release_artifacts import validate_archive_content, validate_names, validate_sdist_names


ROOT = Path(__file__).resolve().parents[1]


def test_evaluation_holdout_is_unpopulated_and_answer_free() -> None:
    holdout = json.loads((ROOT / "evaluation/corpora/final-holdout.stub.json").read_text())
    assert holdout["populated"] is False
    assert holdout["contains_prompts_or_expected_answers"] is False
    assert "tasks" not in holdout


def test_protocol_quality_blocks_efficiency_promotion() -> None:
    protocol = json.loads((ROOT / "evaluation/protocol-v1.json").read_text())
    assert protocol["final_holdout_execution"] == "prohibited_in_this_workload"
    assert protocol["quality"]["promotion_rule"].startswith("quality_noninferior")
    assert protocol["token_goal"]["universal_invariant"] is False


def test_release_allowlist_is_default_deny_for_wheels() -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    assert policy["wheel_allowed_prefixes"] == ["premode/", "premode_router-"]
    assert ".git" in policy["prohibited_parts"]
    assert ".premode" in policy["prohibited_parts"]
    assert "premode/lab73*.py" in policy["wheel_prohibited_globs"]
    assert "/private/tmp/" in policy["content_prohibited_patterns"]
    assert "premode/compiler.py" in policy["wheel_allowed_members"]
    assert "premode/no_write.py" in policy["wheel_allowed_members"]
    assert validate_names(["premode/private_dump.py"], allowed_prefixes=policy["wheel_allowed_prefixes"], policy=policy, exact_wheel=True) == ["unexpected_wheel_member:premode/private_dump.py"]


def test_release_allowlist_is_default_deny_for_sdist_source_members() -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    prefix = "premode_router-0.3.0b1/"
    assert validate_sdist_names([prefix + "src/premode/no_write.py"], policy) == []
    assert validate_sdist_names([prefix + "src/app.py"], policy) == ["unexpected_sdist_member:src/app.py"]
    assert validate_sdist_names([prefix + "src/premode/private_dump.py"], policy) == ["unexpected_sdist_member:src/premode/private_dump.py"]
    assert validate_sdist_names([prefix + "plugins/pcodex/accidental.txt"], policy) == [
        "unexpected_sdist_member:plugins/pcodex/accidental.txt"
    ]
    accidental_wheel = "premode_router-0.3.0b1.data/data/share/premode-router/plugins/pcodex/accidental.txt"
    assert validate_names(
        [accidental_wheel], allowed_prefixes=policy["wheel_allowed_prefixes"], policy=policy, exact_wheel=True
    ) == [f"unexpected_wheel_member:{accidental_wheel}"]


def test_source_distribution_prunes_test_and_release_script_trees() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "prune tests" in manifest
    assert "prune scripts" in manifest


def test_public_repository_hygiene_guard_passes() -> None:
    result = scan(ROOT)
    assert result["passed"], result["failures"]


def test_hygiene_scans_tests_and_detector_files_without_whole_file_exemptions(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    paths = {
        "tests/test_fixture.py": "TO" + "KEN=realistic_unapproved_value\n",
        "src/premode/redaction.py": "REAL = 'ghp_" + "1234567890abcdefghijklmnop'\n",
        "docs/leaks.txt": "\n".join([
            "sk" + "-abcdefghijklmnopqrst",
            "Bearer" + " abcdefghijklmnopqrst",
            "-----BEGIN ENCRYPTED " + "PRIVATE KEY-----",
            "git" + "@github.com:private-org/private-repo.git",
        ]),
    }
    for rel, content in paths.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)

    result = scan(tmp_path)

    assert result["passed"] is False
    assert any("tests/test_fixture.py" in failure for failure in result["failures"])
    assert any("src/premode/redaction.py" in failure for failure in result["failures"])
    assert sum("docs/leaks.txt" in failure for failure in result["failures"]) >= 4


def test_artifact_exact_signature_allowance_does_not_exempt_member(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    wheel = tmp_path / "fixture.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "premode/redaction.py",
            'PATTERN = r"github_' + 'pat_[A-Za-z0-9_]{20,}"\nREAL = "github_' + 'pat_1234567890abcdefghijklmnop"\n',
        )

    failures = validate_archive_content(wheel, policy)

    assert any(item.startswith("prohibited_content:") for item in failures)
    assert any(item.startswith("prohibited_secret:") for item in failures)


def test_artifact_scanner_covers_private_identity_categories(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    wheel = tmp_path / "leaks.whl"
    payload = "\n".join([
        "sk" + "-abcdefghijklmnopqrst",
        "xoxb" + "-1234567890-abcdefghij",
        "eyJ" + "abcdefghijkl.abcdefghijk.abcdefghijkl",
        "Bearer" + " abcdefghijklmnopqrst",
        "-----BEGIN ENCRYPTED " + "PRIVATE KEY-----",
        "person" + "@private-company.example",
        "git" + "@github.com:private-org/private-repo.git",
        "https://service" + ".internal/api",
        "123e4567" + "-e89b-12d3-a456-426614174000",
    ])
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("premode/leaks.py", payload)

    failures = validate_archive_content(wheel, policy)

    assert any(item.startswith("prohibited_secret:") for item in failures)
    assert any(item.startswith("prohibited_email:") for item in failures)
    assert any(item.startswith("prohibited_private_network:") for item in failures)
    assert any(item.startswith("prohibited_system_id:") for item in failures)


def test_artifact_exact_signature_allowance_handles_sdist_prefix_without_hiding_secret(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "premode_router-0/src/premode/redaction.py",
            'PATTERN = r"github_' + 'pat_[A-Za-z0-9_]{20,}"\nREAL = "github_' + 'pat_1234567890abcdefghijklmnop"\n',
        )

    failures = validate_archive_content(archive, policy)

    assert any(item.startswith("prohibited_content:") for item in failures)
    assert any(item.startswith("prohibited_secret:") for item in failures)
