"""Tool: return the active design's script, parameters, and last-build summary."""

from __future__ import annotations

from pydantic import BaseModel

from services.ai.tools_v2 import DesignContext


class ReadDesignInput(BaseModel):
    pass


TOOL_DEFINITION = {
    "name": "read_design",
    "description": (
        "Return the active design's script, current parameter values, named "
        "feature outline, and a summary of the last build (mesh hash, bounding "
        "box, manufacturability status). Call this at the start of a turn if "
        "the user's intent depends on what is currently in the design."
    ),
    "input_schema": ReadDesignInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    """Compact summary of the active design.

    The full script and the per-turn context already arrive in the system
    prompt — read_design's job is to surface what's *not* there yet (build
    status, manufacturability summary) and let the agent confirm the script
    didn't drift since the last turn. Returning the full script here
    duplicates ~3-5k tokens on every turn that calls it.
    """
    design = ctx.design
    feature_outline = [
        {
            "id": f.id,
            "name": f.name,
            "kind": f.kind,
            "parent_feature_ids": f.parent_feature_ids,
            "created_by": f.created_by,
            "revision_id": f.revision_id,
            "user_words": f.user_words,
        }
        for f in design.features
    ]
    parameters = [
        {
            "name": p.name,
            "value": p.value,
            "type": p.type,
            "min": p.min,
            "max": p.max,
        }
        for p in design.parameters
    ]
    last_build = ctx.last_build
    script_lines = design.script.count("\n") + 1
    has_imported_mesh = bool(design.metadata.get("imported_files"))
    return {
        "ok": True,
        "design_id": ctx.design.id,
        "name": design.name,
        "revision_id": design.revision_id,
        "process_target": design.process,
        "script_lines": script_lines,
        "script_note": (
            "The full script is provided in the system prompt context — refer to it there. "
            "If you need it again as a tool result, ask the user."
        ),
        "has_imported_mesh": has_imported_mesh,
        "parameters": parameters,
        "features": feature_outline,
        "last_build": (
            {
                "revision_id": last_build.revision_id,
                "mesh_hash": last_build.mesh_hash,
                "bounding_box_mm": last_build.bounding_box_mm,
                "manufacturability_status": (
                    last_build.manufacturability.status if last_build.manufacturability else None
                ),
                "artifact_kinds": list(last_build.artifacts.keys()),
            }
            if last_build
            else None
        ),
    }


__all__ = ["TOOL_DEFINITION", "ReadDesignInput", "execute"]
