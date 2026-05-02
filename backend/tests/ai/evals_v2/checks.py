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

    # Hole counting is intentionally conservative until feature graph + B-rep
    # face ownership lands. Cases can still declare it; unsupported assertions
    # fail loudly instead of pretending mesh topology gave a reliable count.
    if checks.get("holeCount") is not None:
        failures.append("holeCount predicate is not implemented reliably for raw meshes yet")

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


__all__ = ["run_geometry_checks"]
