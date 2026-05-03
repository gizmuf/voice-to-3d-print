"""Geometry predicates for v2 eval cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_geometry_checks(build: dict[str, Any], checks: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if checks.get("buildsSuccessfully") and not build:
        failures.append("expected a latest_build payload")
        return failures

    bbox_check = checks.get("boundingBoxMm")
    if bbox_check:
        expected = bbox_check[:3]
        tolerance = _tolerance(bbox_check)
        actual = build.get("bounding_box_mm")
        if not actual:
            failures.append("missing bounding_box_mm")
        else:
            for axis, exp, act in zip("xyz", expected, actual, strict=False):
                if abs(float(act) - float(exp)) > tolerance:
                    failures.append(
                        f"bbox {axis} expected {exp}±{tolerance}, got {act}"
                    )

    mesh = None
    if checks.get("isWatertight") is not None or checks.get("holeCount") is not None:
        mesh = _load_stl_mesh(build)
    if checks.get("isWatertight") is not None and mesh is not None:
        expected = bool(checks["isWatertight"])
        if bool(mesh.is_watertight) != expected:
            failures.append(f"isWatertight expected {expected}, got {mesh.is_watertight}")

    min_wall = checks.get("minWallThicknessMm")
    if min_wall is not None:
        issues = ((build.get("manufacturability") or {}).get("issues") or [])
        thin = [i for i in issues if "wall" in str(i.get("code", "")).lower()]
        if thin:
            failures.append(f"minWallThicknessMm expected >= {min_wall}; issues={thin[:2]}")

    if checks.get("holeCount") is not None and mesh is not None:
        expected = int(checks["holeCount"])
        actual = _count_through_holes(mesh)
        if actual != expected:
            failures.append(f"holeCount expected {expected}, got {actual}")

    return failures


def _tolerance(spec: list[Any]) -> float:
    if len(spec) >= 5 and spec[3] == "tolerance":
        return float(spec[4])
    if len(spec) >= 4 and isinstance(spec[3], (int, float)):
        return float(spec[3])
    return 1.0


def _load_stl_mesh(build: dict[str, Any]):
    artifacts = build.get("artifacts") or {}
    stl = artifacts.get("stl") or {}
    path = stl.get("path")
    if not path or not Path(path).exists():
        return None
    import trimesh

    mesh = trimesh.load_mesh(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = trimesh.util.concatenate(tuple(mesh.dump()))  # type: ignore[arg-type]
    return mesh


def _count_through_holes(mesh) -> int:
    """Count genus-style through-holes for watertight manifold meshes.

    Caveat: this is topological genus, so any handle/loop on the surface
    contributes — a torus reports 1, a chain link reports the link count, etc.
    For the flat-plate parts our eval cases cover, genus equals through-hole
    count and the predicate is trustworthy. Cases that test exotic topology
    (handles, knots) should not rely on this.
    """
    if not mesh.is_watertight:
        return 0
    components = mesh.split(only_watertight=False)
    if not components:
        components = [mesh]
    count = 0
    for component in components:
        if not component.is_watertight:
            continue
        genus = int(round((2 - int(component.euler_number)) / 2))
        count += max(0, genus)
    return count


__all__ = ["run_geometry_checks"]
