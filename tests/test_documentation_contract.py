from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_documentation import (
    _contained_regular_file,
    _fenced_blocks,
    _validate_cli_command,
    _validate_shell_command,
    validate_documentation,
)


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_documentation_contract_passes_without_execution() -> None:
    result = validate_documentation(ROOT)

    assert result["status"] == "passed", result["failures"]
    assert result["canonical_documents"] == 10
    assert result["shell_commands_checked"] > 0
    assert result["execution_performed"] is False


def test_documentation_contract_declares_exact_canonical_set_and_threshold_roles() -> None:
    manifest = json.loads((ROOT / "premode.product.json").read_text(encoding="utf-8"))
    contract = manifest["documentation_contract"]

    assert contract["canonical_docs"] == [
        "README.md",
        "docs/GETTING_STARTED.md",
        "docs/CODEX_INTEGRATION.md",
        "docs/OPENCLAW_INTEGRATION.md",
        "docs/TROUBLESHOOTING.md",
        "docs/PRIVACY_AND_SAFETY.md",
        "docs/KNOWN_LIMITATIONS.md",
        "docs/MIGRATION.md",
        "docs/ROLLBACK.md",
        "docs/UNINSTALL.md",
    ]
    assert contract["current_product_version"] == "0.3.0b1"
    assert contract["supported_codex_versions"] == ["0.143.x"]
    assert contract["declared_legacy_product_versions"] == ["0.2.6.24"]


def test_documentation_cli_validation_rejects_abbreviations_and_bad_semantics() -> None:
    assert _validate_cli_command(["pcodex", "status", "--advisory", "--json"]) == []
    assert _validate_cli_command(["pcodex", "doctor", "--strict", "--json"]) == []
    assert _validate_cli_command(["pcodex", "integrate", "codex", "--repair", "--dry-run"]) == []
    assert _validate_cli_command(["pcodex", "status", "--adv"])
    assert _validate_cli_command(["pcodex", "cleanup", "--dry-run"])
    assert _validate_cli_command(["pcodex", "integrate", "codex", "--uninstall", "--write"])
    assert _validate_cli_command(["pcodex", "integrate", "codex", "--status", "--migrate"])
    assert _validate_cli_command(["pcodex", "integrate", "codex", "--disable", "--with-mcp"])


def test_documentation_shell_validation_rejects_wrappers_compounds_and_typos() -> None:
    assert _validate_shell_command(["sudo", "pcodex", "status", "--adv"], ROOT)
    assert _validate_shell_command(["command", "pcodex", "status", "--adv"], ROOT)
    assert _validate_shell_command(["cd", "/tmp", "&&", "pcodex", "status", "--adv"], ROOT)
    assert _validate_shell_command(["pcodez", "status", "--adv"], ROOT)
    assert _validate_shell_command(["evil/python", "-mm", "pipp", "instal", "x"], ROOT)
    assert _validate_shell_command(["python3", "--definitely-not-a-real-flag"], ROOT)
    assert _validate_shell_command(["python3", "-c", 'import os; os.system("rm -rf / ")'], ROOT)
    assert _validate_shell_command(["export", "PATH=$HOME/.pcodex-alhpa/bin:$PATH"], ROOT)


def test_unclosed_fence_and_escaping_or_symlinked_docs_fail_closed(tmp_path: Path) -> None:
    try:
        _fenced_blocks("```console\npcodex status --adv\n")
    except ValueError as exc:
        assert "unclosed" in str(exc)
    else:
        raise AssertionError("unclosed fence was accepted")

    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "LINK.md").symlink_to(outside)
    for relative in ("../outside.md", "docs/LINK.md"):
        try:
            _contained_regular_file(root.resolve(), relative)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe path was accepted: {relative}")


def test_first_run_study_is_protocol_not_manufactured_evidence() -> None:
    protocol = (ROOT / "docs" / "FIRST_RUN_STUDY_PROTOCOL.md").read_text(encoding="utf-8")
    ledger = (ROOT / "docs" / "PRODUCT_READINESS_GATE_LEDGER.md").read_text(encoding="utf-8")

    assert "five testers" in protocol
    assert "under five minutes" in protocol
    assert "median under ten minutes" in protocol
    assert "remains external evidence debt" in protocol
    assert "human" in ledger.lower()
