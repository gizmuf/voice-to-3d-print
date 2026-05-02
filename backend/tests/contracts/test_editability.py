"""Unit tests for the EditabilityAssessment contract."""

from __future__ import annotations

from services.editability import assess
from services.editable_model import (
    BodyNode,
    EditableModel,
    Manufacturability,
)


def _native_disc() -> EditableModel:
    return EditableModel(
        id="m",
        source="native",
        revision_id="r0",
        bodies=[
            BodyNode(
                id="perforated_disc:root",
                kind="body",
                label="Disc",
                params={"_template_id": "perforated_disc", "outer_diameter": 300.0, "thickness": 5.0},
                children=[
                    BodyNode(id="perforated_disc:root:center_hole", kind="hole", label="Center hole", params={"diameter_mm": 16.0}),
                ],
            )
        ],
    )


def test_native_workspace_is_editable() -> None:
    assessment = assess(_native_disc())
    assert assessment.level == "editable"
    assert assessment.export_allowed
    assert assessment.export_mode == "rebuilt"
    assert "perforated_disc:root" in assessment.editable_node_ids
    assert "perforated_disc:root:center_hole" in assessment.editable_node_ids


def test_step_import_is_reference_only() -> None:
    model = EditableModel(
        id="m2",
        source="step_import",
        revision_id="r0",
        bodies=[
            BodyNode(
                id="step:root",
                kind="body",
                label="ref.step",
                editable=False,
                confidence=0.0,
                params={"_template_id": "step_reference", "width_mm": 100.0},
            )
        ],
    )
    assessment = assess(model)
    assert assessment.level == "reference_only"
    assert assessment.export_allowed
    assert assessment.export_mode == "as_is"
    assert assessment.editable_node_ids == []


def test_invalid_manufacturability_locks_workspace() -> None:
    model = _native_disc()
    model.manufacturability = Manufacturability(
        status="invalid", messages=["Holes overlap edge."]
    )
    assessment = assess(model)
    assert assessment.level == "locked_unsafe"
    assert not assessment.export_allowed
    assert assessment.export_mode == "blocked"
    assert assessment.repair_required


def test_partially_editable_when_some_nodes_locked() -> None:
    model = _native_disc()
    locked_child = BodyNode(
        id="locked_child",
        kind="hole",
        label="Locked feature",
        editable=False,
        confidence=0.1,
        params={"diameter_mm": 5.0},
    )
    model.bodies[0].children.append(locked_child)
    assessment = assess(model)
    assert assessment.level == "partially_editable"
    assert "locked_child" in assessment.locked_node_ids
    assert "locked_child" not in assessment.editable_node_ids
