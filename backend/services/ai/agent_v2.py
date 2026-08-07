"""Code-driven Pulsai chat agent.

Same SSE protocol as agent.py, but operates on a Design (build123d script) and
calls the powerful tool set in services/ai/tools_v2/. There is no capability
matrix and no per-template gating; refusals come from the AST audit and the
sandbox build.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any


logger = logging.getLogger(__name__)

from anthropic import Anthropic

from config import settings
from services.ai.compaction import maybe_compact_history
from services.ai.direct_route import ambiguity_question, parse_direct_parameter_edit
from services.ai.prompts_v2 import SYSTEM_PROMPT, render_turn_context
from services.ai.telemetry import record_tool_call
from services.ai.tools_v2 import DesignContext, TOOL_DEFINITIONS, execute as execute_tool
from services.ai.tools_v2.update_parameter import execute_many as execute_parameter_changes
from services.codegen.store import (
    get_build,
    get_design,
    load_conversation,
    record_ai_usage,
    save_conversation,
)


MAX_TOOL_ITERATIONS = 10
MAX_FAILED_TOOL_CALLS = 2


def _serialize_response_block(block: Any) -> dict[str, Any]:
    """Preserve Anthropic content blocks exactly enough for message replay.

    Thinking blocks must be returned unmodified alongside tool results. Saving
    only their ``type`` poisons the conversation because the next Messages API
    request requires both the thinking text and its signature.
    """
    model_dump = getattr(block, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json", exclude_none=True)
        if isinstance(payload, dict):
            return payload

    payload: dict[str, Any] = {"type": str(getattr(block, "type", "unknown"))}
    for field in ("thinking", "signature", "data"):
        value = getattr(block, field, None)
        if value is not None:
            payload[field] = value
    return payload


def _anthropic_cost_usd(
    *, input_tokens: int, output_tokens: int, cache_read_tokens: int, cache_creation_tokens: int
) -> float:
    promo = settings.anthropic_chat_model == "claude-sonnet-5" and time.time() < 1788220800
    input_rate, output_rate = (2.0, 10.0) if promo else (3.0, 15.0)
    return (
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_read_tokens * (input_rate * 0.1)
        + cache_creation_tokens * (input_rate * 1.25)
    ) / 1_000_000


def _system_blocks(
    ctx: DesignContext,
    *,
    selected_feature_id: str | None = None,
    selected_feature_label: str | None = None,
    selected_topology_ref: str | None = None,
) -> list[dict[str, Any]]:
    selected_block = _selected_feature_context(
        ctx,
        selected_feature_id=selected_feature_id,
        selected_feature_label=selected_feature_label,
        selected_topology_ref=selected_topology_ref,
    )
    turn_context = render_turn_context(ctx.design, ctx.last_build)
    if selected_block:
        turn_context = f"{turn_context}\n{selected_block}"
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": turn_context,
        },
    ]


def _selected_feature_context(
    ctx: DesignContext,
    *,
    selected_feature_id: str | None,
    selected_feature_label: str | None,
    selected_topology_ref: str | None,
) -> str:
    if not selected_feature_id and not selected_feature_label and not selected_topology_ref:
        return ""
    match = next(
        (
            f
            for f in ctx.design.features
            if f.id == selected_feature_id or f.name == selected_feature_label
        ),
        None,
    )
    if match:
        words = f" user_words={match.user_words}" if match.user_words else ""
        parents = (
            f" parent_feature_ids={match.parent_feature_ids}"
            if match.parent_feature_ids
            else ""
        )
        topology = f" topology_ref={selected_topology_ref}." if selected_topology_ref else ""
        return (
            "## Selected feature context\n"
            f"User has selected feature `{match.id}` ({match.name}, {match.kind})."
            f"{parents}{words}{topology}\n"
            "Prefer editing this feature unless the user explicitly asks for a different target.\n"
        )
    label = selected_feature_label or selected_feature_id
    return (
        "## Selected feature context\n"
        f"User selected feature `{label}` with topology_ref `{selected_topology_ref}`, but it was not found in the current feature graph. "
        "Ask one short clarification before making a targeted edit.\n"
    )


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def stream_turn(
    design_id: str,
    user_message: str,
    *,
    printer_profile_id: str | None = None,
    selected_feature_id: str | None = None,
    selected_feature_label: str | None = None,
    selected_topology_ref: str | None = None,
) -> Iterator[str]:
    started = time.perf_counter()

    design = get_design(design_id)
    last_build = get_build(design_id)
    ctx = DesignContext(
        design_id=design_id,
        design=design,
        output_dir=settings.output_dir,
        printer_profile_id=printer_profile_id or settings.default_printer_profile_id,
        last_build=last_build,
        current_user_message=user_message,
    )

    history = _repair_dangling_tool_uses(
        _repair_malformed_thinking_blocks(load_conversation(design_id))
    )

    question = ambiguity_question(user_message)
    direct_edit = parse_direct_parameter_edit(user_message, design.parameters)
    if question or direct_edit:
        history.append({"role": "user", "content": user_message})
        yield _sse(
            "turn_start",
            {
                "design_id": design_id,
                "revision_id": ctx.design.revision_id,
                "model": "local",
            },
        )
        if question:
            history.append({"role": "assistant", "content": [{"type": "text", "text": question}]})
            save_conversation(design_id, _compact_for_persist(history))
            yield _sse("assistant_text", {"text": question})
            yield _sse(
                "turn_end",
                {
                    "design_id": design_id,
                    "revision_id": ctx.design.revision_id,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                },
            )
            return

        assert direct_edit is not None
        tool_id = f"local-param-{int(time.time() * 1000)}"
        tool_input = {
            "name": direct_edit.name,
            "new_value": direct_edit.value,
            "rationale": "Explicit numeric parameter edit parsed locally.",
        }
        yield _sse("tool_call_start", {"id": tool_id, "name": "update_parameter", "input": tool_input})
        tool_started = time.perf_counter()
        result = execute_tool("update_parameter", tool_input, ctx)
        record_tool_call(
            tool_name="update_parameter",
            success=not bool(result.get("error")),
            duration_ms=int((time.perf_counter() - tool_started) * 1000),
            design_id=design_id,
        )
        yield _sse(
            "tool_call_end",
            {"id": tool_id, "name": "update_parameter", "result": result, "is_error": bool(result.get("error"))},
        )
        if result.get("error"):
            message = f"Nie zastosowałem zmiany: {result['error']}"
        else:
            message = f"Gotowe — {direct_edit.name} = {direct_edit.value}. Zmiana wykonana lokalnie, bez kosztu modelu."
        history.append({"role": "assistant", "content": [{"type": "text", "text": message}]})
        save_conversation(design_id, _compact_for_persist(history))
        yield _sse("assistant_text", {"text": message})
        yield _sse(
            "turn_end",
            {
                "design_id": design_id,
                "revision_id": ctx.design.revision_id,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
            },
        )
        return

    if not settings.anthropic_api_key:
        yield _sse(
            "error",
            {"message": "ANTHROPIC_API_KEY is not configured on the backend."},
        )
        return

    history, _ = maybe_compact_history(history)
    history.append({"role": "user", "content": user_message})
    yield _sse(
        "turn_start",
        {
            "design_id": design_id,
            "revision_id": ctx.design.revision_id,
            "model": settings.anthropic_chat_model,
        },
    )

    client = Anthropic(api_key=settings.anthropic_api_key)
    total_in = total_out = cache_read = cache_write = 0
    failed_tool_calls = 0
    persisted = False
    recovery_announced = False
    turn_cost_usd = 0.0

    def _persist_history() -> None:
        nonlocal persisted
        if persisted:
            return
        try:
            save_conversation(design_id, _compact_for_persist(history))
        except Exception as exc:  # noqa: BLE001 — telemetry, never block the turn
            # Disk full, permission errors, etc. shouldn't fail the user-facing
            # turn but they need to be visible somewhere or the conversation
            # silently rolls back across restarts.
            logger.warning(
                "save_conversation failed for design %s: %s",
                design_id,
                exc,
            )
        persisted = True

    try:
        for iteration in range(MAX_TOOL_ITERATIONS):
            recovery_mode = failed_tool_calls > 0
            if recovery_mode and not recovery_announced:
                yield _sse(
                    "model_activity",
                    {
                        "model": settings.anthropic_chat_model,
                        "mode": "recovery",
                        "activity": "Pierwsza próba nie przeszła walidacji — analizuję bezpieczną poprawkę…",
                    },
                )
                recovery_announced = True
            try:
                response = client.messages.create(
                    model=settings.anthropic_chat_model,
                    max_tokens=(
                        max(settings.anthropic_max_output_tokens, 3000)
                        if recovery_mode
                        else settings.anthropic_max_output_tokens
                    ),
                    # Sonnet 5 enables adaptive thinking by default. Routine CAD
                    # turns should stay fast and predictable; hard-task routing
                    # can opt into thinking separately when we add it.
                    thinking={"type": "adaptive"} if recovery_mode else {"type": "disabled"},
                    **({"output_config": {"effort": "medium"}} if recovery_mode else {}),
                    system=_system_blocks(
                        ctx,
                        selected_feature_id=selected_feature_id,
                        selected_feature_label=selected_feature_label,
                        selected_topology_ref=selected_topology_ref,
                    ),
                    tools=TOOL_DEFINITIONS,
                    messages=history,
                )
            except Exception as exc:
                yield _sse("error", {"message": f"Anthropic call failed: {exc}"})
                return

            usage = getattr(response, "usage", None)
            if usage is not None:
                total_in += getattr(usage, "input_tokens", 0) or 0
                total_out += getattr(usage, "output_tokens", 0) or 0
                cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0

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
                else:
                    assistant_blocks.append(_serialize_response_block(block))

            history.append({"role": "assistant", "content": assistant_blocks})

            if response.stop_reason != "tool_use" or not tool_uses:
                break

            tool_results: list[dict[str, Any]] = []
            batched_parameter_results: dict[str, dict] = {}
            batched_parameter_duration_ms = 0
            if len(tool_uses) > 1 and all(use["name"] == "update_parameter" for use in tool_uses):
                yield _sse(
                    "model_activity",
                    {
                        "activity": f"Aktualizuję {len(tool_uses)} wymiary w jednym przebudowaniu…",
                        "model": settings.anthropic_chat_model,
                    },
                )
                for use in tool_uses:
                    yield _sse(
                        "tool_call_start",
                        {"id": use["id"], "name": use["name"], "input": use["input"]},
                    )
                batch_started = time.perf_counter()
                batch_results = execute_parameter_changes(
                    [use["input"] for use in tool_uses], ctx
                )
                batched_parameter_duration_ms = int(
                    (time.perf_counter() - batch_started) * 1000
                )
                batched_parameter_results = {
                    use["id"]: result
                    for use, result in zip(tool_uses, batch_results, strict=True)
                }

            for use in tool_uses:
                if use["id"] in batched_parameter_results:
                    result = batched_parameter_results[use["id"]]
                    tool_ms = batched_parameter_duration_ms if use is tool_uses[0] else 0
                else:
                    yield _sse(
                        "tool_call_start",
                        {"id": use["id"], "name": use["name"], "input": use["input"]},
                    )
                    tool_started = time.perf_counter()
                    result = execute_tool(use["name"], use["input"], ctx)
                    tool_ms = int((time.perf_counter() - tool_started) * 1000)
                is_error = bool(result.get("error"))
                if is_error:
                    failed_tool_calls += 1
                record_tool_call(
                    tool_name=use["name"],
                    success=not is_error,
                    duration_ms=tool_ms,
                    design_id=design_id,
                )
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
            if failed_tool_calls >= MAX_FAILED_TOOL_CALLS:
                yield _sse(
                    "error",
                    {
                        "message": (
                            "Stopped after two failed CAD tool calls to avoid a costly retry loop. "
                            "The design is unchanged; refine the request or use a known-good template."
                        )
                    },
                )
                break
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
    finally:
        # Persist on every exit path including client abort (GeneratorExit).
        # The dangling-tool-use repair on the next load patches any in-flight
        # tool_use blocks left without matching results.
        _persist_history()
        if total_in or total_out or cache_read or cache_write:
            turn_cost_usd = _anthropic_cost_usd(
                input_tokens=total_in,
                output_tokens=total_out,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_write,
            )
            try:
                record_ai_usage(
                    design_id,
                    {
                        "provider": "anthropic",
                        "model": settings.anthropic_chat_model,
                        "input_tokens": total_in,
                        "output_tokens": total_out,
                        "cache_read_tokens": cache_read,
                        "cache_creation_tokens": cache_write,
                        "cost_usd": turn_cost_usd,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - accounting must not break the turn
                logger.warning("AI usage persistence failed for design %s: %s", design_id, exc)

    yield _sse(
        "turn_end",
        {
            "design_id": design_id,
            "revision_id": ctx.design.revision_id,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_write,
            "cost_usd": turn_cost_usd,
            "model": settings.anthropic_chat_model,
        },
    )


_PERSIST_TOOL_RESULT_CAP = 1200


def _compact_for_persist(history: list[dict]) -> list[dict]:
    """Trim oversized tool-result content blocks before writing to disk.

    Why: past turns accumulate in ``conversation.json`` and replay on every
    future call to Anthropic. A 5 KB ``query_library`` result or a 4 KB
    ``run_build`` result that mattered in turn N is largely dead weight in
    turn N+5 — the model has already acted on it. We keep the head of each
    blob (where the success flag, key fields, and the most useful summary
    live) and drop the tail.

    Active in-memory history during a turn is *not* trimmed — only the
    persisted version. So same-turn iterations keep full fidelity.
    """
    if not history:
        return history
    out: list[dict] = []
    for msg in history:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue
        new_blocks: list[dict] = []
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and isinstance(block.get("content"), str)
                and len(block["content"]) > _PERSIST_TOOL_RESULT_CAP
            ):
                head = block["content"][:_PERSIST_TOOL_RESULT_CAP]
                trimmed = {
                    **block,
                    "content": (
                        head
                        + f' …[truncated; {len(block["content"]) - _PERSIST_TOOL_RESULT_CAP} more chars]'
                    ),
                }
                new_blocks.append(trimmed)
            else:
                new_blocks.append(block)
        out.append({**msg, "content": new_blocks})
    return out


def _repair_dangling_tool_uses(history: list[dict]) -> list[dict]:
    """Inject synthetic tool_result blocks for any dangling tool_use blocks.

    A turn that was cut off mid-tool-execution (process killed, network
    blip, sandbox timeout) leaves the conversation with an assistant message
    containing tool_use blocks that have no matching tool_result. Anthropic
    rejects the next call with a 400.

    Walks every assistant message in the history (not only the last) and
    inserts an ``is_error: true`` tool_result for any tool_use whose id is
    never answered. Compaction can leave the dangler somewhere in the
    middle, and we want a single load to clean the whole transcript.
    """
    if not history:
        return history

    answered_ids: set[str] = set()
    for msg in history:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and isinstance(block.get("tool_use_id"), str)
            ):
                answered_ids.add(block["tool_use_id"])

    out: list[dict] = []
    for msg in history:
        out.append(msg)
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        pending_ids = [
            block["id"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "tool_use"
            and isinstance(block.get("id"), str)
            and block["id"] not in answered_ids
        ]
        if not pending_ids:
            continue
        out.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": json.dumps(
                            {
                                "error": (
                                    "Tool call was interrupted before the runtime returned a "
                                    "result (process restart, sandbox timeout, or network "
                                    "blip). The design state is unchanged. Either retry the "
                                    "same operation or take a different approach."
                                )
                            }
                        ),
                        "is_error": True,
                    }
                    for tid in pending_ids
                ],
            }
        )
        answered_ids.update(pending_ids)
    return out


def _repair_malformed_thinking_blocks(history: list[dict]) -> list[dict]:
    """Drop legacy incomplete thinking blocks before replaying a transcript.

    Versions deployed before this repair persisted ``{"type": "thinking"}``
    without the required ``thinking`` and ``signature`` fields. The reasoning
    text cannot be reconstructed, but completed tool calls and results remain
    valid without it, so removing only the malformed block safely restores the
    conversation.
    """
    if not history:
        return history

    out: list[dict] = []
    for message in history:
        content = message.get("content")
        if not isinstance(content, list):
            out.append(message)
            continue

        repaired: list[Any] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                if not isinstance(block.get("thinking"), str) or not isinstance(
                    block.get("signature"), str
                ):
                    continue
            if isinstance(block, dict) and block.get("type") == "redacted_thinking":
                if not isinstance(block.get("data"), str):
                    continue
            repaired.append(block)
        out.append({**message, "content": repaired})
    return out


__all__ = ["stream_turn", "MAX_TOOL_ITERATIONS", "MAX_FAILED_TOOL_CALLS"]
