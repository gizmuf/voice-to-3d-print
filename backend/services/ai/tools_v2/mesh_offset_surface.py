"""Tool: uniformly inflate or deflate the mesh by a small offset.

Useful for tolerance fitting ("make it 0.2mm bigger so it press-fits"),
cleaning up rough scans, or preparing for a shrinkage allowance.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build, require_imported_mesh


class MeshOffsetSurfaceInput(BaseModel):
    delta_mm: float = Field(
        description=(
            "Offset distance. Positive = inflate (make bigger), "
            "negative = deflate (make smaller). Typical values: ±0.1 to ±0.5 mm."
        ),
    )
    rationale: str = Field(max_length=200)


TOOL_DEFINITION = {
    "name": "mesh_offset_surface",
    "description": (
        "Uniformly inflate or deflate the imported mesh by a small distance. "
        "Use for tolerance fitting (press-fit / clearance-fit), shrinkage "
        "compensation, or smoothing rough scan surfaces. Implementation moves "
        "every vertex along its averaged normal."
    ),
    "input_schema": MeshOffsetSurfaceInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = MeshOffsetSurfaceInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    err = require_imported_mesh(ctx, "mesh_offset_surface")
    if err is not None:
        return err

    block = (
        "import trimesh as _tm\nimport numpy as _np\n"
        f"_delta = {params.delta_mm!r}\n"
        "_n = mesh.vertex_normals\n"
        "_v = mesh.vertices.copy()\n"
        "_v += _n * _delta\n"
        "mesh = _tm.Trimesh(vertices=_v, faces=mesh.faces.copy(), process=True)\n"
    )
    name = "inflate" if params.delta_mm > 0 else "deflate"
    return append_block_and_build(
        ctx,
        feature_name=f"{name}_surface",
        block=block,
        extra_result_payload={"delta_mm": params.delta_mm},
    )


__all__ = ["TOOL_DEFINITION", "MeshOffsetSurfaceInput", "execute"]
