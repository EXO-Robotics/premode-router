from __future__ import annotations

from pathlib import Path

import pytest

from premode import cli
from premode import bounded_mcp_runtime
from premode import pcodex_mcp
from premode import pcodex_mcp_server


def test_pcodex_main_mcp_server_routes_to_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 17

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("pcodex mcp-server must not route to Codex wrapper"))

    assert cli.pcodex_main(["mcp-server"]) == 17
    assert calls == [["mcp-server"]]


def test_pcodex_main_mcp_server_does_not_append_codex_exec_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        seen.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("unexpected Codex execution wrapper route"))

    assert cli.pcodex_main(["mcp-server"]) == 0
    assert seen == [["mcp-server"]]
    assert "--execute" not in seen[0]
    assert "--output-last-message" not in seen[0]


def test_pcodex_main_mcp_server_help_routes_to_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("mcp-server --help must not launch Codex wrapper"))

    assert cli.pcodex_main(["mcp-server", "--help"]) == 0
    assert calls == [["mcp-server", "--help"]]


@pytest.mark.parametrize("command", ["install", "doctor", "status", "on", "off", "tuned"])
def test_existing_bootstrap_commands_still_route_to_bootstrap(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail(f"{command} must stay on bootstrap route"))

    assert cli.pcodex_main([command]) == 0
    assert calls == [[command]]


@pytest.mark.parametrize(
    "argv",
    [
        ["compile", "Fix completion", "--dry-run"],
        ["run", "Fix completion", "--dry-run"],
    ],
)
def test_compile_and_run_bootstrap_behavior_remains_unchanged(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_bootstrap(passed: list[str] | None = None) -> int:
        calls.append(list(passed or []))
        return 0

    monkeypatch.setattr("premode.pcodex_bootstrap.main", fake_bootstrap)
    monkeypatch.setattr(cli, "main", lambda wrapper_argv=None: pytest.fail("compile/run should stay on bootstrap route"))

    assert cli.pcodex_main(argv) == 0
    assert calls == [argv]


def test_non_command_pcodex_input_fails_closed_instead_of_using_codex_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "main", lambda argv=None: pytest.fail("pcodex shorthand must not route to Codex wrapper"))

    assert cli.pcodex_main(["Inspect hello.txt", "--dry-run", "--no-save"]) != 0


def test_pcodex_mcp_server_registered_command_string_is_stable() -> None:
    assert ["pcodex", "mcp-server"] == ["pcodex", "mcp-server"]


def test_mcp_server_source_remains_stdio_only_and_no_secret_dump() -> None:
    source = "\n".join(
        Path(module.__file__).read_text(encoding="utf-8")
        for module in (pcodex_mcp_server, bounded_mcp_runtime)
    )

    assert "sys.stdin" in source
    assert "sys.stdout" in source
    assert "socket" not in source
    assert "http.server" not in source
    assert "os.environ" not in source


def test_mcp_transform_source_does_not_launch_codex() -> None:
    source = Path(pcodex_mcp.__file__).read_text(encoding="utf-8")

    assert "run_codex" not in source
    assert "build_codex_invocation" not in source
