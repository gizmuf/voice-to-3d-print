"""Tool: read-only lookup against the feature tree."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from services.ai.tools._context import AgentContext
from services.editable_model import BodyNode


class QueryTreeInput(BaseModel):
    node_kind: str | None = Field(
        default=None,
        description="Filter by feature kind (e.g. 'hole', 'circular_pattern'). Optional.",
    )
    label_contains: str | None = Field(
        default=None,
        description="Substring match against the node label (case-insensitive). Optional.",
    )
    node_id: str | None = Field(
        default=None,
        description="If provided, return just that node's details.",
    )


TOOL_DEFINITION = {
    "name": "query_tree",
    "description": (
        "Read-only lookup over the active feature tree. Use this when you are "
        "unsure of a node id, or want to find all features of a given kind. "
        "Returns a list of {id, kind, label, params, editable} entries."
    ),
    "input_schema": QueryTreeInput.model_json_schema(),
}


def _walk(bodies: list[BodyNode]):
    for body in bodies:
        yield body
        yield from _walk(body.children)


def _node_summary(node: BodyNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "label": node.label,
        "editable": node.editable,
        "confidence": node.confidence,
        "params": {k: v for k, v in node.params.items() if not k.startswith("_")},
    }


def execute(payload: dict, ctx: AgentContext) -> dict:
    try:
        params = QueryTreeInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    if params.node_id:
        node, _ = ctx.find_node(params.node_id)
        if node is None:
            return {
                "error": f"No node with id '{params.node_id}'.",
                "current_revision_id": ctx.model.revision_id,
            }
        return {
            "ok": True,
            "revision_id": ctx.model.revision_id,
            "matched": [_node_summary(node)],
        }

    matches: list[dict[str, Any]] = []
    needle = params.label_contains.lower() if params.label_contains else None
    for body in _walk(ctx.model.bodies):
        if params.node_kind and body.kind != params.node_kind:
            continue
        if needle and needle not in body.label.lower():
            continue
        matches.append(_node_summary(body))
    return {
        "ok": True,
        "revision_id": ctx.model.revision_id,
        "matched": matches,
        "match_count": len(matches),
    }


__all__ = ["TOOL_DEFINITION", "QueryTreeInput", "execute"]
