"""Eval suite for the v2 (code-driven) chat agent.

Each case loads a fixture (flagship design or pre-built STL plate), fires
one chat turn, and asserts on tool call shape + (optional) mesh-hash
change. Skipped wholesale without ``ANTHROPIC_API_KEY``.

Approximate cost: varies by model and prompt cache. The suite prints exact token
usage per turn; run it deliberately, not as part of the free unit-test lane.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from .checks import run_geometry_checks


CASES_PATH = Path(__file__).parent / "cases" / "cases.json"
EVAL_BASE_URL = os.getenv("PULSAI_EVAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; skipping live v2 eval suite.",
)


def _load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text())


@pytest.fixture(scope="session")
def grid_plate_stl(tmp_path_factory) -> Path:
    """Build a small STL fixture once per session and reuse it.

    80×60×8 plate with a 4×3 grid of 8 mm-diameter holes — exactly the same
    shape used in the manual smoke tests so eval signal lines up with
    handcrafted expectations.
    """
    from build123d import (
        BuildPart,
        Box,
        Cylinder,
        GridLocations,
        Mode,
        Align,
        export_stl,
    )

    with BuildPart() as p:
        Box(80, 60, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with GridLocations(20, 15, 4, 3):
            Cylinder(
                radius=4,
                height=10,
                mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
            )

    out = tmp_path_factory.mktemp("eval_v2") / "grid_plate.stl"
    export_stl(p.part, str(out))
    return out


def _seed_design_from_fixture(fixture: dict, grid_plate_stl: Path) -> str:
    """Create a Design and return its id."""
    import requests

    if fixture["kind"] == "flagship":
        r = requests.post(
            f"{EVAL_BASE_URL}/design/flagship/fork",
            json={"flagship_id": fixture["id"]},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["design_id"]
    if fixture["kind"] == "template":
        r = requests.post(
            f"{EVAL_BASE_URL}/design/create",
            json={"template_id": fixture["id"], "name": f"Eval: {fixture['id']}", "process": "fdm"},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["design_id"]
    if fixture["kind"] == "stl_grid_plate":
        with open(grid_plate_stl, "rb") as fh:
            r = requests.post(
                f"{EVAL_BASE_URL}/design/import-stl",
                files={"model": ("grid_plate.stl", fh, "application/sla")},
                data={"process": "fdm"},
                timeout=120,
            )
        r.raise_for_status()
        return r.json()["design_id"]
    raise AssertionError(f"unknown fixture kind: {fixture['kind']}")


def _stream_one_turn(design_id: str, message: str) -> dict:
    """Run one chat turn and return parsed events + mesh hash before/after."""
    import requests

    before = requests.get(f"{EVAL_BASE_URL}/design/{design_id}").json()
    before_hash = (before.get("latest_build") or {}).get("mesh_hash")

    resp = requests.post(
        f"{EVAL_BASE_URL}/design/{design_id}/chat",
        json={"message": message},
        stream=True,
        timeout=(30, 600),
    )
    resp.raise_for_status()
    buf = ""
    for raw in resp.iter_lines(decode_unicode=False):
        if raw is None:
            continue
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        buf += line + "\n"

    events: list[tuple[str, dict]] = []
    for blk in buf.split("\n\n"):
        ev = data = ""
        for ln in blk.split("\n"):
            if ln.startswith("event:"):
                ev = ln[6:].strip()
            elif ln.startswith("data:"):
                data += ln[5:].strip()
        if data:
            try:
                events.append((ev, json.loads(data)))
            except Exception:
                pass

    after = requests.get(f"{EVAL_BASE_URL}/design/{design_id}").json()
    after_hash = (after.get("latest_build") or {}).get("mesh_hash")

    return {
        "events": events,
        "before_mesh_hash": before_hash,
        "after_mesh_hash": after_hash,
        "after_build": after.get("latest_build") or {},
    }


@pytest.mark.parametrize(
    "case", _load_cases(), ids=lambda c: c["name"]
)
def test_eval_v2_case(case: dict, grid_plate_stl: Path) -> None:
    design_id = _seed_design_from_fixture(case["fixture"], grid_plate_stl)
    try:
        out = _stream_one_turn(design_id, case["user_message"])
    finally:
        import requests

        requests.delete(f"{EVAL_BASE_URL}/design/{design_id}", timeout=30)

    successful_tools = [
        d.get("name")
        for ev, d in out["events"]
        if ev == "tool_call_end" and not d.get("is_error")
    ]
    failed_tools = [
        d.get("name")
        for ev, d in out["events"]
        if ev == "tool_call_end" and d.get("is_error")
    ]
    assistant_text = "".join(
        d.get("text", "") for ev, d in out["events"] if ev == "assistant_text"
    ).lower()
    final = next((d for ev, d in out["events"] if ev == "turn_end"), {})

    if "expected_tools_called_any" in case:
        assert any(t in successful_tools for t in case["expected_tools_called_any"]), (
            f"expected one of {case['expected_tools_called_any']} to succeed; "
            f"got successful={successful_tools} failed={failed_tools}"
        )

    if case.get("expected_mesh_hash_changes"):
        assert (
            out["before_mesh_hash"] != out["after_mesh_hash"]
        ), (
            f"Expected mesh hash to change but it stayed at "
            f"{out['before_mesh_hash']!r}. The agent reported edits but "
            f"geometry did not move — silent no-op risk."
        )

    if case.get("expected_clarifying_question"):
        assert "?" in assistant_text, (
            f"Expected the agent to ask a clarifying question (no '?' in reply): "
            f"{assistant_text[:200]!r}"
        )

    if case.get("checks"):
        failures = run_geometry_checks(out["after_build"], case["checks"])
        assert not failures, "; ".join(failures)

    if case.get("expected_no_destructive_calls"):
        destructive = [
            t for t in successful_tools
            if t in {
                "update_parameter",
                "replace_feature",
                "append_feature",
                "rewrite_design",
                "mesh_modify_holes",
                "mesh_subtract_primitive",
                "mesh_add_primitive",
                "mesh_offset_surface",
                "mesh_split_at_plane",
                "mesh_mirror",
                "mesh_smooth",
                "mesh_repair",
            }
        ]
        assert not destructive, (
            f"No destructive edits expected, but observed: {destructive}"
        )

    # Cost ceilings
    in_max = case.get("max_input_tokens", 30000)
    out_max = case.get("max_output_tokens", 4000)
    assert (
        int(final.get("input_tokens", 0)) <= in_max
    ), f"input tokens {final.get('input_tokens')} exceed cap {in_max}"
    assert (
        int(final.get("output_tokens", 0)) <= out_max
    ), f"output tokens {final.get('output_tokens')} exceed cap {out_max}"
