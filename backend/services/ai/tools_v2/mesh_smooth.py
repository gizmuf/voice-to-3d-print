"""Tool: Laplacian smoothing pass (cleans up rough mesh surfaces)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build, require_imported_mesh


class MeshSmoothInput(BaseModel):
    iterations: int = Field(default=2, ge=1, le=20, description="Smoothing passes.")
    lamb: float = Field(
        default=0.5,
        ge=0.05,
        le=1.0,
        description="Per-iteration weight (Laplacian step size). 0.5 is a safe default.",
    )
    rationale: str = Field(max_length=200)


TOOL_DEFINITION = {
    "name": "mesh_smooth",
    "description": (
        "Run Laplacian smoothing on the imported mesh. Cleans up faceted "
        "surfaces, scan noise, or rough boolean artifacts. Smooths uniformly "
        "— don't use this on parts that need sharp corners. ~2 iterations "
        "is enough for most cleanup; 5+ over-smooths."
    ),
    "input_schema": MeshSmoothInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = MeshSmoothInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    err = require_imported_mesh(ctx, "mesh_smooth")
    if err is not None:
        return err

    block = (
        "import trimesh as _tm\n"
        f"_tm.smoothing.filter_laplacian(mesh, lamb={params.lamb!r}, "
        f"iterations={params.iterations!r})"
    )
    return append_block_and_build(
        ctx,
        feature_name="smooth",
        block=block,
        extra_result_payload={
            "iterations": params.iterations,
            "lamb": params.lamb,
        },
    )


__all__ = ["TOOL_DEFINITION", "MeshSmoothInput", "execute"]
