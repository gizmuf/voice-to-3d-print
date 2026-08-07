from services.ai.agent_v2 import (
    _repair_malformed_thinking_blocks,
    _serialize_response_block,
)


class _ThinkingBlock:
    type = "thinking"

    def model_dump(self, *, mode: str, exclude_none: bool) -> dict:
        assert mode == "json"
        assert exclude_none is True
        return {
            "type": "thinking",
            "thinking": "Check the failed CAD operation.",
            "signature": "signed-thinking-block",
        }


def test_serialized_thinking_block_keeps_required_anthropic_fields() -> None:
    assert _serialize_response_block(_ThinkingBlock()) == {
        "type": "thinking",
        "thinking": "Check the failed CAD operation.",
        "signature": "signed-thinking-block",
    }


def test_legacy_type_only_thinking_block_is_removed_before_replay() -> None:
    history = [
        {
            "role": "assistant",
            "content": [
                {"type": "thinking"},
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "update_parameter",
                    "input": {"name": "height", "value": 100},
                },
            ],
        }
    ]

    repaired = _repair_malformed_thinking_blocks(history)

    assert repaired == [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "update_parameter",
                    "input": {"name": "height", "value": 100},
                }
            ],
        }
    ]

