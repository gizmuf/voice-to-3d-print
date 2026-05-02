"""Tool: detect cylindrical holes in an imported mesh and resize them.

This is a *macro* tool. Without it, the agent has to write ~50 lines of trimesh
detection + boolean code to do something the user phrased in 5 words ("make all
holes 1 mm smaller"). With it, Claude calls one tool, gets a structured
description of what changed, and the user sees a 3× cheaper turn.

The implementation is a single `append_feature` under the hood — it appends a
``# @feature: shrink_holes`` block that runs at preview time, so the action is
durably represented in the script and can be tweaked later (parameterised
shrink amount, undone via ``replace_feature``, etc.).
"""

from __future__ import annotations

from string import Template

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import (
    audit_then_run,
    derive_named_features,
    derive_parameters,
)
from services.codegen.store import new_revision_id, save_design


class MeshModifyHolesInput(BaseModel):
    delta_mm: float = Field(
        description=(
            "Amount in millimetres to change every hole's radius by. "
            "Positive enlarges, negative shrinks. E.g. -0.5 makes all holes "
            "1mm smaller in diameter."
        )
    )
    min_radius_mm: float | None = Field(
        default=None,
        description=(
            "Optional lower bound for hole radius. Holes smaller than this "
            "are kept as-is (set to None to allow shrinking everything)."
        ),
    )
    max_radius_mm: float | None = Field(
        default=None,
        description=(
            "Optional upper bound — only holes whose detected radius is at "
            "or below this value are modified. Lets you target small holes "
            "(e.g. screw holes) without touching larger pockets."
        ),
    )
    rationale: str = Field(max_length=200, description="One sentence why.")


TOOL_DEFINITION = {
    "name": "mesh_modify_holes",
    "description": (
        "High-level tool for imported meshes: detect every approximately "
        "cylindrical through-hole and offset its radius by `delta_mm`. "
        "Negative values shrink holes; positive enlarge them. Adds a "
        "`shrink_holes` (or `enlarge_holes`) feature block to the script so "
        "the change persists. Optional `min_radius_mm` / `max_radius_mm` "
        "filter which holes are modified by their detected size. "
        "Use this for 'make all holes smaller', 'enlarge mounting holes by "
        "0.5mm', etc. — much cheaper than writing the trimesh code yourself."
    ),
    "input_schema": MeshModifyHolesInput.model_json_schema(),
}


_FEATURE_TEMPLATE = Template('''\
# @feature: $feature_name
# Detect Z-axis cylindrical holes in `mesh` and offset each by $delta_mm mm.
import trimesh as _tm
import numpy as _np


def _detect_z_holes(_m, _horiz_thresh=0.3):
    """Find Z-axis cylindrical holes via face-normal clustering.

    Faces with near-horizontal normals are wall faces. Each connected
    component of such faces (sharing edges) is one cylindrical wall — one
    hole. We compute its centroid + radius and filter to keep only inward-
    facing walls (genuine holes, not bosses).
    """
    if len(_m.faces) == 0:
        return []
    normals = _m.face_normals
    centers = _m.triangles_center
    horiz = _np.abs(normals[:, 2]) < _horiz_thresh
    if not _np.any(horiz):
        return []
    fa = _m.face_adjacency
    if len(fa) == 0:
        return []
    fa_keep = horiz[fa[:, 0]] & horiz[fa[:, 1]]
    horiz_pairs = fa[fa_keep]
    horiz_idx = _np.where(horiz)[0]
    if len(horiz_idx) == 0:
        return []
    parent = dict()
    for i in horiz_idx:
        parent[int(i)] = int(i)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in horiz_pairs:
        union(int(a), int(b))

    groups = dict()
    for idx in horiz_idx:
        root = find(int(idx))
        groups.setdefault(root, []).append(int(idx))

    holes = []
    for root, members in groups.items():
        if len(members) < 8:
            continue
        face_idxs = _np.asarray(members)
        cs = centers[face_idxs]
        cx, cy = float(_np.mean(cs[:, 0])), float(_np.mean(cs[:, 1]))
        radii = _np.linalg.norm(cs[:, :2] - _np.array([cx, cy]), axis=1)
        if radii.size == 0:
            continue
        radius = float(_np.median(radii))
        if radius < 0.1:
            continue
        if float(_np.std(radii)) > max(radius * 0.25, 0.5):
            continue
        z_lo, z_hi = float(_np.min(cs[:, 2])), float(_np.max(cs[:, 2]))
        # Outward-from-axis direction at each face center
        diffs = cs[:, :2] - _np.array([cx, cy])
        norms = _np.linalg.norm(diffs, axis=1, keepdims=True) + 1e-9
        outward = diffs / norms
        face_normals_xy = normals[face_idxs, :2]
        n_norms = _np.linalg.norm(face_normals_xy, axis=1, keepdims=True) + 1e-9
        face_normals_xy = face_normals_xy / n_norms
        dots = _np.sum(face_normals_xy * outward, axis=1)
        # Hole walls face INTO the void → dots < 0. Bosses (outer cylinders)
        # have dots > 0; we skip those.
        if float(_np.median(dots)) > -0.5:
            continue
        holes.append(dict(cx=cx, cy=cy, radius=radius, z_min=z_lo, z_max=z_hi))
    return holes


def _modify_holes(_m, delta, min_r, max_r):
    holes = _detect_z_holes(_m)
    if not holes:
        return _m, []
    z_lo = float(_m.bounds[0][2]) - 1.0
    z_hi = float(_m.bounds[1][2]) + 1.0
    height = z_hi - z_lo
    cutters, fillers, applied = [], [], []
    for h in holes:
        radius = h["radius"]
        if min_r is not None and radius < min_r:
            continue
        if max_r is not None and radius > max_r:
            continue
        new_r = max(radius + delta, 0.05)
        if abs(new_r - radius) < 1e-3:
            continue
        cy_mid = (z_lo + z_hi) / 2
        if new_r > radius:
            cyl = _tm.creation.cylinder(radius=new_r, height=height, sections=64)
            cyl.apply_translation([h["cx"], h["cy"], cy_mid])
            cutters.append(cyl)
        else:
            outer = _tm.creation.cylinder(radius=radius, height=height, sections=64)
            inner = _tm.creation.cylinder(radius=new_r, height=height + 2, sections=64)
            ring = outer.difference(inner)
            ring.apply_translation([h["cx"], h["cy"], cy_mid])
            fillers.append(ring)
        applied.append(dict(cx=h["cx"], cy=h["cy"], old_r=radius, new_r=new_r))
    out = _m.copy()
    if fillers:
        out = _tm.boolean.union([out, *fillers])
    for c in cutters:
        out = out.difference(c)
    return out, applied


mesh, _hole_changes = _modify_holes(mesh, $delta_mm, $min_r_repr, $max_r_repr)
log(f"hole_modify: {len(_hole_changes)} hole(s) changed, delta=$delta_mm mm")
# @end
''')


def _format_optional_float(v: float | None) -> str:
    if v is None:
        return "None"
    return f"{float(v):.6g}"


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = MeshModifyHolesInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    if not ctx.design.metadata.get("imported_files"):
        return {
            "error": (
                "mesh_modify_holes only works on designs seeded from an STL "
                "upload. The current design is parametric — use "
                "update_parameter on the relevant hole_diameter instead."
            ),
        }

    feature_name = "shrink_holes" if params.delta_mm < 0 else "enlarge_holes"
    block = _FEATURE_TEMPLATE.substitute(
        feature_name=feature_name,
        delta_mm=f"{params.delta_mm:.6g}",
        min_r_repr=_format_optional_float(params.min_radius_mm),
        max_r_repr=_format_optional_float(params.max_radius_mm),
    )

    # Insert before the `result = ...` line.
    script = ctx.design.script
    lines = script.splitlines()
    insert_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("result"):
            insert_idx = i
            break
    new_script = "\n".join(lines[:insert_idx] + ["", block] + lines[insert_idx:])

    overrides = {p.name: p.value for p in ctx.design.parameters}
    sandbox_result = audit_then_run(
        script=new_script,
        parameter_overrides=overrides,
        targets=["stl"],
        imported_files=ctx.design.metadata.get("imported_files") or None,
    )
    if not sandbox_result.ok:
        return {
            "error": (
                "Hole modification build failed; design unchanged. "
                f"Sandbox said: {sandbox_result.payload.get('error')}"
            ),
            "traceback": (sandbox_result.payload.get("traceback") or "")[:600],
        }

    ctx.design.parent_revision_id = ctx.design.revision_id
    ctx.design.revision_id = new_revision_id()
    ctx.design.script = new_script
    ctx.design.parameters = derive_parameters(sandbox_result.payload)
    ctx.design.features = derive_named_features(sandbox_result.payload, new_script)
    save_design(ctx.design)
    return {
        "ok": True,
        "feature_name": feature_name,
        "delta_mm": params.delta_mm,
        "min_radius_mm": params.min_radius_mm,
        "max_radius_mm": params.max_radius_mm,
        "new_revision_id": ctx.design.revision_id,
    }


__all__ = ["TOOL_DEFINITION", "MeshModifyHolesInput", "execute"]
