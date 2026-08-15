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
    "perforated_disc": "Perforated disc",
    "phone_stand": "Phone stand",
    "simple_box": "Simple box",
    "tray": "Tray",
    "hook": "Hook",
    "cable_organizer": "Cable organizer",
    "bracket": "Bracket",
    "cylindrical_holder": "Cylindrical holder",
    "wall_mount": "Wall mount",
    "jewelry_piece": "Jewelry piece",
    "jewelry_pendant": "Jewelry pendant",
    "jewelry_ring": "Jewelry ring",
}

DEFAULT_SPECS: Dict[str, Dict[str, Any]] = {
    "perforated_disc": {
        "object_label": "Perforated disc",
        "dimensions_mm": {"outer_diameter": 340.0, "thickness": 15.0},
        "constraints": {
            "hole_diameter_mm": 7.08,
            "center_hole_diameter_mm": 32.93,
            "ring_count": 12.0,
            "radial_spacing_mm": 9.387,
            "tangential_spacing_mm": 7.0,
            "edge_margin_mm": 12.421,
        },
    },
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
    "jewelry_piece": {
        "object_label": "Jewelry piece",
        "dimensions_mm": {"width": 42.0, "height": 58.0, "thickness": 2.2},
        "constraints": {
            "loop_outer_diameter_mm": 7.0,
            "loop_inner_diameter_mm": 3.2,
            "relief_depth_mm": 0.8,
            "edge_bevel_mm": 0.5,
            "shape_profile": "oval",
            "attachment_count": 1.0,
            "jewelry_context": "freeform",
        },
    },
    "jewelry_pendant": {
        "object_label": "Jewelry pendant",
        "dimensions_mm": {"width": 32.0, "height": 42.0, "thickness": 2.2},
        "constraints": {
            "loop_outer_diameter_mm": 7.0,
            "loop_inner_diameter_mm": 3.2,
            "relief_depth_mm": 0.8,
            "edge_bevel_mm": 0.5,
            "shape_profile": "oval",
            "attachment_count": 1.0,
            "jewelry_context": "pendant",
        },
    },
    "jewelry_ring": {
        "object_label": "Jewelry ring",
        "dimensions_mm": {"inner_diameter": 17.3, "band_width": 4.0},
        "constraints": {
            "band_thickness_mm": 1.8,
            "comfort_bevel_mm": 0.35,
            "relief_depth_mm": 0.6,
            "stone_seat_diameter_mm": 0.0,
        },
    },
}

USEFUL_KEYWORDS = {
    "perforated_disc": ("perforated", "disc", "plate", "panel", "filter", "strainer"),
    "phone_stand": ("stand", "dock", "phone", "tablet"),
    "simple_box": ("box", "container", "case", "enclosure"),
    "tray": ("tray", "dish", "organizer tray"),
    "hook": ("hook", "hanger"),
    "cable_organizer": ("cable", "cord", "wire", "organizer"),
    "bracket": ("bracket", "support", "mounting"),
    "cylindrical_holder": ("cup", "holder", "pen", "cylinder"),
    "wall_mount": ("wall mount", "wall-mounted", "mount"),
    "jewelry_piece": ("jewelry", "necklace", "earring", "bracelet", "brooch", "charm", "ornament", "wearable"),
    "jewelry_pendant": ("pendant",),
    "jewelry_ring": ("jewelry ring", "ring size", "finger ring", "bezel", "signet"),
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
    "figurka",
    "postać",
    "postac",
    "rzeźba",
    "rzezba",
    "motoparalotniarz",
)

UNSUPPORTED_SEMANTIC_SHAPES = (
    "triangle",
    "triangular",
    "pentagon",
    "pentagonal",
    "hexagon",
    "hexagonal",
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
    "perforated_disc",
    "phone_stand",
    "simple_box",
    "tray",
    "hook",
    "cable_organizer",
    "bracket",
    "cylindrical_holder",
    "wall_mount",
    "jewelry_piece",
    "jewelry_pendant",
    "jewelry_ring",
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


def _detect_template(text: str, existing_template: str | None = None) -> str | None:
    lowered = text.lower()
    if "perforated" in lowered and any(word in lowered for word in ("disc", "plate", "panel", "filter", "strainer")):
        return "perforated_disc"
    if any(phrase in lowered for phrase in ("disc with holes", "plate with holes", "hole pattern disc", "perforated disk")):
        return "perforated_disc"
    if "phone stand" in lowered or ("stand" in lowered and "phone" in lowered):
        return "phone_stand"
    if any(word in lowered for word in ("cylindrical holder", "pen holder", "cup holder")):
        return "cylindrical_holder"
    if any(word in lowered for word in ("jewelry ring", "finger ring", "ring size", "signet ring")):
        return "jewelry_ring"
    if any(word in lowered for word in ("jewelry", "necklace", "pendant", "charm", "earring", "bracelet", "brooch", "ornament", "wearable")):
        return "jewelry_piece"
    if any(word in lowered for word in UNSUPPORTED_SEMANTIC_SHAPES):
        return None
    best_template = existing_template
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
    if "hole" in lowered or "holes" in lowered:
        return None
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
    if mode == "useful" and template_id is None:
        reason = "The prompt looks like a precise CAD request, but it does not match a supported semantic template yet. Rephrase using a supported object type or import a reference model."
    else:
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
    lowered = prompt.lower()
    for keyword in keywords:
        pattern = rf"{re.escape(keyword.lower())}\s*:?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in|inch|inches)?"
        match = re.search(pattern, lowered)
        if match:
            value, unit = match.groups()
            return _to_mm(float(value), unit or "mm")
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


def _parse_count(prompt: str, keywords: Tuple[str, ...], default: float) -> float:
    lowered = prompt.lower()
    for keyword in keywords:
        match = re.search(rf"(\d+)\s*{re.escape(keyword)}", lowered)
        if match:
            return float(match.group(1))
        match = re.search(rf"(\d+)\s+(?:\w+\s+){{0,3}}{re.escape(keyword)}", lowered)
        if match:
            return float(match.group(1))
        match = re.search(rf"{re.escape(keyword)}\s*(?:count)?\s*(?:of)?\s*(\d+)", lowered)
        if match:
            return float(match.group(1))
    return default


def _perforated_disc_params(spec: Dict[str, Any]) -> Dict[str, float]:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    return {
        "outer_diameter": max(float(dims.get("outer_diameter", 0.0) or 0.0), 1.0),
        "thickness": max(float(dims.get("thickness", 0.0) or 0.0), 0.8),
        "hole_diameter": max(float(constraints.get("hole_diameter_mm", 0.0) or 0.0), 0.8),
        "center_hole_diameter": max(float(constraints.get("center_hole_diameter_mm", 0.0) or 0.0), 0.0),
        "ring_count": max(int(round(float(constraints.get("ring_count", 1.0) or 1.0))), 1),
        "radial_spacing": max(float(constraints.get("radial_spacing_mm", 0.0) or 0.0), 0.1),
        "tangential_spacing": max(float(constraints.get("tangential_spacing_mm", 0.0) or 0.0), 0.0),
        "edge_margin": max(float(constraints.get("edge_margin_mm", 0.0) or 0.0), 0.0),
    }


def _perforated_disc_layout(spec: Dict[str, Any]) -> tuple[list[tuple[float, float]], list[float], list[int]]:
    params = _perforated_disc_params(spec)
    outer_radius = params["outer_diameter"] / 2.0
    hole_radius = params["hole_diameter"] / 2.0
    center_block_radius = params["center_hole_diameter"] / 2.0
    min_wall = 0.8

    min_center_radius = center_block_radius + params["edge_margin"] + hole_radius
    max_center_radius = outer_radius - params["edge_margin"] - hole_radius
    if max_center_radius <= min_center_radius:
        raise ValueError("Perforated disc has no usable ring area after center hole and edge margin.")

    ring_count = params["ring_count"]
    if ring_count == 1:
        ring_radii = [(min_center_radius + max_center_radius) / 2.0]
    else:
        required_span = (ring_count - 1) * params["radial_spacing"]
        available_span = max_center_radius - min_center_radius
        if required_span > available_span + 1e-6:
            raise ValueError("Ring count and radial spacing push the pattern beyond the disc boundary.")
        ring_radii = [min_center_radius + index * params["radial_spacing"] for index in range(ring_count)]

    if len(ring_radii) > 1 and params["radial_spacing"] < params["hole_diameter"] + min_wall:
        raise ValueError("Radial spacing is too small for the current hole diameter and wall thickness.")

    pitch = params["hole_diameter"] + params["tangential_spacing"]
    points: list[tuple[float, float]] = []
    holes_per_ring: list[int] = []
    for radius in ring_radii:
        circumference = 2.0 * math.pi * radius
        hole_count = max(int(math.floor(circumference / max(pitch, 0.1))), 4)
        arc_pitch = circumference / hole_count
        if arc_pitch < params["hole_diameter"] + min_wall:
            raise ValueError("Tangential spacing is too small for the current hole diameter and wall thickness.")
        holes_per_ring.append(hole_count)
        for hole_index in range(hole_count):
            angle = (2.0 * math.pi * hole_index) / hole_count
            points.append((math.cos(angle) * radius, math.sin(angle) * radius))
    return points, ring_radii, holes_per_ring


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
    if template_id is None:
        raise ValueError(
            "This prompt asks for a precise semantic shape that is not supported yet. "
            "Right now the semantic workspace supports specific native templates such as perforated disc, phone stand, box, tray, hook, cable organizer, bracket, cylindrical holder, wall mount, freeform jewelry piece, and jewelry ring."
        )
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
    elif template_id == "perforated_disc":
        dimensions["outer_diameter"] = _parse_dimension_value(
            prompt,
            ("outer diameter", "disc diameter", "plate diameter", "diameter"),
            dimensions["outer_diameter"],
        )
        dimensions["thickness"] = _parse_dimension_value(
            prompt,
            ("thickness",),
            dimensions["thickness"],
        )
        constraints["hole_diameter_mm"] = _parse_dimension_value(
            prompt,
            ("hole diameter", "hole size", "opening diameter"),
            constraints["hole_diameter_mm"],
        )
        constraints["center_hole_diameter_mm"] = _parse_dimension_value(
            prompt,
            ("center hole", "center diameter", "center opening"),
            constraints["center_hole_diameter_mm"],
        )
        constraints["radial_spacing_mm"] = _parse_dimension_value(
            prompt,
            ("radial spacing", "ring spacing"),
            constraints["radial_spacing_mm"],
        )
        shared_spacing = _parse_dimension_value(
            prompt,
            ("spacing",),
            0.0,
        )
        if shared_spacing > 0:
            constraints["radial_spacing_mm"] = shared_spacing
            constraints["tangential_spacing_mm"] = shared_spacing
        constraints["tangential_spacing_mm"] = _parse_dimension_value(
            prompt,
            ("tangential spacing", "arc spacing"),
            constraints["tangential_spacing_mm"],
        )
        constraints["edge_margin_mm"] = _parse_dimension_value(
            prompt,
            ("edge margin", "margin"),
            constraints["edge_margin_mm"],
        )
        constraints["ring_count"] = _parse_count(
            prompt,
            ("rings", "ring"),
            constraints["ring_count"],
        )
    elif template_id in {"jewelry_piece", "jewelry_pendant"}:
        if prompt_triplet:
            dimensions["width"], dimensions["height"], dimensions["thickness"] = prompt_triplet
        dimensions["width"] = _parse_dimension_value(
            prompt,
            ("jewelry width", "necklace width", "pendant width", "charm width", "earring width", "bracelet width", "width"),
            dimensions["width"],
        )
        dimensions["height"] = _parse_dimension_value(
            prompt,
            ("jewelry height", "necklace height", "pendant height", "charm height", "earring height", "bracelet height", "height", "tall"),
            dimensions["height"],
        )
        dimensions["thickness"] = _parse_dimension_value(
            prompt,
            ("thickness", "wall"),
            dimensions["thickness"],
        )
        constraints["loop_inner_diameter_mm"] = _parse_dimension_value(
            prompt,
            ("loop inner diameter", "chain hole", "jump ring hole", "hole"),
            constraints["loop_inner_diameter_mm"],
        )
        constraints["loop_outer_diameter_mm"] = max(
            _parse_dimension_value(prompt, ("loop outer diameter", "loop diameter"), constraints["loop_outer_diameter_mm"]),
            float(constraints["loop_inner_diameter_mm"]) + 2.4,
        )
        constraints["relief_depth_mm"] = _parse_dimension_value(
            prompt,
            ("relief depth", "raised detail", "engraving depth", "detail depth"),
            constraints["relief_depth_mm"],
        )
        constraints["edge_bevel_mm"] = _parse_dimension_value(
            prompt,
            ("bevel", "roundover", "rounded edge"),
            constraints["edge_bevel_mm"],
        )
        if "circle" in lowered or "round" in lowered:
            constraints["shape_profile"] = "round"
        elif "rectangle" in lowered or "tag" in lowered:
            constraints["shape_profile"] = "rounded_rectangle"
        elif "necklace" in lowered:
            constraints["shape_profile"] = "necklace_arc"
            constraints["jewelry_context"] = "necklace"
            constraints["attachment_count"] = max(_parse_count(prompt, ("links", "elements", "pieces"), 5.0), 3.0)
        elif "earring" in lowered:
            constraints["jewelry_context"] = "earring"
            constraints["attachment_count"] = 1.0
        elif "bracelet" in lowered:
            constraints["jewelry_context"] = "bracelet"
            constraints["attachment_count"] = max(_parse_count(prompt, ("links", "elements", "pieces"), 7.0), 3.0)
        elif "brooch" in lowered:
            constraints["jewelry_context"] = "brooch"
            constraints["attachment_count"] = 0.0
        else:
            constraints["shape_profile"] = "oval"
    elif template_id == "jewelry_ring":
        dimensions["inner_diameter"] = _parse_dimension_value(
            prompt,
            ("inner diameter", "ring inner diameter", "finger diameter", "diameter"),
            dimensions["inner_diameter"],
        )
        dimensions["band_width"] = _parse_dimension_value(
            prompt,
            ("band width", "ring width", "width"),
            dimensions["band_width"],
        )
        constraints["band_thickness_mm"] = _parse_dimension_value(
            prompt,
            ("band thickness", "wall", "thickness"),
            constraints["band_thickness_mm"],
        )
        constraints["comfort_bevel_mm"] = _parse_dimension_value(
            prompt,
            ("comfort bevel", "bevel", "rounded edge"),
            constraints["comfort_bevel_mm"],
        )
        constraints["relief_depth_mm"] = _parse_dimension_value(
            prompt,
            ("relief depth", "raised detail", "engraving depth", "detail depth"),
            constraints["relief_depth_mm"],
        )
        constraints["stone_seat_diameter_mm"] = _parse_dimension_value(
            prompt,
            ("stone seat", "stone diameter", "bezel diameter"),
            constraints["stone_seat_diameter_mm"],
        )

    _apply_relative_revisions(prompt, dimensions, constraints)

    if not re.search(r"\d", lowered):
        assumptions.append("Using template defaults because no explicit measurements were detected.")
    if template_id == "phone_stand" and constraints.get("cable_hole_diameter_mm", 0) <= 0:
        assumptions.append("No cable hole requested; preview uses a closed base lip.")
    if template_id in {"simple_box", "tray"} and constraints.get("wall_thickness_mm", 0) <= 0:
        assumptions.append("Wall thickness defaulted to 3 mm.")
    if template_id == "perforated_disc":
        assumptions.append("Hole counts per ring are derived automatically from tangential spacing.")
    if template_id in {"jewelry_piece", "jewelry_pendant", "jewelry_ring"}:
        assumptions.append("Sketch/photo input is treated as a reference only; this is a rough editable jewelry starting point, not a category lock.")
        assumptions.append("Use resin/SLA or castable resin for fine jewelry detail; FDM is only suitable for coarse prototypes.")

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


def _build_perforated_disc_cadquery(spec: Dict[str, Any]):
    params = _perforated_disc_params(spec)
    points, _, _ = _perforated_disc_layout(spec)
    thickness = params["thickness"]
    outer_radius = params["outer_diameter"] / 2.0

    result = cq.Workplane("XY").circle(outer_radius).extrude(thickness)
    hole_diameter = params["hole_diameter"]
    if points:
        result = result.faces(">Z").workplane().pushPoints(points).hole(hole_diameter, depth=thickness)
    center_hole_diameter = params["center_hole_diameter"]
    if center_hole_diameter > 0:
        result = result.faces(">Z").workplane().hole(center_hole_diameter, depth=thickness)
    return result


def _build_jewelry_piece_cadquery(spec: Dict[str, Any]):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = float(dims["width"])
    height = float(dims["height"])
    thickness = max(float(dims["thickness"]), 1.0)
    loop_outer = max(float(constraints.get("loop_outer_diameter_mm", 7.0)), 3.0)
    loop_inner = max(float(constraints.get("loop_inner_diameter_mm", 3.2)), 1.2)
    relief_depth = max(float(constraints.get("relief_depth_mm", 0.8)), 0.0)
    bevel = max(float(constraints.get("edge_bevel_mm", 0.5)), 0.0)
    profile = str(constraints.get("shape_profile", "oval"))
    attachment_count = max(0, int(round(float(constraints.get("attachment_count", 1.0) or 0.0))))

    if profile == "necklace_arc":
        result = None
        count = max(3, attachment_count)
        radius = width / 2.0
        bead_width = max(width / (count * 1.75), 4.0)
        bead_height = max(height / 7.0, 5.0)
        for index in range(count):
            t = 0.0 if count == 1 else index / (count - 1)
            angle = math.radians(205 + t * 130)
            x = math.cos(angle) * radius
            y = math.sin(angle) * height * 0.42 + height * 0.35
            bead = (
                cq.Workplane("XY")
                .ellipse(bead_width / 2.0, bead_height / 2.0)
                .extrude(thickness)
                .translate((x, y, 0))
            )
            result = bead if result is None else result.union(bead)
        assert result is not None
        return result

    if profile == "round":
        body = cq.Workplane("XY").circle(min(width, height) / 2.0).extrude(thickness)
    elif profile == "rounded_rectangle":
        body = cq.Workplane("XY").box(width, height, thickness, centered=(True, True, False))
        if bevel > 0:
            try:
                body = body.edges("|Z").fillet(min(bevel, width / 8.0, height / 8.0))
            except Exception:
                pass
    else:
        body = cq.Workplane("XY").ellipse(width / 2.0, height / 2.0).extrude(thickness)

    result = body
    if attachment_count > 0:
        attachment_points = [(0.0, height / 2.0 + loop_outer * 0.32)]
        if attachment_count >= 2:
            attachment_points = [
                (-width * 0.36, height / 2.0 + loop_outer * 0.18),
                (width * 0.36, height / 2.0 + loop_outer * 0.18),
            ]
        for x, y in attachment_points[:attachment_count]:
            loop = (
                cq.Workplane("XY")
                .circle(loop_outer / 2.0)
                .circle(min(loop_inner / 2.0, loop_outer / 2.0 - 0.8))
                .extrude(thickness)
                .translate((x, y, 0))
            )
            result = result.union(loop)

    if relief_depth > 0:
        relief = (
            cq.Workplane("XY")
            .ellipse(max(width * 0.18, 2.0), max(height * 0.28, 2.0))
            .extrude(min(relief_depth, thickness))
            .translate((0, 0, thickness))
        )
        result = result.union(relief)
    return result


def _build_jewelry_pendant_cadquery(spec: Dict[str, Any]):
    return _build_jewelry_piece_cadquery(spec)


def _build_jewelry_ring_cadquery(spec: Dict[str, Any]):
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    inner_diameter = float(dims["inner_diameter"])
    band_width = max(float(dims["band_width"]), 1.2)
    band_thickness = max(float(constraints.get("band_thickness_mm", 1.8)), 1.0)
    relief_depth = max(float(constraints.get("relief_depth_mm", 0.6)), 0.0)
    stone_seat = max(float(constraints.get("stone_seat_diameter_mm", 0.0)), 0.0)
    outer_radius = inner_diameter / 2.0 + band_thickness

    ring = (
        cq.Workplane("XY")
        .circle(outer_radius)
        .circle(max(inner_diameter / 2.0, 1.0))
        .extrude(band_width)
    )
    if relief_depth > 0:
        signet = (
            cq.Workplane("XY")
            .ellipse(max(outer_radius * 0.42, 2.0), max(band_thickness * 1.2, 1.4))
            .extrude(band_width + relief_depth)
            .translate((0, outer_radius - band_thickness * 0.15, 0))
        )
        ring = ring.union(signet)
    if stone_seat > 0:
        cutter = (
            cq.Workplane("XY")
            .circle(stone_seat / 2.0)
            .extrude(band_width + relief_depth + 1.0)
            .translate((0, outer_radius - band_thickness * 0.15, -0.5))
        )
        ring = ring.cut(cutter)
    return ring


def _build_perforated_disc(spec: Dict[str, Any]) -> trimesh.Trimesh:
    params = _perforated_disc_params(spec)
    points, _, _ = _perforated_disc_layout(spec)
    thickness = params["thickness"]
    outer_radius = params["outer_diameter"] / 2.0

    mesh = trimesh.creation.cylinder(radius=outer_radius, height=thickness, sections=192)
    center_hole_diameter = params["center_hole_diameter"]
    if center_hole_diameter > 0:
        center_cutter = trimesh.creation.cylinder(
            radius=center_hole_diameter / 2.0,
            height=thickness * 1.5,
            sections=96,
        )
        mesh = _apply_subtract(mesh, center_cutter, [])

    for x, y in points:
        cutter = trimesh.creation.cylinder(
            radius=params["hole_diameter"] / 2.0,
            height=thickness * 1.5,
            sections=48,
        )
        cutter.apply_translation((x, y, 0))
        mesh = _apply_subtract(mesh, cutter, [])
    return mesh


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
    if template_id == "perforated_disc":
        return _build_perforated_disc_cadquery(spec)
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
    if template_id == "jewelry_piece":
        return _build_jewelry_piece_cadquery(spec)
    if template_id == "jewelry_pendant":
        return _build_jewelry_pendant_cadquery(spec)
    if template_id == "jewelry_ring":
        return _build_jewelry_ring_cadquery(spec)
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


def _build_jewelry_piece(spec: Dict[str, Any]) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    width = float(dims["width"])
    height = float(dims["height"])
    thickness = max(float(dims["thickness"]), 1.0)
    loop_outer = max(float(constraints.get("loop_outer_diameter_mm", 7.0)), 3.0)
    profile = str(constraints.get("shape_profile", "oval"))
    attachment_count = max(0, int(round(float(constraints.get("attachment_count", 1.0) or 0.0))))

    if profile == "round":
        body = trimesh.creation.cylinder(radius=min(width, height) / 2.0, height=thickness, sections=96)
    elif profile == "necklace_arc":
        count = max(3, attachment_count)
        radius = width / 2.0
        parts = []
        for index in range(count):
            t = 0.0 if count == 1 else index / (count - 1)
            angle = math.radians(205 + t * 130)
            bead = trimesh.creation.uv_sphere(radius=max(width / (count * 2.4), 2.0), count=[24, 12])
            bead.apply_scale((1.2, 0.8, max(thickness / 4.0, 0.45)))
            bead.apply_translation((math.cos(angle) * radius, math.sin(angle) * height * 0.42 + height * 0.35, 0))
            parts.append(bead)
        return _apply_union(parts, [])
    else:
        body = trimesh.creation.uv_sphere(radius=1.0, count=[48, 24])
        body.apply_scale((width / 2.0, height / 2.0, thickness / 2.0))

    parts = [body]
    if attachment_count > 0:
        loop = trimesh.creation.torus(
            major_radius=loop_outer / 2.0,
            minor_radius=max((loop_outer - float(constraints.get("loop_inner_diameter_mm", 3.2))) / 4.0, 0.6),
            major_segments=48,
            minor_segments=12,
        )
        loop.apply_translation((0, height / 2.0 + loop_outer * 0.32, 0))
        parts.append(loop)
    return _apply_union(parts, [])


def _build_jewelry_ring(spec: Dict[str, Any]) -> trimesh.Trimesh:
    dims = spec["dimensions_mm"]
    constraints = spec["constraints"]
    inner_diameter = float(dims["inner_diameter"])
    band_width = max(float(dims["band_width"]), 1.2)
    band_thickness = max(float(constraints.get("band_thickness_mm", 1.8)), 1.0)
    outer_radius = inner_diameter / 2.0 + band_thickness
    outer = trimesh.creation.cylinder(radius=outer_radius, height=band_width, sections=128)
    inner = trimesh.creation.cylinder(radius=inner_diameter / 2.0, height=band_width * 1.4, sections=96)
    ring = _apply_subtract(outer, inner, [])
    relief_depth = max(float(constraints.get("relief_depth_mm", 0.6)), 0.0)
    if relief_depth > 0:
        boss = trimesh.creation.uv_sphere(radius=max(band_thickness * 1.4, 1.6), count=[32, 16])
        boss.apply_scale((1.5, 0.7, max(relief_depth / 2.0, 0.3)))
        boss.apply_translation((0, outer_radius - band_thickness * 0.15, band_width / 2.0))
        ring = _apply_union([ring, boss], [])
    return ring


def mesh_from_structured_spec(spec: Dict[str, Any]) -> trimesh.Trimesh:
    template_id = spec["template_id"]
    if template_id == "perforated_disc":
        return _build_perforated_disc(spec)
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
    if template_id in {"jewelry_piece", "jewelry_pendant"}:
        return _build_jewelry_piece(spec)
    if template_id == "jewelry_ring":
        return _build_jewelry_ring(spec)
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
