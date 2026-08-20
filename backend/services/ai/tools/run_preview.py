"""Tool: rebuild the model and refresh the preview artifacts.

Returns ``revision_id`` and ``mesh_hash`` so downstream tools (and the export
endpoint) can verify the artifacts match the displayed revision. This is the
'revision truth' guarantee: an exported file always corresponds to the latest
preview, never a stale one.
"""

from __future__ import annotations

from pydantic import BaseModel

from services.ai.tools._context import AgentContext
from services.codegen.engine import run_manufacturability
from services.editable_rebuild import export_editable_preview
from services.workspace import record_preview


class RunPreviewInput(BaseModel):
    pass


TOOL_DEFINITION = {
    "name": "run_preview",
    "description": (
        "Rebuild the model from the current parameters and refresh the GLB/STL "
        "preview. Always call this after a mutation, before responding with "
        "text to the user. Returns revision_id, mesh_hash, artifact URLs, and "
        "a manufacturability summary."
    ),
    "input_schema": RunPreviewInput.model_json_schema(),
}


def execute(payload: dict, ctx: AgentContext) -> dict:
    workspace_dir = ctx.output_dir / "workspaces" / ctx.workspace_id
    try:
        glb_path, stl_path, validation = export_editable_preview(ctx.model, workspace_dir)
    except Exception as exc:
        return {
            "error": f"Preview build failed: {exc}",
            "current_revision_id": ctx.model.revision_id,
        }

    glb_url = ctx.workspace_artifact_url(glb_path)
    stl_url = ctx.workspace_artifact_url(stl_path)

    try:
        report = run_manufacturability(
            stl_path=stl_path,
            process="fdm",
            printer_profile_id=ctx.printer_profile.id,
        )
        mesh_hash = report.mesh_hash
    except Exception as exc:
        mesh_hash = ""
        report = None
        validation = {**validation, "manufacturability_error": str(exc)}

    record_preview(
        ctx.workspace_id,
        revision_id=ctx.model.revision_id,
        glb_url=glb_url,
        stl_url=stl_url,
        validation={
            **validation,
            "mesh_hash": mesh_hash,
            "manufacturability": report.model_dump() if report is not None else None,
        },
    )

    result: dict = {
        "ok": True,
        "revision_id": ctx.model.revision_id,
        "mesh_hash": mesh_hash,
        "glb_url": glb_url,
        "stl_url": stl_url,
        "validation": validation,
    }
    if report is not None:
        result["manufacturability"] = {
            "status": report.status,
            "issue_count": len(report.issues),
            "summary": [
                f"[{i.severity}] {i.code}: {i.message}" for i in report.issues
            ],
        }
    ctx.last_preview = {
        "revision_id": ctx.model.revision_id,
        "mesh_hash": mesh_hash,
        "stl_path": str(stl_path),
        "glb_url": glb_url,
        "stl_url": stl_url,
    }
    return result


__all__ = ["TOOL_DEFINITION", "RunPreviewInput", "execute"]
