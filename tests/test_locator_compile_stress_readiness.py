from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_runner():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "locator_readiness_stress.py"
    spec = importlib.util.spec_from_file_location("locator_readiness_stress", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_lab_7_2e_compile_only_stress_readiness_suite_passes(tmp_path: Path) -> None:
    runner = _load_runner()

    results = runner.run_stress_suite(base_tmp=tmp_path)

    failures = {result.case: result.notes for result in results if result.result != "pass"}
    assert len(results) == 12
    assert not failures
    assert all(result.packet_token_count <= result.budget_report["hard_packet_token_budget"] for result in results)
