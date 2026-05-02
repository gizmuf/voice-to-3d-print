"""Tool: remove a feature from the tree.

Phase 1: always refuses. The current rebuild path always emits the canonical
feature set per template, so removing a tree node would not change the
exported geometry.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.capabilities import capability_for, refusal_for_tool
from services.ai.tools._context import AgentContext


class RemoveFeatureInput(BaseModel):
    node_id: str = Field(description="Stable ID of the node to remove.")


TOOL_DEFINITION = {
    "name": "remove_feature",
    "description": (
        "Remove a feature node from the tree. "
        "**Phase 1: this tool currently refuses for all workspaces** because "
        "the codegen path is hardcoded per template; removing tree nodes "
        "would not affect exported geometry."
    ),
    "input_schema": RemoveFeatureInput.model_json_schema(),
}


def execute(payload: dict, ctx: AgentContext) -> dict:
    capability = capability_for(ctx.model)
    reason = refusal_for_tool(capability, "remove_feature") or (
        "remove_feature is not enabled in Phase 1."
    )
    return {
        "error": reason,
        "current_revision_id": ctx.model.revision_id,
        "suggestion": (
            "If the user wants to disable a feature, mutate its parameter to a "
            "neutral value (e.g. set hole diameter to 0 if the rebuild path "
            "honors that)."
        ),
    }


__all__ = ["TOOL_DEFINITION", "RemoveFeatureInput", "execute"]
