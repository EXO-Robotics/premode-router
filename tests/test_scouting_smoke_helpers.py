from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "scouting_smoke.py"
SPEC = importlib.util.spec_from_file_location("scouting_smoke", SCRIPT)
assert SPEC and SPEC.loader
scouting_smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scouting_smoke)


def test_token_usage_aggregates_turns() -> None:
    run = {
        "turns": [
            {"response": {"usage": {"prompt_tokens": 10, "completion_tokens": 2}}},
            {"response": {"usage": {"prompt_tokens": 15, "completion_tokens": 3}}},
        ]
    }
    assert scouting_smoke.token_usage(run) == {"input_tokens": 25, "output_tokens": 5, "total_tokens": 30}


def test_smoke_spans_four_repositories_and_classes() -> None:
    assert len(scouting_smoke.SMOKE_TASK_IDS) == 4
    assert len(set(value.split("-t", 1)[0] for value in scouting_smoke.SMOKE_TASK_IDS)) == 4
    assert scouting_smoke.ARMS == ("STANDARD", "B0")
