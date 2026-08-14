"""Tool: run a full build for the active design and refresh the artifacts.

Uses the design's current parameters; produces STL + STEP + GLB by default,
optionally DXF (for CNC handoff) and G-code (FDM only).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import DesignBuildError, build_design
from services.codegen.models import Build
from services.codegen.store import save_build


class RunBuildInput(BaseModel):
    targets: list[str] = Field(
        default_factory=lambda: ["stl", "step", "glb"],
        description="Subset of ['stl','step','dxf','glb'].",
    )
    process: str = Field(
        default="fdm",
        description="'fdm' for 3D printing or 'cnc' for milling. Drives the manufacturability check.",
    )
    slice_gcode: bool = Field(
        default=False,
        description="If true and process=='fdm', also slice STL to G-code.",
    )


TOOL_DEFINITION = {
    "name": "run_build",
    "description": (
        "Run a full build of the active design — execute the script, export "
        "the requested artifacts, and run a process-aware manufacturability "
        "check. Returns artifact URLs, mesh hash, bounding box, and the "
        "manufacturability report. Call this after every edit before "
        "responding to the user, so they see the latest geometry."
    ),
    "input_schema": RunBuildInput.model_json_schema(),
}


def _slice_gcode(stl_path: Path, profile_id: str) -> tuple[str | None, str]:
    """Return (gcode_path or None, status_message)."""
    from slicer_service import _slice_mesh

    gcode_path = stl_path.parent / "model.gcode"
    try:
        ok = _slice_mesh(stl_path, gcode_path, profile_id=profile_id)
    except Exception as exc:
        return None, f"slicer failed: {exc}"
    if not ok or not gcode_path.exists():
        return None, "slicer skipped (PrusaSlicer path missing)"
    return str(gcode_path), "ok"


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = RunBuildInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    try:
        build = build_design(
            ctx.design,
            targets=params.targets,
            printer_profile_id=ctx.printer_profile_id,
            process=params.process,
        )
    except DesignBuildError as exc:
        return {
            "error": f"Build failed: {exc}",
            "audit_errors": exc.audit_errors,
        }

    gcode_status: str | None = None
    if params.slice_gcode and params.process == "fdm" and "stl" in build.artifacts:
        gcode_path_str, status = _slice_gcode(
            Path(build.artifacts["stl"].path), ctx.printer_profile_id
        )
        gcode_status = status
        if gcode_path_str:
            gcode_path = Path(gcode_path_str)
            from services.codegen.estimate import parse_gcode_estimate
            from services.codegen.models import BuildArtifact

            build.artifacts["gcode"] = BuildArtifact(
                kind="gcode",
                url=f"/artifacts/designs/{ctx.design.id}/{gcode_path.name}",
                path=str(gcode_path),
                bytes=gcode_path.stat().st_size,
            )
            estimate = parse_gcode_estimate(gcode_path)
            if estimate is not None:
                build.print_estimate = estimate

    save_build(ctx.design.id, build)
    ctx.last_build = build

    return {
        "ok": True,
        "revision_id": build.revision_id,
        "mesh_hash": build.mesh_hash,
        "selection_map": {k: v.model_dump() for k, v in build.selection_map.items()},
        "bounding_box_mm": build.bounding_box_mm,
        "artifacts": {k: a.url for k, a in build.artifacts.items()},
        "manufacturability": (
            {
                "process": build.manufacturability.process,
                "status": build.manufacturability.status,
                "issues": [
                    {
                        "severity": i.severity,
                        "code": i.code,
                        "message": i.message,
                        "suggestion": i.suggestion,
                    }
                    for i in build.manufacturability.issues
                ],
            }
            if build.manufacturability
            else None
        ),
        "print_estimate": (
            build.print_estimate.model_dump() if build.print_estimate else None
        ),
        "gcode_status": gcode_status,
        "duration_ms": build.duration_ms,
    }


__all__ = ["TOOL_DEFINITION", "RunBuildInput", "execute"]
