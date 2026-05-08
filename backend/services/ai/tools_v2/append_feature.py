"""Tool: append a new `# @feature: name ... # @end` block to the script."""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import audit_then_run, derive_named_features, derive_parameters
from services.codegen.store import new_revision_id, save_design


class AppendFeatureInput(BaseModel):
    name: str = Field(
        description="Unique feature name. Letters, digits, underscores; no spaces.",
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
    )
    code: str = Field(
        description=(
            "build123d code for the new block. Do NOT include the "
            "`# @feature:` and `# @end` markers — the engine wraps automatically. "
            "Do not assign `result` here; assign the updated BuildPart context to "
            "`part`, and the tool will keep the single final `result = part.part` "
            "export line coherent."
        )
    )
    rationale: str = Field(max_length=300, description="One sentence why.")


TOOL_DEFINITION = {
    "name": "append_feature",
    "description": (
        "Append a new feature block to the end of the design script. The new "
        "code can reference parameters and any objects produced by earlier "
        "blocks (typically the `part` BuildPart context). Validated by a "
        "sandbox build; rolled back on failure."
    ),
    "input_schema": AppendFeatureInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = AppendFeatureInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    if any(f.name == params.name for f in ctx.design.features):
        return {
            "error": (
                f"Feature '{params.name}' already exists. Use replace_feature "
                "to modify it."
            )
        }

    if any(line.lstrip().startswith("result") for line in params.code.splitlines()):
        return {
            "error": (
                "append_feature code must not assign `result`. Build the updated "
                "geometry and assign it to `part`; the tool owns the single final "
                "`result = part.part` line so stale exports cannot override edits."
            )
        }

    block = (
        f"\n# @feature: {params.name}\n"
        f"{params.code.rstrip()}\n"
        "# @end\n"
    )

    # Insert the new block before the final `result = ...` statement so that
    # `result` reflects the new block's effect.
    script = ctx.design.script
    lines = script.splitlines()
    insert_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("result"):
            insert_idx = i
            break
    assigns_part = any(line.lstrip().startswith("part =") for line in params.code.splitlines())
    if insert_idx < len(lines) and assigns_part:
        lines[insert_idx] = "result = part.part"
    new_script = "\n".join(lines[:insert_idx] + [block] + lines[insert_idx:])

    overrides = {p.name: p.value for p in ctx.design.parameters}
    sandbox_result = audit_then_run(
        script=new_script,
        parameter_overrides=overrides,
        targets=["stl"],
        imported_files=ctx.design.metadata.get("imported_files") or None,
    )
    if not sandbox_result.ok:
        return {
            "error": (
                "Append_feature build failed; design unchanged. "
                f"Sandbox said: {sandbox_result.payload.get('error')}"
            ),
            "traceback": sandbox_result.payload.get("traceback") or "",
        }

    previous_features = list(ctx.design.features)
    ctx.design.parent_revision_id = ctx.design.revision_id
    ctx.design.revision_id = new_revision_id()
    ctx.design.script = new_script
    ctx.design.parameters = derive_parameters(sandbox_result.payload)
    ctx.design.features = derive_named_features(
        sandbox_result.payload,
        new_script,
        previous_features=previous_features,
        revision_id=ctx.design.revision_id,
        created_by="user_prompt",
        source_prompt=ctx.current_user_message,
    )
    save_design(ctx.design)
    return {
        "ok": True,
        "feature_name": params.name,
        "new_revision_id": ctx.design.revision_id,
        "feature_count": len(ctx.design.features),
    }


__all__ = ["TOOL_DEFINITION", "AppendFeatureInput", "execute"]
