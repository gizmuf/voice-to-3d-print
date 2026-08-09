from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from services.printer_profiles import PrinterProfile, get_profile


Severity = Literal["info", "warn", "error"]
Status = Literal["safe", "warn", "unprintable"]


class Issue(BaseModel):
    severity: Severity
    code: str
    message: str
    location: tuple[float, float, float] | None = None
    suggestion: str | None = None


class ManufacturabilityReport(BaseModel):
    status: Status
    issues: list[Issue] = Field(default_factory=list)
    estimated_volume_mm3: float | None = None
    bounding_box_mm: tuple[float, float, float] | None = None
    printer_profile_id: str
    mesh_hash: str
    duration_ms: int


_OVERHANG_ANGLE_DEG = 45.0


def _hash_mesh(mesh: trimesh.Trimesh) -> str:
    """Stable identifier for a mesh's geometry only."""
    h = hash((mesh.vertices.tobytes(), mesh.faces.tobytes()))
    return f"{h & 0xFFFFFFFFFFFFFFFF:016x}"


def _check_manifold(mesh: trimesh.Trimesh, issues: list[Issue]) -> None:
    if not mesh.is_watertight:
        issues.append(
            Issue(
                severity="error",
                code="non_watertight",
                message="Mesh is not watertight — has holes or open edges.",
                suggestion="Run mesh repair or re-export from CAD with closed boundaries.",
            )
        )
    if not mesh.is_winding_consistent:
        issues.append(
            Issue(
                severity="warn",
                code="winding_inconsistent",
                message="Mesh face normals are inconsistent.",
                suggestion="Run mesh repair to recompute outward normals.",
            )
        )
    if abs(float(mesh.volume)) <= 0:
        issues.append(
            Issue(
                severity="error",
                code="zero_volume",
                message="Mesh has zero or negative volume.",
                suggestion="Inspect for inverted or degenerate geometry.",
            )
        )


def _check_print_volume(
    mesh: trimesh.Trimesh, profile: PrinterProfile, issues: list[Issue]
) -> None:
    extents = mesh.bounding_box.extents
    bx, by, bz = profile.bed_size_mm
    overflows: list[str] = []
    if extents[0] > bx:
        overflows.append(f"X {extents[0]:.1f} > {bx:.1f}")
    if extents[1] > by:
        overflows.append(f"Y {extents[1]:.1f} > {by:.1f}")
    if extents[2] > bz:
        overflows.append(f"Z {extents[2]:.1f} > {bz:.1f}")
    if overflows:
        issues.append(
            Issue(
                severity="error",
                code="exceeds_bed",
                message=f"Model exceeds printer bed on {', '.join(overflows)} (mm).",
                suggestion="Scale the model down or pick a larger printer profile.",
            )
        )


def _check_overhangs(mesh: trimesh.Trimesh, issues: list[Issue]) -> None:
    """Flag faces overhanging steeper than threshold relative to build plate (-Z)."""
    if len(mesh.faces) == 0:
        return
    cos_threshold = math.cos(math.radians(_OVERHANG_ANGLE_DEG))
    normals = mesh.face_normals
    z_min = float(mesh.bounds[0][2])
    centers = mesh.triangles_center
    # Faces pointing downward (normal dotted with -Z > cos(45)) are overhang candidates.
    down = -normals[:, 2]
    supported_by_bed = centers[:, 2] <= z_min + 0.25
    overhanging = (down > cos_threshold) & ~supported_by_bed
    if not bool(np.any(overhanging)):
        return
    overhang_area = float(mesh.area_faces[overhanging].sum())
    total_area = float(mesh.area_faces.sum())
    if total_area <= 0:
        return
    fraction = overhang_area / total_area
    if fraction < 0.02:
        return
    centroid_idx = int(np.argmax(mesh.area_faces * overhanging))
    location = tuple(float(c) for c in mesh.triangles_center[centroid_idx])
    severity: Severity = "error" if fraction > 0.20 else "warn"
    issues.append(
        Issue(
            severity=severity,
            code="overhang_steep",
            message=(
                f"~{fraction*100:.0f}% of surface area overhangs at greater than "
                f"{_OVERHANG_ANGLE_DEG:.0f}°."
            ),
            location=location,
            suggestion="Add support material, reorient on the build plate, or chamfer the overhang.",
        )
    )


def _check_min_wall(
    mesh: trimesh.Trimesh, profile: PrinterProfile, issues: list[Issue], samples: int = 300
) -> None:
    """Sampled inward ray-cast to estimate the thinnest wall in the part."""
    if len(mesh.faces) == 0 or not mesh.is_watertight:
        return
    threshold = max(profile.nozzle_mm * 2.0, 0.8)
    points, face_indices = trimesh.sample.sample_surface(mesh, samples)
    normals = mesh.face_normals[face_indices]
    # Step slightly inward to avoid hitting the originating face.
    epsilon = max(profile.nozzle_mm * 0.1, 0.01)
    origins = points - normals * epsilon
    directions = -normals
    locations, ray_index, triangle_index = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=directions, multiple_hits=False
    )
    if len(ray_index) == 0:
        return
    distances = np.linalg.norm(locations - origins[ray_index], axis=1)
    hit_normals = mesh.face_normals[triangle_index]
    source_normals = normals[ray_index]
    opposing = np.einsum("ij,ij->i", source_normals, hit_normals) < -0.5
    distances = distances[opposing]
    filtered_ray_index = ray_index[opposing]
    if len(distances) == 0:
        return
    thin_mask = distances < threshold
    if not bool(np.any(thin_mask)):
        return
    thinnest_idx = int(np.argmin(distances))
    thinnest = float(distances[thinnest_idx])
    location = tuple(float(c) for c in points[filtered_ray_index[thinnest_idx]])
    fraction = float(np.sum(thin_mask)) / float(samples)
    severity: Severity = "error" if thinnest < profile.nozzle_mm * 1.5 else "warn"
    issues.append(
        Issue(
            severity=severity,
            code="min_wall_thin",
            message=(
                f"Wall thickness as low as {thinnest:.2f} mm "
                f"(threshold {threshold:.2f} mm; ~{fraction*100:.0f}% of sampled points)."
            ),
            location=location,
            suggestion="Thicken thin sections to at least 0.8 mm for FDM, or 2x nozzle diameter.",
        )
    )


def _aggregate_status(issues: list[Issue]) -> Status:
    if any(i.severity == "error" for i in issues):
        return "unprintable"
    if any(i.severity == "warn" for i in issues):
        return "warn"
    return "safe"


def check_mesh(
    mesh: trimesh.Trimesh, profile: PrinterProfile | None = None
) -> ManufacturabilityReport:
    """Run all manufacturability checks on a loaded mesh."""
    import time

    started = time.perf_counter()
    profile = profile or get_profile()
    issues: list[Issue] = []
    _check_manifold(mesh, issues)
    _check_print_volume(mesh, profile, issues)
    _check_overhangs(mesh, issues)
    try:
        _check_min_wall(mesh, profile, issues)
    except Exception as exc:  # ray-casting can fail on degenerate meshes
        issues.append(
            Issue(
                severity="info",
                code="min_wall_skipped",
                message=f"Wall-thickness check could not run: {exc}",
            )
        )
    duration_ms = int((time.perf_counter() - started) * 1000)
    try:
        volume = float(abs(mesh.volume)) if mesh.is_volume else None
    except Exception:
        volume = None
    return ManufacturabilityReport(
        status=_aggregate_status(issues),
        issues=issues,
        estimated_volume_mm3=volume,
        bounding_box_mm=tuple(float(v) for v in mesh.bounding_box.extents),
        printer_profile_id=profile.id,
        mesh_hash=_hash_mesh(mesh),
        duration_ms=duration_ms,
    )


def check_stl_file(
    stl_path: Path, profile: PrinterProfile | None = None
) -> ManufacturabilityReport:
    """Convenience wrapper: load an STL from disk and run checks."""
    mesh = trimesh.load_mesh(stl_path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        # `load_mesh` may return a Scene if the file has multiple parts.
        mesh = trimesh.util.concatenate(tuple(mesh.dump()))  # type: ignore[arg-type]
    return check_mesh(mesh, profile)
