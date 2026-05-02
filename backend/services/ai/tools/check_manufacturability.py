"""Tool: run mesh-based manufacturability checks against the latest preview."""

from __future__ import annotations

from pathlib import Path

import trimesh
from pydantic import BaseModel

from services.ai.tools._context import AgentContext
from services.editable_rebuild import export_editable_preview
from services.manufacturability import check_mesh


class CheckManufacturabilityInput(BaseModel):
    pass


TOOL_DEFINITION = {
    "name": "check_manufacturability",
    "description": (
        "Inspect the current mesh for 3D-printability issues: minimum wall "
        "thickness, overhangs steeper than 45°, watertightness, and bed-size "
        "fit. Returns a status (safe|warn|unprintable) and a list of issues "
        "with locations and suggested fixes. Re-runs the preview if it is "
        "stale."
    ),
    "input_schema": CheckManufacturabilityInput.model_json_schema(),
}


def _load_mesh(stl_path: Path):
    mesh = trimesh.load_mesh(stl_path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = trimesh.util.concatenate(tuple(mesh.dump()))  # type: ignore[arg-type]
    return mesh


def execute(payload: dict, ctx: AgentContext) -> dict:
    workspace_dir = ctx.output_dir / "workspaces" / ctx.workspace_id
    stale = (
        ctx.last_preview is None
        or ctx.last_preview.get("revision_id") != ctx.model.revision_id
    )
    try:
        if stale:
            _, stl_path, _ = export_editable_preview(ctx.model, workspace_dir)
        else:
            stl_path = Path(ctx.last_preview["stl_path"])  # type: ignore[index]
            if not stl_path.exists():
                _, stl_path, _ = export_editable_preview(ctx.model, workspace_dir)
        mesh = _load_mesh(stl_path)
    except Exception as exc:
        return {
            "error": f"Could not build preview for manufacturability check: {exc}",
            "current_revision_id": ctx.model.revision_id,
        }

    report = check_mesh(mesh, ctx.printer_profile)
    return {
        "ok": True,
        "revision_id": ctx.model.revision_id,
        "mesh_hash": report.mesh_hash,
        "report": report.model_dump(),
    }


__all__ = ["TOOL_DEFINITION", "CheckManufacturabilityInput", "execute"]
