from __future__ import annotations

import json
from pathlib import Path


CASES = json.loads((Path(__file__).parent / "cases" / "cases.json").read_text())


def test_quality_benchmark_contains_exactly_30_real_maker_tasks() -> None:
    assert len(CASES) == 30
    assert len({case["name"] for case in CASES}) == 30


def test_quality_benchmark_covers_polish_english_and_failure_safety() -> None:
    names = {case["name"] for case in CASES}
    categories = {case["category"] for case in CASES}
    fixture_kinds = {case["fixture"]["kind"] for case in CASES}

    assert any("polish" in name for name in names)
    assert "ambiguity" in categories
    assert {"flagship", "template", "stl_grid_plate"}.issubset(fixture_kinds)
    assert sum(bool(case.get("expected_no_destructive_calls")) for case in CASES) >= 3


def test_local_benchmark_cases_have_zero_cost_contracts() -> None:
    local_cases = [case for case in CASES if case.get("expected_model") == "local"]
    assert len(local_cases) >= 8
    for case in local_cases:
        assert "update_parameter" in case.get("expected_tools_called_any", [])
