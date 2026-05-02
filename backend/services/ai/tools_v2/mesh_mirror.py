"""Tool: duplicate-and-mirror the mesh across a plane (symmetric parts)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build, require_imported_mesh


class MeshMirrorInput(BaseModel):
    plane: Literal["x", "y", "z"] = Field(
        description="Mirror plane normal. 'x' mirrors left-right (across YZ plane)."
    )
    position: float | None = Field(
        default=None,
        description="Plane position along the axis. Defaults to centre of mesh.",
    )
    keep_original: bool = Field(
        default=True,
        description=(
            "If True, output is original ∪ mirror (a symmetric duplicate). "
            "If False, output is just the mirror image."
        ),
    )
    rationale: str = Field(max_length=200)


TOOL_DEFINITION = {
    "name": "mesh_mirror",
    "description": (
        "Mirror the imported mesh across a plane. With keep_original=True you "
        "get a symmetric duplicate (original + mirror). Useful for making "
        "left/right pairs of brackets, symmetric enclosures, etc."
    ),
    "input_schema": MeshMirrorInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = MeshMirrorInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    err = require_imported_mesh(ctx, "mesh_mirror")
    if err is not None:
        return err

    axis_idx = {"x": 0, "y": 1, "z": 2}[params.plane]
    pos_expr = (
        f"{params.position!r}"
        if params.position is not None
        else f"((float(mesh.bounds[0][{axis_idx}]) + float(mesh.bounds[1][{axis_idx}])) / 2)"
    )
    block_lines = [
        "import trimesh as _tm",
        "import numpy as _np",
        f"_pos = {pos_expr}",
        f"_M = _np.eye(4); _M[{axis_idx}, {axis_idx}] = -1",
        f"_M[{axis_idx}, 3] = 2 * _pos",
        "_mirror = mesh.copy()",
        "_mirror.apply_transform(_M)",
        "_mirror.invert()  # flip winding so the mirror is solid the right way",
    ]
    if params.keep_original:
        block_lines.append("mesh = _tm.util.concatenate([mesh, _mirror])")
    else:
        block_lines.append("mesh = _mirror")
    block = "\n".join(block_lines)
    return append_block_and_build(
        ctx,
        feature_name=f"mirror_{params.plane}",
        block=block,
        extra_result_payload={"plane": params.plane, "keep_original": params.keep_original},
    )


__all__ = ["TOOL_DEFINITION", "MeshMirrorInput", "execute"]
