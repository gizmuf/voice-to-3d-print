"""Per-(source, template) capability matrix for AI tool calls.

The matrix is consulted before every mutating tool call. It guarantees that:

- An AI tool can never silently mutate something that won't appear in the
  exported geometry. If the structured-spec rebuild path doesn't read a
  parameter, the matrix refuses to mutate it.
- Refusals carry a clear human-readable reason.
- New reconstruction features must opt into the matrix before becoming
  AI-editable. Contract tests in ``backend/tests/contracts`` enforce this.

Phase 1 reflects the present rebuild path:
``services.editable_rebuild.rebuild_from_editable`` ->
``services.native_converter.editable_to_structured_spec`` ->
``services.useful_objects._cadquery_workplane_for_spec``.

Only parameters that round-trip through that pipeline are listed as mutable.
``add_feature`` and ``remove_feature`` are refused workspace-wide in Phase 1
because the rebuild path is hardcoded to a fixed feature set per template.
Phase 2 will introduce a generic ``compile_tree`` and lift those refusals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from services.editable_model import EditableModel, WorkspaceSource


ToolName = Literal[
    "mutate_parameter",
    "add_feature",
    "remove_feature",
    "run_preview",
    "check_manufacturability",
    "query_tree",
]


class ToolCapability(BaseModel):
    """Per-template/source declaration of supported edits."""

    template_id: str
    source: WorkspaceSource
    mutable_params_by_node_kind: dict[str, list[str]] = Field(default_factory=dict)
    addable_feature_kinds: list[str] = Field(default_factory=list)
    removable_node_kinds: list[str] = Field(default_factory=list)
    unsupported_reasons: dict[ToolName, str] = Field(default_factory=dict)


# Mapping of template_id -> mutable params per kind, for native CadQuery templates.
# Only params that ``editable_to_structured_spec`` actually copies into the spec
# are listed; everything else is refused.
_NATIVE_MUTABLE: dict[str, dict[str, list[str]]] = {
    "perforated_disc": {
        "body": ["outer_diameter", "thickness"],
        "hole": ["diameter_mm"],
        "circular_pattern": [
            "hole_diameter_mm",
            "ring_count",
            "radial_spacing_mm",
            "tangential_spacing_mm",
            "edge_margin_mm",
        ],
        "thickness": ["thickness_mm"],
    },
    "phone_stand": {
        "body": ["width", "depth", "height"],
        "thickness": [
            "base_thickness_mm",
            "back_thickness_mm",
            "lip_height_mm",
            "angle_deg",
        ],
        "hole": ["cable_hole_diameter_mm"],
    },
    "simple_box": {
        "body": ["width", "depth", "height"],
        "thickness": ["wall_thickness_mm", "open_top", "hollow"],
        "fillet": ["fillet_mm"],
    },
    "tray": {
        "body": ["width", "depth", "height"],
        "thickness": ["wall_thickness_mm", "open_top", "hollow"],
        "fillet": ["fillet_mm"],
    },
    "hook": {
        "body": ["width", "depth", "height"],
        "thickness": [
            "plate_thickness_mm",
            "hook_thickness_mm",
            "hook_gap_mm",
        ],
    },
    "cable_organizer": {
        "body": ["width", "depth", "height"],
        "linear_pattern": ["slot_count", "slot_width_mm", "wall_thickness_mm"],
    },
    "bracket": {
        "body": ["width", "depth", "height"],
        "thickness": ["thickness_mm"],
        "hole": ["hole_diameter_mm"],
    },
    "cylindrical_holder": {
        # DEFAULT_SPECS uses "diameter"/"height" for this template — not the
        # "outer_diameter"/"thickness" names other shapes use. Stay aligned with
        # the actual seeded tree so the contract tests don't drift.
        "body": ["diameter", "height"],
        "thickness": ["wall_thickness_mm", "base_thickness_mm"],
    },
    "wall_mount": {
        "body": ["width", "depth", "height"],
        "thickness": [
            "plate_thickness_mm",
            "arm_thickness_mm",
            "arm_drop_mm",
        ],
    },
}


# STL reconstruction currently produces only a perforated-disc-shaped tree
# (see services/stl_reconstruction.py). Mutable params mirror that shape.
_STL_RECONSTRUCTED_MUTABLE: dict[str, dict[str, list[str]]] = {
    "perforated_disc": {
        "body": ["outer_diameter", "thickness"],
        "hole": ["diameter_mm"],
        "circular_pattern": [
            "hole_diameter_mm",
            "ring_count",
            "radial_spacing_mm",
            "tangential_spacing_mm",
            "edge_margin_mm",
        ],
        "thickness": ["thickness_mm"],
    },
}


_PHASE_1_REFUSALS: dict[ToolName, str] = {
    "add_feature": (
        "Phase 1 supports parameter mutation only. Adding new features "
        "(holes, fillets, slots) will be available in Phase 2 once the "
        "generic codegen path is in place."
    ),
    "remove_feature": (
        "Phase 1 supports parameter mutation only. Removing features will "
        "be available in Phase 2."
    ),
}


def _step_import_capability(template_id: str) -> ToolCapability:
    return ToolCapability(
        template_id=template_id or "unknown",
        source="step_import",
        unsupported_reasons={
            "mutate_parameter": "STEP imports are reference-only in Phase 1.",
            "add_feature": "STEP imports are reference-only in Phase 1.",
            "remove_feature": "STEP imports are reference-only in Phase 1.",
        },
    )


def _native_capability(template_id: str) -> ToolCapability:
    mutable = _NATIVE_MUTABLE.get(template_id, {})
    if not mutable:
        return ToolCapability(
            template_id=template_id or "unknown",
            source="native",
            unsupported_reasons={
                "mutate_parameter": (
                    f"Template '{template_id}' is not in the Phase 1 capability "
                    "matrix. No editable parameters declared."
                ),
                **_PHASE_1_REFUSALS,
            },
        )
    return ToolCapability(
        template_id=template_id,
        source="native",
        mutable_params_by_node_kind=mutable,
        unsupported_reasons=dict(_PHASE_1_REFUSALS),
    )


def _stl_reconstructed_capability(template_id: str) -> ToolCapability:
    mutable = _STL_RECONSTRUCTED_MUTABLE.get(template_id)
    if not mutable:
        return ToolCapability(
            template_id=template_id or "unknown",
            source="stl_reconstructed",
            unsupported_reasons={
                "mutate_parameter": (
                    "STL reconstruction did not recognize this geometry as "
                    "an editable shape. The model is reference-only."
                ),
                **_PHASE_1_REFUSALS,
            },
        )
    return ToolCapability(
        template_id=template_id,
        source="stl_reconstructed",
        mutable_params_by_node_kind=mutable,
        unsupported_reasons=dict(_PHASE_1_REFUSALS),
    )


def template_id_for(model: EditableModel) -> str:
    if not model.bodies:
        return "unknown"
    return str(model.bodies[0].params.get("_template_id", "unknown"))


def capability_for(model: EditableModel) -> ToolCapability:
    """Look up the active capability for a workspace's editable model."""
    template_id = template_id_for(model)
    if model.source == "step_import":
        return _step_import_capability(template_id)
    if model.source == "stl_reconstructed":
        return _stl_reconstructed_capability(template_id)
    if model.source == "native":
        return _native_capability(template_id)
    return ToolCapability(
        template_id=template_id,
        source=model.source,
        unsupported_reasons={
            "mutate_parameter": f"Unknown workspace source: {model.source}.",
            **_PHASE_1_REFUSALS,
        },
    )


def can_mutate_param(
    capability: ToolCapability, node_kind: str, param_name: str
) -> tuple[bool, str | None]:
    """Return (allowed, refusal_reason). ``refusal_reason`` is None when allowed."""
    if "mutate_parameter" in capability.unsupported_reasons:
        return False, capability.unsupported_reasons["mutate_parameter"]
    allowed = capability.mutable_params_by_node_kind.get(node_kind, [])
    if param_name in allowed:
        return True, None
    if not allowed:
        return False, (
            f"Node kind '{node_kind}' has no mutable parameters declared in the "
            f"Phase 1 capability matrix for template '{capability.template_id}'."
        )
    return False, (
        f"Parameter '{param_name}' is not mutable on node kind '{node_kind}'. "
        f"Allowed: {sorted(allowed)}."
    )


def refusal_for_tool(capability: ToolCapability, tool: ToolName) -> str | None:
    return capability.unsupported_reasons.get(tool)


def capability_summary(capability: ToolCapability) -> str:
    """Compact human/Claude-readable summary, included in the agent prompt."""
    lines = [
        f"source={capability.source} template={capability.template_id}",
    ]
    if capability.mutable_params_by_node_kind:
        lines.append("mutable parameters by node kind:")
        for kind, params in sorted(capability.mutable_params_by_node_kind.items()):
            lines.append(f"  - {kind}: {', '.join(params)}")
    else:
        lines.append("no mutable parameters in Phase 1")
    if capability.unsupported_reasons:
        lines.append("refusals:")
        for tool, reason in capability.unsupported_reasons.items():
            lines.append(f"  - {tool}: {reason}")
    return "\n".join(lines)


__all__ = [
    "ToolCapability",
    "ToolName",
    "capability_for",
    "capability_summary",
    "can_mutate_param",
    "refusal_for_tool",
    "template_id_for",
]
