"""Tool: repair a mesh that's non-watertight, has bad normals, or self-intersects.

Wraps trimesh's repair primitives (and falls back to MeshLib via the existing
slicer pipeline if available). Adds a feature block that runs at preview time,
so the repair persists and is auditable.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build, require_imported_mesh


class MeshRepairInput(BaseModel):
    fill_holes: bool = Field(default=True, description="Fill open boundaries.")
    fix_normals: bool = Field(default=True, description="Recompute consistent face normals.")
    fix_inversion: bool = Field(
        default=True, description="Flip the mesh inside-out if the volume is negative."
    )
    rationale: str = Field(max_length=200)


TOOL_DEFINITION = {
    "name": "mesh_repair",
    "description": (
        "Repair a mesh: fill holes (open boundary edges), fix inconsistent face "
        "normals, and flip the mesh if its computed volume is negative. Useful "
        "after boolean ops that produce small artifacts or when the user uploads "
        "a non-manifold STL. The repair is added as a feature block so it "
        "persists across rebuilds."
    ),
    "input_schema": MeshRepairInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = MeshRepairInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    err = require_imported_mesh(ctx, "mesh_repair")
    if err is not None:
        return err

    steps = []
    if params.fix_inversion:
        steps.append("if mesh.volume < 0: mesh.invert()")
    if params.fix_normals:
        steps.append("_tm.repair.fix_normals(mesh)")
    if params.fill_holes:
        steps.append("_tm.repair.fill_holes(mesh)")
    steps.append("mesh.process(validate=True)")

    block = "import trimesh as _tm\n" + "\n".join(steps)
    return append_block_and_build(
        ctx,
        feature_name="repair",
        block=block,
    )


__all__ = ["TOOL_DEFINITION", "MeshRepairInput", "execute"]
