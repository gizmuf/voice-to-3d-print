"""Anthropic tool definitions and dispatch table for the agent loop."""

from __future__ import annotations

from typing import Any, Callable

from services.ai.tools._context import AgentContext
from services.ai.tools import (
    add_feature as _add_feature,
    check_manufacturability as _check_manufacturability,
    mutate_parameter as _mutate_parameter,
    query_tree as _query_tree,
    remove_feature as _remove_feature,
    run_preview as _run_preview,
)


_MODULES = [
    _mutate_parameter,
    _add_feature,
    _remove_feature,
    _run_preview,
    _check_manufacturability,
    _query_tree,
]


TOOL_DEFINITIONS: list[dict[str, Any]] = [m.TOOL_DEFINITION for m in _MODULES]
TOOL_DISPATCH: dict[str, Callable[[dict, AgentContext], dict]] = {
    m.TOOL_DEFINITION["name"]: m.execute for m in _MODULES
}


def execute(name: str, payload: dict, ctx: AgentContext) -> dict:
    """Run a tool by name. Returns a JSON-serialisable dict."""
    handler = TOOL_DISPATCH.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return handler(payload, ctx)
    except Exception as exc:
        return {"error": f"Tool {name} raised: {exc}"}


__all__ = ["AgentContext", "TOOL_DEFINITIONS", "TOOL_DISPATCH", "execute"]
