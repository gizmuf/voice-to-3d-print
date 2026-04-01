from __future__ import annotations

import hashlib
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
MAX_OPENINGS_PER_CLUSTER = 512
FEATURE_ID_QUANTIZATION_MM = 0.05
CIRCLE_GROUP_TOLERANCE_MM = 0.35
RECT_GROUP_TOLERANCE_MM = 0.5
PATTERN_TARGET_MIN_COUNT = 4
MIN_PATTERN_WALL_MM = 0.8
TARGET_SELECTABLE_CONFIDENCE = 0.7
TARGET_PRIMARY_CONFIDENCE = 0.85


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
                "openings": openings[:MAX_OPENINGS_PER_CLUSTER],
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


def _quantize_mm(value: float, step: float = FEATURE_ID_QUANTIZATION_MM) -> float:
    if step <= 0:
        return round(value, 4)
    return round(round(value / step) * step, 4)


def _hash_id(prefix: str, *parts: object) -> str:
    payload = "::".join(str(part) for part in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _stable_face_id(cluster: dict) -> str:
    normal = cluster.get("normal") or [0.0, 0.0, 1.0]
    origin = cluster.get("origin_mm") or [0.0, 0.0, 0.0]
    bounds = cluster.get("local_bounds_mm") or {}
    plane_offset = sum(float(normal[index]) * float(origin[index]) for index in range(3))
    return _hash_id(
        "face",
        *(round(float(value), 4) for value in normal),
        _quantize_mm(float(plane_offset)),
        _quantize_mm(float(bounds.get("min_x", 0.0))),
        _quantize_mm(float(bounds.get("max_x", 0.0))),
        _quantize_mm(float(bounds.get("min_y", 0.0))),
        _quantize_mm(float(bounds.get("max_y", 0.0))),
    )


def _stable_feature_id(face_id: str, opening: dict) -> str:
    center = opening.get("center_mm") or {}
    return _hash_id(
        "feature",
        face_id,
        _quantize_mm(float(center.get("x", 0.0))),
        _quantize_mm(float(center.get("y", 0.0))),
    )


def _openings_match_for_group(group: dict, opening: dict) -> bool:
    opening_shape = opening.get("shape_guess") or opening.get("type")
    if group["shape_guess"] != opening_shape:
        return False
    width_delta = abs(group["avg_width"] - float(opening.get("width_mm", 0.0)))
    height_delta = abs(group["avg_height"] - float(opening.get("height_mm", 0.0)))
    if opening_shape == "circle":
        return max(width_delta, height_delta) <= CIRCLE_GROUP_TOLERANCE_MM
    return width_delta <= RECT_GROUP_TOLERANCE_MM and height_delta <= RECT_GROUP_TOLERANCE_MM


def _group_title(shape_guess: str, count: int, avg_width: float, avg_height: float) -> str:
    avg_size = (avg_width + avg_height) / 2.0
    if count > 1:
        return "Small repeated holes" if avg_size <= 12.0 else "Repeated openings"
    return "Large opening" if avg_size > 15.0 else "Single opening"


def _face_bounds_center(cluster: dict) -> tuple[float, float]:
    bounds = cluster.get("local_bounds_mm") or {}
    return (
        (float(bounds.get("min_x", 0.0)) + float(bounds.get("max_x", 0.0))) / 2.0,
        (float(bounds.get("min_y", 0.0)) + float(bounds.get("max_y", 0.0))) / 2.0,
    )


def _cluster_scalar_values(values: Sequence[float], tolerance: float) -> list[float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return []
    buckets: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if abs(value - buckets[-1][-1]) <= tolerance:
            buckets[-1].append(value)
        else:
            buckets.append([value])
    return [round(sum(bucket) / len(bucket), 3) for bucket in buckets]


def _feature_major_dimension(feature: dict) -> float:
    return max(
        float(feature.get("width_mm", 0.0) or 0.0),
        float(feature.get("height_mm", 0.0) or 0.0),
        float(feature.get("diameter_mm", 0.0) or 0.0),
    )


def _feature_minor_dimension(feature: dict) -> float:
    candidates = [
        float(feature.get("width_mm", 0.0) or 0.0),
        float(feature.get("height_mm", 0.0) or 0.0),
        float(feature.get("diameter_mm", 0.0) or 0.0),
    ]
    non_zero = [value for value in candidates if value > 0]
    return min(non_zero) if non_zero else 0.0


def _target_id(prefix: str, *parts: object) -> str:
    return _hash_id(prefix, *parts)


def _face_frame_payload(cluster: dict) -> dict:
    frame = cluster.get("local_frame") or {}
    return {
        "origin": [round(float(value), 4) for value in (cluster.get("origin_mm") or [0.0, 0.0, 0.0])],
        "x_axis": [round(float(value), 6) for value in (frame.get("x_axis") or [1.0, 0.0, 0.0])],
        "y_axis": [round(float(value), 6) for value in (frame.get("y_axis") or [0.0, 1.0, 0.0])],
        "normal": [round(float(value), 6) for value in (cluster.get("normal") or frame.get("z_axis") or [0.0, 0.0, 1.0])],
    }


def _face_polygon_2d(cluster: dict) -> list[list[float]]:
    bounds = cluster.get("local_bounds_mm") or {}
    min_x = float(bounds.get("min_x", 0.0))
    max_x = float(bounds.get("max_x", 0.0))
    min_y = float(bounds.get("min_y", 0.0))
    max_y = float(bounds.get("max_y", 0.0))
    return [
        [round(min_x, 4), round(min_y, 4)],
        [round(max_x, 4), round(min_y, 4)],
        [round(max_x, 4), round(max_y, 4)],
        [round(min_x, 4), round(max_y, 4)],
    ]


def _circle_outline(center_x: float, center_y: float, radius: float, segments: int = 24) -> list[list[float]]:
    return [
        [
            round(center_x + math.cos((2.0 * math.pi * index) / segments) * radius, 4),
            round(center_y + math.sin((2.0 * math.pi * index) / segments) * radius, 4),
        ]
        for index in range(segments)
    ]


def _opening_outline_2d(opening: dict) -> list[list[float]]:
    if opening.get("vertices_2d"):
        return [
            [round(float(point[0]), 4), round(float(point[1]), 4)]
            for point in opening["vertices_2d"]
            if len(point) >= 2
        ]

    center = opening.get("center_mm") or {}
    center_x = float(center.get("x", 0.0))
    center_y = float(center.get("y", 0.0))
    width = float(opening.get("width_mm", 0.0) or 0.0)
    height = float(opening.get("height_mm", 0.0) or 0.0)
    if (opening.get("shape_guess") or opening.get("type")) == "circle":
        return _circle_outline(center_x, center_y, min(width, height) / 2.0)

    half_width = width / 2.0
    half_height = height / 2.0
    return [
        [round(center_x - half_width, 4), round(center_y - half_height, 4)],
        [round(center_x + half_width, 4), round(center_y - half_height, 4)],
        [round(center_x + half_width, 4), round(center_y + half_height, 4)],
        [round(center_x - half_width, 4), round(center_y + half_height, 4)],
    ]


def _feature_geometry_2d(cluster: dict, features: Sequence[dict]) -> list[dict]:
    openings_by_id = {
        opening.get("opening_id"): opening
        for opening in cluster.get("openings", [])
        if opening.get("opening_id")
    }
    geometry: list[dict] = []
    for feature in features:
        opening = openings_by_id.get(feature.get("opening_id"))
        geometry.append(
            {
                "id": feature["id"],
                "center": [
                    round(float(feature["center_mm"]["x"]), 4),
                    round(float(feature["center_mm"]["y"]), 4),
                ],
                "outline": _opening_outline_2d(opening or feature),
            }
        )
    return geometry


def _build_feature_projection(analysis: dict) -> dict:
    projected_clusters: list[dict] = []
    features: list[dict] = []
    groups: list[dict] = []

    for cluster in analysis.get("planar_face_clusters", []):
        face_id = _stable_face_id(cluster)
        cluster_openings = cluster.get("openings", [])
        cluster_features: list[dict] = []

        for opening in cluster_openings:
            center = opening.get("center_mm") or {}
            width_mm = float(opening.get("width_mm", 0.0) or 0.0)
            height_mm = float(opening.get("height_mm", 0.0) or 0.0)
            if min(width_mm, height_mm) < 1.0:
                continue
            feature = {
                "id": _stable_feature_id(face_id, opening),
                "type": opening.get("shape_guess", "unknown"),
                "face_id": face_id,
                "cluster_id": cluster.get("cluster_id"),
                "opening_id": opening.get("opening_id"),
                "center_mm": {
                    "x": round(float(center.get("x", 0.0)), 3),
                    "y": round(float(center.get("y", 0.0)), 3),
                },
                "width_mm": width_mm,
                "height_mm": height_mm,
                "diameter_mm": round(
                    min(width_mm, height_mm),
                    3,
                ),
                "bounds_mm": opening.get("bounds_mm"),
                "group_id": None,
                "summary": f"{opening.get('shape_guess', 'opening')} · {float(opening.get('width_mm', 0.0)):.2f} × {float(opening.get('height_mm', 0.0)):.2f} mm",
            }
            cluster_features.append(feature)
            features.append(feature)

        grouped_buckets: list[dict] = []
        for feature in cluster_features:
            match = next((bucket for bucket in grouped_buckets if _openings_match_for_group(bucket, feature)), None)
            if not match:
                grouped_buckets.append(
                    {
                        "shape_guess": feature["type"],
                        "avg_width": float(feature.get("width_mm", 0.0) or 0.0),
                        "avg_height": float(feature.get("height_mm", 0.0) or 0.0),
                        "features": [feature],
                    }
                )
                continue
            match["features"].append(feature)
            match["avg_width"] = sum(float(item.get("width_mm", 0.0) or 0.0) for item in match["features"]) / len(match["features"])
            match["avg_height"] = sum(float(item.get("height_mm", 0.0) or 0.0) for item in match["features"]) / len(match["features"])

        grouped_buckets.sort(
            key=lambda bucket: (
                -len(bucket["features"]),
                bucket["avg_width"] + bucket["avg_height"],
            )
        )

        projected_groups: list[dict] = []
        for bucket in grouped_buckets:
            representative = min(
                bucket["features"],
                key=lambda item: math.hypot(
                    float(item.get("width_mm", 0.0) or 0.0) - bucket["avg_width"],
                    float(item.get("height_mm", 0.0) or 0.0) - bucket["avg_height"],
                ),
            )
            group_id = _hash_id(
                "group",
                face_id,
                bucket["shape_guess"],
                _quantize_mm(bucket["avg_width"]),
                _quantize_mm(bucket["avg_height"]),
            )
            for feature in bucket["features"]:
                feature["group_id"] = group_id
            projected_group = {
                "id": group_id,
                "type": bucket["shape_guess"],
                "face_id": face_id,
                "cluster_id": cluster.get("cluster_id"),
                "count": len(bucket["features"]),
                "representative_feature_id": representative["id"],
                "feature_ids": [feature["id"] for feature in bucket["features"]],
                "opening_ids": [feature["opening_id"] for feature in bucket["features"]],
                "title": _group_title(bucket["shape_guess"], len(bucket["features"]), bucket["avg_width"], bucket["avg_height"]),
                "summary": f"{bucket['shape_guess']} · {len(bucket['features'])} opening{'s' if len(bucket['features']) != 1 else ''} · {bucket['avg_width']:.1f} × {bucket['avg_height']:.1f} mm",
                "avg_width_mm": round(bucket["avg_width"], 3),
                "avg_height_mm": round(bucket["avg_height"], 3),
            }
            projected_groups.append(projected_group)
            groups.append(projected_group)

        projected_clusters.append(
            {
                "cluster_id": cluster.get("cluster_id"),
                "face_id": face_id,
                "face_count": cluster.get("face_count"),
                "area_mm2": cluster.get("area_mm2"),
                "normal": cluster.get("normal"),
                "origin_mm": cluster.get("origin_mm"),
                "local_frame": cluster.get("local_frame"),
                "local_bounds_mm": cluster.get("local_bounds_mm"),
                "openings": cluster_openings,
                "groups": projected_groups,
            }
        )

    return {
        "clusters": projected_clusters,
        "features": features,
        "groups": groups,
    }


def _detect_center_hole_for_target(cluster: dict, face_features: Sequence[dict], excluded_feature_ids: set[str]) -> dict | None:
    center_x, center_y = _face_bounds_center(cluster)
    best_feature: dict | None = None
    best_score = float("inf")
    for feature in face_features:
        if feature["id"] in excluded_feature_ids:
            continue
        if feature.get("type") != "circle":
            continue
        diameter = float(feature.get("diameter_mm", 0.0) or 0.0)
        if diameter < 8.0:
            continue
        center = feature.get("center_mm") or {}
        distance = math.hypot(float(center.get("x", 0.0)) - center_x, float(center.get("y", 0.0)) - center_y)
        score = distance - diameter * 0.12
        if score < best_score:
            best_feature = feature
            best_score = score
    return best_feature


def _fit_rectangular_pattern_target(group: dict, cluster: dict, face_features: Sequence[dict]) -> dict | None:
    features = [feature for feature in face_features if feature["id"] in set(group.get("feature_ids") or [])]
    if len(features) < PATTERN_TARGET_MIN_COUNT:
        return None

    avg_width = float(group.get("avg_width_mm", 0.0) or 0.0)
    avg_height = float(group.get("avg_height_mm", 0.0) or 0.0)
    line_tolerance_x = max(avg_width * 0.6, 0.8)
    line_tolerance_y = max(avg_height * 0.6, 0.8)
    x_positions = _cluster_scalar_values([feature["center_mm"]["x"] for feature in features], line_tolerance_x)
    y_positions = _cluster_scalar_values([feature["center_mm"]["y"] for feature in features], line_tolerance_y)
    if len(x_positions) < 2 or len(y_positions) < 2:
        return None

    expected = max(len(x_positions) * len(y_positions), 1)
    occupancy = len(features) / expected
    if occupancy < 0.45:
        return None
    if occupancy > 1.35:
        return None

    spacing_x = round(
        sum(abs(right - left) for left, right in zip(x_positions, x_positions[1:])) / max(len(x_positions) - 1, 1),
        3,
    )
    spacing_y = round(
        sum(abs(right - left) for left, right in zip(y_positions, y_positions[1:])) / max(len(y_positions) - 1, 1),
        3,
    )
    bounds = cluster.get("local_bounds_mm") or {}
    min_margin = min(
        min(float(feature["bounds_mm"]["min_x"]) - float(bounds.get("min_x", 0.0)) for feature in features),
        min(float(bounds.get("max_x", 0.0)) - float(feature["bounds_mm"]["max_x"]) for feature in features),
        min(float(feature["bounds_mm"]["min_y"]) - float(bounds.get("min_y", 0.0)) for feature in features),
        min(float(bounds.get("max_y", 0.0)) - float(feature["bounds_mm"]["max_y"]) for feature in features),
    )
    center_hole = _detect_center_hole_for_target(cluster, face_features, set(group.get("feature_ids") or []))
    confidence = min(0.96, 0.52 + min(occupancy, 1.0) * 0.28 + (0.08 if len(features) >= 8 else 0.0))
    editable = confidence >= TARGET_SELECTABLE_CONFIDENCE
    warnings = []
    if confidence < TARGET_SELECTABLE_CONFIDENCE:
        warnings.append("Detected pattern is too low-confidence for safe editing.")
    elif confidence < TARGET_PRIMARY_CONFIDENCE:
        warnings.append("Detected pattern is editable, but verify the target before previewing changes.")

    element_type = "circular_hole" if group.get("type") == "circle" else "rectangular_cutout"
    size_text = (
        f"{group['avg_width_mm']:.2f} mm"
        if element_type == "circular_hole"
        else f"{group['avg_width_mm']:.2f} × {group['avg_height_mm']:.2f} mm"
    )
    return {
        "id": _target_id("target", cluster.get("face_id"), "rectangular", group.get("id")),
        "type": "planar_pattern_face",
        "confidence": round(confidence, 3),
        "editable": editable,
        "label": "Rectangular repeated pattern",
        "summary": f"{len(features)} repeated {group.get('type')} openings on a planar grid · {size_text}",
        "preview_capability": "supported" if editable else "limited",
        "supported_operations": ["resize_feature", "adjust_spacing", "adjust_count", "adjust_margin"],
        "warnings": warnings,
        "topology": "rectangular",
        "element_type": element_type,
        "feature_kind": element_type,
        "face_frame": _face_frame_payload(cluster),
        "face_polygon_2d": _face_polygon_2d(cluster),
        "feature_geometry_2d": _feature_geometry_2d(cluster, features),
        "feature_ids": list(group.get("feature_ids") or []),
        "face_id": cluster.get("face_id"),
        "measured": {
            "feature_size": round(float(group.get("avg_width_mm", 0.0)), 3)
            if element_type == "circular_hole"
            else {
                "width": round(float(group.get("avg_width_mm", 0.0)), 3),
                "height": round(float(group.get("avg_height_mm", 0.0)), 3),
            },
            "spacing_x": spacing_x,
            "spacing_y": spacing_y,
            "count_x": len(x_positions),
            "count_y": len(y_positions),
            "margin": round(max(min_margin, 0.0), 3),
            "center_hole_diameter": round(float(center_hole.get("diameter_mm", 0.0)), 3) if center_hole else None,
        },
        "pattern": {
            "element_type": element_type,
            "count": len(features),
            "spacing_x": spacing_x,
            "spacing_y": spacing_y,
            "count_x": len(x_positions),
            "count_y": len(y_positions),
            "margin": round(max(min_margin, 0.0), 3),
            "center_hole_diameter": round(float(center_hole.get("diameter_mm", 0.0)), 3) if center_hole else None,
        },
        "dimensions": {
            "hole_diameter": round(float(group.get("avg_width_mm", 0.0)), 3)
            if element_type == "circular_hole"
            else None,
            "width": round(float(group.get("avg_width_mm", 0.0)), 3),
            "height": round(float(group.get("avg_height_mm", 0.0)), 3),
        },
        "fit": {
            "center_x": round(sum(x_positions) / len(x_positions), 3),
            "center_y": round(sum(y_positions) / len(y_positions), 3),
            "x_positions": x_positions,
            "y_positions": y_positions,
            "center_hole_feature_id": center_hole["id"] if center_hole else None,
        },
    }


def _fit_radial_pattern_target(group: dict, cluster: dict, face_features: Sequence[dict]) -> dict | None:
    features = [feature for feature in face_features if feature["id"] in set(group.get("feature_ids") or [])]
    if len(features) < PATTERN_TARGET_MIN_COUNT:
        return None

    center_x, center_y = _face_bounds_center(cluster)
    radii = [
        math.hypot(float(feature["center_mm"]["x"]) - center_x, float(feature["center_mm"]["y"]) - center_y)
        for feature in features
    ]
    average_size = max(float(group.get("avg_width_mm", 0.0) or 0.0), 1.0)
    ring_tolerance = max(average_size * 0.75, 2.5)
    ring_radii = _cluster_scalar_values(radii, ring_tolerance)
    if len(ring_radii) < 2:
        return None

    holes_per_ring: list[int] = []
    grouped_rings: list[list[dict]] = [[] for _ in ring_radii]
    for feature in features:
        radius = math.hypot(float(feature["center_mm"]["x"]) - center_x, float(feature["center_mm"]["y"]) - center_y)
        ring_index = min(range(len(ring_radii)), key=lambda index: abs(radius - ring_radii[index]))
        grouped_rings[ring_index].append(feature)
    holes_per_ring = [len(bucket) for bucket in grouped_rings]
    if max(holes_per_ring, default=0) < 4:
        return None

    spacing_values = [abs(right - left) for left, right in zip(ring_radii, ring_radii[1:]) if abs(right - left) > 1e-6]
    radial_spacing = round(sum(spacing_values) / len(spacing_values), 3) if spacing_values else 0.0

    uniformity_scores: list[float] = []
    for radius, bucket in zip(ring_radii, grouped_rings):
        if len(bucket) < 3 or radius <= 1e-6:
            continue
        angles = sorted(
            math.atan2(float(feature["center_mm"]["y"]) - center_y, float(feature["center_mm"]["x"]) - center_x)
            for feature in bucket
        )
        wrapped = angles + [angles[0] + 2.0 * math.pi]
        gaps = [wrapped[index + 1] - wrapped[index] for index in range(len(angles))]
        gap_mean = sum(gaps) / len(gaps)
        gap_std = (sum((gap - gap_mean) ** 2 for gap in gaps) / len(gaps)) ** 0.5 if gaps else 0.0
        uniformity_scores.append(max(0.0, 1.0 - (gap_std / max(gap_mean, 1e-6))))

    uniformity = sum(uniformity_scores) / len(uniformity_scores) if uniformity_scores else 0.0
    confidence = min(
        0.97,
        0.56 + min(uniformity, 1.0) * 0.24 + (0.1 if len(ring_radii) >= 3 else 0.0) + (0.06 if len(features) >= 12 else 0.0),
    )
    editable = confidence >= TARGET_SELECTABLE_CONFIDENCE
    warnings = []
    if confidence < TARGET_SELECTABLE_CONFIDENCE:
        warnings.append("Detected pattern is too low-confidence for safe editing.")
    elif confidence < TARGET_PRIMARY_CONFIDENCE:
        warnings.append("Detected pattern is editable, but verify the target before previewing changes.")

    bounds = cluster.get("local_bounds_mm") or {}
    representative_radius = float(group.get("avg_width_mm", 0.0) or 0.0) / 2.0
    outer_radius = max(ring_radii, default=0.0) + representative_radius
    radial_margin = min(
        abs(float(bounds.get("max_x", 0.0)) - center_x) - outer_radius,
        abs(center_x - float(bounds.get("min_x", 0.0))) - outer_radius,
        abs(float(bounds.get("max_y", 0.0)) - center_y) - outer_radius,
        abs(center_y - float(bounds.get("min_y", 0.0))) - outer_radius,
    )
    center_hole = _detect_center_hole_for_target(cluster, face_features, set(group.get("feature_ids") or []))
    element_type = "circular_hole" if group.get("type") == "circle" else "rectangular_cutout"
    size_text = (
        f"{group['avg_width_mm']:.2f} mm"
        if element_type == "circular_hole"
        else f"{group['avg_width_mm']:.2f} × {group['avg_height_mm']:.2f} mm"
    )

    return {
        "id": _target_id("target", cluster.get("face_id"), "radial", group.get("id")),
        "type": "planar_pattern_face",
        "confidence": round(confidence, 3),
        "editable": editable,
        "label": "Radial repeated pattern",
        "summary": f"{len(features)} repeated {group.get('type')} openings in concentric rings · {size_text}",
        "preview_capability": "supported" if editable else "limited",
        "supported_operations": ["resize_feature", "adjust_spacing", "adjust_count", "adjust_margin"],
        "warnings": warnings,
        "topology": "radial",
        "element_type": element_type,
        "feature_kind": element_type,
        "face_frame": _face_frame_payload(cluster),
        "face_polygon_2d": _face_polygon_2d(cluster),
        "feature_geometry_2d": _feature_geometry_2d(cluster, features),
        "feature_ids": list(group.get("feature_ids") or []),
        "face_id": cluster.get("face_id"),
        "measured": {
            "feature_size": round(float(group.get("avg_width_mm", 0.0)), 3)
            if element_type == "circular_hole"
            else {
                "width": round(float(group.get("avg_width_mm", 0.0)), 3),
                "height": round(float(group.get("avg_height_mm", 0.0)), 3),
            },
            "radial_spacing": radial_spacing,
            "ring_count": len(ring_radii),
            "holes_per_ring": holes_per_ring,
            "margin": round(max(radial_margin, 0.0), 3),
            "center_hole_diameter": round(float(center_hole.get("diameter_mm", 0.0)), 3) if center_hole else None,
        },
        "pattern": {
            "element_type": element_type,
            "count": len(features),
            "radial_spacing": radial_spacing,
            "ring_count": len(ring_radii),
            "holes_per_ring": holes_per_ring,
            "margin": round(max(radial_margin, 0.0), 3),
            "center_hole_diameter": round(float(center_hole.get("diameter_mm", 0.0)), 3) if center_hole else None,
        },
        "dimensions": {
            "hole_diameter": round(float(group.get("avg_width_mm", 0.0)), 3)
            if element_type == "circular_hole"
            else None,
            "width": round(float(group.get("avg_width_mm", 0.0)), 3),
            "height": round(float(group.get("avg_height_mm", 0.0)), 3),
        },
        "fit": {
            "center_x": round(center_x, 3),
            "center_y": round(center_y, 3),
            "ring_radii": ring_radii,
            "holes_per_ring": holes_per_ring,
            "center_hole_feature_id": center_hole["id"] if center_hole else None,
        },
    }


def _build_pattern_target(group: dict, cluster: dict, face_features: Sequence[dict]) -> dict | None:
    if group.get("count", 0) < PATTERN_TARGET_MIN_COUNT:
        return None
    if group.get("type") not in {"circle", "rectangle"}:
        return None
    radial_target = _fit_radial_pattern_target(group, cluster, face_features)
    rectangular_target = _fit_rectangular_pattern_target(group, cluster, face_features)
    candidates: list[dict] = []
    for candidate in (radial_target, rectangular_target):
        if not candidate:
            continue
        try:
            default_params = _normalized_target_params(candidate, None)
            positions = _build_pattern_positions(candidate, default_params)
            _validate_pattern_target_edit(cluster, candidate, default_params, positions)
        except Exception:
            continue
        candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: float(candidate.get("confidence", 0.0)))


def _build_single_feature_targets(projection: dict) -> list[dict]:
    candidates: list[dict] = []
    features_by_face: dict[str, list[dict]] = {}
    for feature in projection["features"]:
        features_by_face.setdefault(feature["face_id"], []).append(feature)

    single_candidates = [
        feature
        for feature in projection["features"]
        if feature.get("type") in {"circle", "slot", "rectangle"} and _feature_major_dimension(feature) >= 6.0
    ]
    single_candidates.sort(
        key=lambda feature: (
            -_feature_major_dimension(feature),
            feature["face_id"],
        )
    )
    seen_ids: set[str] = set()
    for feature in single_candidates:
        if feature["id"] in seen_ids:
            continue
        seen_ids.add(feature["id"])
        feature_type = (
            "circular_hole"
            if feature.get("type") == "circle"
            else "slot"
            if feature.get("type") == "slot"
            else "rectangular_cutout"
        )
        face_id = feature["face_id"]
        confidence = 0.9 if feature.get("group_id") is None else 0.76
        label = "Single circular hole" if feature_type == "circular_hole" else "Single slot" if feature_type == "slot" else "Single rectangular cutout"
        size_summary = (
            f"{float(feature.get('diameter_mm', 0.0) or 0.0):.2f} mm"
            if feature_type == "circular_hole"
            else f"{float(feature.get('width_mm', 0.0) or 0.0):.2f} × {float(feature.get('height_mm', 0.0) or 0.0):.2f} mm"
        )
        candidates.append(
            {
                "id": _target_id("target", face_id, "single", feature["id"]),
                "type": "single_planar_feature",
                "confidence": round(confidence, 3),
                "editable": confidence >= TARGET_SELECTABLE_CONFIDENCE,
                "label": label,
                "summary": f"{label.lower()} · {size_summary}",
                "preview_capability": "supported" if confidence >= TARGET_SELECTABLE_CONFIDENCE else "limited",
                "supported_operations": ["resize_feature"],
                "warnings": (
                    []
                    if confidence >= TARGET_PRIMARY_CONFIDENCE
                    else ["Detected feature is editable, but verify the target before previewing changes."]
                    if confidence >= TARGET_SELECTABLE_CONFIDENCE
                    else ["Detected feature is too low-confidence for safe editing."]
                ),
                "face_id": face_id,
                "feature_type": feature_type,
                "feature_kind": feature_type,
                "feature_id": feature["id"],
                "feature_ids": [feature["id"]],
                "face_frame": _face_frame_payload(
                    next(
                        cluster
                        for cluster in projection["clusters"]
                        if cluster.get("face_id") == face_id
                    )
                ),
                "face_polygon_2d": _face_polygon_2d(
                    next(
                        cluster
                        for cluster in projection["clusters"]
                        if cluster.get("face_id") == face_id
                    )
                ),
                "feature_outline_2d": _opening_outline_2d(
                    next(
                        opening
                        for opening in next(
                            cluster for cluster in projection["clusters"] if cluster.get("face_id") == face_id
                        ).get("openings", [])
                        if opening.get("opening_id") == feature.get("opening_id")
                    )
                ),
                "measured": {
                    "diameter": round(float(feature.get("diameter_mm", 0.0) or 0.0), 3)
                    if feature_type == "circular_hole"
                    else None,
                    "width": round(float(feature.get("width_mm", 0.0) or 0.0), 3),
                    "height": round(float(feature.get("height_mm", 0.0) or 0.0), 3),
                },
                "dimensions": {
                    "hole_diameter": round(float(feature.get("diameter_mm", 0.0) or 0.0), 3)
                    if feature_type == "circular_hole"
                    else None,
                    "width": round(float(feature.get("width_mm", 0.0) or 0.0), 3),
                    "height": round(float(feature.get("height_mm", 0.0) or 0.0), 3),
                },
            }
        )
    return candidates


def _build_target_projection(analysis: dict, projection: dict | None = None) -> dict:
    projection = projection or _build_feature_projection(analysis)
    targets: list[dict] = []
    unsupported_reasons: list[str] = []

    features_by_face: dict[str, list[dict]] = {}
    groups_by_face: dict[str, list[dict]] = {}
    for feature in projection["features"]:
        features_by_face.setdefault(feature["face_id"], []).append(feature)
    for group in projection["groups"]:
        groups_by_face.setdefault(group["face_id"], []).append(group)

    for cluster in projection["clusters"]:
        face_id = cluster.get("face_id")
        face_features = features_by_face.get(face_id, [])
        candidate_groups = groups_by_face.get(face_id, [])
        for group in sorted(candidate_groups, key=lambda item: (-item["count"], item["avg_width_mm"])):
            target = _build_pattern_target(group, cluster, face_features)
            if target:
                targets.append(target)

    targets.extend(_build_single_feature_targets(projection))

    deduped_targets: list[dict] = []
    seen_target_ids: set[str] = set()
    for target in sorted(targets, key=lambda item: (-float(item.get("confidence", 0.0)), item.get("label", ""), item["id"])):
        if target["id"] in seen_target_ids:
            continue
        seen_target_ids.add(target["id"])
        deduped_targets.append(target)
    targets = deduped_targets

    supported_targets = [
        target
        for target in targets
        if bool(target.get("editable")) and float(target.get("confidence", 0.0)) >= TARGET_PRIMARY_CONFIDENCE
    ]
    primary_target_id = supported_targets[0]["id"] if supported_targets else None

    if not targets:
        unsupported_reasons.append("No safe planar repeated pattern or isolated feature could be fit from this STL.")
    elif not supported_targets:
        unsupported_reasons.append("Detected editable regions were too low-confidence for the primary editor.")

    return {
        "primary_target_id": primary_target_id,
        "targets": targets,
        "unsupported_reasons": unsupported_reasons,
    }


def public_analysis_payload(analysis: dict) -> dict:
    projection = _build_feature_projection(analysis)
    target_projection = _build_target_projection(analysis, projection)
    clusters: list[dict] = []
    for cluster in projection["clusters"]:
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
                "face_id": cluster.get("face_id"),
                "face_count": cluster.get("face_count"),
                "area_mm2": cluster.get("area_mm2"),
                "normal": cluster.get("normal"),
                "origin_mm": cluster.get("origin_mm"),
                "local_frame": cluster.get("local_frame"),
                "local_bounds_mm": cluster.get("local_bounds_mm"),
                "openings": openings,
                "groups": cluster.get("groups", []),
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
        "features": projection["features"],
        "groups": projection["groups"],
        "primary_target_id": target_projection["primary_target_id"],
        "targets": target_projection["targets"],
        "unsupported_reasons": target_projection["unsupported_reasons"],
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
    face_id = selection.get("face_id")
    feature_id = selection.get("feature_id")
    group_id = selection.get("group_id")
    feature_projection = _build_feature_projection(analysis)
    if feature_id:
        feature = next((item for item in feature_projection["features"] if item["id"] == feature_id), None)
        if not feature:
            raise ValueError("Selected feature was not found on the current model.")
        cluster_id = feature.get("cluster_id")
    elif group_id:
        group = next((item for item in feature_projection["groups"] if item["id"] == group_id), None)
        if not group:
            raise ValueError("Selected feature group was not found on the current model.")
        cluster_id = group.get("cluster_id")

    if face_id and not cluster_id:
        for cluster in feature_projection["clusters"]:
            if cluster.get("face_id") == face_id:
                cluster_id = cluster.get("cluster_id")
                break
    if not cluster_id:
        raise ValueError("Selection requires planar_face_id.")
    for cluster in analysis.get("planar_face_clusters", []):
        if cluster.get("cluster_id") == cluster_id:
            return cluster
    raise ValueError("Selected planar face cluster was not found on the current model.")


def _resolve_opening(cluster: dict, selection: dict) -> dict | None:
    opening_id = selection.get("opening_id")
    feature_id = selection.get("feature_id")
    if feature_id and not opening_id:
        face_id = _stable_face_id(cluster)
        opening = next(
            (
                candidate
                for candidate in cluster.get("openings", [])
                if _stable_feature_id(face_id, candidate) == feature_id
            ),
            None,
        )
        if opening:
            return opening
    if not opening_id:
        return None
    for opening in cluster.get("openings", []):
        if opening.get("opening_id") == opening_id:
            return opening
    raise ValueError("Selected opening was not found on the current planar face cluster.")


def _resolve_target_openings(cluster: dict, selection: dict) -> list[dict]:
    face_id = _stable_face_id(cluster)
    indexed_openings = {
        opening.get("opening_id"): opening
        for opening in cluster.get("openings", [])
        if opening.get("opening_id")
    }
    indexed_features = {
        _stable_feature_id(face_id, opening): opening
        for opening in cluster.get("openings", [])
        if opening.get("opening_id")
    }
    if selection.get("scope") == "group" and selection.get("group_id"):
        projection = _build_feature_projection({"planar_face_clusters": [cluster]})
        group = next((item for item in projection["groups"] if item["id"] == selection.get("group_id")), None)
        if not group:
            raise ValueError("Selected feature group was not found on the current face.")
        return [indexed_openings[opening_id] for opening_id in group["opening_ids"] if opening_id in indexed_openings]

    opening_ids = selection.get("opening_ids") or []
    feature_ids = selection.get("feature_ids") or []
    if not opening_ids and not feature_ids:
        opening = _resolve_opening(cluster, selection)
        return [opening] if opening else []

    indexed_openings = {
        opening.get("opening_id"): opening
        for opening in cluster.get("openings", [])
        if opening.get("opening_id")
    }
    resolved: list[dict] = []
    for opening_id in opening_ids:
        opening = indexed_openings.get(opening_id)
        if not opening:
            raise ValueError("One of the selected openings was not found on the current planar face cluster.")
        resolved.append(opening)
    for feature_id in feature_ids:
        opening = indexed_features.get(feature_id)
        if not opening:
            raise ValueError("One of the selected features was not found on the current planar face cluster.")
        if opening not in resolved:
            resolved.append(opening)
    return resolved


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
            "face_id": selection.get("face_id"),
            "opening_id": selection.get("opening_id"),
            "feature_id": selection.get("feature_id"),
            "group_id": selection.get("group_id"),
            "scope": selection.get("scope") or "one",
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


def _build_targeted_cutter_meshes(
    structured_edit: dict,
    cluster: dict,
    target_openings: list[dict],
    z_min: float,
    z_max: float,
    temp_path: Path,
) -> trimesh.Trimesh:
    if len(target_openings) <= 1:
        return _build_local_cutter_mesh(structured_edit, cluster, z_min, z_max, temp_path)

    base_request = dict(structured_edit)
    base_request["pattern"] = "none"
    base_request["count"] = 1

    meshes: list[trimesh.Trimesh] = []
    for index, opening in enumerate(target_openings, start=1):
        per_opening_request = dict(base_request)
        per_opening_request["center_mm"] = {
            "x": float(opening["center_mm"]["x"]),
            "y": float(opening["center_mm"]["y"]),
        }
        meshes.append(
            _build_local_cutter_mesh(
                per_opening_request,
                cluster,
                z_min,
                z_max,
                temp_path.with_name(f"{temp_path.stem}-{index}{temp_path.suffix}"),
            )
        )
    return trimesh.util.concatenate(meshes)


def _build_targeted_plug_meshes(
    structured_edit: dict,
    cluster: dict,
    target_openings: list[dict],
    z_min: float,
    z_max: float,
    tolerance_mm: float,
    temp_path: Path,
) -> trimesh.Trimesh | None:
    if not target_openings:
        return None
    if structured_edit["operation"] == "resize_cutout":
        return None

    plug_meshes: list[trimesh.Trimesh] = []
    for index, opening in enumerate(target_openings, start=1):
        plug_meshes.append(
            _build_opening_plug_mesh(
                opening,
                cluster,
                z_min,
                z_max,
                tolerance_mm,
                temp_path.with_name(f"{temp_path.stem}-{index}{temp_path.suffix}"),
            )
        )
    return trimesh.util.concatenate(plug_meshes)


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


def _resolve_target(analysis: dict, target_id: str) -> tuple[dict, dict]:
    projection = _build_target_projection(analysis)
    target = next((item for item in projection["targets"] if item["id"] == target_id), None)
    if not target:
        raise ValueError("Selected target was not found on the current model.")
    if target.get("type") == "unsupported":
        raise ValueError(target.get("unsupported_reason") or "This target cannot be edited safely.")
    if not bool(target.get("editable")):
        raise ValueError("Selected target is not safe enough to edit.")
    cluster = next(
        (candidate for candidate in analysis.get("planar_face_clusters", []) if _stable_face_id(candidate) == target.get("face_id")),
        None,
    )
    if not cluster:
        raise ValueError("Selected target face was not found on the current model.")
    return target, cluster


def _feature_lookup_for_cluster(cluster: dict) -> dict[str, dict]:
    face_id = _stable_face_id(cluster)
    return {
        _stable_feature_id(face_id, opening): opening
        for opening in cluster.get("openings", [])
    }


def _opening_for_feature_id(cluster: dict, feature_id: str | None) -> dict | None:
    if not feature_id:
        return None
    return _feature_lookup_for_cluster(cluster).get(feature_id)


def _default_target_params(target: dict) -> dict:
    if target.get("type") == "planar_pattern_face":
        pattern = target.get("pattern") or {}
        dimensions = target.get("dimensions") or {}
        defaults = {
            "margin": pattern.get("margin"),
            "center_hole_diameter": pattern.get("center_hole_diameter"),
        }
        if target.get("topology") == "rectangular":
            defaults.update(
                {
                    "hole_diameter": dimensions.get("hole_diameter"),
                    "width": dimensions.get("width"),
                    "height": dimensions.get("height"),
                    "spacing_x": pattern.get("spacing_x"),
                    "spacing_y": pattern.get("spacing_y"),
                    "count_x": pattern.get("count_x"),
                    "count_y": pattern.get("count_y"),
                }
            )
        else:
            defaults.update(
                {
                    "hole_diameter": dimensions.get("hole_diameter"),
                    "width": dimensions.get("width"),
                    "height": dimensions.get("height"),
                    "radial_spacing": pattern.get("radial_spacing"),
                    "ring_count": pattern.get("ring_count"),
                    "holes_per_ring": pattern.get("holes_per_ring"),
                }
            )
        return defaults

    dimensions = target.get("dimensions") or {}
    return {
        "hole_diameter": dimensions.get("hole_diameter"),
        "width": dimensions.get("width"),
        "height": dimensions.get("height"),
    }


def _numeric_or_default(params: dict, key: str, default: float | None) -> float | None:
    if key not in params:
        return default
    value = params.get(key)
    if value in ("", None):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _int_or_default(params: dict, key: str, default: int | None) -> int | None:
    if key not in params:
        return default
    value = params.get(key)
    if value in ("", None):
        return default
    try:
        return int(round(float(value)))
    except Exception:
        return default


def _normalized_target_params(target: dict, params: dict | None) -> dict:
    params = params or {}
    defaults = _default_target_params(target)
    normalized = dict(defaults)
    for key in (
        "hole_diameter",
        "width",
        "height",
        "spacing_x",
        "spacing_y",
        "radial_spacing",
        "margin",
        "center_hole_diameter",
    ):
        normalized[key] = _numeric_or_default(params, key, normalized.get(key))
    for key in ("count_x", "count_y", "ring_count"):
        normalized[key] = _int_or_default(params, key, normalized.get(key))
    if "holes_per_ring" in params and isinstance(params.get("holes_per_ring"), list):
        normalized["holes_per_ring"] = [max(int(round(float(value))), 1) for value in params["holes_per_ring"]]
    return normalized


def _build_pattern_positions(target: dict, normalized_params: dict) -> list[tuple[float, float]]:
    fit = target.get("fit") or {}
    topology = target.get("topology")
    if topology == "rectangular":
        original_x_positions = [float(value) for value in (fit.get("x_positions") or [])]
        original_y_positions = [float(value) for value in (fit.get("y_positions") or [])]
        original_spacing_x = float((target.get("pattern") or {}).get("spacing_x") or 0.0)
        original_spacing_y = float((target.get("pattern") or {}).get("spacing_y") or 0.0)
        count_x = max(int(normalized_params.get("count_x") or len(original_x_positions) or 1), 1)
        count_y = max(int(normalized_params.get("count_y") or len(original_y_positions) or 1), 1)
        spacing_x = max(float(normalized_params.get("spacing_x") or original_spacing_x or 0.0), 0.1)
        spacing_y = max(float(normalized_params.get("spacing_y") or original_spacing_y or 0.0), 0.1)

        use_original_x = len(original_x_positions) == count_x and abs(spacing_x - original_spacing_x) <= 0.35
        use_original_y = len(original_y_positions) == count_y and abs(spacing_y - original_spacing_y) <= 0.35
        if use_original_x and original_x_positions:
            x_positions = original_x_positions
        else:
            center_x = float(fit.get("center_x", 0.0))
            x_positions = [
                round(center_x + (x_index - (count_x - 1) / 2.0) * spacing_x, 4)
                for x_index in range(count_x)
            ]
        if use_original_y and original_y_positions:
            y_positions = original_y_positions
        else:
            center_y = float(fit.get("center_y", 0.0))
            y_positions = [
                round(center_y + (y_index - (count_y - 1) / 2.0) * spacing_y, 4)
                for y_index in range(count_y)
            ]

        positions: list[tuple[float, float]] = []
        for x in x_positions:
            for y in y_positions:
                positions.append((round(x, 4), round(y, 4)))
        return positions

    center_x = float(fit.get("center_x", 0.0))
    center_y = float(fit.get("center_y", 0.0))
    original_ring_radii = [float(value) for value in (fit.get("ring_radii") or [])]
    original_holes_per_ring = [max(int(value), 1) for value in (fit.get("holes_per_ring") or [])]
    ring_count = max(int(normalized_params.get("ring_count") or len(original_ring_radii) or 1), 1)
    radial_spacing = float(normalized_params.get("radial_spacing") or 0.0)
    if radial_spacing <= 0 and len(original_ring_radii) > 1:
        radial_spacing = (original_ring_radii[-1] - original_ring_radii[0]) / max(len(original_ring_radii) - 1, 1)
    radial_spacing = max(radial_spacing, 0.1)
    first_ring_radius = float(original_ring_radii[0]) if original_ring_radii else radial_spacing
    if original_ring_radii and original_holes_per_ring:
        average_arc_spacing = sum(
            (2.0 * math.pi * radius) / max(count, 1)
            for radius, count in zip(original_ring_radii, original_holes_per_ring)
            if radius > 1e-6 and count > 0
        ) / max(len(original_ring_radii), 1)
    else:
        average_arc_spacing = radial_spacing * 1.6

    requested_holes = normalized_params.get("holes_per_ring") or []
    positions: list[tuple[float, float]] = []
    use_original_rings = ring_count == len(original_ring_radii) and abs(radial_spacing - float((target.get("pattern") or {}).get("radial_spacing") or radial_spacing)) <= 0.35
    ring_radii = original_ring_radii if use_original_rings and original_ring_radii else [first_ring_radius + ring_index * radial_spacing for ring_index in range(ring_count)]

    for ring_index, radius in enumerate(ring_radii[:ring_count]):
        if ring_index < len(requested_holes):
            hole_count = max(int(requested_holes[ring_index]), 1)
        elif ring_index < len(original_holes_per_ring):
            hole_count = max(int(original_holes_per_ring[ring_index]), 1)
        else:
            hole_count = max(int(round((2.0 * math.pi * radius) / max(average_arc_spacing, 1e-6))), 1)
        for hole_index in range(hole_count):
            angle = (2.0 * math.pi * hole_index) / hole_count
            positions.append(
                (
                    round(center_x + math.cos(angle) * radius, 4),
                    round(center_y + math.sin(angle) * radius, 4),
                )
            )
    return positions


def _validate_pattern_target_edit(cluster: dict, target: dict, params: dict, positions: Sequence[tuple[float, float]]) -> None:
    bounds = cluster.get("local_bounds_mm") or {}
    margin = max(float(params.get("margin") or 0.0), 0.0)
    element_type = target.get("element_type")
    if element_type == "circular_hole":
        diameter = float(params.get("hole_diameter") or 0.0)
        if diameter <= 0:
            raise ValueError("Hole diameter must be greater than 0 mm.")
        half_width = diameter / 2.0
        half_height = diameter / 2.0
    else:
        width = float(params.get("width") or 0.0)
        height = float(params.get("height") or 0.0)
        if width <= 0 or height <= 0:
            raise ValueError("Pattern width and height must be greater than 0 mm.")
        half_width = width / 2.0
        half_height = height / 2.0

    min_x = float(bounds.get("min_x", 0.0)) + margin
    max_x = float(bounds.get("max_x", 0.0)) - margin
    min_y = float(bounds.get("min_y", 0.0)) + margin
    max_y = float(bounds.get("max_y", 0.0)) - margin
    for x, y in positions:
        if x - half_width < min_x or x + half_width > max_x or y - half_height < min_y or y + half_height > max_y:
            raise ValueError("Target exceeds face boundary or requested margin.")

    min_gap = MIN_PATTERN_WALL_MM
    for index, (left_x, left_y) in enumerate(positions):
        for compare_index in range(index + 1, len(positions)):
            right_x, right_y = positions[compare_index]
            if element_type == "circular_hole":
                center_distance = math.hypot(left_x - right_x, left_y - right_y)
                if center_distance < (half_width + half_width + min_gap):
                    raise ValueError("Hole overlap detected at the requested spacing.")
            else:
                if abs(left_x - right_x) < (half_width * 2.0 + min_gap) and abs(left_y - right_y) < (half_height * 2.0 + min_gap):
                    raise ValueError("Cutout overlap detected at the requested spacing.")

    center_hole_diameter = float(params.get("center_hole_diameter") or 0.0)
    if center_hole_diameter > 0:
        fit = target.get("fit") or {}
        center_x = float(fit.get("center_x", 0.0))
        center_y = float(fit.get("center_y", 0.0))
        center_radius = center_hole_diameter / 2.0
        for x, y in positions:
            center_distance = math.hypot(x - center_x, y - center_y)
            clearance = half_width if element_type == "circular_hole" else math.hypot(half_width, half_height)
            if center_distance < center_radius + clearance + min_gap:
                raise ValueError("Center hole conflicts with the repeated pattern at the requested size.")


def _build_pattern_cutter_mesh(
    cluster: dict,
    target: dict,
    params: dict,
    positions: Sequence[tuple[float, float]],
    z_min: float,
    z_max: float,
    temp_path: Path,
) -> trimesh.Trimesh:
    tolerance_mm = DEFAULT_TOLERANCE_MM
    element_type = target.get("element_type")
    hole_diameter = float(params.get("hole_diameter") or 0.0)
    width = float(params.get("width") or 0.0)
    height = float(params.get("height") or 0.0)
    if element_type == "circular_hole":
        shape = "circle"
        width = hole_diameter
        height = hole_diameter
    else:
        shape = "rectangle"

    total_depth = (z_max - z_min) + tolerance_mm * 4.0
    base_solid = _build_shape_solid(
        shape,
        width + tolerance_mm,
        height + tolerance_mm,
        hole_diameter + tolerance_mm,
        0.0,
        total_depth,
    )
    base_mesh = _export_cq_solid_to_mesh(base_solid, temp_path)
    z_center = (z_min + z_max) / 2.0

    meshes: list[trimesh.Trimesh] = []
    for index, (x, y) in enumerate(positions, start=1):
        clone = base_mesh.copy()
        clone.apply_translation((x, y, z_center))
        meshes.append(clone)

    center_hole_diameter = float(params.get("center_hole_diameter") or 0.0)
    if center_hole_diameter > 0:
        fit = target.get("fit") or {}
        center_mesh = _export_cq_solid_to_mesh(
            _build_shape_solid("circle", center_hole_diameter, center_hole_diameter, center_hole_diameter, 0.0, total_depth),
            temp_path.with_name(f"{temp_path.stem}-center{temp_path.suffix}"),
        )
        center_mesh.apply_translation((float(fit.get("center_x", 0.0)), float(fit.get("center_y", 0.0)), z_center))
        meshes.append(center_mesh)

    combined = trimesh.util.concatenate(meshes)
    combined.apply_transform(_local_transform_matrix(cluster))
    return combined


def _build_pattern_plug_mesh(
    cluster: dict,
    target_openings: Sequence[dict],
    center_hole_opening: dict | None,
    z_min: float,
    z_max: float,
    temp_path: Path,
) -> trimesh.Trimesh | None:
    openings = list(target_openings)
    if center_hole_opening is not None:
        openings.append(center_hole_opening)
    if not openings:
        return None
    meshes: list[trimesh.Trimesh] = []
    for index, opening in enumerate(openings, start=1):
        meshes.append(
            _build_opening_plug_mesh(
                opening,
                cluster,
                z_min,
                z_max,
                DEFAULT_TOLERANCE_MM,
                temp_path.with_name(f"{temp_path.stem}-{index}{temp_path.suffix}"),
            )
        )
    return trimesh.util.concatenate(meshes)


def _build_legacy_request_from_target(target: dict, params: dict) -> tuple[dict, dict]:
    feature_type = target.get("feature_type")
    feature_id = target.get("feature_id")
    if feature_type == "circular_hole":
        diameter = float(params.get("hole_diameter") or 0.0)
        edit_request = {
            "operation": "resize_cutout",
            "target_shape": "circle",
            "diameter_mm": diameter,
            "width_mm": diameter,
            "height_mm": diameter,
            "through_all": True,
            "tolerance_mm": DEFAULT_TOLERANCE_MM,
        }
    else:
        width = float(params.get("width") or 0.0)
        height = float(params.get("height") or 0.0)
        edit_request = {
            "operation": "resize_cutout",
            "target_shape": "rounded_slot" if feature_type == "slot" else "rectangle",
            "width_mm": width,
            "height_mm": height,
            "diameter_mm": min(width, height),
            "through_all": True,
            "tolerance_mm": DEFAULT_TOLERANCE_MM,
        }
    selection = {
        "feature_id": feature_id,
        "scope": "one",
    }
    return selection, edit_request


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


def _perform_target_edit(
    *,
    model_id: str,
    job_id: str,
    target_id: str,
    params: dict | None,
    prompt: str | None,
    parent_revision_id: str | None,
    preview: bool,
) -> EditedModelResult:
    base_stl_path = _resolve_base_stl(model_id, parent_revision_id)
    base_mesh = _load_mesh(base_stl_path)
    analysis = analyze_mesh(base_mesh)
    target, cluster = _resolve_target(analysis, target_id)
    normalized_params = _normalized_target_params(target, params)

    if target.get("type") == "single_planar_feature":
        selection, edit_request = _build_legacy_request_from_target(target, normalized_params)
        return _perform_edit(
            model_id=model_id,
            job_id=job_id,
            selection=selection,
            edit_request=edit_request,
            prompt=prompt,
            parent_revision_id=parent_revision_id,
            preview=preview,
            target_id=None,
            params=None,
        )

    frame = cluster["local_frame"]
    origin = np.asarray(cluster["origin_mm"], dtype=float)
    x_axis = np.asarray(frame["x_axis"], dtype=float)
    y_axis = np.asarray(frame["y_axis"], dtype=float)
    z_axis = np.asarray(frame["z_axis"], dtype=float)
    local_vertices = _project_points(np.asarray(base_mesh.vertices, dtype=float), origin, x_axis, y_axis, z_axis)
    z_min = float(local_vertices[:, 2].min())
    z_max = float(local_vertices[:, 2].max())

    positions = _build_pattern_positions(target, normalized_params)
    _validate_pattern_target_edit(cluster, target, normalized_params, positions)

    opening_lookup = _feature_lookup_for_cluster(cluster)
    target_openings = [opening_lookup[feature_id] for feature_id in target.get("feature_ids", []) if feature_id in opening_lookup]
    center_hole_opening = _opening_for_feature_id(cluster, (target.get("fit") or {}).get("center_hole_feature_id"))

    job_dir = _job_dir(job_id)
    analysis_path = job_dir / "analysis.json"
    preview_glb_path = job_dir / "preview.glb"
    result_glb_path = preview_glb_path if preview else job_dir / "model.glb"
    result_stl_path = job_dir / "model.stl"

    cutter_mesh = _build_pattern_cutter_mesh(
        cluster,
        target,
        normalized_params,
        positions,
        z_min,
        z_max,
        job_dir / "pattern-cutter.stl",
    )
    plug_mesh = _build_pattern_plug_mesh(
        cluster,
        target_openings,
        center_hole_opening if normalized_params.get("center_hole_diameter") is not None else None,
        z_min,
        z_max,
        job_dir / "pattern-plug.stl",
    )

    edited_stl_path, fallback_strategy_used = _run_edit_boolean_chain(base_stl_path, plug_mesh, cutter_mesh, job_dir)
    edited_mesh = _load_mesh(edited_stl_path)
    edited_mesh.export(result_stl_path)
    _write_glb(edited_mesh, result_glb_path)
    validation = validate_mesh_file(result_stl_path)

    current_analysis = analyze_mesh(edited_mesh)
    _write_analysis(analysis_path, current_analysis)
    structured_edit = {
        "editor_type": "pattern_face",
        "target_id": target_id,
        "target_type": target.get("topology"),
        "params": normalized_params,
        "selection": {
            "target_id": target_id,
            "face_id": target.get("face_id"),
            "feature_ids": target.get("feature_ids"),
        },
        "prompt": prompt or "",
    }

    warnings = list(dict.fromkeys([*(validation.get("warnings") or []), *target.get("warnings", [])]))
    return EditedModelResult(
        job_id=job_id,
        model_id=model_id,
        glb_path=result_glb_path,
        stl_path=result_stl_path,
        analysis=current_analysis,
        structured_edit=structured_edit,
        validation=validation,
        warnings=warnings,
        fallback_strategy_used=fallback_strategy_used,
    )


def _perform_edit(
    *,
    model_id: str,
    job_id: str,
    selection: dict | None,
    edit_request: dict | None,
    prompt: str | None,
    parent_revision_id: str | None,
    preview: bool,
    target_id: str | None = None,
    params: dict | None = None,
) -> EditedModelResult:
    if cq_exporters is None:
        raise RuntimeError("CadQuery is not available for model editing.")

    if target_id:
        return _perform_target_edit(
            model_id=model_id,
            job_id=job_id,
            target_id=target_id,
            params=params,
            prompt=prompt,
            parent_revision_id=parent_revision_id,
            preview=preview,
        )

    if selection is None or edit_request is None:
        raise ValueError("Legacy edit flow requires selection and edit_request.")

    base_stl_path = _resolve_base_stl(model_id, parent_revision_id)
    base_mesh = _load_mesh(base_stl_path)
    analysis = analyze_mesh(base_mesh)
    cluster = _resolve_cluster(analysis, selection)
    opening = _resolve_opening(cluster, selection)
    target_openings = _resolve_target_openings(cluster, selection)
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

    cutter_mesh = _build_targeted_cutter_meshes(
        structured_edit,
        cluster,
        target_openings,
        z_min,
        z_max,
        temp_cutter_path,
    )
    plug_mesh = _build_targeted_plug_meshes(
        structured_edit,
        cluster,
        target_openings,
        z_min,
        z_max,
        tolerance_mm,
        temp_plug_path,
    )

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
    selection: dict | None,
    edit_request: dict | None,
    prompt: str | None = None,
    parent_revision_id: str | None = None,
    target_id: str | None = None,
    params: dict | None = None,
) -> EditedModelResult:
    return _perform_edit(
        model_id=model_id,
        job_id=job_id,
        selection=selection,
        edit_request=edit_request,
        prompt=prompt,
        parent_revision_id=parent_revision_id,
        preview=True,
        target_id=target_id,
        params=params,
    )


def apply_edit(
    *,
    model_id: str,
    job_id: str,
    selection: dict | None,
    edit_request: dict | None,
    prompt: str | None = None,
    parent_revision_id: str | None = None,
    target_id: str | None = None,
    params: dict | None = None,
) -> EditedModelResult:
    return _perform_edit(
        model_id=model_id,
        job_id=job_id,
        selection=selection,
        edit_request=edit_request,
        prompt=prompt,
        parent_revision_id=parent_revision_id,
        preview=False,
        target_id=target_id,
        params=params,
    )
