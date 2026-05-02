"""Tool: re-run process-aware manufacturability against the latest STL."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import build_design, run_manufacturability


class CheckManufacturabilityInput(BaseModel):
    process: str = Field(
        default="fdm",
        description="'fdm' for 3D-printing checks; 'cnc' for milling checks.",
    )


TOOL_DEFINITION = {
    "name": "check_manufacturability",
    "description": (
        "Inspect the current geometry for process-specific issues. For FDM: "
        "minimum wall thickness, overhangs >45°, watertightness, bed-size fit. "
        "For CNC: undercuts, sharp internal corners, watertightness. Reuses "
        "the most recent STL when available; rebuilds otherwise."
    ),
    "input_schema": CheckManufacturabilityInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = CheckManufacturabilityInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    last_build = ctx.last_build
    stl_path: Path | None = None
    if last_build and "stl" in last_build.artifacts and last_build.revision_id == ctx.design.revision_id:
        candidate = Path(last_build.artifacts["stl"].path)
        if candidate.exists():
            stl_path = candidate

    if stl_path is None:
        try:
            build = build_design(
                ctx.design,
                targets=["stl"],
                printer_profile_id=ctx.printer_profile_id,
                process=params.process,
            )
        except Exception as exc:
            return {"error": f"Could not build for manufacturability check: {exc}"}
        ctx.last_build = build
        if "stl" not in build.artifacts:
            return {"error": "Build produced no STL; cannot evaluate manufacturability."}
        stl_path = Path(build.artifacts["stl"].path)

    report = run_manufacturability(
        stl_path=stl_path,
        process=params.process,
        printer_profile_id=ctx.printer_profile_id,
    )
    return {
        "ok": True,
        "revision_id": ctx.design.revision_id,
        "report": report.model_dump(),
    }


__all__ = ["TOOL_DEFINITION", "CheckManufacturabilityInput", "execute"]
