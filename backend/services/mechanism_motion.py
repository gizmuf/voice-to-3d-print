"""Analytic motion checks for supported parametric mechanisms."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.codegen.models import Build, Design


def evaluate_mechanism_motion(design: Design, build: Build | None) -> dict[str, Any]:
    values = {parameter.name: parameter.value for parameter in design.parameters}
    required = {
        "wheel_diameter",
        "track_width",
        "axle_diameter",
        "axle_clearance",
        "ground_clearance",
        "base_thickness",
        "stand_gap",
    }
    if not required.issubset(values):
        return {
            "supported": False,
            "status": "unsupported",
            "summary": "This design has no declared moving joint.",
            "checks": [],
        }

    axle_clearance = float(values["axle_clearance"])
    stand_gap = float(values["stand_gap"])
    base_gap = float(values["ground_clearance"]) - float(values["base_thickness"])
    checks = [
        _check("rotating_node", _has_glb_node(build, "wheel"), "GLB contains a separate wheel node."),
        _check("axle_clearance", axle_clearance >= 0.25, f"Diametral axle clearance is {axle_clearance:.2f} mm."),
        _check("stand_clearance", stand_gap > 0.0, f"Wheel-to-stand gap is {stand_gap:.2f} mm."),
        _check("base_clearance", base_gap > 0.0, f"Wheel-to-base gap is {base_gap:.2f} mm."),
    ]
    failures = [check for check in checks if not check["passed"]]
    status = "blocked" if failures else "safe"
    summary = (
        f"Rotation geometry verified: axle clearance {axle_clearance:.2f} mm, "
        f"minimum static gap {min(stand_gap, base_gap):.2f} mm."
        if not failures
        else f"Rotation blocked by {len(failures)} geometry check(s)."
    )
    return {
        "supported": True,
        "status": status,
        "summary": summary,
        "rotating_node": "wheel",
        "axis_cad": [0.0, 1.0, 0.0],
        "axis_viewer": [0.0, 0.0, 1.0],
        "axle_clearance_mm": axle_clearance,
        "minimum_static_gap_mm": min(stand_gap, base_gap),
        "checks": checks,
        "caveat": "Kinematic clearance preview only; it does not simulate friction, flex, loads, or wear.",
    }


def _check(code: str, passed: bool, message: str) -> dict[str, Any]:
    return {"code": code, "passed": passed, "message": message}


def _has_glb_node(build: Build | None, node_name: str) -> bool:
    if not build or "glb" not in build.artifacts:
        return False
    path = Path(build.artifacts["glb"].path)
    if not path.exists():
        return False
    try:
        import trimesh

        scene = trimesh.load(path, force="scene")
        # Semantic face previews keep the moving assembly as a parent node and
        # place selectable B-rep faces below it. A node need not own one flat
        # geometry blob in order to be a valid separately transformable group.
        return node_name in set(scene.graph.nodes)
    except Exception:
        return False


__all__ = ["evaluate_mechanism_motion"]
