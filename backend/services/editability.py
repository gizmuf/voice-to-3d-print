from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from services.editable_model import BodyNode, EditableModel


EditabilityLevel = Literal[
    "editable",
    "partially_editable",
    "reference_only",
    "locked_unsafe",
]
ExportMode = Literal["rebuilt", "as_is", "blocked"]


class EditabilityAssessment(BaseModel):
    """Backend-authoritative contract for what the user can do with a model.

    The frontend renders this as a badge, but the same values gate every chat tool
    call and every export endpoint. This is what prevents the worst CAD failure
    mode: the chat says an edit happened but the exported geometry is unchanged.
    """

    level: EditabilityLevel
    reasons: list[str] = Field(default_factory=list)
    editable_node_ids: list[str] = Field(default_factory=list)
    locked_node_ids: list[str] = Field(default_factory=list)
    export_allowed: bool
    export_mode: ExportMode
    repair_required: bool = False


def _walk(bodies: list[BodyNode]):
    for body in bodies:
        yield body
        yield from _walk(body.children)


def assess(model: EditableModel) -> EditabilityAssessment:
    """Compute the editability contract for an EditableModel snapshot.

    Inputs considered:
    - `source` (native | stl_reconstructed | step_import)
    - per-node `editable` flag and `confidence` score
    - the model's stored `manufacturability` status (`safe` | `risk` | `invalid`)

    The mesh-based manufacturability check (services.manufacturability) is run
    separately at preview/build time and may override `repair_required` afterward.
    """
    editable_ids: list[str] = []
    locked_ids: list[str] = []
    for body in _walk(model.bodies):
        if body.editable and body.confidence >= 0.5:
            editable_ids.append(body.id)
        else:
            locked_ids.append(body.id)

    reasons: list[str] = []

    if model.manufacturability.status == "invalid":
        return EditabilityAssessment(
            level="locked_unsafe",
            reasons=[
                "Manufacturability check flagged the model as invalid.",
                *model.manufacturability.messages,
            ],
            editable_node_ids=[],
            locked_node_ids=[b.id for b in _walk(model.bodies)],
            export_allowed=False,
            export_mode="blocked",
            repair_required=True,
        )

    if model.source == "step_import":
        reasons.append("STEP imports are reference-only in Phase 1.")
        return EditabilityAssessment(
            level="reference_only",
            reasons=reasons,
            editable_node_ids=[],
            locked_node_ids=[b.id for b in _walk(model.bodies)],
            export_allowed=True,
            export_mode="as_is",
            repair_required=False,
        )

    if not model.bodies:
        reasons.append("Workspace has no bodies.")
        return EditabilityAssessment(
            level="reference_only",
            reasons=reasons,
            editable_node_ids=[],
            locked_node_ids=[],
            export_allowed=False,
            export_mode="blocked",
            repair_required=False,
        )

    if model.source == "native":
        if locked_ids:
            reasons.append(
                f"{len(locked_ids)} non-editable feature(s) on a native model — review."
            )
        return EditabilityAssessment(
            level="editable" if not locked_ids else "partially_editable",
            reasons=reasons,
            editable_node_ids=editable_ids,
            locked_node_ids=locked_ids,
            export_allowed=True,
            export_mode="rebuilt",
            repair_required=False,
        )

    if model.source == "stl_reconstructed":
        if not editable_ids:
            reasons.append(
                "STL reconstruction produced no recognized editable features."
            )
            return EditabilityAssessment(
                level="reference_only",
                reasons=reasons,
                editable_node_ids=[],
                locked_node_ids=locked_ids,
                export_allowed=True,
                export_mode="as_is",
                repair_required=False,
            )
        level: EditabilityLevel = "partially_editable" if locked_ids else "editable"
        if locked_ids:
            reasons.append(
                f"{len(locked_ids)} feature(s) could not be parsed and remain opaque."
            )
        return EditabilityAssessment(
            level=level,
            reasons=reasons,
            editable_node_ids=editable_ids,
            locked_node_ids=locked_ids,
            export_allowed=True,
            export_mode="rebuilt",
            repair_required=False,
        )

    # Unknown source — be conservative.
    return EditabilityAssessment(
        level="reference_only",
        reasons=[f"Unknown workspace source: {model.source}."],
        editable_node_ids=[],
        locked_node_ids=[b.id for b in _walk(model.bodies)],
        export_allowed=False,
        export_mode="blocked",
        repair_required=False,
    )


def is_node_editable(model: EditableModel, node_id: str) -> bool:
    """Is `node_id` allowed to be mutated by an AI tool?"""
    return node_id in assess(model).editable_node_ids
