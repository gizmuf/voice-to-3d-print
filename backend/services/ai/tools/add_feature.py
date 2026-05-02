"""Tool: add a feature node to the tree.

In Phase 1 this tool is wired but always refuses, because the rebuild path
(useful_objects + native_converter) is hardcoded per template — adding nodes
to the tree would not change exported geometry. The capability matrix is
authoritative; the refusal carries a clear suggestion to use mutate_parameter
instead.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.capabilities import capability_for, refusal_for_tool
from services.ai.tools._context import AgentContext


class AddFeatureInput(BaseModel):
    parent_id: str = Field(description="Stable ID of the parent node to add under.")
    kind: str = Field(description="Feature kind (e.g. 'hole', 'fillet', 'chamfer').")
    label: str = Field(description="Human-readable label for the new feature.")
    params: dict[str, float | int | bool | str] = Field(
        default_factory=dict, description="Parameter values for the new feature."
    )


TOOL_DEFINITION = {
    "name": "add_feature",
    "description": (
        "Insert a new feature into the tree under the given parent. "
        "**Phase 1: this tool currently refuses for all workspaces** because "
        "the codegen path is hardcoded per template; adding tree nodes "
        "would not affect exported geometry. Prefer mutate_parameter."
    ),
    "input_schema": AddFeatureInput.model_json_schema(),
}


def execute(payload: dict, ctx: AgentContext) -> dict:
    capability = capability_for(ctx.model)
    reason = refusal_for_tool(capability, "add_feature") or (
        "add_feature is not enabled in Phase 1."
    )
    return {
        "error": reason,
        "current_revision_id": ctx.model.revision_id,
        "suggestion": (
            "Use mutate_parameter on existing nodes. If you genuinely need to "
            "add a new feature, tell the user this is not yet supported and "
            "offer the closest parametric mutation."
        ),
    }


__all__ = ["TOOL_DEFINITION", "AddFeatureInput", "execute"]
