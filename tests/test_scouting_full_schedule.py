from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "scouting_full.py"
SPEC = importlib.util.spec_from_file_location("scouting_full", SCRIPT)
assert SPEC and SPEC.loader
scouting_full = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scouting_full)


def test_full_schedule_is_paired_blocked_and_deterministic() -> None:
    tasks = {
        f"repo-{repository:03d}-g2-t{task_index:02d}": {
            "task_class": f"class-{task_index}",
            "repository_id": f"repo-{repository:03d}",
        }
        for repository in range(1, 8)
        for task_index in range(1, 6)
    }
    first = scouting_full.build_schedule(tasks, 20260713, 3)
    second = scouting_full.build_schedule(tasks, 20260713, 3)
    assert first == second
    assert len(first) == 70
    assert {item["planned_worker_slot"] for item in first} == {0, 1, 2}
    for task_id in tasks:
        assert sorted(item["arm"] for item in first if item["task_id"] == task_id) == ["B0", "STANDARD"]
    for block in range(1, 6):
        assert len({item["task_class"] for item in first if item["block"] == block}) == 1
