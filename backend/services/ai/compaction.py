"""Conversation compaction for the design agent.

Once the persisted history grows past ``settings.history_compact_at``, the
oldest half is replaced with a single short summary turn so the on-wire
context stays small. Without this, every later turn re-sends an ever-longer
uncached transcript and per-turn cost climbs without bound.

The summary call uses the configured Anthropic ``classify`` model (Haiku) —
much cheaper than re-sending the raw history through the chat model would
be. If the summary call fails, we keep the original history untouched; a
slow turn is better than a wrong one.
"""

from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic

from config import settings


_SUMMARY_PROMPT = (
    "You are summarizing the earlier portion of a CAD design conversation so "
    "the editing agent can keep working with bounded context. Output ONLY a "
    "summary of 3-5 sentences. Preserve every concrete decision the user "
    "made, every parameter or feature change that landed, and any active "
    "constraints (locked parameters, target process, manufacturing notes). "
    "Drop pleasantries, tool-call mechanics, and rebuild logs."
)


def maybe_compact_history(
    history: list[dict[str, Any]],
    *,
    threshold: int | None = None,
    client: Anthropic | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """If history is long, replace the oldest half with a short summary.

    Returns ``(new_history, did_compact)``. Caller is expected to persist the
    returned history. The compaction is only applied when the input message
    count exceeds the threshold.
    """
    threshold = threshold or settings.history_compact_at
    if threshold <= 0 or len(history) <= threshold:
        return history, False

    fold_at = len(history) // 2
    older = history[:fold_at]
    newer = history[fold_at:]
    if not older:
        return history, False
    # Don't slice through a tool_use / tool_result pair: an assistant turn
    # whose tool calls are answered in the next user message must stay
    # together. If `newer` starts with a tool_result block, pull it back
    # into `older` so the pair persists in the summary instead.
    while newer and _starts_with_tool_results(newer[0]):
        older.append(newer.pop(0))
    if not newer:
        return history, False

    summary = _summarize(older, client=client)
    if summary is None:
        return history, False

    summary_block = {
        "role": "user",
        "content": f"[Earlier turns, summarized]\n{summary}",
    }
    ack_block = {
        "role": "assistant",
        "content": "Understood — continuing from the summary.",
    }
    return [summary_block, ack_block, *newer], True


def _starts_with_tool_results(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def _flatten_text(messages: list[dict[str, Any]]) -> str:
    """Render the older turns as plain text for the summarizer.

    We strip tool_use / tool_result internals and keep only human-meaningful
    text. The classifier model doesn't need to relive every block; it just
    needs the gist of what was decided.
    """
    out: list[str] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in ("user", "assistant"):
            continue
        if isinstance(content, str):
            out.append(f"{role}: {content}")
            continue
        if not isinstance(content, list):
            continue
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                name = block.get("name", "tool")
                args = block.get("input")
                args_str = json.dumps(args)[:200] if args else ""
                text_parts.append(f"[{name}({args_str})]")
            elif block.get("type") == "tool_result":
                result = block.get("content", "")
                if isinstance(result, str):
                    text_parts.append(f"[tool result] {result[:200]}")
        if text_parts:
            out.append(f"{role}: " + " ".join(text_parts))
    return "\n".join(out)


def _summarize(
    older: list[dict[str, Any]],
    *,
    client: Anthropic | None,
) -> str | None:
    if client is None:
        if not settings.anthropic_api_key:
            return None
        client = Anthropic(api_key=settings.anthropic_api_key)
    text = _flatten_text(older)
    if not text.strip():
        return None
    try:
        response = client.messages.create(
            model=settings.anthropic_classify_model,
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{_SUMMARY_PROMPT}\n\n--- conversation start ---\n"
                        f"{text}\n--- conversation end ---"
                    ),
                }
            ],
        )
    except Exception:
        return None
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    summary = "".join(parts).strip()
    return summary or None


__all__ = ["maybe_compact_history"]
