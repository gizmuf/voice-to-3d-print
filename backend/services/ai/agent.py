"""The Pulsai chat agent loop.

A single sync generator that streams server-sent events for one user turn.
Holds the workspace context, dispatches tool calls, and bounds iteration.
No LangChain — we want every step legible.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from config import settings
from services.ai.capabilities import capability_for
from services.ai.prompts import SYSTEM_PROMPT, render_turn_context
from services.ai.tools import TOOL_DEFINITIONS, execute as execute_tool
from services.ai.tools._context import AgentContext
from services.editability import assess
from services.editable_model import EditableModel
from services.printer_profiles import get_profile
from services.workspace import get_workspace


MAX_TOOL_ITERATIONS = 8


def _conversation_path(workspace_id: str) -> Path:
    return settings.output_dir / "workspaces" / workspace_id / "conversation.json"


def load_conversation(workspace_id: str) -> list[dict[str, Any]]:
    path = _conversation_path(workspace_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_conversation(workspace_id: str, messages: list[dict[str, Any]]) -> None:
    path = _conversation_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2))


def _system_blocks(model: EditableModel) -> list[dict[str, Any]]:
    """System prompt is split into a cached static block and an ephemeral
    per-turn context. Static = identity + rules + schema; ephemeral = current
    workspace state."""
    capability = capability_for(model)
    assessment = assess(model)
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": render_turn_context(model, capability, assessment),
        },
    ]


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def stream_turn(
    workspace_id: str,
    user_message: str,
    *,
    printer_profile_id: str | None = None,
) -> Iterator[str]:
    """Stream one chat turn as server-sent events.

    Each yielded string is a wire-format SSE message. The caller (FastAPI
    StreamingResponse) just forwards them.
    """
    started = time.perf_counter()

    if not settings.anthropic_api_key:
        yield _sse(
            "error",
            {"message": "ANTHROPIC_API_KEY is not configured on the backend."},
        )
        return

    record = get_workspace(workspace_id)
    model = record.editable_model
    profile = get_profile(printer_profile_id)
    ctx = AgentContext(
        workspace_id=workspace_id,
        model=model,
        output_dir=settings.output_dir,
        printer_profile=profile,
    )

    history = load_conversation(workspace_id)
    user_block = {"role": "user", "content": user_message}
    history.append(user_block)
    yield _sse(
        "turn_start",
        {
            "workspace_id": workspace_id,
            "revision_id": ctx.model.revision_id,
            "model": settings.anthropic_chat_model,
        },
    )

    client = Anthropic(api_key=settings.anthropic_api_key)
    total_input_tokens = 0
    total_output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response = client.messages.create(
                model=settings.anthropic_chat_model,
                max_tokens=settings.anthropic_max_output_tokens,
                system=_system_blocks(ctx.model),
                tools=TOOL_DEFINITIONS,
                messages=history,
            )
        except Exception as exc:
            yield _sse("error", {"message": f"Anthropic call failed: {exc}"})
            return

        usage = getattr(response, "usage", None)
        if usage is not None:
            total_input_tokens += getattr(usage, "input_tokens", 0) or 0
            total_output_tokens += getattr(usage, "output_tokens", 0) or 0
            cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_creation_tokens += (
                getattr(usage, "cache_creation_input_tokens", 0) or 0
            )

        assistant_blocks: list[dict[str, Any]] = []
        tool_uses: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
                yield _sse("assistant_text", {"text": block.text})
            elif block.type == "tool_use":
                use = {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input or {},
                }
                assistant_blocks.append(use)
                tool_uses.append(use)
            else:  # pragma: no cover — defensive
                assistant_blocks.append({"type": block.type})

        history.append({"role": "assistant", "content": assistant_blocks})

        if response.stop_reason != "tool_use" or not tool_uses:
            break

        tool_results: list[dict[str, Any]] = []
        for use in tool_uses:
            yield _sse(
                "tool_call_start",
                {"id": use["id"], "name": use["name"], "input": use["input"]},
            )
            result = execute_tool(use["name"], use["input"], ctx)
            is_error = bool(result.get("error"))
            yield _sse(
                "tool_call_end",
                {
                    "id": use["id"],
                    "name": use["name"],
                    "result": result,
                    "is_error": is_error,
                },
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use["id"],
                    "content": json.dumps(result),
                    "is_error": is_error,
                }
            )
        history.append({"role": "user", "content": tool_results})
    else:
        yield _sse(
            "warning",
            {
                "message": (
                    f"Reached max tool iterations ({MAX_TOOL_ITERATIONS}); "
                    "stopping to avoid runaway loops."
                )
            },
        )

    save_conversation(workspace_id, history)
    duration_ms = int((time.perf_counter() - started) * 1000)
    yield _sse(
        "turn_end",
        {
            "workspace_id": workspace_id,
            "revision_id": ctx.model.revision_id,
            "duration_ms": duration_ms,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
        },
    )


__all__ = ["stream_turn", "load_conversation", "save_conversation", "MAX_TOOL_ITERATIONS"]
