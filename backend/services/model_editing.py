from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import cadquery as cq
from cadquery import exporters as cq_exporters
from meshlib import mrmeshpy as mm
import numpy as np
import trimesh
from trimesh import transformations

from config import settings
from slicer_service import validate_mesh_file


PLANAR_NORMAL_TOLERANCE_DEG = 2.5
PLANAR_OFFSET_TOLERANCE_MM = 0.35
MIN_CLUSTER_AREA_MM2 = 25.0
DEFAULT_TOLERANCE_MM = 0.15


@dataclass
class ImportedModel:
    model_id: str
    job_id: str
    stl_path: Path
    glb_path: Path
    analysis: dict


@dataclass
class EditedModelResult:
    job_id: str
    model_id: str
    glb_path: Path
    stl_path: Path
    analysis: dict
    structured_edit: dict
    validation: dict
    warnings: list[str]
    fallback_strategy_used: str | None


def _job_dir(job_id: str) -> Path:
    path = settings.output_dir / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _model_dir(model_id: str) -> Path:
    path = settings.output_dir / model_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize(vector: Sequence[float]) -> np.ndarray:
    array = np.asarray(vector, dtype=float)
    length = np.linalg.norm(array)
    if length <= 1e-9:
        return array
    return array / length


def _frame_for_normal(normal: Sequence[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    z_axis = _normalize(normal)
    ref = np.array([1.0, 0.0, 0.0], dtype=float)
    if abs(float(np.dot(z_axis, ref))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0], dtype=float)
    x_axis = _normalize(np.cross(ref, z_axis))
    y_axis = _normalize(np.cross(z_axis, x_axis))
    return x_axis, y_axis, z_axis


def _project_points(
    points: np.ndarray,
    origin: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    z_axis: np.ndarray,
) -> np.ndarray:
    shifted = points - origin
    return np.column_stack(
        [
            shifted @ x_axis,
            shifted @ y_axis,
            shifted @ z_axis,
        ]
    )


def _polygon_area(points_2d: np.ndarray) -> float:
    if len(points_2d) < 3:
        return 0.0
    x = points_2d[:, 0]
    y = points_2d[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _classify_opening(points_2d: np.ndarray) -> str:
    if len(points_2d) < 3:
        return "unknown"
    bounds_min = points_2d.min(axis=0)
    bounds_max = points_2d.max(axis=0)
    extents = bounds_max - bounds_min
    width = float(extents[0])
    height = float(extents[1])
    if width <= 0 or height <= 0:
        return "unknown"
    center = (bounds_min + bounds_max) / 2.0
    distances = np.linalg.norm(points_2d - center, axis=1)
    mean_distance = float(np.mean(distances)) if len(distances) else 0.0
    radial_variation = float(np.std(distances) / mean_distance) if mean_distance > 1e-6 else 1.0
    aspect = max(width, height) / max(min(width, height), 1e-6)
    if aspect < 1.18 and radial_variation < 0.16:
        return "circle"
    if aspect > 1.8:
        return "slot"
    return "rectangle"


def _boundary_vertex_components(mesh: trimesh.Trimesh, face_indices: np.ndarray) -> list[list[int]]:
    edge_counts: dict[tuple[int, int], int] = {}
    for tri in mesh.faces[face_indices]:
        edges = ((int(tri[0]), int(tri[1])), (int(tri[1]), int(tri[2])), (int(tri[2]), int(tri[0])))
        for a, b in edges:
            key = (a, b) if a < b else (b, a)
            edge_counts[key] = edge_counts.get(key, 0) + 1

    boundary_edges = [edge for edge, count in edge_counts.items() if count == 1]
    adjacency: dict[int, list[int]] = {}
    for a, b in boundary_edges:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    visited_vertices: set[int] = set()
    components: list[list[int]] = []
    for vertex in adjacency:
        if vertex in visited_vertices:
            continue
        stack = [vertex]
        component: list[int] = []
        visited_vertices.add(vertex)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in adjacency.get(current, []):
                if neighbor in visited_vertices:
                    continue
                visited_vertices.add(neighbor)
                stack.append(neighbor)
        if len(component) >= 3:
            components.append(component)
    return components


def _neighbors_from_adjacency(face_count: int, adjacency: np.ndarray) -> list[list[int]]:
    neighbors: list[list[int]] = [[] for _ in range(face_count)]
    for a, b in adjacency:
        neighbors[int(a)].append(int(b))
        neighbors[int(b)].append(int(a))
    return neighbors


def _planar_clusters(mesh: trimesh.Trimesh) -> list[dict]:
    face_count = len(mesh.faces)
    if face_count == 0:
        return []

    neighbors = _neighbors_from_adjacency(face_count, mesh.face_adjacency)
    normals = np.asarray(mesh.face_normals, dtype=float)
    centers = np.asarray(mesh.triangles_center, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    cos_tolerance = math.cos(math.radians(PLANAR_NORMAL_TOLERANCE_DEG))
    visited = np.zeros(face_count, dtype=bool)
    clusters: list[dict] = []

    face_order = np.argsort(-areas)
    for start in face_order:
        index = int(start)
        if visited[index]:
            continue
        seed_normal = _normalize(normals[index])
        plane_offset = float(np.dot(seed_normal, centers[index]))
        stack = [index]
        visited[index] = True
        cluster_faces: list[int] = []

        while stack:
            face_index = stack.pop()
            cluster_faces.append(face_index)
            for neighbor in neighbors[face_index]:
                if visited[neighbor]:
                    continue
                if float(np.dot(seed_normal, normals[neighbor])) < cos_tolerance:
                    continue
                neighbor_offset = float(np.dot(seed_normal, centers[neighbor]))
                if abs(neighbor_offset - plane_offset) > PLANAR_OFFSET_TOLERANCE_MM:
                    continue
                visited[neighbor] = True
                stack.append(neighbor)

        cluster_area = float(np.sum(areas[cluster_faces]))
        if cluster_area < MIN_CLUSTER_AREA_MM2:
            continue

        face_indices = np.asarray(cluster_faces, dtype=int)
        vertex_indices = np.unique(mesh.faces[face_indices].reshape(-1))
        vertices = np.asarray(mesh.vertices[vertex_indices], dtype=float)
        origin = vertices.mean(axis=0)
        x_axis, y_axis, z_axis = _frame_for_normal(seed_normal)
        projected = _project_points(vertices, origin, x_axis, y_axis, z_axis)
        bounds_min = projected[:, :2].min(axis=0)
        bounds_max = projected[:, :2].max(axis=0)
        loops = _boundary_vertex_components(mesh, face_indices)

        loop_payloads: list[dict] = []
        for loop_index, loop in enumerate(loops):
            loop_points_3d = np.asarray(mesh.vertices[np.asarray(loop, dtype=int)], dtype=float)
            loop_points = _project_points(loop_points_3d, origin, x_axis, y_axis, z_axis)[:, :2]
            centroid = loop_points.mean(axis=0)
            angles = np.arctan2(loop_points[:, 1] - centroid[1], loop_points[:, 0] - centroid[0])
            order = np.argsort(angles)
            loop_points = loop_points[order]
            area = abs(_polygon_area(loop_points))
            if area <= 1e-3:
                continue
            loop_bounds_min = loop_points.min(axis=0)
            loop_bounds_max = loop_points.max(axis=0)
            extents = loop_bounds_max - loop_bounds_min
            center = (loop_bounds_min + loop_bounds_max) / 2.0
            loop_payloads.append(
                {
                    "index": loop_index,
                    "vertices_2d": [[round(float(value), 4) for value in point] for point in loop_points.tolist()],
                    "area_mm2": round(float(area), 2),
                    "center_mm": {"x": round(float(center[0]), 2), "y": round(float(center[1]), 2)},
                    "bounds_mm": {
                        "min_x": round(float(loop_bounds_min[0]), 2),
                        "max_x": round(float(loop_bounds_max[0]), 2),
                        "min_y": round(float(loop_bounds_min[1]), 2),
                        "max_y": round(float(loop_bounds_max[1]), 2),
                    },
                    "width_mm": round(float(extents[0]), 2),
                    "height_mm": round(float(extents[1]), 2),
                    "shape_guess": _classify_opening(loop_points),
                }
            )

        loop_payloads.sort(key=lambda item: item["area_mm2"], reverse=True)
        openings = loop_payloads[1:] if len(loop_payloads) > 1 else []
        for opening_number, opening in enumerate(openings, start=1):
            opening["opening_id"] = f"cluster-{index + 1}-opening-{opening_number}"

        clusters.append(
            {
                "cluster_id": f"cluster-{index + 1}",
                "face_count": int(len(face_indices)),
                "area_mm2": round(cluster_area, 2),
                "normal": [round(float(value), 6) for value in seed_normal.tolist()],
                "origin_mm": [round(float(value), 3) for value in origin.tolist()],
                "local_frame": {
                    "x_axis": [round(float(value), 6) for value in x_axis.tolist()],
                    "y_axis": [round(float(value), 6) for value in y_axis.tolist()],
                    "z_axis": [round(float(value), 6) for value in z_axis.tolist()],
                },
                "local_bounds_mm": {
                    "min_x": round(float(bounds_min[0]), 2),
                    "max_x": round(float(bounds_max[0]), 2),
                    "min_y": round(float(bounds_min[1]), 2),
                    "max_y": round(float(bounds_max[1]), 2),
                },
                "openings": openings[:16],
            }
        )

    clusters.sort(key=lambda item: item["area_mm2"], reverse=True)
    trimmed = clusters[:24]
    for cluster_number, cluster in enumerate(trimmed, start=1):
        cluster["cluster_id"] = f"cluster-{cluster_number}"
        for opening_number, opening in enumerate(cluster.get("openings", []), start=1):
            opening["opening_id"] = f"{cluster['cluster_id']}-opening-{opening_number}"
    return trimmed


def analyze_mesh(mesh: trimesh.Trimesh) -> dict:
    extents = [round(float(value), 2) for value in mesh.extents.tolist()]
    warnings: list[str] = []
    if not mesh.is_watertight:
        warnings.append("Imported STL is not watertight.")
    if extents and min(extents) < 1.2:
        warnings.append("Thin geometry detected below roughly 1.2 mm.")
    if extents and max(extents) > 350:
        warnings.append("Large geometry detected; verify printer bed fit.")
    if extents and max(extents) < 10:
        warnings.append("Model appears very small; confirm scale in millimeters.")

    clusters = _planar_clusters(mesh)
    if not clusters:
        warnings.append("No suitable planar face clusters were detected for precision edits.")

    return {
        "bounds_mm": [[round(float(value), 3) for value in row] for row in mesh.bounds.tolist()],
        "extents_mm": extents,
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "face_count": int(len(mesh.faces)),
        "vertex_count": int(len(mesh.vertices)),
        "warnings": warnings,
        "planar_face_clusters": clusters,
    }


def public_analysis_payload(analysis: dict) -> dict:
    clusters: list[dict] = []
    for cluster in analysis.get("planar_face_clusters", []):
        openings = []
        for opening in cluster.get("openings", []):
            openings.append(
                {
                    "opening_id": opening.get("opening_id"),
                    "area_mm2": opening.get("area_mm2"),
                    "center_mm": opening.get("center_mm"),
                    "bounds_mm": opening.get("bounds_mm"),
                    "width_mm": opening.get("width_mm"),
                    "height_mm": opening.get("height_mm"),
                    "shape_guess": opening.get("shape_guess"),
                }
            )
        clusters.append(
            {
                "cluster_id": cluster.get("cluster_id"),
                "face_count": cluster.get("face_count"),
                "area_mm2": cluster.get("area_mm2"),
                "normal": cluster.get("normal"),
                "origin_mm": cluster.get("origin_mm"),
                "local_bounds_mm": cluster.get("local_bounds_mm"),
                "openings": openings,
            }
        )

    return {
        "bounds_mm": analysis.get("bounds_mm", []),
        "extents_mm": analysis.get("extents_mm", []),
        "watertight": analysis.get("watertight"),
        "winding_consistent": analysis.get("winding_consistent"),
        "face_count": analysis.get("face_count"),
        "vertex_count": analysis.get("vertex_count"),
        "warnings": analysis.get("warnings", []),
        "planar_face_clusters": clusters,
    }


def _load_mesh(stl_path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load_mesh(stl_path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise RuntimeError("Uploaded model is not a single mesh.")
    return mesh


def _write_glb(mesh: trimesh.Trimesh, path: Path) -> None:
    scene = trimesh.Scene(mesh)
    path.write_bytes(scene.export(file_type="glb"))


def _write_analysis(path: Path, analysis: dict) -> None:
    try:
        path.write_text(json.dumps(analysis, indent=2))
    except Exception:
        pass


def import_model(content: bytes, filename: str, job_id: str) -> ImportedModel:
    model_id = job_id
    job_dir = _job_dir(job_id)
    stl_path = job_dir / "source.stl"
    glb_path = job_dir / "source.glb"
    analysis_path = job_dir / "analysis.json"
    stl_path.write_bytes(content)
    mesh = _load_mesh(stl_path)
    _write_glb(mesh, glb_path)
    analysis = analyze_mesh(mesh)
    _write_analysis(analysis_path, analysis)
    return ImportedModel(model_id=model_id, job_id=job_id, stl_path=stl_path, glb_path=glb_path, analysis=analysis)


def analyze_model(model_id: str, revision_id: str | None = None) -> dict:
    stl_path = _resolve_base_stl(model_id, revision_id)
    mesh = _load_mesh(stl_path)
    return analyze_mesh(mesh)


def _resolve_base_stl(model_id: str, revision_id: str | None = None) -> Path:
    if revision_id:
        revision_dir = settings.output_dir / revision_id
        for candidate in (revision_dir / "model.stl", revision_dir / "source.stl"):
            if candidate.exists():
                return candidate
    model_dir = _model_dir(model_id)
    for candidate in (model_dir / "model.stl", model_dir / "source.stl"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not find STL for model {model_id}")


def _resolve_cluster(analysis: dict, selection: dict) -> dict:
    cluster_id = selection.get("planar_face_id")
    if not cluster_id:
        raise ValueError("Selection requires planar_face_id.")
    for cluster in analysis.get("planar_face_clusters", []):
        if cluster.get("cluster_id") == cluster_id:
            return cluster
    raise ValueError("Selected planar face cluster was not found on the current model.")


def _resolve_opening(cluster: dict, selection: dict) -> dict | None:
    opening_id = selection.get("opening_id")
    if not opening_id:
        return None
    for opening in cluster.get("openings", []):
        if opening.get("opening_id") == opening_id:
            return opening
    raise ValueError("Selected opening was not found on the current planar face cluster.")


def _local_transform_matrix(cluster: dict) -> np.ndarray:
    frame = cluster["local_frame"]
    origin = np.asarray(cluster["origin_mm"], dtype=float)
    x_axis = np.asarray(frame["x_axis"], dtype=float)
    y_axis = np.asarray(frame["y_axis"], dtype=float)
    z_axis = np.asarray(frame["z_axis"], dtype=float)
    matrix = np.eye(4, dtype=float)
    matrix[:3, 0] = x_axis
    matrix[:3, 1] = y_axis
    matrix[:3, 2] = z_axis
    matrix[:3, 3] = origin
    return matrix


def _to_float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(round(float(value)))
    except Exception:
        return default


def _normalized_edit_request(selection: dict, cluster: dict, opening: dict | None, request: dict, prompt: str | None) -> dict:
    operation = str(request.get("operation") or "replace_cutout_shape")
    requested_shape = str(request.get("target_shape") or "").strip().lower()
    inferred_shape = requested_shape
    if operation == "replace_hole_with_slot":
        inferred_shape = "rounded_slot"
    elif operation == "replace_hole_with_rectangle" or operation == "replace_slot_with_rectangle":
        inferred_shape = "rectangle"
    elif operation == "replace_rectangle_with_circle":
        inferred_shape = "circle"
    elif operation == "resize_cutout":
        inferred_shape = opening.get("shape_guess", "rectangle") if opening else (requested_shape or "rectangle")
    elif not inferred_shape:
        inferred_shape = "rectangle"

    center_x = _to_float(request.get("center_x_mm"), opening["center_mm"]["x"] if opening else 0.0)
    center_y = _to_float(request.get("center_y_mm"), opening["center_mm"]["y"] if opening else 0.0)
    width_default = opening.get("width_mm", 10.0) if opening else 10.0
    height_default = opening.get("height_mm", 10.0) if opening else 10.0
    diameter_default = min(width_default, height_default)
    width_mm = _to_float(request.get("width_mm"), width_default)
    height_mm = _to_float(request.get("height_mm"), height_default)
    diameter_mm = _to_float(request.get("diameter_mm"), diameter_default)
    depth_mm = _to_float(request.get("depth_mm"), 0.0)
    corner_radius_mm = _to_float(request.get("corner_radius_mm"), 0.0)
    tolerance_mm = max(_to_float(request.get("tolerance_mm"), DEFAULT_TOLERANCE_MM), 0.0)
    count = max(_to_int(request.get("count"), 1), 1)
    spacing_mm = _to_float(request.get("spacing_mm"), 12.0)
    array_radius_mm = _to_float(request.get("array_radius_mm"), spacing_mm)
    through_all = bool(request.get("through_all", True))
    pattern = str(request.get("pattern") or ("none" if count <= 1 else "linear")).lower()
    if operation != "array_selected_cutout":
        pattern = "none" if count <= 1 else pattern
    if pattern not in {"none", "linear", "circular"}:
        pattern = "none"

    return {
        "operation": operation,
        "target_shape": inferred_shape,
        "prompt": prompt or "",
        "selection": {
            "planar_face_id": selection.get("planar_face_id"),
            "opening_id": selection.get("opening_id"),
        },
        "center_mm": {"x": round(center_x, 3), "y": round(center_y, 3)},
        "dimensions_mm": {
            "width": round(width_mm, 3),
            "height": round(height_mm, 3),
            "diameter": round(diameter_mm, 3),
            "depth": round(depth_mm, 3),
        },
        "corner_radius_mm": round(corner_radius_mm, 3),
        "through_all": through_all,
        "count": count,
        "pattern": pattern,
        "spacing_mm": round(spacing_mm, 3),
        "array_radius_mm": round(array_radius_mm, 3),
        "tolerance_mm": round(tolerance_mm, 3),
        "opening_shape_guess": opening.get("shape_guess") if opening else None,
        "cluster_bounds_mm": cluster.get("local_bounds_mm"),
    }


def _build_shape_solid(shape: str, width_mm: float, height_mm: float, diameter_mm: float, corner_radius_mm: float, extrusion_height_mm: float):
    if shape == "circle":
        radius = max(diameter_mm / 2.0, 0.6)
        return cq.Workplane("XY").cylinder(extrusion_height_mm, radius, centered=(True, True, True))
    if shape == "rounded_slot":
        slot_length = max(width_mm, height_mm)
        slot_height = max(min(width_mm, height_mm), 0.8)
        return (
            cq.Workplane("XY")
            .slot2D(slot_length, slot_height, 0)
            .extrude(extrusion_height_mm)
            .translate((0, 0, -extrusion_height_mm / 2.0))
        )
    if corner_radius_mm > 0:
        inner_width = max(width_mm - corner_radius_mm * 2.0, 0.8)
        inner_height = max(height_mm - corner_radius_mm * 2.0, 0.8)
        return (
            cq.Workplane("XY")
            .rect(inner_width, inner_height)
            .vertices()
            .circle(corner_radius_mm)
            .consolidateWires()
            .extrude(extrusion_height_mm)
            .translate((0, 0, -extrusion_height_mm / 2.0))
        )
    return cq.Workplane("XY").box(max(width_mm, 0.8), max(height_mm, 0.8), extrusion_height_mm, centered=(True, True, True))


def _export_cq_solid_to_mesh(solid, path: Path) -> trimesh.Trimesh:
    cq_exporters.export(solid, str(path))
    mesh = trimesh.load_mesh(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise RuntimeError("CadQuery export did not produce a valid mesh.")
    return mesh


def _build_local_cutter_mesh(structured_edit: dict, cluster: dict, z_min: float, z_max: float, temp_path: Path) -> trimesh.Trimesh:
    dimensions = structured_edit["dimensions_mm"]
    width_mm = float(dimensions["width"])
    height_mm = float(dimensions["height"])
    diameter_mm = float(dimensions["diameter"])
    tolerance_mm = float(structured_edit["tolerance_mm"])
    depth_mm = float(dimensions["depth"])
    through_all = bool(structured_edit["through_all"])
    total_depth = (z_max - z_min) + tolerance_mm * 4.0 if through_all else max(depth_mm, 0.8)
    base_solid = _build_shape_solid(
        structured_edit["target_shape"],
        width_mm + tolerance_mm,
        height_mm + tolerance_mm,
        diameter_mm + tolerance_mm,
        max(float(structured_edit["corner_radius_mm"]) - tolerance_mm, 0.0),
        total_depth,
    )
    base_mesh = _export_cq_solid_to_mesh(base_solid, temp_path)

    center_x = float(structured_edit["center_mm"]["x"])
    center_y = float(structured_edit["center_mm"]["y"])
    pattern = structured_edit["pattern"]
    count = int(structured_edit["count"])
    spacing_mm = float(structured_edit["spacing_mm"])
    array_radius_mm = float(structured_edit["array_radius_mm"])
    placements: list[tuple[float, float, float]] = [(center_x, center_y, 0.0)]

    if pattern == "linear" and count > 1:
        placements = [
            (center_x + (index - (count - 1) / 2.0) * spacing_mm, center_y, 0.0)
            for index in range(count)
        ]
    elif pattern == "circular" and count > 1:
        placements = []
        radius = array_radius_mm if array_radius_mm > 0 else spacing_mm
        for index in range(count):
            angle = (2.0 * math.pi * index) / count
            placements.append(
                (
                    center_x + math.cos(angle) * radius,
                    center_y + math.sin(angle) * radius,
                    math.degrees(angle),
                )
            )

    meshes: list[trimesh.Trimesh] = []
    z_center = (z_min + z_max) / 2.0 if through_all else (z_min + total_depth / 2.0 if abs(z_min) > abs(z_max) else z_max - total_depth / 2.0)
    for x, y, angle_deg in placements:
        clone = base_mesh.copy()
        if abs(angle_deg) > 1e-6:
            clone.apply_transform(transformations.rotation_matrix(math.radians(angle_deg), [0, 0, 1]))
        clone.apply_translation((x, y, z_center))
        meshes.append(clone)

    combined = trimesh.util.concatenate(meshes)
    combined.apply_transform(_local_transform_matrix(cluster))
    return combined


def _build_opening_plug_mesh(opening: dict, cluster: dict, z_min: float, z_max: float, tolerance_mm: float, temp_path: Path) -> trimesh.Trimesh:
    points = opening.get("vertices_2d") or []
    if len(points) < 3:
        raise ValueError("Selected opening does not contain enough boundary points for replacement.")
    polygon_points = [(float(point[0]), float(point[1])) for point in points]
    height = (z_max - z_min) + tolerance_mm * 4.0
    solid = (
        cq.Workplane("XY")
        .polyline(polygon_points)
        .close()
        .extrude(height)
        .translate((0, 0, z_min - tolerance_mm * 2.0))
    )
    mesh = _export_cq_solid_to_mesh(solid, temp_path)
    mesh.apply_transform(_local_transform_matrix(cluster))
    return mesh


def _save_meshlib_mesh(mesh: mm.Mesh, path: Path) -> None:
    mm.saveMesh(mesh, str(path))


def _run_meshlib_boolean(mesh_a_path: Path, mesh_b_path: Path, operation: mm.BooleanOperation, out_path: Path) -> tuple[bool, str]:
    mesh_a = mm.loadMesh(str(mesh_a_path))
    mesh_b = mm.loadMesh(str(mesh_b_path))
    result = mm.boolean(mesh_a, mesh_b, operation)
    if not result.valid():
        return False, result.errorString or "Boolean operation failed."
    _save_meshlib_mesh(result.mesh, out_path)
    return True, ""


def _run_edit_boolean_chain(
    base_stl_path: Path,
    plug_mesh: trimesh.Trimesh | None,
    cutter_mesh: trimesh.Trimesh,
    working_dir: Path,
) -> tuple[Path, str | None]:
    base_path = working_dir / "base.stl"
    base_mesh = _load_mesh(base_stl_path)
    base_mesh.export(base_path)

    tolerance_steps = [
        ("primary", plug_mesh, cutter_mesh),
        ("simplified-corners", plug_mesh, cutter_mesh.copy()),
        ("tolerance-expanded", plug_mesh, cutter_mesh.copy()),
    ]

    if tolerance_steps[2][2] is not None:
        tolerance_steps[2][2].apply_scale(1.0 + DEFAULT_TOLERANCE_MM / 20.0)

    last_error = "Boolean operation failed."
    for strategy_name, plug_candidate, cutter_candidate in tolerance_steps:
        current_base = base_path
        if plug_candidate is not None:
            plug_path = working_dir / f"{strategy_name}-plug.stl"
            plug_candidate.export(plug_path)
            union_path = working_dir / f"{strategy_name}-union.stl"
            ok, error = _run_meshlib_boolean(current_base, plug_path, mm.BooleanOperation.Union, union_path)
            if not ok:
                last_error = error
                continue
            current_base = union_path

        cutter_path = working_dir / f"{strategy_name}-cutter.stl"
        cutter_candidate.export(cutter_path)
        result_path = working_dir / f"{strategy_name}-result.stl"
        ok, error = _run_meshlib_boolean(current_base, cutter_path, mm.BooleanOperation.DifferenceAB, result_path)
        if ok:
            return result_path, strategy_name
        last_error = error
    raise RuntimeError(last_error)


def _edit_specific_warnings(structured_edit: dict, cluster: dict) -> list[str]:
    warnings: list[str] = []
    bounds = cluster.get("local_bounds_mm") or {}
    width_span = float(bounds.get("max_x", 0.0) - bounds.get("min_x", 0.0))
    height_span = float(bounds.get("max_y", 0.0) - bounds.get("min_y", 0.0))
    dims = structured_edit["dimensions_mm"]
    width = float(dims["width"])
    height = float(dims["height"])
    diameter = float(dims["diameter"])
    min_feature = min(value for value in (width, height, diameter) if value > 0)
    if min_feature < 1.2:
        warnings.append("Requested feature includes geometry below roughly 1.2 mm.")
    if width_span and width > width_span - 2.4:
        warnings.append("Edit width leaves very little wall on the selected face.")
    if height_span and height > height_span - 2.4:
        warnings.append("Edit height leaves very little wall on the selected face.")
    return warnings


def _perform_edit(
    *,
    model_id: str,
    job_id: str,
    selection: dict,
    edit_request: dict,
    prompt: str | None,
    parent_revision_id: str | None,
    preview: bool,
) -> EditedModelResult:
    if cq_exporters is None:
        raise RuntimeError("CadQuery is not available for model editing.")

    base_stl_path = _resolve_base_stl(model_id, parent_revision_id)
    base_mesh = _load_mesh(base_stl_path)
    analysis = analyze_mesh(base_mesh)
    cluster = _resolve_cluster(analysis, selection)
    opening = _resolve_opening(cluster, selection)
    structured_edit = _normalized_edit_request(selection, cluster, opening, edit_request, prompt)

    frame = cluster["local_frame"]
    origin = np.asarray(cluster["origin_mm"], dtype=float)
    x_axis = np.asarray(frame["x_axis"], dtype=float)
    y_axis = np.asarray(frame["y_axis"], dtype=float)
    z_axis = np.asarray(frame["z_axis"], dtype=float)
    local_vertices = _project_points(np.asarray(base_mesh.vertices, dtype=float), origin, x_axis, y_axis, z_axis)
    z_min = float(local_vertices[:, 2].min())
    z_max = float(local_vertices[:, 2].max())
    tolerance_mm = float(structured_edit["tolerance_mm"])

    job_dir = _job_dir(job_id)
    analysis_path = job_dir / "analysis.json"
    preview_glb_path = job_dir / "preview.glb"
    result_glb_path = preview_glb_path if preview else job_dir / "model.glb"
    result_stl_path = job_dir / "model.stl"
    temp_cutter_path = job_dir / "temp-cutter.stl"
    temp_plug_path = job_dir / "temp-plug.stl"

    cutter_mesh = _build_local_cutter_mesh(structured_edit, cluster, z_min, z_max, temp_cutter_path)
    plug_mesh = None
    if opening and structured_edit["operation"] != "resize_cutout":
        plug_mesh = _build_opening_plug_mesh(opening, cluster, z_min, z_max, tolerance_mm, temp_plug_path)
    elif opening and structured_edit["operation"] in {
        "replace_hole_with_rectangle",
        "replace_hole_with_slot",
        "replace_slot_with_rectangle",
        "replace_rectangle_with_circle",
        "replace_cutout_shape",
    }:
        plug_mesh = _build_opening_plug_mesh(opening, cluster, z_min, z_max, tolerance_mm, temp_plug_path)

    edited_stl_path, fallback_strategy_used = _run_edit_boolean_chain(base_stl_path, plug_mesh, cutter_mesh, job_dir)
    edited_mesh = _load_mesh(edited_stl_path)
    edited_mesh.export(result_stl_path)
    _write_glb(edited_mesh, result_glb_path)
    validation = validate_mesh_file(result_stl_path)
    extra_warnings = _edit_specific_warnings(structured_edit, cluster)
    if extra_warnings:
        validation["warnings"] = list(dict.fromkeys([*(validation.get("warnings") or []), *extra_warnings]))
        if validation.get("validation_status") == "ready":
            validation["validation_status"] = "needs_attention"
            validation["estimated_print_risk"] = "medium"

    current_analysis = analyze_mesh(edited_mesh)
    _write_analysis(analysis_path, current_analysis)

    return EditedModelResult(
        job_id=job_id,
        model_id=model_id,
        glb_path=result_glb_path,
        stl_path=result_stl_path,
        analysis=current_analysis,
        structured_edit=structured_edit,
        validation=validation,
        warnings=validation.get("warnings", []),
        fallback_strategy_used=fallback_strategy_used,
    )


def preview_edit(
    *,
    model_id: str,
    job_id: str,
    selection: dict,
    edit_request: dict,
    prompt: str | None = None,
    parent_revision_id: str | None = None,
) -> EditedModelResult:
    return _perform_edit(
        model_id=model_id,
        job_id=job_id,
        selection=selection,
        edit_request=edit_request,
        prompt=prompt,
        parent_revision_id=parent_revision_id,
        preview=True,
    )


def apply_edit(
    *,
    model_id: str,
    job_id: str,
    selection: dict,
    edit_request: dict,
    prompt: str | None = None,
    parent_revision_id: str | None = None,
) -> EditedModelResult:
    return _perform_edit(
        model_id=model_id,
        job_id=job_id,
        selection=selection,
        edit_request=edit_request,
        prompt=prompt,
        parent_revision_id=parent_revision_id,
        preview=False,
    )
