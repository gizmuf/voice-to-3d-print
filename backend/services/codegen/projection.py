"""Projection: ``Design`` -> the legacy ``EditableModel`` shape.

The frontend's existing inspector renders an ``EditableModel`` (a ``BodyNode``
tree). The new code-driven engine doesn't use that schema natively, but to
avoid a big-bang UI rewrite we project a Design into one BodyNode whose
children are the design's named features and whose ``params`` are the design's
exposed parameters. The frontend keeps showing things; the code-gen engine is
the source of truth.
"""

from __future__ import annotations

import uuid

from services.codegen.models import Build, Design
from services.editable_model import (
    BodyNode,
    EditableModel,
    Manufacturability,
    SelectionState,
)


def design_to_editable_model(design: Design, build: Build | None = None) -> EditableModel:
    """Turn a Design + optional latest Build into an EditableModel snapshot."""
    public_params: dict[str, float | str | bool] = {
        p.name: p.value if isinstance(p.value, (int, float, bool, str)) else str(p.value)
        for p in design.parameters
    }
    public_params["_template_id"] = design.metadata.get("template_id", "design")
    public_params["_object_label"] = design.name

    feature_children = [
        BodyNode(
            id=f"{design.id}:feature:{feat.name}",
            kind="body",  # narrow choice; the front-end uses kind for icon/styling, not for behavior anymore
            label=feat.name,
            editable=True,
            confidence=1.0,
            params={"_feature_kind": feat.kind, "_source_preview": feat.source[:200]},
        )
        for feat in design.features
    ]

    root = BodyNode(
        id=f"{design.id}:root",
        kind="body",
        label=design.name,
        editable=True,
        confidence=1.0,
        params=public_params,
        children=feature_children,
    )

    manufacturability = Manufacturability(status="safe", messages=["No build yet."])
    if build and build.manufacturability:
        report = build.manufacturability
        legacy_status = (
            "invalid"
            if report.status == "unprintable"
            else ("risk" if report.status == "warn" else "safe")
        )
        manufacturability = Manufacturability(
            status=legacy_status,
            messages=[i.message for i in report.issues] or ["Build passed all checks."],
        )

    return EditableModel(
        id=design.id,
        source="native",  # the legacy enum doesn't yet have "code-driven"; native is the closest fit
        revision_id=design.revision_id,
        bodies=[root],
        selection=SelectionState(feature_id=root.id, scope="body"),
        manufacturability=manufacturability,
    )


def fresh_workspace_id() -> str:
    return uuid.uuid4().hex


__all__ = ["design_to_editable_model", "fresh_workspace_id"]
