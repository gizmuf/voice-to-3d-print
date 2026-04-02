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
    if not supported_targets:
      if targets or unsupported_reasons:
        return None, "locked"
      return None, "reference"

    radial_pattern = _find_supported_radial_pattern(supported_targets)
    if radial_pattern:
        model = _radial_pattern_to_model(radial_pattern, supported_targets, analysis)
        return model, "reconstruction"

    return None, "locked"


def _find_supported_radial_pattern(targets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for target in targets:
        if (
            target.get("type") == "planar_pattern_face"
            and target.get("topology") == "radial"
            and target.get("feature_kind") == "circular_hole"
        ):
            return target
    return None


def _radial_pattern_to_model(
    pattern_target: dict[str, Any],
    targets: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> EditableModel:
    extents = analysis.get("extents_mm") or [0.0, 0.0, 0.0]
    width = float(extents[0] if len(extents) > 0 else 0.0)
    depth = float(extents[1] if len(extents) > 1 else width)
    height = float(extents[2] if len(extents) > 2 else 0.0)
    outer_diameter = max(width, depth)
    thickness = min(value for value in (width, depth, height) if value > 0) if any(value > 0 for value in (width, depth, height)) else height

    measured = pattern_target.get("measured") or {}
    center_hole_target = _resolve_center_hole_target(pattern_target, targets)
    center_hole_diameter = measured.get("center_hole_diameter")
    if center_hole_diameter in (None, 0) and center_hole_target:
        center_hole_diameter = (center_hole_target.get("measured") or {}).get("diameter")

    root = BodyNode(
        id="stl:root",
        kind="body",
        label="Imported STL reconstruction",
        editable=True,
        confidence=float(pattern_target.get("confidence", 0.0) or 0.0),
        params={
            "_template_id": "perforated_disc",
            "_object_label": "Imported STL reconstruction",
            "outer_diameter": float(outer_diameter),
            "thickness": float(thickness),
        },
        children=[],
    )
    root.children = [
        BodyNode(
            id=center_hole_target["id"] if center_hole_target else "stl:root:center_hole",
            kind="hole",
            label="Center hole",
            editable=center_hole_target.get("editable", True) if center_hole_target else True,
            confidence=float(center_hole_target.get("confidence", pattern_target.get("confidence", 0.0)) or 0.0) if center_hole_target else float(pattern_target.get("confidence", 0.0) or 0.0),
            params={"diameter_mm": _float(center_hole_diameter)},
            unsupported_reason=_warnings(center_hole_target) if center_hole_target else None,
        ),
        BodyNode(
            id=pattern_target["id"],
            kind="circular_pattern",
            label=pattern_target.get("label") or "Hole pattern",
            editable=True,
            confidence=float(pattern_target.get("confidence", 0.0) or 0.0),
            params={
                "hole_diameter_mm": _float(measured.get("feature_size")),
                "ring_count": _float(measured.get("ring_count")),
                "radial_spacing_mm": _float(measured.get("radial_spacing")),
                "tangential_spacing_mm": _float(_derived_tangential_spacing(pattern_target)),
                "edge_margin_mm": _float(measured.get("margin")),
            },
            unsupported_reason=_warnings(pattern_target),
        ),
        BodyNode(
            id="stl:root:thickness",
            kind="thickness",
            label="Thickness",
            editable=True,
            confidence=float(pattern_target.get("confidence", 0.0) or 0.0),
            params={"thickness_mm": float(thickness)},
        ),
    ]

    messages = list(analysis.get("warnings") or [])
    if not messages:
        messages = ["Supported radial circular-hole regions were reconstructed into the semantic workspace."]

    return EditableModel(
        id=uuid.uuid4().hex,
        source="stl_reconstructed",
        revision_id=uuid.uuid4().hex,
        bodies=[root],
        selection=SelectionState(feature_id=pattern_target["id"], scope="body"),
        manufacturability=Manufacturability(
            status="risk" if messages else "safe",
            messages=messages,
        ),
    )


def _resolve_center_hole_target(pattern_target: dict[str, Any], targets: list[dict[str, Any]]) -> dict[str, Any] | None:
    center_feature_id = ((pattern_target.get("fit") or {}).get("center_hole_feature_id"))
    if not center_feature_id:
        return None
    for target in targets:
        if target.get("type") != "single_planar_feature":
            continue
        if target.get("feature_id") == center_feature_id:
            return target
    return None


def _derived_tangential_spacing(pattern_target: dict[str, Any]) -> float:
    measured = pattern_target.get("measured") or {}
    spacing_x = measured.get("spacing_x")
    if isinstance(spacing_x, (int, float)):
        return float(spacing_x)
    feature_size = measured.get("feature_size")
    diameter = _float(feature_size)
    return max(diameter, 1.0)


def _warnings(target: dict[str, Any] | None) -> str | None:
    if not target:
        return None
    warnings = target.get("warnings") or []
    return "; ".join(warnings) if warnings else None


def _float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        if "width" in value:
            return float(value.get("width") or 0.0)
        if "diameter" in value:
            return float(value.get("diameter") or 0.0)
    return 0.0
