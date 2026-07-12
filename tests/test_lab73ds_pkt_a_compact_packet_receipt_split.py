from __future__ import annotations

import json
from pathlib import Path

import premode.cli as cli_module
from premode.cli import build_parser, main
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


PROMPT = "Fix activity auth token handling in src/lib/token_source.py and src/app/api/activity/route.ts."


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _prepare(repo: Path) -> None:
    _write(
        repo / "src" / "lib" / "token_source.py",
        """
def load_activity_token(user_id):
    return f"token:{user_id}"

def normalize_activity_user(user_id):
    return str(user_id).strip()
""",
    )
    _write(
        repo / "src" / "app" / "api" / "activity" / "route.ts",
        """
import { loadActivityToken } from "../../../../lib/token_source"

export function GET(userId: string) {
  return loadActivityToken(userId)
}
""",
    )
    _write(
        repo / "tests" / "test_activity_token_source.py",
        """
from src.lib.token_source import load_activity_token

def test_activity_token_source():
    assert load_activity_token("abc") == "token:abc"
""",
    )
    _write(repo / ".env", "ACTIVITY_TOKEN=secret-value")
    _write(repo / "secrets.json", '{"activity_token": "secret-value"}')
    _write(repo / ".premode" / "pcodex_state.json", '{"secret": true}')
    init_project(repo)
    index_project(repo, "lite")


def _compile(repo: Path, *, packet_detail_mode: str | None = None) -> dict:
    kwargs = {
        "packet_version": "v5",
        "packet_variant": "tool_assisted_anchors_internal",
        "packet_strategy": "literal_symbol",
        "record_artifacts": False,
    }
    if packet_detail_mode:
        kwargs["packet_detail_mode"] = packet_detail_mode
    return compile_prompt(repo, PROMPT, "lite", **kwargs)


def _assert_no_verbose_diagnostics(packet: str) -> None:
    for text in (
        "anchors:",
        "selection_lock_hash",
        "policy_metadata",
        "decision_ledger",
        "support_relations",
        "forbidden_without_user_confirmation",
        "confidence",
        "warnings",
    ):
        assert text not in packet


def test_compact_and_selected_paths_only_split_model_packet_from_audit_receipt(repo: Path) -> None:
    _prepare(repo)

    full = _compile(repo)
    compact = _compile(repo, packet_detail_mode="compact")
    selected = _compile(repo, packet_detail_mode="selected_paths_only")

    assert full["packet"].startswith("PREMODE_CONTEXT_PACKET_V5")
    assert "COMPACT_PCODEX_V1" not in full["packet"]
    assert full["packet_detail_mode"] == "paths_only"
    assert full["packet_receipt_mode"] == "standard"

    assert compact["packet"].startswith("COMPACT_PCODEX_V1")
    assert compact["model_facing_packet_mode"] == "compact_pcodex_v1"
    assert compact["packet_detail_mode"] == "compact"
    assert compact["packet_receipt_mode"] == "sidecar"

    assert selected["packet"].startswith("SELECTED_PATHS_PCODEX_V1")
    assert selected["model_facing_packet_mode"] == "selected_paths_only_v1"
    assert selected["packet_detail_mode"] == "selected_paths_only"
    assert selected["selected_paths_only_first_class"] is True

    full_receipt = full["packet_audit_receipt"]
    compact_receipt = compact["packet_audit_receipt"]
    selected_receipt = selected["packet_audit_receipt"]

    assert compact_receipt["selected_paths"] == full_receipt["selected_paths"]
    assert selected_receipt["selected_paths"] == full_receipt["selected_paths"]
    assert compact_receipt["role_buckets"]["summary"] == full_receipt["role_buckets"]["summary"]
    assert selected_receipt["role_buckets"]["summary"] == full_receipt["role_buckets"]["summary"]
    assert compact_receipt["selection_lock_hash"] == full_receipt["selection_lock_hash"]
    assert selected_receipt["selection_lock_hash"] == full_receipt["selection_lock_hash"]
    assert compact_receipt["content_reads"] == full_receipt["content_reads"] == 0
    assert selected_receipt["content_reads"] == full_receipt["content_reads"] == 0

    selected_paths = set(full_receipt["selected_paths"])
    assert not ({"count", "items", "omitted_count"} & selected_paths)
    assert "src/lib/token_source.py" in selected_paths
    assert ".env" not in selected_paths
    assert "secrets.json" not in selected_paths
    assert ".premode/pcodex_state.json" not in selected_paths

    for packet in (compact["packet"], selected["packet"]):
        _assert_no_verbose_diagnostics(packet)
        assert ".env" not in packet
        assert "secrets.json" not in packet
        assert ".premode/pcodex_state.json" not in packet
        assert "secret-value" not in packet
        assert "src/lib/token_source.py" in packet

    assert compact_receipt["policy_metadata"]["forbidden_without_user_confirmation"]
    assert compact_receipt["selection_lock_hash"]
    assert compact_receipt["ranked_paths"]
    assert compact_receipt["packet_component_accounting"]["packet_byte_count"] == len(compact["packet"].encode("utf-8"))
    assert compact_receipt["packet_sha256"] == compact["compiled_packet_sha256"]
    assert selected_receipt["packet_component_accounting"]["packet_byte_count"] == len(selected["packet"].encode("utf-8"))
    assert not ({"count", "items", "omitted_count"} & set(compact_receipt["selected_paths"]))
    assert not ({"count", "items", "omitted_count"} & set(selected_receipt["selected_paths"]))

    assert len(compact["packet"].encode("utf-8")) <= int(len(full["packet"].encode("utf-8")) * 0.70)
    assert len(selected["packet"].encode("utf-8")) <= int(len(full["packet"].encode("utf-8")) * 0.60)
    assert compact_receipt["model_facing"] is False
    assert selected_receipt["model_facing"] is False

    boundary_prompt = PROMPT + " Do not edit .env or secrets.json."
    boundary_result = compile_prompt(
        repo,
        boundary_prompt,
        "lite",
        packet_version="v5",
        packet_variant="tool_assisted_anchors_internal",
        packet_strategy="literal_symbol",
        packet_detail_mode="compact",
        record_artifacts=False,
    )
    boundary_receipt = boundary_result["packet_audit_receipt"]
    assert boundary_prompt in boundary_result["packet"]
    assert not ({".env", "secrets.json"} & set(boundary_receipt["selected_paths"]))
    assert not ({".env", "secrets.json"} & set(boundary_receipt["ranked_paths"]))
    assert boundary_receipt["selected_sensitive_hits"] == []
    assert boundary_receipt["ranked_sensitive_hits"] == []


def test_compile_cli_exposes_compact_mode_and_saves_sidecar_receipt(repo: Path, monkeypatch, capsys) -> None:
    _prepare(repo)
    monkeypatch.chdir(repo)

    rc = main([
        "compile",
        PROMPT,
        "--profile",
        "lite",
        "--packet-variant",
        "tool_assisted_anchors_internal",
        "--packet-strategy",
        "literal_symbol",
        "--packet-mode",
        "compact",
        "--save",
        "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packet_detail_mode"] == "compact"
    assert payload["model_facing_packet_mode"] == "canonical_core_v1"
    assert payload["packet_audit_receipt"] == {}
    saved = payload["saved_artifacts"]
    assert saved["last_packet_audit_receipt_json"].endswith("last_packet_audit_receipt.json")
    receipt = json.loads((repo / ".premode" / "out" / "last_packet_audit_receipt.json").read_text(encoding="utf-8"))
    assert receipt == {}


def test_compile_and_benchmark_packet_mode_flags_imply_v5(repo: Path, monkeypatch, capsys) -> None:
    parser = build_parser()
    compile_args = parser.parse_args(["compile", PROMPT, "--packet-mode", "selected-paths-only"])
    benchmark_args = parser.parse_args(["benchmark", "--packet-mode", "compact"])

    assert compile_args.packet_version is None
    assert compile_args.packet_mode == "selected-paths-only"
    assert benchmark_args.packet_version is None
    assert benchmark_args.packet_mode == "compact"

    _prepare(repo)
    monkeypatch.chdir(repo)
    calls: list[dict] = []

    def fake_run_benchmark(repo_root: Path, **kwargs):
        calls.append({"repo_root": repo_root, **kwargs})
        return {"status": "ok"}

    monkeypatch.setattr(cli_module, "run_benchmark", fake_run_benchmark)
    for cli_mode, detail_mode in (("compact", "compact"), ("selected-paths-only", "selected_paths_only")):
        assert main(["benchmark", "--packet-mode", cli_mode, "--json"]) == 0
        json.loads(capsys.readouterr().out)
        assert calls[-1]["packet_version"] == "v5"
        assert calls[-1]["packet_detail_mode"] == detail_mode

    assert main(["benchmark", "--packet-version", "v3", "--packet-mode", "compact", "--json"]) == 2
    assert "requires --packet-version v5" in capsys.readouterr().err
