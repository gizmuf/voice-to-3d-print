"""Conversation compaction collapses the oldest half into a summary turn."""

from typing import Any
from unittest.mock import MagicMock

from services.ai.compaction import maybe_compact_history


def _user_msg(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _assistant_msg(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _tool_use_msg(tool_id: str, name: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {}}],
    }


def _tool_result_msg(tool_id: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}],
    }


def _fake_client(text: str) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(type="text", text=text)]
    client.messages.create.return_value = response
    return client


def test_compacts_when_over_threshold(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    history: list[dict[str, Any]] = []
    for i in range(20):
        history.append(_user_msg(f"do thing {i}"))
        history.append(_assistant_msg(f"done {i}"))
    client = _fake_client("Earlier the user iterated on a wall hook design.")
    out, did = maybe_compact_history(history, threshold=10, client=client)
    assert did is True
    # First two messages are summary + ack; the rest is the recent half intact.
    assert out[0]["role"] == "user"
    assert "Earlier turns, summarized" in out[0]["content"]
    assert out[1]["role"] == "assistant"
    assert len(out) < len(history)
    # Newer half preserved verbatim
    assert out[-1] == history[-1]
    assert out[-2] == history[-2]


def test_does_not_compact_below_threshold():
    history = [_user_msg("hi"), _assistant_msg("hello")]
    out, did = maybe_compact_history(history, threshold=10)
    assert did is False
    assert out is history


def test_keeps_tool_use_pair_intact(monkeypatch):
    """Splitting through a tool_use/tool_result pair would corrupt the turn."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    history: list[dict[str, Any]] = []
    for i in range(8):
        history.append(_user_msg(f"q{i}"))
        history.append(_tool_use_msg(f"id{i}", "update_parameter"))
        history.append(_tool_result_msg(f"id{i}"))
        history.append(_assistant_msg(f"ok {i}"))
    client = _fake_client("Summary.")
    out, did = maybe_compact_history(history, threshold=10, client=client)
    assert did is True
    # The first message after the summary/ack pair must NOT be a tool_result —
    # otherwise the agent would receive a result with no preceding tool_use.
    first_real = out[2]
    if first_real["role"] == "user" and isinstance(first_real["content"], list):
        for block in first_real["content"]:
            if isinstance(block, dict):
                assert block.get("type") != "tool_result"


def test_summary_failure_keeps_original_history():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("network down")
    history: list[dict[str, Any]] = []
    for i in range(20):
        history.append(_user_msg(f"do {i}"))
        history.append(_assistant_msg(f"done {i}"))
    out, did = maybe_compact_history(history, threshold=10, client=client)
    assert did is False
    assert out is history
