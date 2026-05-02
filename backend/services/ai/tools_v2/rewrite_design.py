"""Tool: replace the entire design script.

The escape hatch when surgical edits don't fit. The new script must still
declare its parameters via ``pulsai.param`` and assign the final shape to
``result``. AST audit + sandbox build run before the change is committed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import (
    DesignBuildError,
    audit_then_run,
    derive_named_features,
    derive_parameters,
)
from services.codegen.store import new_revision_id, save_design


class RewriteDesignInput(BaseModel):
    script: str = Field(
        description=(
            "Full build123d Python script. Must end with `result = <Part|Compound>`. "
            "Declare parameters via `pulsai.param(name, default, type=..., min=..., max=...)`."
        )
    )
    rationale: str = Field(max_length=400, description="One paragraph why a full rewrite is necessary.")


TOOL_DEFINITION = {
    "name": "rewrite_design",
    "description": (
        "Replace the entire design script. Use only when surgery via "
        "replace_feature/append_feature isn't practical (e.g. fundamental "
        "shape change). Validated by AST audit + sandbox build before commit."
    ),
    "input_schema": RewriteDesignInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = RewriteDesignInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    try:
        sandbox_result = audit_then_run(
            script=params.script,
            parameter_overrides=None,
            targets=["stl"],
            imported_files=ctx.design.metadata.get("imported_files") or None,
        )
    except DesignBuildError as exc:
        return {
            "error": "AST audit refused the new script.",
            "audit_errors": exc.audit_errors,
        }

    if not sandbox_result.ok:
        return {
            "error": (
                "rewrite_design build failed; design unchanged. "
                f"Sandbox said: {sandbox_result.payload.get('error')}"
            ),
            "traceback": sandbox_result.payload.get("traceback") or "",
        }

    previous_features = list(ctx.design.features)
    ctx.design.parent_revision_id = ctx.design.revision_id
    ctx.design.revision_id = new_revision_id()
    ctx.design.script = params.script
    ctx.design.parameters = derive_parameters(sandbox_result.payload)
    ctx.design.features = derive_named_features(
        sandbox_result.payload,
        params.script,
        previous_features=previous_features,
        revision_id=ctx.design.revision_id,
        created_by="user_prompt",
        source_prompt=ctx.current_user_message,
    )
    save_design(ctx.design)

    return {
        "ok": True,
        "new_revision_id": ctx.design.revision_id,
        "parameter_count": len(ctx.design.parameters),
        "feature_count": len(ctx.design.features),
    }


__all__ = ["TOOL_DEFINITION", "RewriteDesignInput", "execute"]
