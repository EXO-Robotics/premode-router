from __future__ import annotations

import json
from pathlib import Path


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
