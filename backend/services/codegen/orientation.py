"""Orientation-aware overhang search for FDM manufacturability.

Many parts that look unprintable as-modeled are fine after a single rotation
that puts a different face on the build plate. This module measures the
overhang fraction at a small set of axis-aligned candidate orientations and
returns the best one. The caller can surface the result alongside the
overhang warning so the user knows whether reorienting would help.

The candidate set covers the six axis-aligned "face-down" orientations: the
identity, plus rotations that put each of the other five faces of the
bounding box on the bed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


_OVERHANG_COS_THRESHOLD = math.cos(math.radians(45))


@dataclass(frozen=True)
class OrientationCandidate:
    """One axis-aligned orientation expressed as Euler XYZ degrees."""

    label: str
    euler_deg: tuple[float, float, float]


# Six axis-aligned orientations. Each puts a different face of the bounding
# box on the bed. Euler XYZ is applied as Rx · Ry · Rz to a point.
ORIENTATION_CANDIDATES: tuple[OrientationCandidate, ...] = (
    OrientationCandidate("as-modeled", (0.0, 0.0, 0.0)),
    OrientationCandidate("flip Z (top down)", (180.0, 0.0, 0.0)),
    OrientationCandidate("rotate X +90", (90.0, 0.0, 0.0)),
    OrientationCandidate("rotate X -90", (-90.0, 0.0, 0.0)),
    OrientationCandidate("rotate Y +90", (0.0, 90.0, 0.0)),
    OrientationCandidate("rotate Y -90", (0.0, -90.0, 0.0)),
)


def compute_overhang_fraction(mesh) -> float:
    """Fraction of surface area whose normal points downward at >45°.

    Returns 0.0 for a degenerate mesh; the caller should already have
    rejected those before slicing anyway.
    """
    if len(mesh.faces) == 0:
        return 0.0
    normals = mesh.face_normals
    down = -normals[:, 2]
    overhanging = down > _OVERHANG_COS_THRESHOLD
    if not bool(np.any(overhanging)):
        return 0.0
    overhang_area = float(mesh.area_faces[overhanging].sum())
    total_area = float(mesh.area_faces.sum()) or 1.0
    return overhang_area / total_area


def find_best_print_orientation(mesh) -> tuple[OrientationCandidate, float]:
    """Return the candidate orientation with the lowest overhang fraction.

    The search rotates a copy of the mesh; the input mesh is left alone. The
    "as-modeled" candidate is always evaluated first so ties prefer keeping
    the user's chosen orientation.
    """
    import trimesh

    best: tuple[OrientationCandidate, float] | None = None
    for candidate in ORIENTATION_CANDIDATES:
        if candidate.euler_deg == (0.0, 0.0, 0.0):
            fraction = compute_overhang_fraction(mesh)
        else:
            rotated = mesh.copy()
            matrix = trimesh.transformations.euler_matrix(
                math.radians(candidate.euler_deg[0]),
                math.radians(candidate.euler_deg[1]),
                math.radians(candidate.euler_deg[2]),
                "sxyz",
            )
            rotated.apply_transform(matrix)
            fraction = compute_overhang_fraction(rotated)
        if best is None or fraction < best[1] - 1e-6:
            best = (candidate, fraction)
    assert best is not None
    return best


__all__ = [
    "ORIENTATION_CANDIDATES",
    "OrientationCandidate",
    "compute_overhang_fraction",
    "find_best_print_orientation",
]
