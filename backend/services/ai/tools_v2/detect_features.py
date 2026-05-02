"""Tool: detect cylindrical holes / cavities in the current mesh and return
their positions, radii, and Z extents.

Read-only. Lets the agent target specific features ("the four corner holes")
without writing detection code itself.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext


class DetectFeaturesInput(BaseModel):
    feature_kind: str = Field(
        default="cylindrical_holes",
        description="What to detect. Currently only 'cylindrical_holes' is supported.",
    )


TOOL_DEFINITION = {
    "name": "detect_features",
    "description": (
        "Inspect the imported mesh and return a structured list of "
        "cylindrical holes / cavities. Each result has center (x, y), "
        "radius, and z-extent. Use this when the user references specific "
        "features ('the four corner holes', 'the small hole on the right') "
        "and you need positions before editing."
    ),
    "input_schema": DetectFeaturesInput.model_json_schema(),
}


def _detect_z_holes_in_mesh(mesh, horiz_thresh: float = 0.3) -> list[dict]:
    """Same algorithm as mesh_modify_holes but exposed as a query."""
    import numpy as np

    if len(mesh.faces) == 0:
        return []
    normals = mesh.face_normals
    centers = mesh.triangles_center
    horiz = np.abs(normals[:, 2]) < horiz_thresh
    if not np.any(horiz):
        return []
    fa = mesh.face_adjacency
    if len(fa) == 0:
        return []
    fa_keep = horiz[fa[:, 0]] & horiz[fa[:, 1]]
    horiz_pairs = fa[fa_keep]
    horiz_idx = np.where(horiz)[0]
    if len(horiz_idx) == 0:
        return []
    parent: dict[int, int] = {int(i): int(i) for i in horiz_idx}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in horiz_pairs:
        union(int(a), int(b))

    groups: dict[int, list[int]] = {}
    for idx in horiz_idx:
        groups.setdefault(find(int(idx)), []).append(int(idx))

    holes: list[dict] = []
    for members in groups.values():
        if len(members) < 8:
            continue
        face_idxs = np.asarray(members)
        cs = centers[face_idxs]
        cx, cy = float(np.mean(cs[:, 0])), float(np.mean(cs[:, 1]))
        radii = np.linalg.norm(cs[:, :2] - np.array([cx, cy]), axis=1)
        if radii.size == 0:
            continue
        radius = float(np.median(radii))
        if radius < 0.1:
            continue
        if float(np.std(radii)) > max(radius * 0.25, 0.5):
            continue
        z_lo, z_hi = float(np.min(cs[:, 2])), float(np.max(cs[:, 2]))
        diffs = cs[:, :2] - np.array([cx, cy])
        norms = np.linalg.norm(diffs, axis=1, keepdims=True) + 1e-9
        outward = diffs / norms
        face_normals_xy = normals[face_idxs, :2]
        n_norms = np.linalg.norm(face_normals_xy, axis=1, keepdims=True) + 1e-9
        face_normals_xy = face_normals_xy / n_norms
        dots = np.sum(face_normals_xy * outward, axis=1)
        if float(np.median(dots)) > -0.5:
            continue
        holes.append(
            {
                "cx": round(cx, 3),
                "cy": round(cy, 3),
                "radius": round(radius, 3),
                "z_min": round(z_lo, 3),
                "z_max": round(z_hi, 3),
            }
        )
    holes.sort(key=lambda h: (h["cx"], h["cy"]))
    return holes


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = DetectFeaturesInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    if params.feature_kind != "cylindrical_holes":
        return {"error": f"Unsupported feature_kind: {params.feature_kind}"}

    last = ctx.last_build
    if last is None or "stl" not in last.artifacts:
        return {
            "error": (
                "No build artifacts to inspect. Call run_build first, "
                "or build via the inspector."
            )
        }
    stl_path = Path(last.artifacts["stl"].path)
    if not stl_path.exists():
        return {"error": f"STL artifact missing on disk: {stl_path}"}

    import trimesh

    mesh = trimesh.load_mesh(stl_path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = trimesh.util.concatenate(tuple(mesh.dump()))

    holes = _detect_z_holes_in_mesh(mesh)
    return {
        "ok": True,
        "feature_kind": params.feature_kind,
        "count": len(holes),
        "features": holes,
        "note": (
            "Each entry has cx, cy (centre), radius (mm), z_min, z_max "
            "(z extent of the hole walls). Use these with "
            "mesh_subtract_primitive / mesh_modify_holes to target individual holes."
        ),
    }


__all__ = ["TOOL_DEFINITION", "DetectFeaturesInput", "execute"]
