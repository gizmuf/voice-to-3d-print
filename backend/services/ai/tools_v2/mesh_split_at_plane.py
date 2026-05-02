"""Tool: split the mesh in half along a plane (e.g. for two-piece prints)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build, require_imported_mesh


class MeshSplitAtPlaneInput(BaseModel):
    axis: Literal["x", "y", "z"] = Field(
        description="Plane axis to split along. 'z' = horizontal slice."
    )
    position: float | None = Field(
        default=None,
        description="Coordinate along the axis to split at. Defaults to mid-point of the mesh.",
    )
    keep: Literal["lower", "upper", "both"] = Field(
        default="lower",
        description=(
            "'lower' keeps the side below the plane, 'upper' the side above, "
            "'both' returns a Compound of both halves (still a single STL "
            "but the two halves can be separated in your slicer)."
        ),
    )
    rationale: str = Field(max_length=200)


TOOL_DEFINITION = {
    "name": "mesh_split_at_plane",
    "description": (
        "Slice the imported mesh with a plane. Use to print a tall part as "
        "two halves, or to extract a section for documentation. Default "
        "position is the geometric mid-point along the chosen axis."
    ),
    "input_schema": MeshSplitAtPlaneInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = MeshSplitAtPlaneInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    err = require_imported_mesh(ctx, "mesh_split_at_plane")
    if err is not None:
        return err

    axis_idx = {"x": 0, "y": 1, "z": 2}[params.axis]
    pos_expr = (
        f"{params.position!r}"
        if params.position is not None
        else f"((float(mesh.bounds[0][{axis_idx}]) + float(mesh.bounds[1][{axis_idx}])) / 2)"
    )
    plane_normal = [0, 0, 0]
    plane_normal[axis_idx] = 1
    keep = params.keep
    block_lines = [
        "import trimesh as _tm",
        "import numpy as _np",
        f"_pos = {pos_expr}",
        f"_n = _np.array({plane_normal!r}, dtype=float)",
        f"_origin = _np.array([0, 0, 0], dtype=float); _origin[{axis_idx}] = _pos",
    ]
    if keep == "lower":
        block_lines.append("mesh = mesh.slice_plane(_origin, -_n, cap=True)")
    elif keep == "upper":
        block_lines.append("mesh = mesh.slice_plane(_origin, _n, cap=True)")
    else:
        block_lines += [
            "_lower = mesh.slice_plane(_origin, -_n, cap=True)",
            "_upper = mesh.slice_plane(_origin, _n, cap=True)",
            "_upper.apply_translation(_n * 0.5)  # tiny gap so they read as separate",
            "mesh = _tm.util.concatenate([_lower, _upper])",
        ]
    block = "\n".join(block_lines)
    return append_block_and_build(
        ctx,
        feature_name=f"split_{params.axis}_{params.keep}",
        block=block,
        extra_result_payload={"axis": params.axis, "keep": params.keep},
    )


__all__ = ["TOOL_DEFINITION", "MeshSplitAtPlaneInput", "execute"]
