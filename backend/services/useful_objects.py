from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import trimesh
try:
    import cadquery as cq
    from cadquery import exporters as cq_exporters
except Exception:  # pragma: no cover - optional dependency
    cq = None
    cq_exporters = None

from config import settings
from services.parametric import (
    _apply_fillet,
    _apply_hollow,
    _apply_subtract,
    _apply_union,
    _parse_angle,
    _parse_hole,
    _parse_pair,
    _parse_triplet,
    _parse_value,
    _to_mm,
)


TEMPLATE_LABELS = {
    "phone_stand": "Phone stand",
    "simple_box": "Simple box",
    "tray": "Tray",
    "hook": "Hook",
    "cable_organizer": "Cable organizer",
    "bracket": "Bracket",
    "cylindrical_holder": "Cylindrical holder",
    "wall_mount": "Wall mount",
}

DEFAULT_SPECS: Dict[str, Dict[str, Any]] = {
    "phone_stand": {
        "object_label": "Phone stand",
        "dimensions_mm": {"width": 80.0, "depth": 90.0, "height": 120.0},
        "constraints": {
            "angle_deg": 65.0,
            "base_thickness_mm": 6.0,
            "back_thickness_mm": 5.0,
            "lip_height_mm": 12.0,
            "cable_hole_diameter_mm": 0.0,
        },
    },
    "simple_box": {
        "object_label": "Simple box",
        "dimensions_mm": {"width": 120.0, "depth": 80.0, "height": 40.0},
        "constraints": {
            "wall_thickness_mm": 3.0,
            "open_top": True,
            "hollow": True,
            "fillet_mm": 0.0,
        },
    },
    "tray": {
        "object_label": "Tray",
        "dimensions_mm": {"width": 140.0, "depth": 100.0, "height": 24.0},
        "constraints": {
            "wall_thickness_mm": 3.0,
            "fillet_mm": 1.5,
        },
    },
    "hook": {
        "object_label": "Hook",
        "dimensions_mm": {"width": 34.0, "depth": 70.0, "height": 80.0},
        "constraints": {
            "plate_thickness_mm": 5.0,
            "hook_thickness_mm": 10.0,
            "hook_gap_mm": 24.0,
        },
    },
    "cable_organizer": {
        "object_label": "Cable organizer",
        "dimensions_mm": {"width": 90.0, "depth": 28.0, "height": 18.0},
        "constraints": {
            "slot_count": 3.0,
            "slot_width_mm": 8.0,
            "wall_thickness_mm": 3.0,
        },
    },
    "bracket": {
        "object_label": "Bracket",
        "dimensions_mm": {"width": 90.0, "depth": 90.0, "height": 90.0},
        "constraints": {
            "thickness_mm": 6.0,
            "hole_diameter_mm": 0.0,
        },
    },
    "cylindrical_holder": {
        "object_label": "Cylindrical holder",
        "dimensions_mm": {"diameter": 70.0, "height": 100.0},
        "constraints": {
            "wall_thickness_mm": 3.0,
            "base_thickness_mm": 4.0,
        },
    },
    "wall_mount": {
        "object_label": "Wall mount",
        "dimensions_mm": {"width": 90.0, "depth": 70.0, "height": 120.0},
        "constraints": {
            "plate_thickness_mm": 6.0,
            "arm_thickness_mm": 12.0,
            "arm_drop_mm": 24.0,
        },
    },
}

USEFUL_KEYWORDS = {
    "phone_stand": ("stand", "dock", "phone", "tablet"),
    "simple_box": ("box", "container", "case", "enclosure"),
    "tray": ("tray", "dish", "organizer tray"),
    "hook": ("hook", "hanger"),
    "cable_organizer": ("cable", "cord", "wire", "organizer"),
    "bracket": ("bracket", "support", "mounting"),
    "cylindrical_holder": ("cup", "holder", "pen", "cylinder"),
    "wall_mount": ("wall mount", "wall-mounted", "mount"),
}

CREATIVE_KEYWORDS = (
    "dragon",
    "statue",
    "figurine",
    "character",
    "creature",
    "toy",
    "monster",
    "art",
    "sculpture",
)


@dataclass
class UsefulPreview:
    job_id: str
    glb_path: Path
    structured_spec: Dict[str, Any]


@dataclass
class UsefulBuild:
    job_id: str
    glb_path: Path
    stl_path: Path
    gcode_path: Path | None
    structured_spec: Dict[str, Any]


CADQUERY_TEMPLATES = {
    "phone_stand",
    "simple_box",
    "tray",
    "hook",
    "cable_organizer",
    "bracket",
    "cylindrical_holder",
    "wall_mount",
}


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def cadquery_available() -> bool:
    return cq is not None and cq_exporters is not None


def _merge_dict(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = _deep_copy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = _deep_copy(value)
    return merged


def _keyword_score(text: str, keywords: Iterable[str]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword in lowered)


def _detect_template(text: str, existing_template: str | None = None) -> str:
    lowered = text.lower()
    if "phone stand" in lowered or ("stand" in lowered and "phone" in lowered):
        return "phone_stand"
    if any(word in lowered for word in ("cylindrical holder", "pen holder", "cup holder")):
        return "cylindrical_holder"
    best_template = existing_template or "phone_stand"
    best_score = 0
    for template_id, keywords in USEFUL_KEYWORDS.items():
        score = _keyword_score(lowered, keywords)
        if score > best_score:
            best_score = score
            best_template = template_id
    if any(word in lowered for word in ("box", "storage", "container", "case")):
        return "simple_box"
    if "tray" in lowered:
        return "tray"
    if "bracket" in lowered:
        return "bracket"
    if "hook" in lowered:
        return "hook"
    if any(word in lowered for word in ("holder", "cylinder", "diameter")) and "mount" not in lowered:
        return "cylindrical_holder"
    if any(word in lowered for word in ("cable", "cord", "wire")) and "stand" not in lowered:
        return "cable_organizer"
    if "wall mount" in lowered or "wall-mounted" in lowered:
        return "wall_mount"
    if " mount" in lowered or lowered.startswith("mount "):
        return "wall_mount"
    return best_template


def route_mode(
    text: str,
    *,
    source: str = "text",
    mode_hint: str | None = None,
    has_image: bool = False,
) -> Dict[str, Any]:
    lowered = text.lower().strip()
    if mode_hint in {"useful", "creative"}:
        mode = mode_hint
    else:
        useful_score = 0
        if re.search(r"\d", lowered):
            useful_score += 2
        if any(unit in lowered for unit in ("mm", "cm", "inch", "inches", "deg", "degree")):
            useful_score += 2
        if any(word in lowered for words in USEFUL_KEYWORDS.values() for word in words):
            useful_score += 3
        if any(word in lowered for word in CREATIVE_KEYWORDS):
            useful_score -= 4
        if has_image and useful_score < 4 and not re.search(r"\d", lowered):
            useful_score -= 1
        mode = "useful" if useful_score >= 3 else "creative"

    template_id = _detect_template(lowered) if mode == "useful" else None
    provider = "useful-cad" if mode == "useful" else "meshy"
    reason = (
        f"Detected measurable utility language for {TEMPLATE_LABELS.get(template_id or '', 'object')}."
        if mode == "useful"
        else "Detected creative language; routed to mesh generation."
    )
    confidence = 0.95 if mode_hint == mode else (0.88 if mode == "useful" else 0.82)
    return {
        "mode": mode,
        "provider": provider,
        "template_id": template_id,
        "route_reason": reason,
        "confidence": confidence,
        "source": source,
    }


def _parse_dimension_value(prompt: str, keywords: Tuple[str, ...], default: float) -> float:
    for keyword in keywords:
        value = _parse_value(prompt, keyword)
        if value:
            return value
    return default


def _apply_relative_revisions(
    prompt: str,
    dimensions: Dict[str, float],
    constraints: Dict[str, Any],
) -> None:
    lowered = prompt.lower()
    if "taller" in lowered:
        key = "height" if "height" in dimensions else "depth"
        dimensions[key] = round(dimensions[key] * 1.15, 2)
    if "shorter" in lowered:
        key = "height" if "height" in dimensions else "depth"
        dimensions[key] = round(dimensions[key] * 0.9, 2)
    if "wider" in lowered and "width" in dimensions:
        dimensions["width"] = round(dimensions["width"] * 1.1, 2)
    if "deeper" in lowered and "depth" in dimensions:
        dimensions["depth"] = round(dimensions["depth"] * 1.1, 2)
    if "thicker" in lowered:
        for key in ("wall_thickness_mm", "base_thickness_mm", "arm_thickness_mm", "thickness_mm"):
            if key in constraints:
                constraints[key] = round(float(constraints[key]) + 1.5, 2)
    if "add hole" in lowered and "cable_hole_diameter_mm" in constraints:
        constraints["cable_hole_diameter_mm"] = max(float(constraints["cable_hole_diameter_mm"]), 10.0)


def build_useful_structured_spec(
    prompt: str,
    *,
    source: str = "text",
    existing_spec: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    base_template = (
        existing_spec.get("template_id")
        if isinstance(existing_spec, dict) and existing_spec.get("template_id") in DEFAULT_SPECS
        else None
    )
    template_id = _detect_template(prompt, base_template)
    template_defaults = _deep_copy(DEFAULT_SPECS[template_id])
    if existing_spec:
        template_defaults = _merge_dict(template_defaults, existing_spec)
    dimensions = template_defaults["dimensions_mm"]
    constraints = template_defaults["constraints"]
    assumptions: list[str] = []

    prompt_triplet = _parse_triplet(prompt)
    lowered = prompt.lower()

    if template_id == "phone_stand":
        if prompt_triplet:
            dimensions["width"], dimensions["depth"], dimensions["height"] = prompt_triplet
        dimensions["height"] = _parse_dimension_value(prompt, ("height", "tall"), dimensions["height"])
        dimensions["width"] = _parse_dimension_value(prompt, ("width",), dimensions["width"])
        dimensions["depth"] = _parse_dimension_value(prompt, ("depth", "base"), dimensions["depth"])
        constraints["angle_deg"] = _parse_angle(prompt) or constraints["angle_deg"]
        constraints["base_thickness_mm"] = _parse_dimension_value(
            prompt,
            ("base thickness", "thickness"),
            constraints["base_thickness_mm"],
        )
        constraints["cable_hole_diameter_mm"] = _parse_hole(prompt) or constraints["cable_hole_diameter_mm"]
        if "cable hole" in lowered and float(constraints["cable_hole_diameter_mm"]) <= 0:
            constraints["cable_hole_diameter_mm"] = 10.0
        slot_pair = _parse_pair(prompt, "slot")
        if slot_pair:
            constraints["slot_width_mm"] = slot_pair[0]
            constraints["slot_depth_mm"] = slot_pair[1]
    elif template_id in {"simple_box", "tray"}:
        if prompt_triplet:
            dimensions["width"], dimensions["depth"], dimensions["height"] = prompt_triplet
        constraints["wall_thickness_mm"] = _parse_dimension_value(
            prompt,
            ("wall", "thickness"),
            constraints["wall_thickness_mm"],
        )
        constraints["fillet_mm"] = _parse_dimension_value(prompt, ("fillet", "rounded"), constraints.get("fillet_mm", 0.0))
        if "solid" in lowered:
            constraints["hollow"] = False
        if "open top" in lowered or template_id == "tray":
            constraints["open_top"] = True
    elif template_id == "hook":
        if prompt_triplet:
            dimensions["width"], dimensions["depth"], dimensions["height"] = prompt_triplet
        dimensions["depth"] = _parse_dimension_value(prompt, ("depth", "reach"), dimensions["depth"])
        constraints["hook_gap_mm"] = _parse_dimension_value(prompt, ("gap", "opening"), constraints["hook_gap_mm"])
        constraints["hook_thickness_mm"] = _parse_dimension_value(prompt, ("thickness",), constraints["hook_thickness_mm"])
    elif template_id == "cable_organizer":
        if prompt_triplet:
            dimensions["width"], dimensions["depth"], dimensions["height"] = prompt_triplet
        slot_count_match = re.search(r"(\d+)\s*(slot|slots)", lowered)
        if slot_count_match:
            constraints["slot_count"] = float(slot_count_match.group(1))
        constraints["slot_width_mm"] = _parse_dimension_value(prompt, ("slot",), constraints["slot_width_mm"])
    elif template_id == "bracket":
        if prompt_triplet:
            dimensions["width"], dimensions["depth"], dimensions["height"] = prompt_triplet
        constraints["thickness_mm"] = _parse_dimension_value(prompt, ("thickness", "wall"), constraints["thickness_mm"])
        constraints["hole_diameter_mm"] = _parse_hole(prompt) or constraints["hole_diameter_mm"]
    elif template_id == "cylindrical_holder":
        diameter = _parse_dimension_value(prompt, ("diameter", "dia"), dimensions["diameter"])
        height = _parse_dimension_value(prompt, ("height",), dimensions["height"])
        dimensions["diameter"] = diameter
        dimensions["height"] = height
        constraints["wall_thickness_mm"] = _parse_dimension_value(prompt, ("wall", "thickness"), constraints["wall_thickness_mm"])
    elif template_id == "wall_mount":
        if prompt_triplet:
            dimensions["width"], dimensions["depth"], dimensions["height"] = prompt_triplet
        constraints["arm_drop_mm"] = _parse_dimension_value(prompt, ("drop",), constraints["arm_drop_mm"])
        constraints["arm_thickness_mm"] = _parse_dimension_value(prompt, ("thickness",), constraints["arm_thickness_mm"])

    _apply_relative_revisions(prompt, dimensions, constraints)

    if not re.search(r"\d", lowered):
        assumptions.append("Using template defaults because no explicit measurements were detected.")
    if template_id == "phone_stand" and constraints.get("cable_hole_diameter_mm", 0) <= 0:
        assumptions.append("No cable hole requested; preview uses a closed base lip.")
    if template_id in {"simple_box", "tray"} and constraints.get("wall_thickness_mm", 0) <= 0:
        assumptions.append("Wall thickness defaulted to 3 mm.")

    keyword_hits = sum(1 for words in USEFUL_KEYWORDS.values() for word in words if word in lowered)
    confidence = min(0.98, 0.55 + (0.1 if re.search(r"\d", lowered) else 0) + keyword_hits * 0.05)

    return {
        "mode": "useful",
        "template_id": template_id,
        "object_label": TEMPLATE_LABELS[template_id],
        "dimensions_mm": {key: round(float(value), 2) for key, value in dimensions.items()},
        "constraints": {
            key: value
            if isinstance(value, bool)
            else round(float(value), 2)
            if isinstance(value, (int, float))
            else value
            for key, value in constraints.items()
        },
        "assumptions": assumptions,
        "confidence": round(confidence, 2),
        "source_inputs": {"text": prompt, "source": source},
        "revision_notes": existing_spec.get("revision_notes", []) if existing_spec else [],
    }


def _translated(mesh: trimesh.Trimesh, offset: Tuple[float, float, float]) -> trimesh.Trimesh:
    clone = mesh.copy()
    clone.apply_translation(offset)
    return clone


def _build_phone_stand_cadquery(spec: Dict[str, Any]):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = float(dims["width"])
    depth = float(dims["depth"])
    height = float(dims["height"])
    angle = float(constraints.get("angle_deg", 65.0))
    base_thickness = float(constraints.get("base_thickness_mm", 6.0))
    back_thickness = float(constraints.get("back_thickness_mm", 5.0))
    lip_height = float(constraints.get("lip_height_mm", 12.0))
    cable_hole = float(constraints.get("cable_hole_diameter_mm", 0.0) or 0.0)

    base = cq.Workplane("XY").box(width, depth, base_thickness, centered=(True, True, False))
    back = (
        cq.Workplane("XY")
        .box(width, back_thickness, height, centered=(True, True, False))
        .rotate((0, 0, 0), (1, 0, 0), -angle)
        .translate((0, depth / 2.0 - back_thickness / 2.0, base_thickness))
    )
    lip = (
        cq.Workplane("XY")
        .box(width * 0.85, back_thickness * 2.4, lip_height, centered=(True, True, False))
        .translate((0, -depth / 2.0 + back_thickness, base_thickness))
    )
    result = base.union(back).union(lip)

    if cable_hole > 0:
        hole = (
            cq.Workplane("XY")
            .cylinder(base_thickness * 2.0, cable_hole / 2.0)
            .translate((0, -depth / 4.0, base_thickness / 2.0))
        )
        result = result.cut(hole)
    return result


def _build_simple_box_cadquery(spec: Dict[str, Any], open_top_default: bool = True):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = float(dims["width"])
    depth = float(dims["depth"])
    height = float(dims["height"])
    wall = max(float(constraints.get("wall_thickness_mm", 3.0)), 1.2)
    open_top = bool(constraints.get("open_top", open_top_default))
    fillet = float(constraints.get("fillet_mm", 0.0) or 0.0)

    outer = cq.Workplane("XY").box(width, depth, height, centered=(True, True, False))
    if bool(constraints.get("hollow", True)) or open_top:
        inner_height = max(1.0, height - (wall if open_top else wall * 2.0))
        inner = (
            cq.Workplane("XY")
            .box(
                max(1.0, width - wall * 2.0),
                max(1.0, depth - wall * 2.0),
                inner_height,
                centered=(True, True, False),
            )
            .translate((0, 0, wall if open_top else wall))
        )
        outer = outer.cut(inner)

    if fillet > 0:
        try:
            outer = outer.edges("|Z").fillet(fillet)
        except Exception:
            pass
    return outer


def _build_hook_cadquery(spec: Dict[str, Any]):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = float(dims["width"])
    depth = float(dims["depth"])
    height = float(dims["height"])
    plate_thickness = float(constraints.get("plate_thickness_mm", 5.0))
    hook_thickness = float(constraints.get("hook_thickness_mm", 10.0))
    gap = float(constraints.get("hook_gap_mm", 24.0))

    plate = cq.Workplane("XY").box(width, plate_thickness, height, centered=(True, True, False))
    spine_length = max(hook_thickness, depth - gap)
    spine = (
        cq.Workplane("XY")
        .box(hook_thickness, spine_length, hook_thickness, centered=(True, True, False))
        .translate((0, spine_length / 2.0, 0))
    )
    tip = (
        cq.Workplane("YZ")
        .center(0, hook_thickness / 2.0)
        .circle(hook_thickness / 2.0)
        .extrude(width * 0.6, both=True)
        .translate((0, depth - hook_thickness, 0))
    )
    return plate.union(spine).union(tip)


def _build_cable_organizer_cadquery(spec: Dict[str, Any]):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = float(dims["width"])
    depth = float(dims["depth"])
    height = float(dims["height"])
    wall = max(float(constraints.get("wall_thickness_mm", 3.0)), 1.2)
    slot_count = max(1, int(round(float(constraints.get("slot_count", 3.0)))))
    slot_width = float(constraints.get("slot_width_mm", 8.0))

    tray = _build_simple_box_cadquery(
        {
            "dimensions_mm": {"width": width, "depth": depth, "height": height},
            "constraints": {
                "wall_thickness_mm": wall,
                "open_top": True,
                "hollow": True,
                "fillet_mm": 1.0,
            },
        },
        open_top_default=True,
    )
    slot_spacing = width / (slot_count + 1)
    for index in range(slot_count):
        slot = (
            cq.Workplane("XY")
            .box(slot_width, depth * 0.8, height * 0.7, centered=(True, True, False))
            .translate((-width / 2.0 + slot_spacing * (index + 1), 0, height * 0.35))
        )
        tray = tray.cut(slot)
    return tray


def _build_bracket_cadquery(spec: Dict[str, Any]):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = float(dims["width"])
    depth = float(dims["depth"])
    height = float(dims["height"])
    thickness = float(constraints.get("thickness_mm", 6.0))
    hole_diameter = float(constraints.get("hole_diameter_mm", 0.0) or 0.0)

    base = cq.Workplane("XY").box(width, depth, thickness, centered=(True, True, False))
    wall = (
        cq.Workplane("XY")
        .box(width, thickness, height, centered=(True, True, False))
        .translate((0, depth / 2.0 - thickness / 2.0, 0))
    )
    bracket = base.union(wall)
    if hole_diameter > 0:
        hole = (
            cq.Workplane("XY")
            .cylinder(thickness * 4.0, hole_diameter / 2.0)
            .translate((0, depth / 3.0, height / 2.0))
        )
        bracket = bracket.cut(hole)
    return bracket


def _build_cylindrical_holder_cadquery(spec: Dict[str, Any]):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    diameter = float(dims["diameter"])
    height = float(dims["height"])
    wall = max(float(constraints.get("wall_thickness_mm", 3.0)), 1.2)
    base_thickness = max(float(constraints.get("base_thickness_mm", 4.0)), 1.2)

    outer = cq.Workplane("XY").cylinder(height, diameter / 2.0, centered=(True, True, False))
    inner = (
        cq.Workplane("XY")
        .cylinder(max(1.0, height - base_thickness), max(1.0, diameter / 2.0 - wall), centered=(True, True, False))
        .translate((0, 0, base_thickness))
    )
    return outer.cut(inner)


def _build_wall_mount_cadquery(spec: Dict[str, Any]):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = float(dims["width"])
    depth = float(dims["depth"])
    height = float(dims["height"])
    plate_thickness = float(constraints.get("plate_thickness_mm", 6.0))
    arm_thickness = float(constraints.get("arm_thickness_mm", 12.0))
    arm_drop = float(constraints.get("arm_drop_mm", 24.0))

    plate = cq.Workplane("XY").box(width, plate_thickness, height, centered=(True, True, False))
    arm = (
        cq.Workplane("XY")
        .box(width * 0.5, depth, arm_thickness, centered=(True, True, False))
        .translate((0, depth / 2.0, height - arm_drop - arm_thickness))
    )
    lip = (
        cq.Workplane("XY")
        .box(width * 0.4, plate_thickness * 3.0, arm_thickness, centered=(True, True, False))
        .translate((0, depth - plate_thickness, height - arm_drop - arm_thickness))
    )
    return plate.union(arm).union(lip)


def _build_phone_stand(spec: Dict[str, Any]) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = dims["width"]
    depth = dims["depth"]
    height = dims["height"]
    angle = float(constraints.get("angle_deg", 65.0))
    base_thickness = float(constraints.get("base_thickness_mm", 6.0))
    back_thickness = float(constraints.get("back_thickness_mm", 5.0))
    lip_height = float(constraints.get("lip_height_mm", 12.0))

    base = trimesh.creation.box(extents=(width, depth, base_thickness))
    base.apply_translation((0, 0, base_thickness / 2.0))

    back = trimesh.creation.box(extents=(width, back_thickness, height))
    back.apply_translation((0, depth / 2.0 - back_thickness / 2.0, base_thickness + height / 2.0))
    pivot = (0, depth / 2.0 - back_thickness / 2.0, base_thickness)
    back.apply_transform(
        trimesh.transformations.rotation_matrix(
            angle=-math.radians(angle),
            direction=(1, 0, 0),
            point=pivot,
        )
    )

    lip = trimesh.creation.box(extents=(width * 0.85, back_thickness * 2.4, lip_height))
    lip.apply_translation((0, -depth / 2.0 + back_thickness, base_thickness + lip_height / 2.0))
    mesh = _apply_union([base, back, lip], [])

    cable_hole = float(constraints.get("cable_hole_diameter_mm", 0.0) or 0.0)
    if cable_hole > 0:
        cutter = trimesh.creation.cylinder(radius=cable_hole / 2.0, height=base_thickness * 2.0, sections=48)
        cutter.apply_translation((0, -depth / 4.0, base_thickness / 2.0))
        mesh = _apply_subtract(mesh, cutter, [])
    return mesh


def _build_simple_box(spec: Dict[str, Any], open_top_default: bool = True) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = dims["width"]
    depth = dims["depth"]
    height = dims["height"]
    wall = max(float(constraints.get("wall_thickness_mm", 3.0)), 1.2)
    open_top = bool(constraints.get("open_top", open_top_default))
    mesh = trimesh.creation.box(extents=(width, depth, height))
    if bool(constraints.get("hollow", True)) or open_top:
        inner_height = max(1.0, height - (wall if open_top else wall * 2.0))
        inner = trimesh.creation.box(
            extents=(max(1.0, width - wall * 2.0), max(1.0, depth - wall * 2.0), inner_height)
        )
        inner_z = wall / 2.0 if open_top else 0
        inner.apply_translation((0, 0, inner_z))
        mesh = _apply_hollow(mesh, inner, [])
    fillet = float(constraints.get("fillet_mm", 0.0) or 0.0)
    if fillet > 0:
        mesh = _apply_fillet(mesh, fillet)
    return mesh


def _cadquery_workplane_for_spec(spec: Dict[str, Any]):
    template_id = spec["template_id"]
    if template_id == "phone_stand":
        return _build_phone_stand_cadquery(spec)
    if template_id == "simple_box":
        return _build_simple_box_cadquery(spec, open_top_default=False)
    if template_id == "tray":
        return _build_simple_box_cadquery(spec, open_top_default=True)
    if template_id == "hook":
        return _build_hook_cadquery(spec)
    if template_id == "cable_organizer":
        return _build_cable_organizer_cadquery(spec)
    if template_id == "bracket":
        return _build_bracket_cadquery(spec)
    if template_id == "cylindrical_holder":
        return _build_cylindrical_holder_cadquery(spec)
    if template_id == "wall_mount":
        return _build_wall_mount_cadquery(spec)
    raise ValueError(f"CadQuery template not implemented: {template_id}")


def _export_cadquery_spec(structured_spec: Dict[str, Any], job_dir: Path, *, preview: bool) -> tuple[Path, Path]:
    if not cadquery_available():
        raise RuntimeError("CadQuery is not installed in the backend environment.")
    workplane = _cadquery_workplane_for_spec(structured_spec)
    stl_path = job_dir / ("preview.stl" if preview else "model.stl")
    glb_path = job_dir / ("preview.glb" if preview else "model.glb")
    cq_exporters.export(workplane, str(stl_path))
    mesh = trimesh.load_mesh(stl_path, force="mesh")
    trimesh.Scene(mesh).export(glb_path)
    return glb_path, stl_path


def _build_hook(spec: Dict[str, Any]) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = dims["width"]
    depth = dims["depth"]
    height = dims["height"]
    plate_thickness = float(constraints.get("plate_thickness_mm", 5.0))
    hook_thickness = float(constraints.get("hook_thickness_mm", 10.0))
    gap = float(constraints.get("hook_gap_mm", 24.0))

    plate = trimesh.creation.box(extents=(width, plate_thickness, height))
    plate.apply_translation((0, 0, height / 2.0))
    spine = trimesh.creation.box(extents=(hook_thickness, depth - gap, hook_thickness))
    spine.apply_translation((0, depth / 2.0 - (depth - gap) / 2.0, hook_thickness / 2.0))
    tip = trimesh.creation.cylinder(radius=hook_thickness / 2.0, height=width * 0.6, sections=48)
    tip.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2.0, (0, 1, 0)))
    tip.apply_translation((0, depth / 2.0 - hook_thickness / 2.0, hook_thickness / 2.0))
    return _apply_union([plate, spine, tip], [])


def _build_cable_organizer(spec: Dict[str, Any]) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = dims["width"]
    depth = dims["depth"]
    height = dims["height"]
    wall = max(float(constraints.get("wall_thickness_mm", 3.0)), 1.2)
    slot_count = max(1, int(round(float(constraints.get("slot_count", 3.0)))))
    slot_width = float(constraints.get("slot_width_mm", 8.0))
    mesh = _build_simple_box(
        {
            "dimensions_mm": dims,
            "constraints": {
                "wall_thickness_mm": wall,
                "open_top": True,
                "hollow": True,
                "fillet_mm": 1.0,
            },
        }
    )
    slot_spacing = width / (slot_count + 1)
    for index in range(slot_count):
        cutter = trimesh.creation.box(extents=(slot_width, depth * 0.8, height * 0.7))
        cutter.apply_translation(
            (
                -width / 2.0 + slot_spacing * (index + 1),
                0,
                height / 2.0,
            )
        )
        mesh = _apply_subtract(mesh, cutter, [])
    return mesh


def _build_bracket(spec: Dict[str, Any]) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = dims["width"]
    depth = dims["depth"]
    height = dims["height"]
    thickness = float(constraints.get("thickness_mm", 6.0))

    base = trimesh.creation.box(extents=(width, depth, thickness))
    base.apply_translation((0, 0, thickness / 2.0))
    wall = trimesh.creation.box(extents=(width, thickness, height))
    wall.apply_translation((0, depth / 2.0 - thickness / 2.0, height / 2.0))
    mesh = _apply_union([base, wall], [])

    hole_diameter = float(constraints.get("hole_diameter_mm", 0.0) or 0.0)
    if hole_diameter > 0:
        cutter = trimesh.creation.cylinder(radius=hole_diameter / 2.0, height=thickness * 4.0, sections=48)
        cutter.apply_translation((0, depth / 3.0, height / 2.0))
        mesh = _apply_subtract(mesh, cutter, [])
    return mesh


def _build_cylindrical_holder(spec: Dict[str, Any]) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    diameter = dims["diameter"]
    height = dims["height"]
    wall = max(float(constraints.get("wall_thickness_mm", 3.0)), 1.2)
    base_thickness = max(float(constraints.get("base_thickness_mm", 4.0)), 1.2)
    outer = trimesh.creation.cylinder(radius=diameter / 2.0, height=height, sections=96)
    inner = trimesh.creation.cylinder(
        radius=max(1.0, diameter / 2.0 - wall),
        height=max(1.0, height - base_thickness),
        sections=64,
    )
    inner.apply_translation((0, 0, base_thickness / 2.0))
    return _apply_hollow(outer, inner, [])


def _build_wall_mount(spec: Dict[str, Any]) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = dims["width"]
    depth = dims["depth"]
    height = dims["height"]
    plate_thickness = float(constraints.get("plate_thickness_mm", 6.0))
    arm_thickness = float(constraints.get("arm_thickness_mm", 12.0))
    arm_drop = float(constraints.get("arm_drop_mm", 24.0))

    plate = trimesh.creation.box(extents=(width, plate_thickness, height))
    plate.apply_translation((0, 0, height / 2.0))
    arm = trimesh.creation.box(extents=(width * 0.5, depth, arm_thickness))
    arm.apply_translation((0, depth / 2.0, height - arm_drop))
    lip = trimesh.creation.box(extents=(width * 0.4, plate_thickness * 3.0, arm_thickness))
    lip.apply_translation((0, depth - plate_thickness, height - arm_drop - arm_thickness / 2.0))
    return _apply_union([plate, arm, lip], [])


def mesh_from_structured_spec(spec: Dict[str, Any]) -> trimesh.Trimesh:
    template_id = spec["template_id"]
    if template_id == "phone_stand":
        return _build_phone_stand(spec)
    if template_id == "simple_box":
        return _build_simple_box(spec, open_top_default=False)
    if template_id == "tray":
        return _build_simple_box(spec, open_top_default=True)
    if template_id == "hook":
        return _build_hook(spec)
    if template_id == "cable_organizer":
        return _build_cable_organizer(spec)
    if template_id == "bracket":
        return _build_bracket(spec)
    if template_id == "cylindrical_holder":
        return _build_cylindrical_holder(spec)
    if template_id == "wall_mount":
        return _build_wall_mount(spec)
    return _build_phone_stand(spec)


def _write_glb(mesh: trimesh.Trimesh, path: Path) -> None:
    scene = trimesh.Scene(mesh)
    path.write_bytes(scene.export(file_type="glb"))


def preview_useful_object(structured_spec: Dict[str, Any], job_id: str | None = None) -> UsefulPreview:
    job_id = job_id or uuid.uuid4().hex
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    if structured_spec["template_id"] in CADQUERY_TEMPLATES and cadquery_available():
        glb_path, _ = _export_cadquery_spec(structured_spec, job_dir, preview=True)
    else:
        glb_path = job_dir / "preview.glb"
        mesh = mesh_from_structured_spec(structured_spec)
        _write_glb(mesh, glb_path)
    return UsefulPreview(job_id=job_id, glb_path=glb_path, structured_spec=structured_spec)


def build_useful_object(
    structured_spec: Dict[str, Any],
    job_id: str | None = None,
) -> UsefulBuild:
    job_id = job_id or uuid.uuid4().hex
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    glb_path = job_dir / "model.glb"
    stl_path = job_dir / "model.stl"
    if structured_spec["template_id"] in CADQUERY_TEMPLATES and cadquery_available():
        glb_path, stl_path = _export_cadquery_spec(structured_spec, job_dir, preview=False)
    else:
        mesh = mesh_from_structured_spec(structured_spec)
        _write_glb(mesh, glb_path)
        mesh.export(stl_path)
    return UsefulBuild(
        job_id=job_id,
        glb_path=glb_path,
        stl_path=stl_path,
        gcode_path=None,
        structured_spec=structured_spec,
    )
