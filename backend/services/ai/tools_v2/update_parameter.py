"""Tool: change one parameter value without rewriting the script.

Fast path. The script is unchanged; we just re-run with an override and let
the script's own validation handle out-of-range values. The new value is
persisted into the Design's parameter list so subsequent reads see it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import DesignBuildError, build_design, parameter_snapshot
from services.codegen.store import save_build, save_design


class UpdateParameterInput(BaseModel):
    name: str = Field(description="Parameter name as declared by `pulsai.param()`.")
    new_value: float | int | bool | str = Field(description="New value (type matches the declared type).")
    rationale: str = Field(max_length=200, description="One sentence why this change.")
    override_locked: bool = Field(default=False, description="True only when the user explicitly asked to unlock/override a locked parameter.")


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


def _validated_change(params: UpdateParameterInput, ctx: DesignContext) -> tuple[object | None, object | None, dict | None]:
    """Validate one requested change without mutating the design."""
    target = next((p for p in ctx.design.parameters if p.name == params.name), None)
    if target is None:
        return None, None, {
            "error": (
                f"No parameter named '{params.name}'. Known parameters: "
                + ", ".join(p.name for p in ctx.design.parameters)
                + "."
            ),
        }
    if target.locked and not params.override_locked:
        return None, None, {
            "error": (
                f"Parameter '{params.name}' is locked by the user. Do not change it "
                "unless the user explicitly asks to unlock or override the lock."
            ),
            "locked": True,
            "name": params.name,
        }

    # Coerce the incoming value to match the existing parameter's type. Claude's
    # tool-use serialization sometimes sends numbers as JSON strings; without
    # this the script gets ``"200"`` and crashes on arithmetic.
    new_value = _coerce(target.value, params.new_value)

    if isinstance(new_value, (int, float)) and not isinstance(new_value, bool):
        if target.min is not None and float(new_value) < target.min:
            return None, None, {
                "error": (
                    f"Parameter '{params.name}' cannot be set to {new_value}; "
                    f"its declared minimum is {target.min}. Do not clamp silently — "
                    "check whether the user meant a different feature or parameter."
                ),
                "code": "parameter_below_minimum",
                "name": params.name,
                "minimum": target.min,
                "rejected_value": new_value,
            }
        if target.max is not None and float(new_value) > target.max:
            return None, None, {
                "error": (
                    f"Parameter '{params.name}' cannot be set to {new_value}; "
                    f"its declared maximum is {target.max}. Do not clamp silently — "
                    "check whether the user meant a different feature or parameter."
                ),
                "code": "parameter_above_maximum",
                "name": params.name,
                "maximum": target.max,
                "rejected_value": new_value,
            }
    if target.choices and str(new_value) not in target.choices:
        return None, None, {
            "error": (
                f"Parameter '{params.name}' must be one of: "
                + ", ".join(target.choices)
            ),
            "code": "parameter_invalid_choice",
            "name": params.name,
            "choices": target.choices,
            "rejected_value": new_value,
        }
    return target, new_value, None


def execute_many(payloads: list[dict], ctx: DesignContext) -> list[dict]:
    """Apply several independent parameter edits transactionally in one build.

    Claude commonly emits multiple ``update_parameter`` calls in one response.
    Building after each call made a two-dimension edit take twice as long and
    created an intermediate revision the user never asked for. Validate every
    value first, then commit all values and create one preview revision.
    """
    if not payloads:
        return [{"error": "No parameter changes supplied."}]

    parsed: list[UpdateParameterInput] = []
    prepared: list[tuple[object, object]] = []
    seen_names: set[str] = set()
    for index, payload in enumerate(payloads):
        try:
            params = UpdateParameterInput.model_validate(payload)
        except Exception as exc:
            error = {"error": f"Invalid input: {exc}", "code": "batch_validation_failed"}
            return [error if i == index else {"error": "Parameter batch was not applied."} for i in range(len(payloads))]
        if params.name in seen_names:
            error = {
                "error": f"Parameter '{params.name}' was requested more than once in the same batch.",
                "code": "duplicate_parameter_change",
            }
            return [error if i == index else {"error": "Parameter batch was not applied."} for i in range(len(payloads))]
        seen_names.add(params.name)
        target, new_value, validation_error = _validated_change(params, ctx)
        if validation_error is not None:
            return [
                validation_error if i == index else {"error": "Parameter batch was not applied."}
                for i in range(len(payloads))
            ]
        assert target is not None
        parsed.append(params)
        prepared.append((target, new_value))

    design = ctx.design
    previous_values = [(target, target.value) for target, _ in prepared]
    previous_revision = design.revision_id
    previous_parent_revision = design.parent_revision_id
    for target, new_value in prepared:
        target.value = new_value
    design.parent_revision_id = previous_revision
    from services.codegen.store import new_revision_id

    design.revision_id = new_revision_id()
    try:
        build = build_design(
            design,
            targets=["stl", "glb"],
            process=design.process if design.process in ("fdm", "cnc") else "fdm",
            printer_profile_id=ctx.printer_profile_id,
        )
    except DesignBuildError as exc:
        for target, previous_value in previous_values:
            target.value = previous_value
        design.revision_id = previous_revision
        design.parent_revision_id = previous_parent_revision
        return [
            {
                "error": f"Parameter change rejected: build failed with the requested values. {exc}",
                "previous_value": previous_value,
                "rejected_value": params.new_value,
            }
            for params, (_, previous_value) in zip(parsed, previous_values, strict=True)
        ]

    save_design(design)
    save_build(design.id, build)
    ctx.last_build = build
    common = {
        "new_revision_id": design.revision_id,
        "snapshot": parameter_snapshot(design),
        "mesh_hash": build.mesh_hash,
        "bounding_box_mm": build.bounding_box_mm,
        "artifacts": {kind: artifact.url for kind, artifact in build.artifacts.items()},
        "manufacturability_status": (
            build.manufacturability.status if build.manufacturability else None
        ),
        "batched_change_count": len(prepared),
    }
    return [
        {"ok": True, "name": params.name, "new_value": new_value, **common}
        for params, (_, new_value) in zip(parsed, prepared, strict=True)
    ]


def execute(payload: dict, ctx: DesignContext) -> dict:
    return execute_many([payload], ctx)[0]


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


__all__ = ["TOOL_DEFINITION", "UpdateParameterInput", "execute", "execute_many"]
