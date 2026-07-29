from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from services.editable_model import BodyNode, EditableModel, Manufacturability, SelectionState
from services.useful_objects import DEFAULT_SPECS, _perforated_disc_layout, _perforated_disc_params


def _root_id(template_id: str) -> str:
    return f"{template_id}:root"


def _child_id(parent_id: str, role: str, index: int | None = None) -> str:
    suffix = f":{role}" if index is None else f":{role}:{index}"
    return f"{parent_id}{suffix}"


def _base_root(spec: dict[str, Any]) -> BodyNode:
    template_id = spec["template_id"]
    label = spec.get("object_label") or template_id.replace("_", " ")
    dims = {
        key: float(value) if isinstance(value, (int, float)) else value
        for key, value in spec.get("dimensions_mm", {}).items()
    }
    dims["_template_id"] = template_id
    dims["_object_label"] = label
    return BodyNode(
        id=_root_id(template_id),
        kind="body",
        label=label,
        editable=True,
        confidence=1.0,
        params=dims,
        children=[],
    )


def structured_spec_to_editable(spec: dict[str, Any]) -> EditableModel:
    template_id = spec["template_id"]
    root = _base_root(spec)
    constraints = deepcopy(spec.get("constraints", {}))

    if template_id == "perforated_disc":
        root.children = [
            BodyNode(
                id=_child_id(root.id, "center_hole"),
                kind="hole",
                label="Center hole",
                params={"diameter_mm": float(constraints.get("center_hole_diameter_mm", 0.0) or 0.0)},
            ),
            BodyNode(
                id=_child_id(root.id, "pattern"),
                kind="circular_pattern",
                label="Hole pattern",
                params={
                    "hole_diameter_mm": float(constraints.get("hole_diameter_mm", 0.0) or 0.0),
                    "ring_count": float(constraints.get("ring_count", 1.0) or 1.0),
                    "radial_spacing_mm": float(constraints.get("radial_spacing_mm", 0.0) or 0.0),
                    "tangential_spacing_mm": float(constraints.get("tangential_spacing_mm", 0.0) or 0.0),
                    "edge_margin_mm": float(constraints.get("edge_margin_mm", 0.0) or 0.0),
                },
            ),
            BodyNode(
                id=_child_id(root.id, "thickness"),
                kind="thickness",
                label="Thickness",
                params={"thickness_mm": float(spec["dimensions_mm"].get("thickness", 0.0) or 0.0)},
            ),
        ]
        manufacturability = _perforated_disc_manufacturability(spec)
        selection = SelectionState(feature_id=_child_id(root.id, "pattern"), scope="body")
    else:
        root.children = _template_children(template_id, root.id, constraints)
        if template_id in {"jewelry_piece", "jewelry_pendant", "jewelry_ring"}:
            manufacturability = _jewelry_manufacturability(spec)
        else:
            manufacturability = Manufacturability(status="safe", messages=["Geometry is within the current manufacturable range."])
        selection = SelectionState(feature_id=root.id, scope="body")

    return EditableModel(
        id=uuid.uuid4().hex,
        source="native",
        revision_id=uuid.uuid4().hex,
        bodies=[root],
        manufacturability=manufacturability,
        selection=selection,
    )


def editable_to_structured_spec(model: EditableModel) -> dict[str, Any]:
    if not model.bodies:
        raise ValueError("Editable model has no root body.")
    root = model.bodies[0]
    template_id = str(root.params.get("_template_id", "perforated_disc"))
    base = deepcopy(DEFAULT_SPECS.get(template_id, DEFAULT_SPECS["perforated_disc"]))
    base["template_id"] = template_id
    base["object_label"] = str(root.params.get("_object_label", base.get("object_label", template_id)))

    for key, value in list(root.params.items()):
        if key.startswith("_"):
            continue
        if key in base["dimensions_mm"]:
            base["dimensions_mm"][key] = value

    for child in root.children:
        if template_id == "perforated_disc":
            if child.kind == "hole" and child.label == "Center hole":
                base["constraints"]["center_hole_diameter_mm"] = _numeric(child.params.get("diameter_mm"))
            elif child.kind == "circular_pattern":
                base["constraints"]["hole_diameter_mm"] = _numeric(child.params.get("hole_diameter_mm"))
                base["constraints"]["ring_count"] = _numeric(child.params.get("ring_count"))
                base["constraints"]["radial_spacing_mm"] = _numeric(child.params.get("radial_spacing_mm"))
                base["constraints"]["tangential_spacing_mm"] = _numeric(child.params.get("tangential_spacing_mm"))
                base["constraints"]["edge_margin_mm"] = _numeric(child.params.get("edge_margin_mm"))
            elif child.kind == "thickness":
                base["dimensions_mm"]["thickness"] = _numeric(child.params.get("thickness_mm"))
            continue

        if child.kind == "thickness":
            for key, value in child.params.items():
                if key in base["constraints"]:
                    base["constraints"][key] = value
        elif child.kind in {"hole", "slot", "pocket", "boss", "linear_pattern", "fillet", "chamfer"}:
            for key, value in child.params.items():
                if key in base["constraints"]:
                    base["constraints"][key] = value

    return base


def refresh_manufacturability(model: EditableModel) -> Manufacturability:
    if not model.bodies:
        return Manufacturability(status="invalid", messages=["Editable model has no root body."])
    root = model.bodies[0]
    template_id = str(root.params.get("_template_id", ""))
    if template_id == "perforated_disc":
        return _perforated_disc_manufacturability(editable_to_structured_spec(model))
    if template_id in {"jewelry_piece", "jewelry_pendant", "jewelry_ring"}:
        return _jewelry_manufacturability(editable_to_structured_spec(model))
    return Manufacturability(status="safe", messages=["Geometry is within the current manufacturable range."])


def _template_children(template_id: str, root_id: str, constraints: dict[str, Any]) -> list[BodyNode]:
    if template_id == "phone_stand":
        return [
            BodyNode(id=_child_id(root_id, "thickness"), kind="thickness", label="Stand thickness", params={
                "base_thickness_mm": _numeric(constraints.get("base_thickness_mm")),
                "back_thickness_mm": _numeric(constraints.get("back_thickness_mm")),
                "lip_height_mm": _numeric(constraints.get("lip_height_mm")),
                "angle_deg": _numeric(constraints.get("angle_deg")),
            }),
            BodyNode(id=_child_id(root_id, "hole"), kind="hole", label="Cable hole", params={
                "cable_hole_diameter_mm": _numeric(constraints.get("cable_hole_diameter_mm")),
            }),
        ]
    if template_id in {"simple_box", "tray"}:
        return [
            BodyNode(id=_child_id(root_id, "thickness"), kind="thickness", label="Wall thickness", params={
                "wall_thickness_mm": _numeric(constraints.get("wall_thickness_mm")),
                "open_top": bool(constraints.get("open_top", template_id == "tray")),
                "hollow": bool(constraints.get("hollow", True)),
            }),
            BodyNode(id=_child_id(root_id, "fillet"), kind="fillet", label="Edge fillet", params={
                "fillet_mm": _numeric(constraints.get("fillet_mm")),
            }),
        ]
    if template_id == "hook":
        return [
            BodyNode(id=_child_id(root_id, "thickness"), kind="thickness", label="Hook section", params={
                "plate_thickness_mm": _numeric(constraints.get("plate_thickness_mm")),
                "hook_thickness_mm": _numeric(constraints.get("hook_thickness_mm")),
                "hook_gap_mm": _numeric(constraints.get("hook_gap_mm")),
            }),
        ]
    if template_id == "cable_organizer":
        return [
            BodyNode(id=_child_id(root_id, "slots"), kind="linear_pattern", label="Cable slots", params={
                "slot_count": _numeric(constraints.get("slot_count")),
                "slot_width_mm": _numeric(constraints.get("slot_width_mm")),
                "wall_thickness_mm": _numeric(constraints.get("wall_thickness_mm")),
            }),
        ]
    if template_id == "bracket":
        return [
            BodyNode(id=_child_id(root_id, "thickness"), kind="thickness", label="Bracket thickness", params={
                "thickness_mm": _numeric(constraints.get("thickness_mm")),
            }),
            BodyNode(id=_child_id(root_id, "hole"), kind="hole", label="Bracket hole", params={
                "hole_diameter_mm": _numeric(constraints.get("hole_diameter_mm")),
            }),
        ]
    if template_id == "cylindrical_holder":
        return [
            BodyNode(id=_child_id(root_id, "thickness"), kind="thickness", label="Holder thickness", params={
                "wall_thickness_mm": _numeric(constraints.get("wall_thickness_mm")),
                "base_thickness_mm": _numeric(constraints.get("base_thickness_mm")),
            }),
        ]
    if template_id == "wall_mount":
        return [
            BodyNode(id=_child_id(root_id, "thickness"), kind="thickness", label="Wall mount thickness", params={
                "plate_thickness_mm": _numeric(constraints.get("plate_thickness_mm")),
                "arm_thickness_mm": _numeric(constraints.get("arm_thickness_mm")),
                "arm_drop_mm": _numeric(constraints.get("arm_drop_mm")),
            }),
        ]
    if template_id in {"jewelry_piece", "jewelry_pendant"}:
        return [
            BodyNode(id=_child_id(root_id, "attachment"), kind="hole", label="Chain / connector openings", params={
                "loop_outer_diameter_mm": _numeric(constraints.get("loop_outer_diameter_mm")),
                "loop_inner_diameter_mm": _numeric(constraints.get("loop_inner_diameter_mm")),
                "attachment_count": _numeric(constraints.get("attachment_count")),
            }),
            BodyNode(id=_child_id(root_id, "relief"), kind="boss", label="Raised or engraved detail", params={
                "relief_depth_mm": _numeric(constraints.get("relief_depth_mm")),
            }),
            BodyNode(id=_child_id(root_id, "finish"), kind="fillet", label="Softened jewelry edges", params={
                "edge_bevel_mm": _numeric(constraints.get("edge_bevel_mm")),
            }),
        ]
    if template_id == "jewelry_ring":
        return [
            BodyNode(id=_child_id(root_id, "band"), kind="thickness", label="Ring band", params={
                "band_thickness_mm": _numeric(constraints.get("band_thickness_mm")),
                "comfort_bevel_mm": _numeric(constraints.get("comfort_bevel_mm")),
                "relief_depth_mm": _numeric(constraints.get("relief_depth_mm")),
            }),
            BodyNode(id=_child_id(root_id, "stone"), kind="hole", label="Optional stone seat", params={
                "stone_seat_diameter_mm": _numeric(constraints.get("stone_seat_diameter_mm")),
            }),
        ]
    return []


def _numeric(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _perforated_disc_manufacturability(spec: dict[str, Any]) -> Manufacturability:
    try:
        params = _perforated_disc_params(spec)
        _perforated_disc_layout(spec)
        messages: list[str] = []
        status = "safe"
        if params["edge_margin"] < 4:
            status = "risk"
            messages.append("Edge margin is tight near the outer boundary.")
        if params["radial_spacing"] < params["hole_diameter"] + 1.4:
            status = "risk"
            messages.append("Wall thickness between rings is getting tight.")
        if params["tangential_spacing"] < 1.4:
            status = "risk"
            messages.append("Tangential spacing is getting tight around the rings.")
        if not messages:
            messages.append("Geometry is within the current manufacturable range.")
        return Manufacturability(status=status, messages=messages)
    except Exception as exc:
        return Manufacturability(status="invalid", messages=[str(exc)])


def _jewelry_manufacturability(spec: dict[str, Any]) -> Manufacturability:
    template_id = spec.get("template_id")
    dims = spec.get("dimensions_mm", {})
    constraints = spec.get("constraints", {})
    status = "safe"
    messages: list[str] = []

    if template_id == "jewelry_ring":
        band_thickness = _numeric(constraints.get("band_thickness_mm"))
        band_width = _numeric(dims.get("band_width"))
        if band_thickness < 1.2:
            status = "risk"
            messages.append("Ring band thickness is below 1.2 mm; it may be fragile after casting or resin printing.")
        if band_width < 2.0:
            status = "risk"
            messages.append("Ring band width is very narrow for wearable jewelry.")
    else:
        thickness = _numeric(dims.get("thickness"))
        loop_inner = _numeric(constraints.get("loop_inner_diameter_mm"))
        if thickness < 1.2:
            status = "risk"
            messages.append("Jewelry body thickness is below 1.2 mm; fine details may break.")
        if 0 < loop_inner < 2.0:
            status = "risk"
            messages.append("Connector opening is under 2 mm; chains or jump rings may not fit cleanly.")

    if not messages:
        messages.append("Jewelry starter is in a reasonable resin-printable range. Confirm final metal/casting tolerances before production.")
    return Manufacturability(status=status, messages=messages)
