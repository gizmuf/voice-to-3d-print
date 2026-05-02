"""Tool: boolean-union a parametric primitive onto the mesh.

Common pattern for "add a boss", "add a tab", "extend the part with a stub."
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build, require_imported_mesh


class MeshAddPrimitiveInput(BaseModel):
    primitive: Literal["cylinder", "box", "sphere"]
    cx: float
    cy: float
    cz: float | None = Field(default=None, description="Z centre. Defaults to top of mesh.")
    radius: float | None = None
    height: float | None = None
    size_x: float | None = None
    size_y: float | None = None
    size_z: float | None = None
    name_suffix: str = ""
    rationale: str = Field(max_length=200)


TOOL_DEFINITION = {
    "name": "mesh_add_primitive",
    "description": (
        "Boolean-union a primitive onto the imported mesh. Use for adding "
        "bosses, tabs, mounting stubs, or extending the part. The primitive "
        "is positioned by `cx, cy, cz` (mm). For cylinders sitting on the "
        "top face, omit cz."
    ),
    "input_schema": MeshAddPrimitiveInput.model_json_schema(),
}


def _primitive_code(p: MeshAddPrimitiveInput) -> str:
    cz_expr = (
        f"{p.cz!r}" if p.cz is not None
        else "(float(mesh.bounds[1][2]))"
    )
    if p.primitive == "cylinder":
        radius = p.radius or 5.0
        height = p.height or 5.0
        return (
            f"_tool = _tm.creation.cylinder(radius={radius!r}, height={height!r}, sections=64)\n"
            f"_tool.apply_translation([{p.cx!r}, {p.cy!r}, {cz_expr} + ({height!r}/2)])\n"
            "mesh = _tm.boolean.union([mesh, _tool])"
        )
    if p.primitive == "box":
        sx = p.size_x or 10.0
        sy = p.size_y or 10.0
        sz = p.size_z or 5.0
        return (
            f"_tool = _tm.creation.box([{sx!r}, {sy!r}, {sz!r}])\n"
            f"_tool.apply_translation([{p.cx!r}, {p.cy!r}, {cz_expr} + ({sz!r}/2)])\n"
            "mesh = _tm.boolean.union([mesh, _tool])"
        )
    radius = p.radius or 5.0
    return (
        f"_tool = _tm.creation.icosphere(radius={radius!r}, subdivisions=3)\n"
        f"_tool.apply_translation([{p.cx!r}, {p.cy!r}, {cz_expr}])\n"
        "mesh = _tm.boolean.union([mesh, _tool])"
    )


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = MeshAddPrimitiveInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    err = require_imported_mesh(ctx, "mesh_add_primitive")
    if err is not None:
        return err

    block = (
        "import trimesh as _tm\nimport numpy as _np\n"
        + _primitive_code(params)
    )
    suffix = f"_{params.name_suffix}" if params.name_suffix else ""
    return append_block_and_build(
        ctx,
        feature_name=f"add_{params.primitive}{suffix}",
        block=block,
    )


__all__ = ["TOOL_DEFINITION", "MeshAddPrimitiveInput", "execute"]
