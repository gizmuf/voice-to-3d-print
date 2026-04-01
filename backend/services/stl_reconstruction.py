from __future__ import annotations

import uuid
from typing import Any

from services.editable_model import BodyNode, EditableModel, Manufacturability, SelectionState


def reconstruct_from_analysis(analysis: dict[str, Any]) -> tuple[EditableModel | None, str]:
    targets = analysis.get("targets") or []
    unsupported_reasons = analysis.get("unsupported_reasons") or []
    supported_targets = [
        target
        for target in targets
        if target.get("type") != "unsupported" and bool(target.get("editable", False))
    ]
    if supported_targets:
        model = _targets_to_model(supported_targets, analysis)
        return model, "reconstruction"
    if targets or unsupported_reasons:
        return None, "locked"
    return None, "reference"


def _targets_to_model(targets: list[dict[str, Any]], analysis: dict[str, Any]) -> EditableModel:
    root = BodyNode(
        id="stl:root",
        kind="body",
        label="Imported STL",
        editable=False,
        confidence=1.0,
        params={
            "_template_id": "stl_reconstructed",
            "_object_label": "Imported STL",
            "width_mm": float((analysis.get("extents_mm") or [0, 0, 0])[0]),
            "depth_mm": float((analysis.get("extents_mm") or [0, 0, 0])[1]),
            "height_mm": float((analysis.get("extents_mm") or [0, 0, 0])[2]),
        },
        children=[],
    )
    children: list[BodyNode] = []
    for index, target in enumerate(targets):
        target_type = target.get("type")
        label = target.get("label") or f"Target {index + 1}"
        confidence = float(target.get("confidence", 0.0) or 0.0)
        warnings = target.get("warnings") or []
        if target_type == "planar_pattern_face":
            measured = target.get("measured") or {}
            params = {
                "hole_diameter_mm": _float(measured.get("feature_size")),
                "ring_count": _float(measured.get("ring_count") or measured.get("count_y")),
                "radial_spacing_mm": _float(measured.get("radial_spacing") or measured.get("spacing_y")),
                "tangential_spacing_mm": _float(measured.get("spacing_x")),
                "edge_margin_mm": _float(measured.get("margin")),
            }
            children.append(
                BodyNode(
                    id=target["id"],
                    kind="circular_pattern" if target.get("topology") == "radial" else "linear_pattern",
                    label=label,
                    editable=True,
                    confidence=confidence,
                    params=params,
                    unsupported_reason="; ".join(warnings) if warnings else None,
                )
            )
        elif target_type == "single_planar_feature":
            measured = target.get("measured") or {}
            children.append(
                BodyNode(
                    id=target["id"],
                    kind="hole" if target.get("feature_kind") == "circular_hole" else "slot",
                    label=label,
                    editable=True,
                    confidence=confidence,
                    params={
                        "diameter_mm": _float(measured.get("diameter")),
                        "width_mm": _float(measured.get("width")),
                        "height_mm": _float(measured.get("height")),
                    },
                    unsupported_reason="; ".join(warnings) if warnings else None,
                )
            )
    root.children = children
    selection = SelectionState(feature_id=children[0].id, scope="body") if children else None
    return EditableModel(
        id=uuid.uuid4().hex,
        source="stl_reconstructed",
        revision_id=uuid.uuid4().hex,
        bodies=[root],
        selection=selection,
        manufacturability=Manufacturability(
            status="risk" if analysis.get("warnings") else "safe",
            messages=list(analysis.get("warnings") or ["Reconstructed editable regions are limited to supported high-confidence targets."]),
        ),
    )


def _float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        if "width" in value:
            return float(value.get("width") or 0.0)
    return 0.0

