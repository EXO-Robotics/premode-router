from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile
import io

import pytest

from scripts.check_public_hygiene import scan
from scripts.compare_release_artifacts import compare
from scripts.build_release_artifacts import (
    build,
    require_probe_passed,
    run_json_probe,
    persist_lifecycle_probe,
    validate_archive_content,
    validate_archive_structure,
    validate_names,
    validate_required_plugin_resources,
    validate_sdist_names,
    validated_python_interpreter,
    write_smoke_fixture,
    write_release_evidence,
    write_tester_bundle,
)


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


def test_release_allowlist_requires_every_canonical_plugin_resource() -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    required = policy["plugin_allowed_members"]
    wheel_names = [
        "premode_router-0.3.0b1.data/data/share/premode-router/plugins/pcodex/" + item
        for item in required
    ]
    sdist_names = ["premode_router-0.3.0b1/plugins/pcodex/" + item for item in required]
    assert validate_required_plugin_resources(wheel_names, policy, archive_kind="wheel") == []
    assert validate_required_plugin_resources(sdist_names, policy, archive_kind="sdist") == []
    assert validate_required_plugin_resources(wheel_names[1:], policy, archive_kind="wheel") == [
        f"missing_plugin_resource:{required[0]}"
    ]


def test_builder_requires_an_absolute_validated_python_interpreter() -> None:
    try:
        validated_python_interpreter("python3")
    except RuntimeError as exc:
        assert "absolute" in str(exc)
    else:
        raise AssertionError("relative interpreter unexpectedly accepted")


def test_builder_refuses_to_skip_sdist_qualification(tmp_path: Path) -> None:
    try:
        build("HEAD", tmp_path / "out", python=str(Path(sys.executable).resolve()), with_sdist=False)
    except RuntimeError as exc:
        assert "wheel and sdist" in str(exc)
    else:
        raise AssertionError("builder unexpectedly permitted wheel-only qualification")


def test_failed_json_probe_preserves_structured_receipts(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text('import json; print(json.dumps({"schema_version":"fixture.v1","passed":False})); raise SystemExit(1)\n')
    output = tmp_path / "evidence"
    payload, returncode = run_json_probe(
        str(Path(sys.executable).resolve()),
        str(probe), output=output, label="expected-failure", cwd=tmp_path, env=dict(os.environ),
    )
    assert returncode == 1
    assert payload["passed"] is False
    assert json.loads((output / "private-receipts/probe-execution/expected-failure.json").read_text())["payload"] == payload
    assert json.loads((output / "receipts/probe-execution/expected-failure.json").read_text())["payload_passed"] is False
    try:
        require_probe_passed("fixture", payload, returncode)
    except RuntimeError as exc:
        assert "structured evidence" in str(exc)
    else:
        raise AssertionError("failed probe unexpectedly accepted")


def test_tester_bundle_preserves_resolver_executable_mode(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "fixture.whl").write_bytes(b"wheel")
    output = tmp_path / "out"
    output.mkdir()
    bundle = write_tester_bundle(ROOT, output, artifacts)
    with zipfile.ZipFile(bundle) as archive:
        resolver = archive.getinfo("plugins/pcodex/skills/pcodex/bin/resolve-pcodex.sh")
        skill = archive.getinfo("plugins/pcodex/skills/pcodex/SKILL.md")
    assert resolver.external_attr >> 16 == 0o755
    assert skill.external_attr >> 16 == 0o644


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


def test_tester_bundle_scans_nested_members_not_opaque_archive_bytes(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    nested_bytes = io.BytesIO()
    with zipfile.ZipFile(nested_bytes, "w", compression=zipfile.ZIP_STORED) as nested:
        # The identity-like string exists only in container metadata. Artifact
        # member names are validated separately; content scanning must inspect
        # the clean payload rather than treating compressed bytes as text.
        nested.writestr("metadata/person" + "@private.example", b"clean payload")
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as outer:
        outer.writestr("artifacts/fixture.zip", nested_bytes.getvalue())

    assert validate_archive_content(bundle, policy) == []

    leaking_bytes = io.BytesIO()
    with zipfile.ZipFile(leaking_bytes, "w") as nested:
        nested.writestr("payload.txt", b"person" + b"@private.example")
    with zipfile.ZipFile(bundle, "w") as outer:
        outer.writestr("artifacts/fixture.zip", leaking_bytes.getvalue())
    assert any(item.startswith("prohibited_email:") for item in validate_archive_content(bundle, policy))


def test_archive_structure_rejects_traversal_links_and_resource_exhaustion(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", b"escape")
        link = zipfile.ZipInfo("link")
        link.external_attr = (0o120777 << 16)
        archive.writestr(link, b"target")
        archive.writestr("large.txt", b"x" * (1024 * 1024 + 1), compress_type=zipfile.ZIP_DEFLATED)
    strict = dict(policy)
    strict["archive_limits"] = {
        "max_entries": 2,
        "max_member_uncompressed_bytes": 1024,
        "max_total_uncompressed_bytes": 2048,
        "max_compression_ratio": 2.0,
    }

    failures = validate_archive_structure(archive_path, strict)

    assert any(item.startswith("unsafe_archive_path:") for item in failures)
    assert any(item.startswith("archive_link_member:") for item in failures)
    assert any(item.startswith("archive_entry_limit:") for item in failures)
    assert any(item.startswith("archive_member_size:") for item in failures)
    assert any(item.startswith("archive_compression_ratio:") for item in failures)
    assert any(item.startswith("archive_total_size:") for item in failures)


def test_archive_structure_rejects_tar_special_members(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    archive_path = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "target"
        archive.addfile(link)

    assert any(
        item.startswith("archive_special_member:link")
        for item in validate_archive_structure(archive_path, policy)
    )


def test_tar_validation_streams_without_getmembers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    policy["archive_limits"]["max_entries"] = 2
    archive_path = tmp_path / "bounded.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for index in range(3):
            info = tarfile.TarInfo(f"file-{index}.txt")
            payload = f"value-{index}".encode()
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(
        tarfile.TarFile,
        "getmembers",
        lambda _self: pytest.fail("unbounded getmembers must not be used"),
    )
    failures = validate_archive_structure(archive_path, policy)
    content_failures = validate_archive_content(archive_path, policy)

    assert any(item.startswith("archive_entry_limit:") for item in failures)
    assert any(item.startswith("archive_entry_limit:") for item in content_failures)


def test_tar_validation_stops_at_first_declared_resource_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    policy["archive_limits"]["max_member_uncompressed_bytes"] = 8
    policy["archive_limits"]["max_total_uncompressed_bytes"] = 16
    archive_path = tmp_path / "bounded.tar.gz"
    archive_path.write_bytes(b"fixture")

    class SentinelTar:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            first = tarfile.TarInfo("oversized.bin")
            first.size = 9
            yield first
            pytest.fail("tar validation advanced after the declared member limit")

        def extractfile(self, _item):
            pytest.fail("oversized tar member must not be read")

    monkeypatch.setattr(tarfile, "open", lambda *_args, **_kwargs: SentinelTar())

    structure_failures = validate_archive_structure(archive_path, policy)
    content_failures = validate_archive_content(archive_path, policy)

    assert any(item.startswith("archive_member_size:") for item in structure_failures)
    assert any(item.startswith("archive_resource_limit:") for item in content_failures)


def test_archive_structure_rejects_duplicates_and_casefold_collisions(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())
    archive_path = tmp_path / "collisions.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("safe/name.txt", b"one")
        archive.writestr("safe/name.txt", b"two")
        archive.writestr("SAFE/NAME.TXT", b"three")

    failures = validate_archive_structure(archive_path, policy)

    assert any(item.startswith("archive_duplicate_member:") for item in failures)
    assert any(item.startswith("archive_casefold_collision:") for item in failures)


@pytest.mark.parametrize("name", ["../escape", "../../etc/passwd", "/absolute", "C:/absolute"])
def test_archive_name_validation_does_not_strip_unsafe_prefixes(name: str) -> None:
    policy = json.loads((ROOT / "release/artifact-allowlist.json").read_text())

    failures = validate_names([name], allowed_prefixes=[], policy=policy)

    assert any(item.startswith("unsafe_path:") for item in failures)


def test_release_evidence_emits_sbom_provenance_and_qualification(tmp_path: Path) -> None:
    inventory = [
        {
            "file": "artifacts/fixture.whl",
            "sha256": "a" * 64,
            "size": 123,
            "members": ["premode/__init__.py"],
        },
        {
            "file": "artifacts/fixture.tar.gz",
            "sha256": "c" * 64,
            "size": 456,
            "members": ["fixture/src/premode/__init__.py"],
        },
    ]
    installed = {
        "wheel_lifecycle": {"passed": True},
        "sdist_lifecycle": {"passed": True},
        "wheel_no_write": {"passed": True},
        "sdist_no_write": {"passed": True},
        "wheel_codex_plugin": {"passed": True, "codex_version": "0.143.0"},
        "sdist_codex_plugin": {"passed": True, "codex_version": "0.143.0"},
        "upgrade_rollback": {
            "passed": True,
            "failed_upgrade_post_mutation_rollback": {"passed": True},
            "unsupported_downgrade_fail_closed": True,
        },
    }

    write_release_evidence(
        tmp_path,
        schema_root=ROOT / "schemas",
        commit_sha="b" * 40,
        evidence_timestamp="2026-07-13T00:00:00Z",
        product_version="0.3.0b1",
        python=str(Path(sys.executable)),
        inventory=inventory,
        install_smoke=installed,
        policy_hashes={"release/artifact-allowlist.json": "d" * 64},
        wheel_sdist_parity={
            "passed": True,
            "comparison": "normalized_member_sha256_excluding_record",
            "direct_wheel_sha256": "e" * 64,
            "sdist_rebuilt_wheel_sha256": "f" * 64,
            "normalized_member_count": 12,
        },
    )

    sbom = json.loads((tmp_path / "release/SBOM.cyclonedx.json").read_text())
    provenance = json.loads((tmp_path / "release/provenance.intoto.json").read_text())
    qualification = json.loads((tmp_path / "receipts/qualification-summary.json").read_text())
    assert sbom["bomFormat"] == "CycloneDX"
    assert provenance["predicateType"] == "https://slsa.dev/provenance/v1"
    assert qualification["status"] == "passed"
    assert qualification["wheel_sdist_parity_evidence"]["passed"] is True
    assert qualification["artifacts"][0]["digest"]["sha256"] == "a" * 64
    assert qualification["public_registry_published"] is False


def test_public_lifecycle_summary_omits_per_run_identifiers(tmp_path: Path) -> None:
    operation_id = "8ba874a9" + "-d287-47da-a6f3-d345cedd7244"
    summary = persist_lifecycle_probe(
        tmp_path,
        "wheel",
        {
            "schema_version": "pcodex.installed-lifecycle-probe.v1",
            "passed": True,
            "receipts": {
                "schemas_validated": True,
                "repair_public": {"operation_id": operation_id},
            },
            "full_cycle": {
                "install": "installed",
                "status_installed": {
                    "schema_version": "pcodex.lifecycle-status.v1",
                    "state": "healthy_installation",
                    "readiness": "READY",
                    "recommended_action": "pcodex status --advisory",
                    "exit_code": 0,
                    "repair_plan": {
                        "ownership_id": operation_id,
                        "authority_receipt_hash": "a" * 64,
                    },
                },
            },
        },
    )

    assert summary["receipt_evidence"]["public_receipt_types"] == ["repair_public"]
    public_text = (tmp_path / "receipts/installed-lifecycle-wheel.json").read_text()
    assert operation_id not in public_text
    assert "ownership_id" not in public_text
    assert "authority_receipt_hash" not in public_text
    assert summary["full_cycle"]["status_installed"]["readiness"] == "READY"
    assert operation_id in (tmp_path / "private-receipts/lifecycle/wheel.json").read_text()


def test_release_artifact_reproducibility_requires_six_identical_matrix_receipts(
    tmp_path: Path,
) -> None:
    inventory = [
        {"file": "artifacts/product.whl", "sha256": "a" * 64},
        {"file": "artifacts/product.tar.gz", "sha256": "b" * 64},
    ]
    for index in range(6):
        receipt = tmp_path / f"cell-{index}" / "receipts/artifact-inventory.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps(inventory), encoding="utf-8")

    result = compare(tmp_path)

    assert result["passed"] is True
    assert result["matrix_receipts"] == 6


def test_release_artifact_reproducibility_rejects_empty_inventories(tmp_path: Path) -> None:
    for index in range(6):
        receipt = tmp_path / f"cell-{index}" / "receipts/artifact-inventory.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one wheel and one sdist"):
        compare(tmp_path)


def test_upgrade_smoke_fixture_contains_source_and_validation(tmp_path: Path) -> None:
    write_smoke_fixture(tmp_path)

    assert (tmp_path / "src/app.py").is_file()
    assert (tmp_path / "tests/test_app.py").is_file()
    authority = json.loads((ROOT / "release/previous-supported.json").read_text())
    assert authority["previous_version"] == "0.2.6.24"
    assert authority["previous_commit"] == "b9aede455c8d49217ef0a67e8dec0c8cf2c565a6"
