"""End-to-end eval suite for the chat agent.

Each case spins up a fresh workspace seeded from a template, fires one chat
turn against the real Anthropic API, and asserts on the tool calls and the
resulting feature tree.

Skipped wholesale if ``ANTHROPIC_API_KEY`` is not set, so unit-test CI stays
free; nightly (or pre-release) jobs run with the key.

Approximate cost: ~$0.05 per case × 20 cases ≈ $1 per run.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest


CASES_PATH = Path(__file__).parent / "cases" / "cases.json"


def _has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


pytestmark = pytest.mark.skipif(
    not _has_api_key(),
    reason="ANTHROPIC_API_KEY not set; skipping live eval suite.",
)


def _load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text())


@pytest.fixture(scope="session")
def cases() -> list[dict]:
    return _load_cases()


@pytest.fixture
def fresh_workspace(tmp_path, monkeypatch):
    """Create an isolated workspace seeded from a Phase 1 template."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    # Re-import settings under the patched env.
    import importlib

    import config

    importlib.reload(config)
    from services.native_converter import structured_spec_to_editable
    from services.useful_objects import build_useful_structured_spec
    from services.workspace import create_workspace

    def factory(template_id: str) -> tuple[str, str]:
        prompt_for_template = {
            "perforated_disc": "speaker grill 300mm with 12 rings",
            "phone_stand": "phone stand for iPhone 15",
            "simple_box": "simple box 80x80x40",
            "tray": "tray 100x100x20",
            "hook": "wall hook for coats",
            "cable_organizer": "cable organizer with 5 slots",
            "bracket": "right-angle bracket 60mm",
            "cylindrical_holder": "cylindrical pen holder",
            "wall_mount": "wall mount for camera",
        }
        prompt = prompt_for_template.get(template_id, template_id.replace("_", " "))
        spec = build_useful_structured_spec(prompt, source="text")
        spec["template_id"] = template_id  # force-pin for deterministic seeding
        editable = structured_spec_to_editable(spec)
        record = create_workspace(
            "native", editable, workspace_id=uuid.uuid4().hex
        )
        return record.workspace_id, record.editable_model.revision_id

    return factory


def _collect(workspace_id: str, message: str) -> dict:
    """Run one chat turn and collect every SSE event."""
    from services.ai.agent import stream_turn

    events: list[tuple[str, dict]] = []
    for raw in stream_turn(workspace_id, message):
        if not raw.startswith("event:"):
            continue
        # raw looks like: "event: name\ndata: {...}\n\n"
        head, data_line, _ = raw.split("\n", 2)
        ev = head[len("event: "):].strip()
        data_text = data_line[len("data: "):].strip()
        try:
            payload = json.loads(data_text)
        except json.JSONDecodeError:
            payload = {"_raw": data_text}
        events.append((ev, payload))
    tool_calls: list[dict] = []
    assistant_text: list[str] = []
    final: dict = {}
    for ev, payload in events:
        if ev == "tool_call_end":
            tool_calls.append(payload)
        elif ev == "assistant_text":
            assistant_text.append(str(payload.get("text", "")))
        elif ev == "turn_end":
            final = payload
    return {
        "events": events,
        "tool_calls": tool_calls,
        "assistant_text": "".join(assistant_text),
        "final": final,
    }


def _matches_param_change(
    tool_calls: list[dict], expectation: dict, current_workspace_id: str
) -> bool:
    """Did any successful mutate_parameter call match this expectation?"""
    from services.workspace import get_workspace

    record = get_workspace(current_workspace_id)
    target_param = expectation.get("param_name")
    target_kind = expectation.get("node_kind")
    approx = expectation.get("approx_new_value")

    for tc in tool_calls:
        if tc.get("name") != "mutate_parameter":
            continue
        if tc.get("is_error"):
            continue
        result = tc.get("result") or {}
        if not result.get("ok"):
            continue
        if target_param and result.get("param_name") != target_param:
            continue
        if approx is not None:
            new_value = result.get("new_value")
            if not isinstance(new_value, (int, float)):
                continue
            if abs(float(new_value) - float(approx)) > max(0.5, 0.1 * abs(float(approx))):
                continue
        if target_kind:
            node_id = result.get("node_id")
            from services.ai.tools._context import _find  # type: ignore

            node, _ = _find(record.editable_model.bodies, node_id, parent=None)
            if node is None or node.kind != target_kind:
                continue
        return True
    return False


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["name"])
def test_eval_case(case, fresh_workspace):
    workspace_id, _ = fresh_workspace(case["initial_template"])
    out = _collect(workspace_id, case["user_message"])
    tool_names = [tc["name"] for tc in out["tool_calls"] if not tc.get("is_error")]
    failing_tool_names = [tc["name"] for tc in out["tool_calls"] if tc.get("is_error")]
    assistant_text = out["assistant_text"].lower()

    if "expected_tools_called" in case:
        for required in case["expected_tools_called"]:
            assert required in tool_names, (
                f"Expected tool {required} but observed: "
                f"successful={tool_names} failed={failing_tool_names}"
            )

    if "expected_tools_called_any" in case:
        assert any(t in tool_names for t in case["expected_tools_called_any"]), (
            f"Expected any of {case['expected_tools_called_any']} in {tool_names}"
        )

    if "expected_param_changes" in case:
        for expectation in case["expected_param_changes"]:
            assert _matches_param_change(
                out["tool_calls"], expectation, workspace_id
            ), f"No mutate_parameter matched expectation {expectation}"

    if "expected_no_successful_tool" in case:
        assert case["expected_no_successful_tool"] not in tool_names, (
            f"Tool {case['expected_no_successful_tool']} should not have succeeded "
            f"in Phase 1, but it did."
        )

    if case.get("expected_no_param_change"):
        successful_mutations = [
            tc
            for tc in out["tool_calls"]
            if tc["name"] == "mutate_parameter"
            and not tc.get("is_error")
            and (tc.get("result") or {}).get("ok")
        ]
        assert not successful_mutations, (
            f"No parameter changes were expected, but observed: {successful_mutations}"
        )

    if case.get("expected_clarifying_question"):
        assert "?" in assistant_text, (
            "Expected the agent to ask a clarifying question (no '?' in reply)."
        )

    if "expected_assistant_mentions_any" in case:
        assert any(
            phrase.lower() in assistant_text
            for phrase in case["expected_assistant_mentions_any"]
        ), f"Reply did not mention any of {case['expected_assistant_mentions_any']}: {assistant_text!r}"

    # Cost ceiling — stop a regression from blowing past budget.
    final = out["final"]
    input_tokens = int(final.get("input_tokens", 0))
    output_tokens = int(final.get("output_tokens", 0))
    assert input_tokens < 30_000, f"Input tokens too high: {input_tokens}"
    assert output_tokens < 4_000, f"Output tokens too high: {output_tokens}"
