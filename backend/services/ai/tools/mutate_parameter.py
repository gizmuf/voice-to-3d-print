"""Tool: change exactly one parameter on one feature."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from services.ai.capabilities import can_mutate_param, capability_for
from services.ai.tools._context import AgentContext
from services.editability import is_node_editable
from services.editable_model import BodyParamUpdate, WorkspaceMutation
from services.workspace import update_workspace


class MutateParameterInput(BaseModel):
    node_id: str = Field(description="Stable ID of the FeatureNode to mutate.")
    param_name: str = Field(
        description="Name of the parameter on this node (e.g. 'radius', 'cable_hole_diameter_mm')."
    )
    new_value: float | int | bool | str = Field(
        description="The new value. Must match the existing parameter's type (number/bool/string)."
    )
    rationale: str = Field(
        max_length=200,
        description="One sentence explaining why this change is being made.",
    )


TOOL_DEFINITION = {
    "name": "mutate_parameter",
    "description": (
        "Change exactly one parameter on one feature in the active model. "
        "Use this for direct user requests like 'make the holes 7mm' or 'taller'. "
        "After calling, you typically need to call run_preview to see the result. "
        "If the parameter does not exist on the node or the node is not editable, "
        "this returns an error and you should try query_tree first or refuse the request."
    ),
    "input_schema": MutateParameterInput.model_json_schema(),
}


def _coerce_value(existing: Any, new_value: Any) -> Any:
    """Coerce ``new_value`` to the type of ``existing`` so JSON ints land as floats etc."""
    if isinstance(existing, bool):
        if isinstance(new_value, bool):
            return new_value
        if isinstance(new_value, (int, float)):
            return bool(new_value)
        if isinstance(new_value, str):
            return new_value.lower() in ("1", "true", "yes")
    if isinstance(existing, float) or isinstance(new_value, (int, float)):
        try:
            return float(new_value)
        except (TypeError, ValueError):
            pass
    return new_value


def execute(payload: dict, ctx: AgentContext) -> dict:
    try:
        params = MutateParameterInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    node, _ = ctx.find_node(params.node_id)
    if node is None:
        return {
            "error": f"No node with id '{params.node_id}' in current tree.",
            "current_revision_id": ctx.model.revision_id,
            "suggestion": "Call query_tree to find a valid node id.",
        }

    if not is_node_editable(ctx.model, params.node_id):
        return {
            "error": (
                f"Node '{params.node_id}' is not editable in the current "
                f"workspace (source={ctx.model.source})."
            ),
            "current_revision_id": ctx.model.revision_id,
        }

    if params.param_name not in node.params:
        return {
            "error": (
                f"Parameter '{params.param_name}' does not exist on node "
                f"'{params.node_id}'. Existing params: "
                f"{sorted(k for k in node.params if not k.startswith('_'))}."
            ),
            "current_revision_id": ctx.model.revision_id,
        }

    capability = capability_for(ctx.model)
    allowed, reason = can_mutate_param(capability, node.kind, params.param_name)
    if not allowed:
        return {
            "error": reason or "Mutation not allowed by capability matrix.",
            "current_revision_id": ctx.model.revision_id,
        }

    existing = node.params[params.param_name]
    new_value = _coerce_value(existing, params.new_value)
    if existing == new_value:
        return {
            "error": (
                f"Parameter '{params.param_name}' is already {existing}. "
                "No change applied — would have been a silent no-op."
            ),
            "current_revision_id": ctx.model.revision_id,
        }

    try:
        record = update_workspace(
            ctx.workspace_id,
            WorkspaceMutation(
                expected_revision_id=ctx.model.revision_id,
                body_updates=[
                    BodyParamUpdate(
                        body_id=params.node_id,
                        params={params.param_name: new_value},
                    )
                ],
            ),
        )
    except HTTPException as exc:
        return {
            "error": f"Mutation rejected: {exc.detail}",
            "current_revision_id": ctx.model.revision_id,
        }

    ctx.reload(record.editable_model)
    return {
        "ok": True,
        "node_id": params.node_id,
        "param_name": params.param_name,
        "previous_value": existing,
        "new_value": new_value,
        "new_revision_id": record.editable_model.revision_id,
        "manufacturability": record.editable_model.manufacturability.model_dump(),
    }


__all__ = ["TOOL_DEFINITION", "MutateParameterInput", "execute"]
