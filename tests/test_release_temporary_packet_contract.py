from __future__ import annotations

from pathlib import Path

from premode import pcodex_bootstrap
from premode import pcodex_subagent


def test_subagent_transform_does_not_persist_shared_temp_packet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        pcodex_subagent.pcodex,
        "resolve_mode_state",
        lambda *_args, **_kwargs: {
            "configured_mode": "on",
            "effective_mode": "on",
            "state_status": "valid",
            "fallback": {},
            "tuning": {},
        },
    )
    monkeypatch.setattr(
        pcodex_subagent.pcodex,
        "record_runtime_telemetry",
        lambda *_args, **_kwargs: {"telemetry": {}},
    )

    result = pcodex_subagent.transform_subagent_prompt(
        "Fix app.py",
        tmp_path,
        compile_runner=lambda *_args, **_kwargs: {
            "packet": "TASK\nFix app.py\nLIKELY FILES\n\nPRIMARY\n\n* app.py\n",
            "route": "plugin_alias",
        },
    )

    assert result.transform_applied is True
    assert result.packet_path is None


def test_dry_run_source_has_no_persistent_temp_packet_writer() -> None:
    source = Path(pcodex_bootstrap.__file__).read_text(encoding="utf-8")
    subagent_source = Path(pcodex_subagent.__file__).read_text(encoding="utf-8")
    assert "pcodex_packet_" not in source
    assert "pcodex_subagent_packet_" not in subagent_source
    assert "NamedTemporaryFile" not in subagent_source
