"""Tool: surgically replace the body of a `# @feature: name ... # @end` block."""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import (
    DesignBuildError,
    audit_then_run,
    derive_named_features,
    derive_parameters,
    design_script_is_trusted,
    trusted_script_metadata,
)
from services.codegen.ast_audit import audit_generated_cad_fragment
from services.codegen.store import new_revision_id, save_design


class ReplaceFeatureInput(BaseModel):
    feature_name: str = Field(description="Name of the existing feature block to replace.")
    new_code: str = Field(
        description=(
            "build123d code for the new block body. Do NOT include the "
            "`# @feature:` and `# @end` markers — the engine wraps your code "
            "with them automatically. Use parameters by name, not literals. "
            "For side-wall hole rings, place horizontal cutters at the middle "
            "of wall thickness with radial axes; don't leave them centered at "
            "the origin. Do not assign temporary Cylinder/Box cutters inside "
            "an active BuildPart; build cutters first, then subtract them."
        )
    )
    rationale: str = Field(max_length=300, description="One sentence why.")


TOOL_DEFINITION = {
    "name": "replace_feature",
    "description": (
        "Replace the body of a named feature block in the design script. "
        "The block is identified by its `# @feature: <name>` marker. The "
        "rest of the script is preserved. The new code is sandbox-validated "
        "before the change is committed; if the build fails the design is "
        "rolled back."
    ),
    "input_schema": ReplaceFeatureInput.model_json_schema(),
}


def _replace_block(script: str, name: str, new_body: str) -> tuple[str, bool]:
    out_lines: list[str] = []
    skipping = False
    replaced = False
    for line in script.splitlines():
        stripped = line.strip()
        if not skipping and stripped.startswith("# @feature:"):
            current_name = stripped[len("# @feature:") :].strip()
            if current_name == name:
                out_lines.append(line)
                # Inject the new body
                indent_prefix = line[: len(line) - len(line.lstrip())]
                for body_line in new_body.splitlines():
                    out_lines.append(indent_prefix + body_line if body_line else body_line)
                skipping = True
                replaced = True
                continue
        if skipping and stripped == "# @end":
            out_lines.append(line)
            skipping = False
            continue
        if skipping:
            continue
        out_lines.append(line)
    return "\n".join(out_lines), replaced


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = ReplaceFeatureInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    new_script, replaced = _replace_block(ctx.design.script, params.feature_name, params.new_code)
    if not replaced:
        existing = [f.name for f in ctx.design.features]
        return {
            "error": (
                f"No `# @feature: {params.feature_name}` block found. "
                f"Known features: {existing}. Use append_feature to add a new one."
            ),
        }

    fragment_audit = audit_generated_cad_fragment(params.new_code)
    if not fragment_audit.ok:
        raise DesignBuildError(
            "Generated feature failed the strict CAD allowlist audit.",
            audit_errors=fragment_audit.errors,
        )

    source_is_trusted = design_script_is_trusted(ctx.design)
    overrides = {p.name: p.value for p in ctx.design.parameters}
    sandbox_result = audit_then_run(
        script=new_script,
        parameter_overrides=overrides,
        targets=["stl"],
        imported_files=ctx.design.metadata.get("imported_files") or None,
        trusted_source=source_is_trusted,
    )
    if not sandbox_result.ok:
        return {
            "error": (
                "Replace_feature build failed; design unchanged. "
                f"Sandbox said: {sandbox_result.payload.get('error')}"
            ),
            "audit_or_runtime": sandbox_result.payload.get("traceback") or "",
        }

    previous_features = list(ctx.design.features)
    ctx.design.parent_revision_id = ctx.design.revision_id
    ctx.design.revision_id = new_revision_id()
    ctx.design.script = new_script
    ctx.design.metadata.pop("trusted_script", None)
    ctx.design.metadata.pop("trusted_script_sha256", None)
    if source_is_trusted:
        # Trust is propagated only from an exact reviewed source and only after
        # the edited script passes the AST audit and isolated sandbox build.
        ctx.design.metadata.update(trusted_script_metadata(new_script))
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
        "feature_name": params.feature_name,
        "new_revision_id": ctx.design.revision_id,
        "feature_count": len(ctx.design.features),
        "parameters": [p.name for p in ctx.design.parameters],
    }


__all__ = ["TOOL_DEFINITION", "ReplaceFeatureInput", "execute"]
