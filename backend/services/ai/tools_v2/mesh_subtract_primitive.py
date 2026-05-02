"""Tool: subtract a parametric primitive (cylinder/box/sphere) from the mesh.

Common pattern for "drill a hole at (x, y)", "cut a slot", "make a pocket".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build, require_imported_mesh


class MeshSubtractPrimitiveInput(BaseModel):
    primitive: Literal["cylinder", "box", "sphere"]
    cx: float = Field(description="X centre of the primitive (mm).")
    cy: float = Field(description="Y centre (mm).")
    cz: float | None = Field(
        default=None,
        description="Z centre (mm). If omitted, defaults to mid-height of the mesh.",
    )
    # Cylinder-specific
    radius: float | None = Field(default=None, description="Cylinder/sphere radius (mm).")
    height: float | None = Field(
        default=None, description="Cylinder height (mm). Default: mesh height + 2."
    )
    axis: Literal["x", "y", "z"] = Field(
        default="z",
        description="Cylinder axis. 'z' is most common (vertical hole through the part).",
    )
    # Box-specific
    size_x: float | None = None
    size_y: float | None = None
    size_z: float | None = None
    name_suffix: str = Field(
        default="",
        description="Optional suffix to disambiguate multiple cuts (e.g. 'left', 'right').",
    )
    rationale: str = Field(max_length=200, description="One sentence why.")


TOOL_DEFINITION = {
    "name": "mesh_subtract_primitive",
    "description": (
        "Boolean-subtract a primitive (cylinder, box, or sphere) from the "
        "imported mesh. Common uses: drill a hole, cut a slot, carve a "
        "pocket, route a channel. For cylinders, omit `height` to cut all "
        "the way through. Cheaper and more reliable than writing the "
        "trimesh boolean code yourself."
    ),
    "input_schema": MeshSubtractPrimitiveInput.model_json_schema(),
}


def _primitive_code(p: MeshSubtractPrimitiveInput) -> str:
    if p.primitive == "cylinder":
        radius = p.radius or 5.0
        height = p.height or "(float(mesh.bounds[1][2] - mesh.bounds[0][2]) + 2.0)"
        if p.axis == "z":
            transform = "_tm.transformations.identity_matrix()"
        elif p.axis == "x":
            transform = "_tm.transformations.rotation_matrix(_np.pi/2, [0, 1, 0])"
        else:  # y
            transform = "_tm.transformations.rotation_matrix(_np.pi/2, [1, 0, 0])"
        cz_expr = (
            f"{p.cz!r}" if p.cz is not None
            else "((float(mesh.bounds[0][2]) + float(mesh.bounds[1][2])) / 2)"
        )
        return (
            f"_tool = _tm.creation.cylinder(radius={radius!r}, height={height}, sections=64)\n"
            f"_tool.apply_transform({transform})\n"
            f"_tool.apply_translation([{p.cx!r}, {p.cy!r}, {cz_expr}])\n"
            "mesh = mesh.difference(_tool)"
        )
    if p.primitive == "box":
        sx = p.size_x or 10.0
        sy = p.size_y or 10.0
        sz = p.size_z or "(float(mesh.bounds[1][2] - mesh.bounds[0][2]) + 2.0)"
        cz_expr = (
            f"{p.cz!r}" if p.cz is not None
            else "((float(mesh.bounds[0][2]) + float(mesh.bounds[1][2])) / 2)"
        )
        return (
            f"_tool = _tm.creation.box([{sx!r}, {sy!r}, {sz}])\n"
            f"_tool.apply_translation([{p.cx!r}, {p.cy!r}, {cz_expr}])\n"
            "mesh = mesh.difference(_tool)"
        )
    # sphere
    radius = p.radius or 5.0
    cz_expr = (
        f"{p.cz!r}" if p.cz is not None
        else "((float(mesh.bounds[0][2]) + float(mesh.bounds[1][2])) / 2)"
    )
    return (
        f"_tool = _tm.creation.icosphere(radius={radius!r}, subdivisions=3)\n"
        f"_tool.apply_translation([{p.cx!r}, {p.cy!r}, {cz_expr}])\n"
        "mesh = mesh.difference(_tool)"
    )


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = MeshSubtractPrimitiveInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    err = require_imported_mesh(ctx, "mesh_subtract_primitive")
    if err is not None:
        return err

    block = (
        "import trimesh as _tm\nimport numpy as _np\n"
        + _primitive_code(params)
    )
    suffix = f"_{params.name_suffix}" if params.name_suffix else ""
    return append_block_and_build(
        ctx,
        feature_name=f"subtract_{params.primitive}{suffix}",
        block=block,
        extra_result_payload={"primitive": params.primitive},
    )


__all__ = ["TOOL_DEFINITION", "MeshSubtractPrimitiveInput", "execute"]
