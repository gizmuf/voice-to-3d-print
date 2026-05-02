"""Tool: change one parameter value without rewriting the script.

Fast path. The script is unchanged; we just re-run with an override and let
the script's own validation handle out-of-range values. The new value is
persisted into the Design's parameter list so subsequent reads see it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import audit_then_run, parameter_snapshot
from services.codegen.store import save_design


class UpdateParameterInput(BaseModel):
    name: str = Field(description="Parameter name as declared by `pulsai.param()`.")
    new_value: float | int | bool | str = Field(description="New value (type matches the declared type).")
    rationale: str = Field(max_length=200, description="One sentence why this change.")


TOOL_DEFINITION = {
    "name": "update_parameter",
    "description": (
        "Change exactly one parameter on the active design. The script does not "
        "change; the new value is fed to the script on the next build. Faster "
        "and safer than rewriting code for purely numeric edits ('make it "
        "thicker', 'twice as many holes'). Validates by running the script "
        "once with the override; rejects the change if the build fails."
    ),
    "input_schema": UpdateParameterInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = UpdateParameterInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}

    design = ctx.design
    target = next((p for p in design.parameters if p.name == params.name), None)
    if target is None:
        return {
            "error": (
                f"No parameter named '{params.name}'. Known parameters: "
                + ", ".join(p.name for p in design.parameters)
                + "."
            ),
        }

    # Coerce the incoming value to match the existing parameter's type. Claude's
    # tool-use serialization sometimes sends numbers as JSON strings; without
    # this the script gets ``"200"`` and crashes on arithmetic.
    new_value = _coerce(target.value, params.new_value)

    overrides = {p.name: p.value for p in design.parameters}
    overrides[params.name] = new_value

    sandbox_result = audit_then_run(
        script=design.script,
        parameter_overrides=overrides,
        targets=["stl"],
        imported_files=design.metadata.get("imported_files") or None,
    )
    if not sandbox_result.ok:
        return {
            "error": (
                f"Parameter change rejected: build failed with new value. "
                f"Sandbox said: {sandbox_result.payload.get('error')}"
            ),
            "previous_value": target.value,
            "rejected_value": params.new_value,
        }

    target.value = new_value
    design.parent_revision_id = design.revision_id
    from services.codegen.store import new_revision_id

    design.revision_id = new_revision_id()
    save_design(design)
    ctx.reload(design)
    return {
        "ok": True,
        "name": params.name,
        "new_value": new_value,
        "new_revision_id": design.revision_id,
        "snapshot": parameter_snapshot(design),
    }


def _coerce(existing_value, new_value):
    """Match the existing parameter's runtime type so the script doesn't crash
    on arithmetic when the LLM serialised a number as a JSON string."""
    if isinstance(existing_value, bool):
        if isinstance(new_value, bool):
            return new_value
        if isinstance(new_value, (int, float)):
            return bool(new_value)
        if isinstance(new_value, str):
            return new_value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(existing_value, int) and not isinstance(existing_value, bool):
        try:
            return int(float(new_value))
        except (TypeError, ValueError):
            pass
    if isinstance(existing_value, float):
        try:
            return float(new_value)
        except (TypeError, ValueError):
            pass
    if isinstance(existing_value, str):
        return str(new_value)
    # Fallback: attempt float, else passthrough
    try:
        return float(new_value)
    except (TypeError, ValueError):
        return new_value


__all__ = ["TOOL_DEFINITION", "UpdateParameterInput", "execute"]
